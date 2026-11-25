"""REQ-804: Invertierter Volltextindex mit Präfix-Abgleich (Port von
``M2InvertedIndexSelfTest``, Java-Referenz).

Exakte Treffer, Präfix-Fallback (``Ziel`` findet ``Ziele``/
``Zielsetzungen``), keine Teilstring-Treffer, Scope-Filter,
Score-Reihenfolge und Snippets.
"""

from __future__ import annotations

import pytest

from sni.search.fulltext import LocalFullTextIndex
from sni.search.page_source import PageSource


def _build_index() -> tuple[LocalFullTextIndex, PageSource, PageSource]:
    index = LocalFullTextIndex()
    p1 = PageSource(
        "d1",
        "SIA 1",
        "2026",
        1,
        "1",
        "Die Bauherrschaft definiert die Projektziele und Zielsetzungen.",
    )
    p2 = PageSource(
        "d1", "SIA 1", "2026", 2, "2", "Der Projektplan enthält Ziele, Zeitpläne und Nachweise."
    )
    p3 = PageSource("d2", "SIA 2", "2026", 1, "1", "Bauliche Normen für Gründungen und Tragwerke.")
    index.replace("d1", [p1, p2])
    index.replace("d2", [p3])
    return index, p1, p2


def test_req804_inverted_index_documents_indexed() -> None:
    index, _p1, _p2 = _build_index()
    assert index.document_count() == 2


def test_req804_inverted_index_exact_hit() -> None:
    index, _p1, _p2 = _build_index()
    exact = index.search("Bauherrschaft", {"d1"}, 5)
    assert len(exact) == 1
    assert exact[0].source.page == 1


def test_req804_inverted_index_prefix_finds_variants() -> None:
    index, _p1, _p2 = _build_index()
    prefix = index.search("Ziel", {"d1"}, 5)
    assert len(prefix) == 2
    assert {hit.source.page for hit in prefix} == {1, 2}


def test_req804_inverted_index_no_substring_hit() -> None:
    index, _p1, _p2 = _build_index()
    assert index.search("iele", {"d1"}, 5) == []


def test_req804_inverted_index_scope_filter() -> None:
    index, _p1, _p2 = _build_index()
    assert index.search("Projekt", {"d2"}, 5) == []


def test_req804_inverted_index_score_order_and_snippets() -> None:
    index, _p1, _p2 = _build_index()
    scored = index.search("Projekt Projektziele", {"d1"}, 5)
    assert len(scored) == 2
    assert scored[0].source.page == 1
    assert all(hit.snippet.strip() for hit in scored)


def test_req804_inverted_index_pages_access() -> None:
    index, _p1, _p2 = _build_index()
    doc_pages = index.pages("d1")
    assert len(doc_pages) == 2
    assert doc_pages[1].page == 2


def test_req804_inverted_index_delete() -> None:
    index, _p1, _p2 = _build_index()
    index.delete("d1")
    assert index.document_count() == 1
    assert index.search("Bauherrschaft", set(), 5) == []


def test_req804_inverted_index_wrong_document_id_rejected() -> None:
    index, p1, p2 = _build_index()
    with pytest.raises(ValueError, match="Falsche Dokument-ID"):
        index.replace("d1", [p1, p2, PageSource("d2", "SIA 2", "2026", 1, "1", "Fremd.")])
    with pytest.raises(ValueError, match="Falsche Dokument-ID"):
        index.replace("d3", [p1])


def test_req804_inverted_index_empty_query_no_hits() -> None:
    index, _p1, _p2 = _build_index()
    assert index.search("", {"d1"}, 5) == []
    assert index.search("!!!", {"d1"}, 5) == []
