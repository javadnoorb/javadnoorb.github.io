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
site never regresses to empty data because of a transient block.
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

MAX_AUTHORS = 5

# A zero-citation entry is kept only if it's recent enough that it plausibly
# just hasn't accrued citations yet, rather than being a long-settled poster
# nobody ever cited.
RECENT_YEARS_WINDOW = 2

# Conference-abstract venues and poster-board-number title suffixes are
# dropped regardless of recency - these are never going to become "real"
# publications no matter how new they are.
POSTER_VENUE_PATTERN = re.compile(r"abstracts?\b", re.IGNORECASE)
POSTER_TITLE_PATTERN = re.compile(r":\s*\d{2,4}$")


def is_poster(pub):
    venue = pub.get("venue") or ""
    title = pub.get("title") or ""
    return bool(POSTER_VENUE_PATTERN.search(venue) or POSTER_TITLE_PATTERN.search(title))

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
    article, its preprint, and a conference abstract of it) into one entry,
    keeping the most-cited version."""
    groups = []
    for pub in publications:
        for group in groups:
            if _same_paper(pub.get("title"), group[0].get("title")):
                group.append(pub)
                break
        else:
            groups.append([pub])
    return [max(group, key=lambda p: p.get("citations") or 0) for group in groups]


def load_profile():
    profile = yaml.safe_load((DATA / "profile.yaml").read_text())
    scholar_id = profile.get("scholar_id", "")
    if not scholar_id or scholar_id.startswith("XXXX"):
        print("No real scholar_id set in data/profile.yaml yet; skipping fetch.")
        sys.exit(0)
    return scholar_id, profile.get("name")


def fetch_via_serpapi(scholar_id, api_key, owner_name):
    from serpapi import GoogleSearch

    params = {
        "engine": "google_scholar_author",
        "author_id": scholar_id,
        "api_key": api_key,
    }
    results = GoogleSearch(params).get_dict()
    articles = results.get("articles", [])
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
    return publications


def fetch_via_scholarly(scholar_id, owner_name):
    from scholarly import scholarly

    author = scholarly.search_author_id(scholar_id)
    author = scholarly.fill(author, sections=["publications"])
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
    return publications


def main():
    scholar_id, owner_name = load_profile()
    api_key = os.environ.get("SERPAPI_KEY")

    try:
        if api_key:
            print("Fetching publications via SerpApi...")
            publications = fetch_via_serpapi(scholar_id, api_key, owner_name)
        else:
            print("Fetching publications via scholarly (may be blocked in CI)...")
            publications = fetch_via_scholarly(scholar_id, owner_name)
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

    out_path = DATA / "publications.json"
    out_path.write_text(json.dumps(publications, indent=2))
    print(f"Wrote {len(publications)} publications to {out_path}")


if __name__ == "__main__":
    main()
