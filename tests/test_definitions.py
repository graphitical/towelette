from __future__ import annotations

from pathlib import Path

import pytest


def test_create_db(tmp_path: Path):
    from towelette.definitions import create_db

    db_path = tmp_path / "definitions.db"
    conn = create_db(db_path)
    assert db_path.exists()
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='definitions'")
    assert cursor.fetchone() is not None
    conn.close()


def test_insert_and_lookup(tmp_path: Path):
    from towelette.definitions import create_db, insert_definitions, lookup_symbol

    db_path = tmp_path / "definitions.db"
    conn = create_db(db_path)
    insert_definitions(conn, [
        ("occt", "MakeBox", "BRepPrimAPI_MakeBox", "BRepPrimAPI/BRepPrimAPI_MakeBox.hxx", 15, "class", None),
        ("occt", "Shape", "BRepPrimAPI_MakeBox::Shape", "BRepPrimAPI/BRepPrimAPI_MakeBox.hxx", 30, "method", "BRepPrimAPI_MakeBox"),
    ])
    conn.close()

    results = lookup_symbol(db_path, "MakeBox")
    assert len(results) >= 1
    assert results[0]["symbol"] == "MakeBox"
    assert results[0]["qualified_name"] == "BRepPrimAPI_MakeBox"


def test_lookup_case_insensitive(tmp_path: Path):
    from towelette.definitions import create_db, insert_definitions, lookup_symbol

    db_path = tmp_path / "definitions.db"
    conn = create_db(db_path)
    insert_definitions(conn, [
        ("project", "MyClass", "mymodule.MyClass", "src/mymodule.py", 10, "class", None),
    ])
    conn.close()

    results = lookup_symbol(db_path, "myclass")
    assert len(results) >= 1
    assert results[0]["symbol"] == "MyClass"


def test_lookup_qualified_name_partial(tmp_path: Path):
    from towelette.definitions import create_db, insert_definitions, lookup_symbol

    db_path = tmp_path / "definitions.db"
    conn = create_db(db_path)
    insert_definitions(conn, [
        ("occt", "Shape", "BRepPrimAPI_MakeBox::Shape", "BRepPrimAPI/BRepPrimAPI_MakeBox.hxx", 30, "method", "BRepPrimAPI_MakeBox"),
    ])
    conn.close()

    results = lookup_symbol(db_path, "BRepPrimAPI_MakeBox::Shape")
    assert len(results) >= 1


def test_clear_source(tmp_path: Path):
    from towelette.definitions import clear_source, create_db, insert_definitions, lookup_symbol

    db_path = tmp_path / "definitions.db"
    conn = create_db(db_path)
    insert_definitions(conn, [
        ("lib_a", "Foo", "lib_a.Foo", "foo.py", 1, "class", None),
        ("lib_b", "Bar", "lib_b.Bar", "bar.py", 1, "class", None),
    ])
    clear_source(conn, "lib_a")
    conn.close()

    results = lookup_symbol(db_path, "Foo")
    assert len(results) == 0
    results = lookup_symbol(db_path, "Bar")
    assert len(results) == 1


def test_lookup_with_source_filter(tmp_path: Path):
    from towelette.definitions import create_db, insert_definitions, lookup_symbol

    db_path = tmp_path / "definitions.db"
    conn = create_db(db_path)
    insert_definitions(conn, [
        ("lib_a", "Foo", "lib_a.Foo", "foo.py", 1, "class", None),
        ("lib_b", "Foo", "lib_b.Foo", "foo.py", 1, "class", None),
    ])
    conn.close()

    results = lookup_symbol(db_path, "Foo", source="lib_a")
    assert len(results) == 1
    assert results[0]["source"] == "lib_a"
