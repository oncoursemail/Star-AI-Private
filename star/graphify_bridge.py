"""Read-only adapter for Graphify's exported NetworkX node-link graph.json.

This is an adapter, not a second graph generator and not an executable MCP
bridge. Users produce the graph with official Graphify tooling, then STAR
queries its existing, local, project-scoped graph with bounded results.
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache
import json
from pathlib import Path
import re

MAX_GRAPH_BYTES = 64_000_000   # STAR's own code graph is 29 MB (21,503 nodes, 54,336 edges)
MAX_NODES = 100_000
MAX_EDGES = 300_000


def _endpoint(value) -> str:
    if isinstance(value, dict):
        value = next((value[k] for k in ("id", "node_id", "key") if k in value), "")
    return str(value) if value is not None else ""


@lru_cache(maxsize=3)
def _load(path: str, modified: int, size: int):
    with open(path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise ValueError("Not a supported Graphify node-link graph")
    raw_nodes = data["nodes"]
    raw_edges = data.get("links", data.get("edges", []))
    if (not isinstance(raw_edges, list) or len(raw_nodes) > MAX_NODES
            or len(raw_edges) > MAX_EDGES):
        raise ValueError("Graph size exceeds the STAR read-only limits")
    nodes = {}
    for item in raw_nodes:
        if not isinstance(item, dict):
            continue
        ident = _endpoint(item.get("id", item.get("node_id")))
        if ident:
            nodes[ident] = {
                "id": ident,
                "label": str(item.get("label", item.get("name", ident)))[:250],
                "source_file": str(item.get("source_file", ""))[:400],
                "source_location": str(item.get("source_location", ""))[:200],
                "file_type": str(item.get("file_type", ""))[:60],
                "community": str(item.get("community", ""))[:80],
            }
    edges = []
    adjacent = {key: [] for key in nodes}
    for item in raw_edges:
        if not isinstance(item, dict):
            continue
        source, target = _endpoint(item.get("source")), _endpoint(item.get("target"))
        if source not in nodes or target not in nodes:
            continue
        edge = {
            "source": source, "target": target,
            "relation": str(item.get("relation", item.get("type", "related")))[:100],
            "confidence": str(item.get("confidence", "UNKNOWN"))[:30],
            "source_file": str(item.get("source_file", ""))[:300],
        }
        edges.append(edge)
        adjacent[source].append((target, edge))
        if target != source:
            adjacent[target].append((source, edge))
    meta = data.get("graph", {})
    if not isinstance(meta, dict):
        meta = {}
    return nodes, edges, adjacent, {
        "schema_version": str(meta.get("schema_version", "")),
        "graphify_version": str(meta.get("graphify_version", "")),
        "directed": bool(data.get("directed", False)),
    }


_SEPARATORS = re.compile(r"[_\-./\\]+")


def _symbol_name(label: str) -> str:
    """'connection_for()' and '.connection_for()' -> 'connection_for' (lower-case input)."""
    return re.sub(r"\(\)$", "", label.strip()).lstrip(".")


class GraphifyGraph:
    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("Select a directory before using Graphify")
        self.path = self.workspace / "graphify-out" / "graph.json"

    def _data(self):
        file = self.path
        if (file.is_symlink() or not file.is_file()
                or not file.resolve(strict=True).is_relative_to(self.workspace)):
            raise FileNotFoundError("No project graph found. Generate graphify-out/graph.json first")
        size = file.stat().st_size
        if size > MAX_GRAPH_BYTES:
            raise ValueError("Graphify graph is larger than STAR's 20 MB safety limit")
        return _load(str(file), file.stat().st_mtime_ns, size)

    def available(self) -> bool:
        try:
            self._data()
            return True
        except (OSError, ValueError, json.JSONDecodeError, UnicodeError):
            return False

    def stats(self) -> dict:
        nodes, edges, _, meta = self._data()
        return {"nodes": len(nodes), "edges": len(edges), "metadata": meta,
                "graph": "graphify-out/graph.json", "read_only": True}

    @staticmethod
    def _rank(nodes, query: str):
        words = re.findall(r"[a-z0-9]{2,}", query.lower())[:10]
        if not words:
            words = [query.strip().lower()]
        query_low = query.strip().lower()
        # Graphify labels a function "name()" and a method ".name()". A symbol whose own name is
        # exactly the query must outrank a docstring sentence that merely mentions it.
        query_name = _symbol_name(query_low)
        query_spaced = _SEPARATORS.sub(" ", query_low).strip()
        ranked = []
        for ident, node in nodes.items():
            label = node["label"].lower()
            spaced = _SEPARATORS.sub(" ", label)   # "priority_proxy.py" must answer "priority proxy"
            source = _SEPARATORS.sub(" ", node["source_file"].lower())
            score = (20 if _symbol_name(label) == query_name else 12 if label == query_low
                     else 6 if query_low in label or (query_spaced and query_spaced in spaced) else 0)
            score += sum((4 if word in spaced else 0) + (1 if word in source else 0) for word in words)
            if score:
                ranked.append((score, ident))
        # Ties: the shorter label first (a symbol name before a sentence), then alphabetical.
        ranked.sort(key=lambda item: (-item[0], len(nodes[item[1]]["label"]), nodes[item[1]]["label"].lower()))
        return [ident for _, ident in ranked]

    @staticmethod
    def _edge_view(edge: dict, nodes: dict) -> dict:
        return {
            "from": nodes[edge["source"]]["label"],
            "relation": edge["relation"],
            "to": nodes[edge["target"]]["label"],
            "confidence": edge["confidence"],
            "source_file": edge["source_file"],
        }

    def query(self, question: str, *, limit: int = 8) -> dict:
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 220:
            raise ValueError("Question must be 1–220 characters")
        if not isinstance(limit, int) or not 1 <= limit <= 15:
            raise ValueError("Limit must be 1–15")
        nodes, _, adjacent, meta = self._data()
        ranked = self._rank(nodes, question)[:limit]
        matches = []
        for ident in ranked:
            neighbors = [self._edge_view(edge, nodes) for _, edge in adjacent[ident][:6]]
            matches.append({"node": nodes[ident], "connections": neighbors})
        return {"question": question, "matches": matches, "metadata": meta,
                "notice": "Graph edges are source-attributed relationships. INFERRED edges are not verified facts."}

    def explain(self, concept: str) -> dict:
        if not isinstance(concept, str) or not 1 <= len(concept.strip()) <= 220:
            raise ValueError("Concept must be 1–220 characters")
        nodes, _, adjacent, _ = self._data()
        ranked = self._rank(nodes, concept)
        if not ranked:
            return {"concept": concept, "found": False, "connections": []}
        ident = ranked[0]
        return {"concept": concept, "found": True, "node": nodes[ident],
                "degree": len(adjacent[ident]),
                "connections": [self._edge_view(edge, nodes) for _, edge in adjacent[ident][:30]]}

    def path_between(self, start: str, end: str) -> dict:
        if (not isinstance(start, str) or not isinstance(end, str)
                or not 1 <= len(start.strip()) <= 200 or not 1 <= len(end.strip()) <= 200):
            raise ValueError("Supply two node names of at most 200 characters")
        nodes, _, adjacent, _ = self._data()
        left = self._rank(nodes, start)
        right = self._rank(nodes, end)
        if not left or not right:
            return {"found": False, "reason": "One or both concepts are missing"}
        origin, destination = left[0], right[0]
        queue = deque([origin])
        prev = {origin: None}
        used = {}
        while queue and len(prev) <= 8000:
            ident = queue.popleft()
            if ident == destination:
                break
            # Avoid returning noisy indirect paths that traverse the entire graph.
            for neighbor, edge in adjacent[ident]:
                if neighbor not in prev and len(prev) < 8000:
                    prev[neighbor] = ident
                    used[neighbor] = edge
                    queue.append(neighbor)
        if destination not in prev:
            return {"found": False, "reason": "No path found within the search limit"}
        route = []
        current = destination
        while current != origin:
            route.append({"node": nodes[current], "via": self._edge_view(used[current], nodes)})
            current = prev[current]
        route.append({"node": nodes[origin]})
        route.reverse()
        return {"found": True, "hops": len(route) - 1, "path": route[:30],
                "notice": "Traversal can cross edges backwards; relation arrows retain their original direction."}
