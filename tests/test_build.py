import re

import build
import pytest

OWNER = "Javad Noorbakhsh"


def test_get_highlighted_uses_picks_in_order():
    pubs = [{"title": "Alpha study", "year": 2020, "citations": 5},
            {"title": "Beta: a study", "year": 2024, "citations": 1},
            {"title": "Gamma", "year": 2019, "citations": 900}]
    assert [p["title"] for p in build.get_highlighted(pubs, picks=["beta a", "ALPHA", "missing"])] == \
        ["Beta: a study", "Alpha study"]
    assert build.get_highlighted(pubs, count=1)[0]["title"] == "Gamma"


def test_format_authors_bolds_owner_only_when_asked():
    authors = "A Smith, J Noorbakhsh, et al."
    assert build.format_authors(authors) == "A Smith, J Noorbakhsh, et al."
    assert build.format_authors(authors, "Javad Noorbakhsh") == \
        "A Smith, <strong>J Noorbakhsh</strong>, et al."


def test_format_authors_normalizes_both_scholar_shapes():
    assert build.format_authors("A Smith and B Jones and C Wu") == "A Smith, B Jones, C Wu"
    assert build.format_authors("A Smith, B Jones, et al.") == "A Smith, B Jones, et al."
    assert build.format_authors("PhD Javad Noorbakhsh and MS Harshpreet Chandok") == \
        "Javad Noorbakhsh, Harshpreet Chandok"
    assert build.format_authors(None) == ""


@pytest.mark.parametrize("raw, expected", [
    ("Nature communications", "Nature Communications"),
    ("PLoS computational biology", "PLoS Computational Biology"),
    ("Journal of the american", "Journal of the American"),
    ("BioRxiv", "bioRxiv"),
    ("medrxiv", "medRxiv"),
    ("ACM-BCB 2020", "ACM-BCB 2020"),
    ("None", ""),
    (None, ""),
])
def test_format_venue(raw, expected):
    assert build.format_venue(raw) == expected


def test_patent_number():
    assert build.patent_number("https://patents.google.com/patent/US20250378559A1/en") == "US 2025/0378559 A1"
    assert build.patent_number("https://patents.google.com/patent/US12380555B2/en") == "US 12,380,555 B2"
    assert build.patent_number("https://www.nature.com/articles/ng.3876") == ""


def test_patent_citation():
    assert (build.patent_citation("https://patents.google.com/patent/US20250378559A1/en")
            == "U.S. Patent Application US 2025/0378559 A1")
    assert build.patent_citation("https://patents.google.com/patent/US12380555B2/en") == "U.S. Patent 12,380,555 B2"
    assert build.patent_citation("https://www.nature.com/articles/ng.3876") == ""


def test_split_patents():
    pubs = [{"link": "https://patents.google.com/patent/US20250378559A1/en"},
            {"link": "https://www.nature.com/articles/ng.3876"}]
    papers, patents = build.split_patents(pubs)
    assert papers == [pubs[1]] and patents == [pubs[0]]


@pytest.mark.parametrize("link, doi", [
    ("https://www.nature.com/articles/ng.3876", "10.1038/ng.3876"),
    ("https://www.nature.com/articles/s41586-019-1775-1", "10.1038/s41586-019-1775-1"),
    ("https://link.springer.com/article/10.15252/msb.20145352", "10.15252/msb.20145352"),
    ("https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0072676", "10.1371/journal.pone.0072676"),
    ("https://www.biorxiv.org/content/10.1101/2024.04.28.591552.abstract", "10.1101/2024.04.28.591552"),
    ("https://academic.oup.com/gigascience/article-abstract/doi/10.1093/gigascience/giaf128/8287720",
     "10.1093/gigascience/giaf128"),
    ("https://dl.acm.org/doi/abs/10.1145/3388440.3412414", "10.1145/3388440.3412414"),
    ("https://www.sciencedirect.com/science/article/pii/S2589408019300110", ""),
    ("https://patents.google.com/patent/US20250378559A1/en", ""),
    (None, ""),
])
def test_doi_from_link(link, doi):
    assert build.doi_from_link(link) == doi


@pytest.mark.parametrize("authors, role", [
    ("Javad Noorbakhsh and Jeffrey H Chuang", "first"),
    ("J Noorbakhsh, A Smith, et al.", "first"),
    ("Jeffrey H Chuang and Javad Noorbakhsh", "senior"),
    # A truncated list's last slot may be the owner swapped in by the
    # fetch step, so it says nothing about real author position.
    ("A Smith, B Jones, C Wu, D Lee, Javad Noorbakhsh, et al.", None),
    ("A Smith and Javad Noorbakhsh and C Wu", None),
    ("Javad Noorbakhsh", None),
    (None, None),
])
def test_author_role(authors, role):
    assert build.author_role(authors, OWNER) == role


