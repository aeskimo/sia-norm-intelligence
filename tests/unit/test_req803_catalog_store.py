"""REQ-801/803: In-Memory-Katalog (``sni.shop.catalog``).

1:1-Tests des Java-Ports von ``ch.sia.reader.product.catalog.CatalogStore``:
Login-Ersetzung, Suche (Teilzeichenkette, Sprache, Gültigkeit), Score-
Sortierung (Nummer vor Titel) und Limit-Regel (Default 50, max. 500).
Synthetische Testdaten (G4).
"""

from __future__ import annotations

from datetime import date

from sni.shop.catalog import CatalogStore
from sni.shop.catalog_xml import StandardDocument


def _doc(
    product_id: str,
    number: str = "",
    title: str = "",
    language: str = "DE",
    valid_from: date | None = None,
    valid_until: date | None = None,
) -> StandardDocument:
    return StandardDocument(
        product_id=product_id,
        number=number,
        title=title,
        description="",
        keywords="",
        language=language,
        year="",
        revision="",
        valid_from=valid_from,
        valid_until=valid_until,
        remote_filename="",
        view_allowed=True,
        print_allowed=False,
        copy_allowed=False,
    )


def _store(docs: list[StandardDocument]) -> CatalogStore:
    store = CatalogStore()
    store.replace_all(docs)
    return store


def test_req803_catalog_replace_by_id_size() -> None:
    store = _store([_doc("a"), _doc("b")])
    assert store.size() == 2
    assert store.by_id("a") is not None
    assert store.by_id("zz") is None
    store.replace_all([_doc("c")])
    assert store.size() == 1
    assert store.by_id("a") is None  # Java: byId.clear()


def test_req803_catalog_search_substring_and_empty_query() -> None:
    store = _store(
        [
            _doc("a", "SIA 101", "Wärmebrüche"),
            _doc("b", "SIA 202", "Feuchtigkeit"),
        ]
    )
    assert [d.product_id for d in store.search("wärme", None, False, 50)] == ["a"]
    # Suchtext umfasst Nummer/Titel/Beschreibung/Stichworte/Sprache/Jahr/Revision.
    assert [d.product_id for d in store.search("101", None, False, 50)] == ["a"]
    assert len(store.search("", None, False, 50)) == 2  # leere Query = alle
    assert len(store.search(None, None, False, 50)) == 2


def test_req803_catalog_search_language_filter() -> None:
    store = _store([_doc("de", "SIA 1", language="DE"), _doc("fr", "SIA 2", language="FR")])
    assert [d.product_id for d in store.search(None, "fr", False, 50)] == ["fr"]
    # Java: trim + uppercase vor dem Vergleich.
    assert [d.product_id for d in store.search(None, " de ", False, 50)] == ["de"]


def test_req803_catalog_search_valid_only() -> None:
    today = date.today()
    store = _store(
        [
            _doc("valid", valid_from=today, valid_until=today),
            _doc("expired", valid_from=date(2000, 1, 1), valid_until=date(2001, 1, 1)),
            _doc("open"),  # ohne Datumsangaben = dauerhaft gültig
        ]
    )
    hits = store.search(None, None, True, 50)
    assert sorted(d.product_id for d in hits) == ["open", "valid"]
    assert len(store.search(None, None, False, 50)) == 3


def test_req803_catalog_search_score_sorting() -> None:
    # Java: score — Nummer-Exakt(100) > Nummer-Start(80) > Titel-Start(60)
    # > Nummer-Enthält(50) > Titel-Enthält(40) > sonst 10.
    store = _store(
        [
            _doc("title-contain", "SIA 500", "X101"),
            _doc("number-contain", "XSIA 101", "Unbeteiligte"),
            _doc("title-start", "SIA 600", "101 Norm"),
            _doc("number-start", "1010", "Unbeteiligte"),
            _doc("number-equal", "101", "Unbeteiligte"),
            _doc("no-hit", "SIA 900", "Andere"),
        ]
    )
    hits = store.search("101", None, False, 50)
    assert [d.product_id for d in hits] == [
        "number-equal",
        "number-start",
        "title-start",
        "number-contain",
        "title-contain",
    ]


def test_req803_catalog_search_tie_break_by_number_then_title() -> None:
    store = _store(
        [
            _doc("z", "B 200", "Beta"),
            _doc("a", "A 200", "Alpha"),
            _doc("b", "A 200", "Beta"),
        ]
    )
    hits = store.search("200", None, False, 50)
    assert [d.product_id for d in hits] == ["a", "b", "z"]  # thenComparing number, title


def test_req803_catalog_search_limit_rules() -> None:
    store = _store([_doc(f"p{i:03d}", f"N {i}", f"T {i}") for i in range(120)])
    assert len(store.search(None, None, False, 0)) == 50  # Java: limit<1 → 50
    assert len(store.search(None, None, False, -5)) == 50
    assert len(store.search(None, None, False, 7)) == 7
    assert len(store.search(None, None, False, 500)) == 120
    assert len(store.search(None, None, False, 600)) == 120  # min(600, 500) > 120
