import build
import pytest

OWNER = "Javad Noorbakhsh"


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
    assert build.patent_number("https://www.nature.com/articles/ng.3876") == ""


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
    assert "<strong>1,734</strong> citations" in html and "<strong>16</strong> h-index" in html
