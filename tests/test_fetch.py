import fetch_publications as fp


def test_truncate_authors_keeps_owner_visible():
    names = ", ".join(f"Author {i}" for i in range(10)) + ", Javad Noorbakhsh"
    out = fp.truncate_authors(names, "Javad Noorbakhsh")
    assert out.endswith("Javad Noorbakhsh, et al.")
    assert out.count(",") == 5
    assert fp.truncate_authors("A B and C D", "X") == "A B and C D"


def test_is_poster():
    assert fp.is_poster({"venue": "Cancer Research Abstracts"})
    assert fp.is_poster({"title": "Some poster: 1234"})
    assert fp.is_poster({"link": "https://aacrjournals.org/cancerres/article/83/7_Supplement/1/1"})
    assert not fp.is_poster({"title": "A real paper", "venue": "Nature"})


def test_is_garbled_title():
    assert fp.is_garbled_title("Foroughi pour A, Namburi S, Caruana D, Rimm D, et al")
    assert fp.is_garbled_title("Something and Jeffrey H")
    assert not fp.is_garbled_title("Treating cancer as an invasive species")


def test_dedupe_prefers_published_version_but_keeps_top_citations():
    journal = {"title": "Deep learning cross classification of tumor images", "venue": "Nature communications",
               "citations": 10, "link": "https://www.nature.com/articles/x"}
    preprint = {"title": "Deep learning cross-classification of tumor images", "venue": "bioRxiv",
                "citations": 40, "link": "https://www.biorxiv.org/content/10.1101/1"}
    other = {"title": "Something entirely different", "venue": "Science", "citations": 3}
    merged = fp.dedupe_publications([preprint, journal, other])
    assert len(merged) == 2
    assert merged[0]["venue"] == "Nature communications"
    assert merged[0]["citations"] == 40
    assert preprint["citations"] == 40 and journal["citations"] == 10  # inputs not mutated


def test_apply_venue_overrides_only_fills_missing():
    pubs = [{"title": "Treating Cancer as an Invasive Species", "venue": None},
            {"title": "Treating cancer as an invasive species", "venue": "Elsewhere"}]
    fp.apply_venue_overrides(pubs)
    assert pubs[0]["venue"] == "Molecular Cancer Research"
    assert pubs[1]["venue"] == "Elsewhere"


def test_looks_truncated():
    assert fp.looks_truncated(5, 24)
    assert not fp.looks_truncated(20, 24)
    assert not fp.looks_truncated(3, 0)


def test_serpapi_stats():
    results = {"cited_by": {"table": [
        {"citations": {"all": 1700, "since_2021": 900}},
        {"h_index": {"all": 16, "since_2021": 12}},
        {"i10_index": {"all": 20, "since_2021": 15}},
    ]}}
    assert fp.serpapi_stats(results) == {"citations": 1700, "h_index": 16, "i10_index": 20}
    assert fp.serpapi_stats({}) == {}


def test_add_dois_prefers_link_then_cache_and_never_raises(monkeypatch):
    def boom(pub):
        raise OSError("network down")
    monkeypatch.setattr(fp, "crossref_doi", boom)
    pubs = [{"title": "A", "link": "https://www.nature.com/articles/ng.3876"},
            {"title": "B", "link": "https://www.sciencedirect.com/science/article/pii/S1"},
            {"title": "C", "link": "https://www.sciencedirect.com/science/article/pii/S2"},
            {"title": "D", "link": "https://patents.google.com/patent/US20250378559A1/en"}]
    fp.add_dois(pubs, existing=[{"title": "B", "doi": "10.1016/b"}])
    assert pubs[0]["doi"] == "10.1038/ng.3876"
    assert pubs[1]["doi"] == "10.1016/b"
    assert "doi" not in pubs[2] and "doi" not in pubs[3]
