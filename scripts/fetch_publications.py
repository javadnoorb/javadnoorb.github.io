"""
Fetches publications from Google Scholar and writes data/publications.json.

Two backends are supported:
  1. SerpApi's Google Scholar Author API (recommended for CI) - set the
     SERPAPI_KEY environment variable / GitHub secret.
  2. The `scholarly` package, which scrapes Google Scholar directly. This
     works fine on a local machine but is frequently blocked or captcha'd
     when run from datacenter IPs such as GitHub Actions runners. If you
     hit that, get a free SerpApi key instead.

On any failure, the existing publications.json is left untouched so the
site never regresses to empty data because of a transient block. The same
goes for a fetch that comes back suspiciously short (see
MIN_RETAINED_FRACTION) - set FORCE_PUBLICATIONS_UPDATE=1 to accept it anyway,
e.g. after deliberately removing papers from the Scholar profile.

Also writes data/scholar_stats.json (total citations, h-index, i10-index)
and fills in DOIs, looked up on Crossref when the link doesn't contain one.
"""
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

from build import doi_from_link, is_preprint

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PUBLICATIONS_PATH = DATA / "publications.json"
STATS_PATH = DATA / "scholar_stats.json"

MAX_AUTHORS = 5

# A fetch that keeps fewer than this fraction of the papers already on the
# site is treated as a partial/broken scrape, not a real change.
MIN_RETAINED_FRACTION = 0.7

SERPAPI_PAGE_SIZE = 100

# A zero-citation entry is kept only if it's recent enough that it plausibly
# just hasn't accrued citations yet, rather than being a long-settled poster
# nobody ever cited.
RECENT_YEARS_WINDOW = 2

# Conference-abstract venues and poster-board-number title suffixes are
# dropped regardless of recency - these are never going to become "real"
# publications no matter how new they are.
POSTER_VENUE_PATTERN = re.compile(r"abstracts?\b", re.IGNORECASE)
POSTER_TITLE_PATTERN = re.compile(r":\s*\d{2,4}$|^abstract\b", re.IGNORECASE)
# AACR publishes its annual-meeting abstracts as "Supplement" issues of real
# journals (Cancer Research, Clinical Cancer Research), so the venue alone
# looks like a journal article - the link path is what gives them away.
POSTER_LINK_PATTERN = re.compile(r"_Supplement/", re.IGNORECASE)


def is_poster(pub):
    venue = pub.get("venue") or ""
    title = pub.get("title") or ""
    link = pub.get("link") or ""
    return bool(POSTER_VENUE_PATTERN.search(venue) or POSTER_TITLE_PATTERN.search(title)
                or POSTER_LINK_PATTERN.search(link))

# Google Scholar's scrape sometimes drops the venue entirely. These are
# known gaps, cross-checked against the owner's own CV, filled in by
# matching on a distinctive substring of the title.
VENUE_OVERRIDES = [
    ("computational estimation of quality and clinical relevance of cancer cell lines", "Molecular Systems Biology"),
    ("machine learning in biology and medicine", "Advances in Molecular Pathology"),
    ("emerging ai approaches for cancer spatial omics", "GigaScience"),
    ("treating cancer as an invasive species", "Molecular Cancer Research"),
    ("integrative deep learning for pancancer molecular subtype classification", "ACM-BCB 2020"),
]


def apply_venue_overrides(publications):
    for pub in publications:
        if pub.get("venue"):
            continue
        title = (pub.get("title") or "").lower()
        for needle, venue in VENUE_OVERRIDES:
            if needle in title:
                pub["venue"] = venue
                break
    return publications

# Google Scholar's scraped bib data occasionally mangles a citation string
# into a fake "publication" whose title is actually a truncated author list
# (e.g. "Foroughi pour A, Namburi S, Caruana D, Rimm D, et al" or "... and
# Jeffrey H"). These patterns catch that shape and let us drop the entry.
GARBLED_TITLE_PATTERNS = [
    re.compile(r",\s*et al\.?$", re.IGNORECASE),
    re.compile(r"\band [A-Z][a-zA-Z\-]+ [A-Z]$"),
]


