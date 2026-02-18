#!/usr/bin/env python3
"""Query memory nodes from memory/nodes.jsonl.

Examples:
  python3 memory/tools/query_nodes.py --scope agentoffice --type incident
  python3 memory/tools/query_nodes.py --tag ralph-loop
  python3 memory/tools/query_nodes.py --q "rate limit"

Exit codes:
  0 success
  1 no matches
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, Iterable, List


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def load_nodes(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []

    nodes: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                nodes.append(json.loads(line))
            except json.JSONDecodeError:
                # skip bad lines but keep going
                continue
    return nodes


def contains_query(node: Dict[str, Any], q: str) -> bool:
    if not q:
        return True

    hay = []
    for k in ("id", "type", "scope", "text"):
        v = node.get(k)
        if isinstance(v, str):
            hay.append(v)

    meta = node.get("meta")
    if meta is not None:
        try:
            hay.append(json.dumps(meta, ensure_ascii=False))
        except Exception:
            pass

    joined = "\n".join(hay).lower()
    return q.lower() in joined


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", default=None, help="global or project slug")
    ap.add_argument("--nodes", default=None, help="path to nodes.jsonl (override)")
    ap.add_argument("--type", default=None, dest="type_", help="project|rule|decision|incident|note|pointer")
    ap.add_argument("--tag", action="append", default=[], help="tag filter (repeatable)")
    ap.add_argument("--id", dest="id_", default=None, help="exact id match")
    ap.add_argument("--q", default=None, help="substring query across id/scope/text/meta")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--json", action="store_true", help="emit JSON array")
    args = ap.parse_args()

    nodes_path = args.nodes or os.path.join(repo_root(), "memory_system", "data", "nodes.jsonl")
    nodes = load_nodes(nodes_path)

    out: List[Dict[str, Any]] = []
    for n in nodes:
        if args.id_ and n.get("id") != args.id_:
            continue
        if args.scope and n.get("scope") != args.scope:
            continue
        if args.type_ and n.get("type") != args.type_:
            continue
        if args.tag:
            tags = set(n.get("tags") or [])
            if any(t not in tags for t in args.tag):
                continue
        if args.q and not contains_query(n, args.q):
            continue
        out.append(n)

    # newest first when timestamps exist
    def ts_key(n: Dict[str, Any]) -> str:
        return str(n.get("ts") or "")

    out.sort(key=ts_key, reverse=True)
    out = out[: args.limit]

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for n in out:
            tags = ",".join(n.get("tags") or [])
            text = (n.get("text") or "").strip().replace("\n", " ")
            if len(text) > 160:
                text = text[:157] + "..."
            print(f"{n.get('ts','')}	{n.get('id','')}	{n.get('type','')}	{n.get('scope','')}	[{tags}]\t{text}")

    return 0 if out else 1


if __name__ == "__main__":
    raise SystemExit(main())
