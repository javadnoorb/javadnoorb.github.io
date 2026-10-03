"""
Renders the Jinja2 templates + data into the static site in _site/, and
generates a PDF version of the resume with WeasyPrint. _site/ is build
output only (gitignored); CI uploads it straight to GitHub Pages.
"""
import hashlib
import json
import re
import shutil
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
OUTPUT = ROOT / "_site"

PAGES = ["index.html", "research.html", "projects.html", "publications.html", "resume.html"]
OG_IMAGE = "static/images/og-profile.png"


def load_data():
    profile = yaml.safe_load((DATA / "profile.yaml").read_text())
    # "{years}" in the bio is the years since career_start_year, so the
    # number never goes stale.
    if profile.get("bio") and profile.get("career_start_year"):
        years = date.today().year - int(profile["career_start_year"])
        profile["bio"] = profile["bio"].replace("{years}", str(years))
    pubs_path = DATA / "publications.json"
    publications = json.loads(pubs_path.read_text()) if pubs_path.exists() else []
    publications.sort(key=lambda p: p.get("year") or 0, reverse=True)
    stats_path = DATA / "scholar_stats.json"
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    return profile, publications, stats


def get_initials(name):
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def asset_version(rel_path):
    """Content hash for a static asset, used as a `?v=` cache-busting query
    string. Keyed to content rather than build time, so an unchanged file
    keeps the same URL forever (and stays cacheable) while a changed file
    always gets a fresh one - the browser never has to be trusted to
    revalidate on its own, which mobile Chrome in particular has proven
    unreliable about even within GitHub Pages' 10-minute max-age."""
    if rel_path == "resume.pdf":
        # The generated PDF's bytes aren't deterministic (WeasyPrint embeds
        # a creation timestamp), so hash the inputs that actually determine
        # its visible content instead of the output file.
        sources = [DATA / "profile.yaml", DATA / "publications.json", TEMPLATES / "resume_pdf.html",
                   ROOT / "scripts" / "build.py"]
    else:
        sources = [ROOT / rel_path]
    h = hashlib.md5()
    for src in sources:
        if src.exists():
            h.update(src.read_bytes())
    return h.hexdigest()[:8]


@lru_cache(maxsize=None)
def image_size(rel_path):
    """(width, height) of a static image, so templates can set explicit
    dimensions and the page doesn't jump around as figures load."""
    path = ROOT / rel_path
    try:
        from PIL import Image
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


MONTHS = {m: m[:3] for m in ["January", "February", "March", "April", "May", "June", "July",
                             "August", "September", "October", "November", "December"]}
DEGREE_PREFIX = re.compile(r"^(?:PhD|MD|MS|MSc|BS|BSc|MA|MPH|DVM)\s+")
# Scholar's venue strings are inconsistently cased ("Nature communications",
# "PLoS computational biology"). Title-case them for display, keeping short
# connecting words lowercase and leaving mixed-case names (bioRxiv) alone.
LOWERCASE_WORDS = {"of", "and", "in", "for", "the", "on", "to"}
VENUE_SPELLINGS = {"biorxiv": "bioRxiv", "medrxiv": "medRxiv", "arxiv": "arXiv"}
PREPRINT_VENUES = {"biorxiv", "medrxiv", "arxiv"}


def short_period(period):
    """'September 2009 - December 2014' -> 'Sep 2009 – Dec 2014'."""
    text = period or ""
    for full, abbr in MONTHS.items():
        text = text.replace(full, abbr)
    return text.replace(" - ", " – ")


def author_names(authors):
    """Split Scholar's two author-list shapes ('A and B and C' vs
    'A, B, C, et al.') into a list of names, degree prefixes stripped.
    A trailing 'et al.' / '...' stays in the list as its own entry."""
    if not authors:
        return []
    names = [n.strip() for n in re.split(r",\s*| and ", authors) if n.strip()]
    return [DEGREE_PREFIX.sub("", name) for name in names]


def format_authors(authors):
    """Normalize author lists into one comma-separated form. The owner's
    name is deliberately not emphasized: bolding it in every entry read as
    showy and competed with the paper titles."""
    return ", ".join(author_names(authors))


def is_truncated(names):
    return bool(names) and names[-1].rstrip(".") in ("et al", "…", "..")


def _same_person(name, owner):
    """'Javad Noorbakhsh' matches 'J Noorbakhsh' and 'Javad Noorbakhsh'."""
    a, b = name.lower().split(), (owner or "").lower().split()
    return bool(a and b) and a[-1] == b[-1] and a[0][0] == b[0][0]


def author_role(authors, owner):
    """'first' / 'senior' when the owner's position is actually known from
    the list, else None. The fetch step may swap the owner into the last
    visible slot of a truncated list, so only position 1, or the final slot
    of an untruncated list, is trusted."""
    names = author_names(authors)
    if len(names) < 2:
        return None
    if _same_person(names[0], owner):
        return "first"
    if not is_truncated(names) and _same_person(names[-1], owner):
        return "senior"
    return None