@pytest.mark.parametrize("authors, position", [
    ("Javad Noorbakhsh and Jeffrey H Chuang", 1),
    ("Lin Chen, Javad Noorbakhsh, Rhys M Adams, B Jones, C Wu, et al.", 2),
    ("A Smith and B Jones and Javad Noorbakhsh", 3),
    # Last visible slot of a truncated list may be the swapped-in owner.
    ("A Smith, B Jones, C Wu, D Lee, Javad Noorbakhsh, et al.", None),
    ("A Smith and B Jones", None),
    (None, None),
])
def test_author_position(authors, position):
    assert build.author_position(authors, OWNER) == position


def test_group_by_year_puts_undated_last():
    pubs = [{"year": 2019}, {"year": None}, {"year": 2024}, {"year": 2019}]
    groups = build.group_by_year(pubs)
    assert [y for y, _ in groups] == [2024, 2019, "Undated"]
    assert len(groups[1][1]) == 2


def test_get_highlighted_picks_most_cited_then_sorts_by_year():
    pubs = [{"year": 2010, "citations": 500}, {"year": 2024, "citations": 1},
            {"year": 2020, "citations": 50}]
    assert [p["year"] for p in build.get_highlighted(pubs, count=2)] == [2020, 2010]


def test_bibtex_entry():
    pub = {"title": "Treating cancer as an invasive species", "venue": "Molecular Cancer Research",
           "year": 2020, "authors": "Javad Noorbakhsh, Zi-Ming Zhao, et al.",
           "link": "https://www.nature.com/articles/abc"}
    entry = build.bibtex_entry(pub)
    assert entry.startswith("@article{noorbakhsh2020treating,")
    assert "author = {Javad Noorbakhsh and Zi-Ming Zhao and others}" in entry
    assert "doi = {10.1038/abc}" in entry
    preprint = build.bibtex_entry(dict(pub, venue="bioRxiv", title="R&D at 50% scale"))
    assert preprint.startswith("@misc{") and r"R\&D at 50\% scale" in preprint


def test_bibtex_keys_are_unique():
    used = set()
    pub = {"title": "Same title here", "year": 2020, "authors": "A Smith"}
    assert build.bibtex_key(pub, used) == "smith2020same"
    assert build.bibtex_key(pub, used) == "smith2020same2"


def test_site_renders(tmp_path, monkeypatch):
    """Smoke test: every page renders from the real data without errors."""
    monkeypatch.setattr(build, "OUTPUT", tmp_path)
    profile, publications, stats = build.load_data()
    build.render_site(build.make_env(), profile, publications, stats)
    build.write_seo_files(profile)
    for page in build.PAGES + ["404.html"]:
        html = (tmp_path / page).read_text()
        assert "<title>" in html and 'name="description"' in html
    assert 'aria-current="page"' in (tmp_path / "publications.html").read_text()
    assert (tmp_path / "publications.bib").read_text().count("@") >= 1
    assert "<loc>https://javadnoorb.github.io/</loc>" in (tmp_path / "sitemap.xml").read_text()


def test_scholar_stats_render_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "OUTPUT", tmp_path)
    profile, publications, _ = build.load_data()
    build.render_site(build.make_env(), profile, publications,
                      {"citations": 1734, "h_index": 16, "i10_index": 20})
    html = (tmp_path / "index.html").read_text()
    assert "<strong>1,734</strong> citations" in html
    # h-index and i10-index are fetched but deliberately not shown.
    assert "h-index" not in html and "i10-index" not in html


def test_homepage_links_each_profile_once(tmp_path, monkeypatch):
    """The icon buttons are the only homepage link to each profile; the
    Publications page, which has no buttons, keeps its Scholar link."""
    monkeypatch.setattr(build, "OUTPUT", tmp_path)
    profile, publications, _ = build.load_data()
    build.render_site(build.make_env(), profile, publications, {"citations": 1734})
    home = (tmp_path / "index.html").read_text()
    for url in filter(None, profile["social"].values()):
        assert home.count(f'href="{url}"') == 1, url
    if profile["social"].get("scholar"):
        assert f'href="{profile["social"]["scholar"]}"' in (tmp_path / "publications.html").read_text()


def test_pub_meta_skips_blank_parts():
    template = build.make_env().from_string(
        '{% from "_macros.html" import pub_meta, citation_badge %}'
        "{{ pub_meta(pub) }}|{{ pub_meta(pub, year=false) }}|{{ citation_badge(pub) }}")
    pub = {"authors": "A Smith and B Jones", "venue": None, "year": 2020, "citations": 1}
    assert template.render(pub=pub) == \
        ('A Smith, B Jones &middot; 2020|A Smith, B Jones|'
         '<span class="visually-hidden"> &middot; </span><span class="citation-badge">1 citation</span>')
    pub.update(venue="nature communications", year=None, citations=2)
    assert template.render(pub=pub).startswith(
        "A Smith, B Jones &middot; Nature Communications|A Smith, B Jones &middot; Nature Communications|")
    assert "2 citations" in template.render(pub=pub)


