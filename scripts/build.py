"""
Renders the Jinja2 templates + data into the static site in docs/, and
generates a PDF version of the resume with WeasyPrint.
"""
import hashlib
import json
import re
import shutil
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
OUTPUT = ROOT / "docs"


def load_data():
    profile = yaml.safe_load((DATA / "profile.yaml").read_text())
    pubs_path = DATA / "publications.json"
    publications = json.loads(pubs_path.read_text()) if pubs_path.exists() else []
    publications.sort(key=lambda p: p.get("year") or 0, reverse=True)
    return profile, publications


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


MONTHS = {m: m[:3] for m in ["January", "February", "March", "April", "May", "June", "July",
                             "August", "September", "October", "November", "December"]}
DEGREE_PREFIX = re.compile(r"^(?:PhD|MD|MS|MSc|BS|BSc|MA|MPH|DVM)\s+")
# Scholar's venue strings are inconsistently cased ("Nature communications",
# "PLoS computational biology"). Title-case them for display, keeping short
# connecting words lowercase and leaving mixed-case names (bioRxiv) alone.
LOWERCASE_WORDS = {"of", "and", "in", "for", "the", "on", "to"}
VENUE_SPELLINGS = {"biorxiv": "bioRxiv", "medrxiv": "medRxiv", "arxiv": "arXiv"}


def short_period(period):
    """'September 2009 - December 2014' -> 'Sep 2009 – Dec 2014'."""
    text = period or ""
    for full, abbr in MONTHS.items():
        text = text.replace(full, abbr)
    return text.replace(" - ", " – ")


def format_authors(authors):
    """Normalize Scholar's two author-list shapes ('A and B and C' vs
    'A, B, C, et al.') into one comma-separated form and strip stray degree
    prefixes. The owner's name is deliberately not emphasized: bolding it
    in every entry read as showy and competed with the paper titles."""
    if not authors:
        return ""
    names = [n.strip() for n in re.split(r",\s*| and ", authors) if n.strip()]
    return ", ".join(DEGREE_PREFIX.sub("", name) for name in names)


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


def display_url(url):
    """Strip scheme/www/trailing slash for a compact printed link."""
    return re.sub(r"^https?://(www\.)?", "", url or "").rstrip("/")


def get_highlighted(publications, count=5):
    """Favors impact over recency: most-cited papers, shown newest-first
    among themselves so the selection doesn't read as a fixed leaderboard."""
    ranked = sorted(publications, key=lambda p: p.get("citations") or 0, reverse=True)
    highlighted = ranked[:count]
    highlighted.sort(key=lambda p: p.get("year") or 0, reverse=True)
    return highlighted


def render_site(env, profile, publications):
    OUTPUT.mkdir(exist_ok=True)
    initials = get_initials(profile.get("name"))
    papers, patents = split_patents(publications)
    highlighted = get_highlighted(papers)
    pages = ["index.html", "research.html", "projects.html", "publications.html", "resume.html"]
    for name in pages:
        template = env.get_template(name)
        html = template.render(profile=profile, publications=papers, patents=patents,
                                highlighted=highlighted, initials=initials)
        (OUTPUT / name).write_text(html)


def copy_static():
    dest = OUTPUT / "static"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(STATIC, dest)


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


def main():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    env.globals["asset_version"] = asset_version
    env.filters["short_period"] = short_period
    env.filters["format_authors"] = format_authors
    env.filters["format_venue"] = format_venue
    env.filters["display_url"] = display_url
    env.filters["patent_number"] = patent_number
    profile, publications = load_data()
    render_site(env, profile, publications)
    copy_static()
    render_pdf(env, profile, publications)
    (OUTPUT / ".nojekyll").touch()
    print(f"Built site with {len(publications)} publications -> {OUTPUT}")


if __name__ == "__main__":
    main()