def author_position(authors, owner):
    """The owner's 1-based position in the author list, or None when it
    isn't trustworthy. In a truncated list the last visible slot may hold
    the owner swapped in by the fetch step, so it's not a real position."""
    names = author_names(authors)
    truncated = is_truncated(names)
    shown = names[:-1] if truncated else names
    for i, name in enumerate(shown):
        if _same_person(name, owner):
            if truncated and i == len(shown) - 1:
                return None
            return i + 1
    return None


def format_venue(venue):
    if not venue or venue == "None":
        return ""
    if venue.lower() in VENUE_SPELLINGS:
        return VENUE_SPELLINGS[venue.lower()]
    words = venue.split()
    fixed = []
    for i, word in enumerate(words):
        if word != word.lower():
            fixed.append(word)
        elif i > 0 and word in LOWERCASE_WORDS:
            fixed.append(word)
        else:
            fixed.append(word[:1].upper() + word[1:])
    return " ".join(fixed)


def is_preprint(pub):
    venue = (pub.get("venue") or "").lower()
    link = (pub.get("link") or "").lower()
    return venue in PREPRINT_VENUES or any(f"{v}.org" in link for v in PREPRINT_VENUES)


def display_url(url):
    """Strip scheme/www/trailing slash for a compact printed link."""
    return re.sub(r"^https?://(www\.)?", "", url or "").rstrip("/")


DOI_PATTERN = re.compile(r"\b(10\.\d{4,9}/[^\s?#&]+)")
# Publisher URLs that embed the DOI suffix without the "10.xxxx/" prefix.
DOI_FROM_PATH = [
    (re.compile(r"nature\.com/articles/([^/?#]+)"), "10.1038/{}"),
]
# OUP article URLs append an internal id after the DOI
# (.../doi/10.1093/gigascience/giaf128/8287720).
OUP_DOI = re.compile(r"academic\.oup\.com/.*/doi/(10\.1093/[^/]+/[^/?#]+)")


def doi_from_link(link):
    """Best-effort DOI recovered from a publisher URL, or ''."""
    link = link or ""
    if "patents.google.com" in link:
        return ""
    m = OUP_DOI.search(link)
    if m:
        return m.group(1)
    m = DOI_PATTERN.search(link)
    if m:
        return re.sub(r"\.(abstract|full(\.pdf)?)$", "", m.group(1)).rstrip("/")
    for pattern, template in DOI_FROM_PATH:
        m = pattern.search(link)
        if m:
            return template.format(m.group(1))
    return ""


def pub_doi(pub):
    return pub.get("doi") or doi_from_link(pub.get("link"))


BIBTEX_SPECIAL = str.maketrans({"&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_"})


def bibtex_key(pub, used=None):
    names = [n for n in author_names(pub.get("authors")) if not is_truncated([n])]
    surname = re.sub(r"[^a-z]", "", names[0].split()[-1].lower()) if names else "anon"
    words = [w for w in re.findall(r"[a-z]+", (pub.get("title") or "").lower()) if len(w) > 3]
    key = f"{surname}{pub.get('year') or ''}{words[0] if words else ''}"
    if used is not None:
        base, n = key, 1
        while key in used:
            n += 1
            key = f"{base}{n}"
        used.add(key)
    return key


def bibtex_entry(pub, key=None):
    names = author_names(pub.get("authors"))
    authors = [n for n in names if not is_truncated([n])]
    if is_truncated(names):
        authors.append("others")
    venue = format_venue(pub.get("venue"))
    fields = [("title", "{" + (pub.get("title") or "").rstrip(".") + "}"),
              ("author", " and ".join(authors))]
    if venue:
        fields.append(("howpublished" if is_preprint(pub) else "journal", venue))
    if pub.get("year"):
        fields.append(("year", str(pub["year"])))
    doi = pub_doi(pub)
    if doi:
        fields.append(("doi", doi))
    if pub.get("link"):
        fields.append(("url", pub["link"]))
    kind = "misc" if is_preprint(pub) else "article"
    body = ",\n".join(f"  {name} = {{{value.translate(BIBTEX_SPECIAL) if name not in ('url', 'doi') else value}}}"
                      for name, value in fields)
    return f"@{kind}{{{key or bibtex_key(pub)},\n{body}\n}}"


def enrich(publications, owner):
    """Attach display-only fields (DOI, author role, BibTeX) to each paper."""
    used = set()
    for pub in publications:
        pub["doi"] = pub_doi(pub)
        pub["role"] = author_role(pub.get("authors"), owner)
        pub["position"] = author_position(pub.get("authors"), owner)
        pub["bibtex_key"] = bibtex_key(pub, used)
        pub["bibtex"] = bibtex_entry(pub, pub["bibtex_key"])
    return publications


