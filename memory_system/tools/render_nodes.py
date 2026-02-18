#!/usr/bin/env python3
"""Render memory_system/data/nodes.jsonl into memory/nodes.md for indexing.

Clawdbot's memory_search indexes Markdown only, so this keeps the node ledger
searchable without abandoning JSONL.

Usage:
  python3 memory_system/tools/render_nodes.py
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def load_nodes(path: str) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return nodes
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                nodes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return nodes


def main() -> int:
    root = repo_root()
    jsonl_path = os.path.join(root, "memory_system", "data", "nodes.jsonl")
    # NOTE: Clawdbot's memory indexer targets Markdown, so we render to a stable
    # Markdown file under memory_system/data/.
    md_path = os.path.join(root, "memory_system", "data", "NODES.md")

    nodes = load_nodes(jsonl_path)

    header = (
        "# Memory Nodes (rendered)\n\n"
        "This file is a rendered, searchable view of `memory_system/data/nodes.jsonl`.\n"
        "- Source of truth: `memory_system/data/nodes.jsonl` (append-only)\n"
        "- Purpose: make nodes available to Clawdbot `memory_search` (Markdown-only index)\n\n"
        "## Retrieval note\n"
        "- For **exact id lookups** (e.g. `incident:claude-rate-limit`), use `python3 memory_system/tools/query_nodes.py` (deterministic).\n"
        "- For **semantic recall across Markdown** in the dashboard, use `memory_search` or `clawdbot memory search`.\n"
        "- When testing `memory_search`, prefer `--min-score 0` unless you intentionally want a stricter threshold.\n\n"
        "---\n\n"
    )

    # newest first by ts if present
    nodes.sort(key=lambda n: str(n.get("ts") or ""), reverse=True)

    parts = [header]
    for n in nodes:
        nid = n.get("id", "")
        ntype = n.get("type", "")
        scope = n.get("scope", "")
        ts = n.get("ts", "")
        tags = ", ".join(n.get("tags") or [])
        text = (n.get("text") or "").strip()
        links = n.get("links") or []
        meta = n.get("meta")

        parts.append(f"## {nid}\n")
        parts.append(f"- type: `{ntype}`\n")
        parts.append(f"- scope: `{scope}`\n")
        parts.append(f"- ts: `{ts}`\n")
        if tags:
            parts.append(f"- tags: {tags}\n")
        if links:
            parts.append(f"- links: {', '.join(links)}\n")
        if text:
            parts.append("\n" + text + "\n")
        if meta is not None:
            parts.append("\n```json\n" + json.dumps(meta, ensure_ascii=False, indent=2) + "\n```\n")
        parts.append("\n---\n\n")

    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))

    print(f"Wrote {md_path} ({len(nodes)} nodes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