def truncate_authors(authors, owner_name=None):
    if not authors:
        return authors
    separator = " and " if " and " in authors else ", "
    names = [n.strip() for n in authors.split(separator)]
    if len(names) <= MAX_AUTHORS:
        return authors
    shown = names[:MAX_AUTHORS]
    # If the site owner is a co-author but got cut by the truncation (e.g. a
    # 90-author consortium paper), swap them into the last visible slot so
    # their own name doesn't disappear from their own showcased publication.
    if owner_name and owner_name not in shown and owner_name in names:
        shown = shown[:-1] + [owner_name]
    return ", ".join(shown) + ", et al."


def is_garbled_title(title):
    if not title:
        return False
    return any(p.search(title) for p in GARBLED_TITLE_PATTERNS)


def _title_words(title):
    if not title:
        return set()
    t = re.sub(r"^abstract\s+\S+:\s*", "", title.lower())
    return {w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 2}


def _same_paper(title_a, title_b):
    words_a, words_b = _title_words(title_a), _title_words(title_b)
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b) / len(words_a | words_b)
    return overlap >= 0.7


def dedupe_publications(publications):
    """Merges different scraped versions of the same paper (e.g. a journal
    article, its preprint, and a conference abstract of it) into one entry.
    The published version wins over a preprint even when Scholar credits
    the preprint with more citations; among equals, the most-cited wins.
    The kept entry carries the group's highest citation count."""
    groups = []
    for pub in publications:
        for group in groups:
            if _same_paper(pub.get("title"), group[0].get("title")):
                group.append(pub)
                break
        else:
            groups.append([pub])
    merged = []
    for group in groups:
        best = dict(max(group, key=lambda p: (not is_preprint(p), p.get("citations") or 0)))
        citations = [p.get("citations") for p in group if p.get("citations") is not None]
        if citations:
            best["citations"] = max(citations)
        merged.append(best)
    return merged


def load_existing():
    if not PUBLICATIONS_PATH.exists():
        return []
    try:
        return json.loads(PUBLICATIONS_PATH.read_text())
    except ValueError:
        return []


def looks_truncated(new_count, old_count):
    """True when a fetch returned far fewer papers than are already on the
    site - the signature of a partial scrape or a pagination bug."""
    return old_count > 0 and new_count < old_count * MIN_RETAINED_FRACTION