def group_by_year(publications):
    """Newest year first; papers Scholar gave no year for go last under
    'Undated' (Jinja's groupby would crash comparing None with ints)."""
    groups = {}
    for pub in publications:
        groups.setdefault(pub.get("year"), []).append(pub)
    dated = sorted((y for y in groups if y), reverse=True)
    result = [(y, groups[y]) for y in dated]
    if None in groups:
        result.append(("Undated", groups[None]))
    return result


def get_highlighted(publications, count=5):
    """Favors impact over recency: most-cited papers, shown newest-first
    among themselves so the selection doesn't read as a fixed leaderboard."""
    ranked = sorted(publications, key=lambda p: p.get("citations") or 0, reverse=True)
    highlighted = ranked[:count]
    highlighted.sort(key=lambda p: p.get("year") or 0, reverse=True)
    return highlighted


PATENT_LINK = re.compile(r"patents\.google\.com/patent/([A-Z]{2})(\d{4})(\d+)([A-Z]\d)?")


def patent_number(link):
    """'.../patent/US20250378559A1/en' -> 'US 2025/0378559 A1'."""
    m = PATENT_LINK.search(link or "")
    if not m:
        return ""
    country, year, serial, kind = m.groups()
    return f"{country} {year}/{serial}" + (f" {kind}" if kind else "")


def split_patents(publications):
    """Scholar lists patents alongside papers; the site and PDF show them apart."""
    papers, patents = [], []
    for pub in publications:
        (patents if patent_number(pub.get("link")) else papers).append(pub)
    return papers, patents


def site_url(profile):
    return (profile.get("site_url") or "").rstrip("/") + "/"


def person_jsonld(profile):
    """schema.org Person markup, so search engines can tie the site to the
    same person's Scholar/ORCID/GitHub/LinkedIn profiles."""
    url = site_url(profile)
    data = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": profile.get("name"),
        "jobTitle": profile.get("title"),
        "url": url,
        "image": url + OG_IMAGE,
        "description": " ".join((profile.get("bio") or "").split()),
        "sameAs": [u for u in (profile.get("social") or {}).values() if u],
    }
    if profile.get("location"):
        data["address"] = {"@type": "PostalAddress", "addressLocality": profile["location"]}
    return data


def render_site(env, profile, publications, stats):
    OUTPUT.mkdir(exist_ok=True)
    papers, patents = split_patents(publications)
    enrich(papers, profile.get("name"))
    context = dict(
        profile=profile, publications=papers, patents=patents, stats=stats,
        highlighted=get_highlighted(papers),
        lead_author_papers=[p for p in papers if p["position"] in (1, 2)],
        year_groups=group_by_year(papers),
        initials=get_initials(profile.get("name")), site_url=site_url(profile),
        og_image=OG_IMAGE, person_jsonld=person_jsonld(profile),
    )
    for name in PAGES + ["404.html"]:
        html = env.get_template(name).render(page=name, **context)
        (OUTPUT / name).write_text(html)
    bib = "\n\n".join(p["bibtex"] for p in papers)
    (OUTPUT / "publications.bib").write_text(bib + "\n")


def write_seo_files(profile):
    url = site_url(profile)
    entries = "\n".join(f"  <url><loc>{url}{'' if page == 'index.html' else page}</loc></url>"
                         for page in PAGES)
    (OUTPUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n</urlset>\n")
    (OUTPUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {url}sitemap.xml\n")


def copy_static():
    dest = OUTPUT / "static"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(STATIC, dest)
    # Link-preview crawlers (LinkedIn, Slack, ...) don't reliably accept
    # WebP and want at least ~200px, so derive a PNG social card image.
    try:
        from PIL import Image
        with Image.open(STATIC / "images" / "profile.webp") as img:
            img.convert("RGB").resize((400, 400), Image.LANCZOS).save(OUTPUT / OG_IMAGE)
    except Exception as e:
        print(f"Could not generate {OG_IMAGE}: {e}")


def render_pdf(env, profile, publications):
    try:
        from weasyprint import HTML
    except ImportError:
        print("weasyprint not installed, skipping PDF generation")
        return
    template = env.get_template("resume_pdf.html")
    papers, patents = split_patents(publications)
    html_str = template.render(profile=profile, publications=papers, patents=patents)
    HTML(string=html_str, base_url=str(ROOT)).write_pdf(OUTPUT / "resume.pdf")


def make_env():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    env.globals["asset_version"] = asset_version
    env.globals["image_size"] = image_size
    env.filters["short_period"] = short_period
    env.filters["format_authors"] = format_authors
    env.filters["format_venue"] = format_venue
    env.filters["display_url"] = display_url
    env.filters["patent_number"] = patent_number
    return env


def main():
    env = make_env()
    profile, publications, stats = load_data()
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    render_site(env, profile, publications, stats)
    copy_static()
    write_seo_files(profile)
    render_pdf(env, profile, publications)
    (OUTPUT / ".nojekyll").touch()
    print(f"Built site with {len(publications)} publications -> {OUTPUT}")


if __name__ == "__main__":
    main()
