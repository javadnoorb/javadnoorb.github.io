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
import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

MAX_AUTHORS = 5


def truncate_authors(authors):
    if not authors:
        return authors
    separator = " and " if " and " in authors else ", "
    names = [n.strip() for n in authors.split(separator)]
    if len(names) <= MAX_AUTHORS:
        return authors
    return ", ".join(names[:MAX_AUTHORS]) + ", et al."


def load_scholar_id():
    profile = yaml.safe_load((DATA / "profile.yaml").read_text())
    scholar_id = profile.get("scholar_id", "")
    if not scholar_id or scholar_id.startswith("XXXX"):
        print("No real scholar_id set in data/profile.yaml yet; skipping fetch.")
        sys.exit(0)
    return scholar_id


def fetch_via_serpapi(scholar_id, api_key):
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
            "authors": truncate_authors(a.get("authors")),
            "venue": a.get("publication"),
            "year": int(year) if str(year).isdigit() else None,
            "citations": (a.get("cited_by") or {}).get("value"),
            "link": a.get("link"),
        })
    return publications


def fetch_via_scholarly(scholar_id):
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
            "authors": truncate_authors(bib.get("author")),
            "venue": bib.get("venue") or bib.get("journal"),
            "year": int(year) if str(year).isdigit() else None,
            "citations": filled.get("num_citations"),
            "link": filled.get("pub_url"),
        })
    return publications


def main():
    scholar_id = load_scholar_id()
    api_key = os.environ.get("SERPAPI_KEY")

    try:
        if api_key:
            print("Fetching publications via SerpApi...")
            publications = fetch_via_serpapi(scholar_id, api_key)
        else:
            print("Fetching publications via scholarly (may be blocked in CI)...")
            publications = fetch_via_scholarly(scholar_id)
    except Exception as e:
        print(f"Failed to fetch publications: {e}")
        print("Leaving existing publications.json untouched.")
        sys.exit(0)

    if not publications:
        print("Fetch returned zero publications; leaving existing file untouched.")
        sys.exit(0)

    out_path = DATA / "publications.json"
    out_path.write_text(json.dumps(publications, indent=2))
    print(f"Wrote {len(publications)} publications to {out_path}")


if __name__ == "__main__":
    main()
