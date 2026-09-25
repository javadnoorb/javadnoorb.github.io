"""
Renders the Jinja2 templates + data into the static site in docs/, and
generates a PDF version of the resume with WeasyPrint.
"""
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


def render_site(env, profile, publications):
    OUTPUT.mkdir(exist_ok=True)
    pages = ["index.html", "publications.html", "resume.html"]
    for name in pages:
        template = env.get_template(name)
        html = template.render(profile=profile, publications=publications)
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
    profile, publications = load_data()
    render_site(env, profile, publications)
    copy_static()
    render_pdf(env, profile, publications)
    (OUTPUT / ".nojekyll").touch()
    print(f"Built site with {len(publications)} publications -> {OUTPUT}")


if __name__ == "__main__":
    main()