def test_built_site_has_no_broken_local_links(tmp_path, monkeypatch):
    """Every relative href/src in the rendered pages points at a file the
    build actually produces (pages, static assets, highlight figures)."""
    monkeypatch.setattr(build, "OUTPUT", tmp_path)
    monkeypatch.setattr(build, "render_pdf", lambda *args: (tmp_path / "resume.pdf").touch())
    build.main()
    missing = []
    for page in tmp_path.glob("*.html"):
        for url in re.findall(r'(?:href|src)="([^"]+)"', page.read_text()):
            if url.startswith(("http:", "https:", "mailto:", "data:", "#", "/")):
                continue
            if not (tmp_path / url.split("?")[0].split("#")[0]).exists():
                missing.append(f"{page.name} -> {url}")
    assert not missing


def test_icon_inlines_decorative_svg():
    line = str(build.icon("github"))
    assert line.startswith("<svg ") and 'aria-hidden="true"' in line
    assert 'stroke="currentColor"' in line and "@license" not in line
    brand = str(build.icon("orcid"))
    assert 'fill="currentColor"' in brand and "<title>" not in brand


# --- Link integrity -------------------------------------------------------
# A Scholar scrape once came back with link=None for every paper, and the
# templates rendered it as href="None" - 28 dead title links went live.

def test_pub_url_falls_back_to_doi_then_empty():
    assert build.pub_url({"link": "https://x.org/a", "doi": "10.1/b"}) == "https://x.org/a"
    assert build.pub_url({"link": None, "doi": "10.1/b"}) == "https://doi.org/10.1/b"
    assert build.pub_url({"link": None}) == ""
    assert build.pub_url({}) == ""


HREF = re.compile(r'\b(?:href|src)="([^"]*)"')


def _render(tmp_path, monkeypatch, publications):
    monkeypatch.setattr(build, "OUTPUT", tmp_path)
    profile, _, stats = build.load_data()
    build.render_site(build.make_env(), profile, publications, stats)
    return {p.name: p.read_text() for p in tmp_path.glob("*.html")}


def _assert_links_ok(pages):
    built = {"publications.bib", "resume.pdf", "sitemap.xml"}
    for name, html in pages.items():
        for url in HREF.findall(html):
            assert url.strip(), f"{name}: empty href/src"
            assert url not in ("None", "none", "null", "undefined"), f"{name}: href={url!r}"
            assert "None" not in url.split("/")[-1:], f"{name}: href={url!r}"
            if re.match(r"^(https?:|mailto:|data:|#|//)", url):
                continue
            path = url.split("#")[0].split("?")[0]
            if not path or path.endswith("/"):  # sibling GitHub Pages project sites
                continue
            assert (path in built or (build.OUTPUT / path).exists()
                    or (build.ROOT / path).exists()), f"{name}: broken internal link {url!r}"


def test_built_pages_have_no_broken_links(tmp_path, monkeypatch):
    _, publications, _ = build.load_data()
    _assert_links_ok(_render(tmp_path, monkeypatch, publications))


def test_bare_publications_render_without_none_links(tmp_path, monkeypatch):
    bare = [{"title": "Doi only paper", "year": 2024, "citations": 3, "doi": "10.1234/abc"},
            {"title": "Nothing known paper", "year": 2023, "citations": 1}]
    pages = _render(tmp_path, monkeypatch, bare)
    _assert_links_ok(pages)
    assert 'href="https://doi.org/10.1234/abc"' in pages["publications.html"]
    assert "Nothing known paper" in pages["publications.html"]


def test_committed_publication_data_is_complete():
    """Guards data/publications.json itself, so a degraded scrape fails CI
    before it is deployed or committed."""
    _, publications, _ = build.load_data()
    assert publications
    for pub in publications:
        assert pub.get("title"), pub
        assert build.pub_url(pub), f"no link or DOI: {pub['title']!r}"
        assert pub.get("authors"), f"no authors: {pub['title']!r}"


def test_committed_scholar_stats_are_sane():
    """Guards data/scholar_stats.json, which the weekly job also rewrites."""
    import datetime
    _, publications, stats = build.load_data()
    assert isinstance(stats.get("citations"), int) and stats["citations"] > 0
    for key in ("h_index", "i10_index"):
        if key in stats:
            assert isinstance(stats[key], int) and 0 < stats[key] <= len(publications) + 50, key
    if "h_index" in stats and "i10_index" in stats:
        assert stats["i10_index"] >= stats["h_index"] or stats["h_index"] < 10
    # The total can't be below any single paper's count.
    assert stats["citations"] >= max((p.get("citations") or 0) for p in publications)
    datetime.date.fromisoformat(stats["updated"])
