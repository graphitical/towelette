"""ChromaDB query logic -- semantic search and exact lookup."""
from __future__ import annotations

import chromadb

from towelette.embed import get_embedding_function


def _get_collections(
    client: chromadb.ClientAPI,
    scope: str | None = None,
) -> list:
    """Get collections to search, optionally filtered by scope."""
    ef = get_embedding_function()
    all_collections = client.list_collections()

    if not scope or scope == "all":
        return [
            client.get_collection(c.name, embedding_function=ef)
            for c in all_collections
        ]

    matched = []
    for col_meta in all_collections:
        col = client.get_collection(col_meta.name, embedding_function=ef)
        col_source = (col.metadata or {}).get("source", "")
        if col_source == scope or col_meta.name.startswith(scope):
            matched.append(col)

    return matched


def semantic_search(
    client: chromadb.ClientAPI,
    query: str,
    scope: str | None = None,
    limit: int = 5,
    max_per_class: int = 1,
) -> list[dict]:
    """Semantic search across indexed collections.

    Returns list of dicts with: content, class_name, source, file_path, chunk_type, distance.
    """
    collections = _get_collections(client, scope)
    if not collections:
        return []

    all_results: list[dict] = []
    fetch_limit = max(limit * 3, 10)

    for collection in collections:
        if collection.count() == 0:
            continue
        actual_limit = min(fetch_limit, collection.count())
        try:
            result = collection.query(
                query_texts=[query],
                n_results=actual_limit,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            continue

        if not result["documents"] or not result["documents"][0]:
            continue

        for doc, meta, dist in zip(
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        ):
            all_results.append({
                "content": doc,
                "class_name": meta.get("class_name", ""),
                "source": meta.get("source", ""),
                "file_path": meta.get("file_path", ""),
                "chunk_type": meta.get("chunk_type", ""),
                "symbols": meta.get("symbols", ""),
                "distance": dist,
            })

    all_results.sort(key=lambda r: r["distance"])

    seen_classes: dict[str, int] = {}
    filtered: list[dict] = []
    for r in all_results:
        cn = r["class_name"]
        if seen_classes.get(cn, 0) >= max_per_class:
            continue
        seen_classes[cn] = seen_classes.get(cn, 0) + 1
        filtered.append(r)
        if len(filtered) >= limit:
            break

    return filtered


def exact_lookup(
    client: chromadb.ClientAPI,
    name: str,
    scope: str | None = None,
) -> list[dict]:
    """Exact name lookup -- by class_name metadata, then symbol, then semantic fallback.

    Returns list of dicts with: content, class_name, source, file_path, chunk_type.
    """
    collections = _get_collections(client, scope)
    results: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for collection in collections:
        if collection.count() == 0:
            continue

        # 1. Exact class_name match
        try:
            exact = collection.get(
                where={"class_name": name},
                include=["documents", "metadatas"],
            )
        except Exception:
            exact = {"ids": []}

        if exact["ids"]:
            for doc, meta in zip(exact["documents"], exact["metadatas"]):
                key = (meta.get("file_path", ""), meta.get("class_name", ""))
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "content": doc,
                        "class_name": meta.get("class_name", ""),
                        "source": meta.get("source", ""),
                        "file_path": meta.get("file_path", ""),
                        "chunk_type": meta.get("chunk_type", ""),
                    })

        # 2. Symbol substring match
        if not results:
            try:
                sym_match = collection.get(
                    where={"symbols": {"$contains": name}},
                    limit=5,
                    include=["documents", "metadatas"],
                )
            except Exception:
                sym_match = {"ids": []}

            if sym_match["ids"]:
                for doc, meta in zip(sym_match["documents"], sym_match["metadatas"]):
                    key = (meta.get("file_path", ""), meta.get("class_name", ""))
                    if key not in seen:
                        seen.add(key)
                        results.append({
                            "content": doc,
                            "class_name": meta.get("class_name", ""),
                            "source": meta.get("source", ""),
                            "file_path": meta.get("file_path", ""),
                            "chunk_type": meta.get("chunk_type", ""),
                        })

    # 3. Semantic fallback
    if not results:
        results = semantic_search(client, name, scope=scope, limit=3)

    return results