def crossref_doi(pub, timeout=10):
    """Looks a paper up on Crossref by title (+ first author), returning its
    DOI only when the matched record's title really is the same paper."""
    title = pub.get("title")
    if not title:
        return ""
    query = {"query.bibliographic": title, "rows": "3", "select": "DOI,title"}
    first_author = (pub.get("authors") or "").replace(" and ", ", ").split(",")[0].strip()
    if first_author:
        query["query.author"] = first_author
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={
        "User-Agent": "personal-site-publications/1.0 (+https://javadnoorb.github.io/)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        items = json.load(resp).get("message", {}).get("items", [])
    for item in items:
        for candidate in item.get("title") or []:
            if _same_paper(title, candidate):
                return item.get("DOI", "").lower()
    return ""


def add_dois(publications, existing):
    """DOI from the link when it contains one; otherwise reuse a DOI found
    on an earlier run, and only then ask Crossref. Lookup failures are
    non-fatal - the paper just goes without a DOI link this time."""
    known = {p.get("title"): p.get("doi") for p in existing if p.get("doi")}
    for pub in publications:
        if "patents.google.com" in (pub.get("link") or ""):
            continue
        doi = doi_from_link(pub.get("link")) or known.get(pub.get("title"))
        if not doi:
            try:
                doi = crossref_doi(pub)
            except Exception as e:
                print(f"Crossref lookup failed for {pub.get('title')!r}: {e}")
        if doi:
            pub["doi"] = doi
    return publications


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_profile():
    profile = yaml.safe_load((DATA / "profile.yaml").read_text())
    scholar_id = profile.get("scholar_id", "")
    if not scholar_id or scholar_id.startswith("XXXX"):
        print("No real scholar_id set in data/profile.yaml yet; skipping fetch.")
        sys.exit(0)
    return scholar_id, profile.get("name")


def fetch_via_serpapi(scholar_id, api_key, owner_name):
    """Returns (publications, stats). The author endpoint pages its article
    list (20 per page by default), so request the maximum page size and keep
    paging until a short page comes back."""
    from serpapi import GoogleSearch

    articles, stats, start = [], {}, 0
    while True:
        params = {
            "engine": "google_scholar_author",
            "author_id": scholar_id,
            "api_key": api_key,
            "num": SERPAPI_PAGE_SIZE,
            "start": start,
        }
        results = GoogleSearch(params).get_dict()
        if results.get("error"):
            raise RuntimeError(results["error"])
        if start == 0:
            stats = serpapi_stats(results)
        page = results.get("articles", [])
        articles.extend(page)
        if len(page) < SERPAPI_PAGE_SIZE:
            break
        start += SERPAPI_PAGE_SIZE
    publications = []
    for a in articles:
        year = a.get("year")
        publications.append({
            "title": a.get("title"),
            "authors": truncate_authors(a.get("authors"), owner_name),
            "venue": a.get("publication"),
            "year": int(year) if str(year).isdigit() else None,
            "citations": (a.get("cited_by") or {}).get("value"),
            "link": a.get("link"),
        })
    return publications, stats


def serpapi_stats(results):
    """Flattens SerpApi's cited_by table ([{"citations": {"all": N}}, ...])."""
    stats = {}
    for row in (results.get("cited_by") or {}).get("table", []):
        for key, values in row.items():
            if isinstance(values, dict) and _int(values.get("all")) is not None:
                stats[key] = _int(values["all"])
    return stats


def fetch_via_scholarly(scholar_id, owner_name):
    from scholarly import scholarly

    author = scholarly.search_author_id(scholar_id)
    author = scholarly.fill(author, sections=["basics", "indices", "publications"])
    stats = {"citations": _int(author.get("citedby")), "h_index": _int(author.get("hindex")),
             "i10_index": _int(author.get("i10index"))}
    publications = []
    for pub in author.get("publications", []):
        try:
            filled = scholarly.fill(pub)
        except Exception:
            filled = pub
        bib = filled.get("bib", {})
        year = bib.get("pub_year")
        publications.append({
            "title": bib.get("title"),
            "authors": truncate_authors(bib.get("author"), owner_name),
            "venue": bib.get("venue") or bib.get("journal"),
            "year": int(year) if str(year).isdigit() else None,
            "citations": filled.get("num_citations"),
            "link": filled.get("pub_url"),
        })
    return publications, stats


def write_stats(stats):
    stats = {k: v for k, v in (stats or {}).items() if v is not None}
    if not stats.get("citations"):
        print("No citation stats in this fetch; leaving scholar_stats.json untouched.")
        return
    stats["updated"] = datetime.date.today().isoformat()
    STATS_PATH.write_text(json.dumps(stats, indent=2) + "\n")
    print(f"Wrote Scholar stats to {STATS_PATH}")


def main():
    scholar_id, owner_name = load_profile()
    api_key = os.environ.get("SERPAPI_KEY")

    try:
        if api_key:
            print("Fetching publications via SerpApi...")
            publications, stats = fetch_via_serpapi(scholar_id, api_key, owner_name)
        else:
            print("Fetching publications via scholarly (may be blocked in CI)...")
            publications, stats = fetch_via_scholarly(scholar_id, owner_name)
    except Exception as e:
        print(f"Failed to fetch publications: {e}")
        print("Leaving existing publications.json untouched.")
        sys.exit(0)

    if not publications:
        print("Fetch returned zero publications; leaving existing file untouched.")
        sys.exit(0)

    before = len(publications)
    publications = [p for p in publications if not is_garbled_title(p.get("title"))]
    publications = dedupe_publications(publications)
    publications = apply_venue_overrides(publications)
    publications = [p for p in publications if not is_poster(p)]

    current_year = datetime.date.today().year
    def keep_uncited(p):
        return p.get("citations") or (
            p.get("year") and p["year"] >= current_year - RECENT_YEARS_WINDOW
        )
    publications = [p for p in publications if keep_uncited(p)]

    print(f"Cleaned {before} raw entries down to {len(publications)} (dropped "
          f"garbled/duplicate/poster entries and stale zero-citation ones)")

    existing = load_existing()
    if looks_truncated(len(publications), len(existing)) and not os.environ.get("FORCE_PUBLICATIONS_UPDATE"):
        print(f"Fetch kept only {len(publications)} publications versus {len(existing)} "
              f"currently on the site; treating it as a partial scrape and leaving "
              f"publications.json untouched. Set FORCE_PUBLICATIONS_UPDATE=1 to accept it.")
        sys.exit(0)

    publications = add_dois(publications, existing)
    PUBLICATIONS_PATH.write_text(json.dumps(publications, indent=2))
    print(f"Wrote {len(publications)} publications to {PUBLICATIONS_PATH}")
    write_stats(stats)


if __name__ == "__main__":
    main()
