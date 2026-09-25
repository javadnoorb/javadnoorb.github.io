"""
Renders the Jinja2 templates + data into the static site in docs/, and
generates a PDF version of the resume with WeasyPrint.
"""
import hashlib
import json
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
        sources = [DATA / "profile.yaml", DATA / "publications.json", TEMPLATES / "resume_pdf.html"]
    else:
        sources = [ROOT / rel_path]
    h = hashlib.md5()
    for src in sources:
        if src.exists():
            h.update(src.read_bytes())
    return h.hexdigest()[:8]


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
    highlighted = get_highlighted(publications)
    pages = ["index.html", "research.html", "projects.html", "publications.html", "resume.html"]
    for name in pages:
        template = env.get_template(name)
        html = template.render(profile=profile, publications=publications,
                                highlighted=highlighted, initials=initials)
        (OUTPUT / name).write_text(html)


def copy_static():
    dest = OUTPUT / "static"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(STATIC, dest)


def render_pdf(env, profile, publications):
    try:
        from weasyprint import HTML
    except ImportError:
        print("weasyprint not installed, skipping PDF generation")
        return
    template = env.get_template("resume_pdf.html")
    html_str = template.render(profile=profile, publications=publications)
    HTML(string=html_str, base_url=str(ROOT)).write_pdf(OUTPUT / "resume.pdf")


def main():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    env.globals["asset_version"] = asset_version
    profile, publications = load_data()
    render_site(env, profile, publications)
    copy_static()
    render_pdf(env, profile, publications)
    (OUTPUT / ".nojekyll").touch()
    print(f"Built site with {len(publications)} publications -> {OUTPUT}")


if __name__ == "__main__":
    main()
