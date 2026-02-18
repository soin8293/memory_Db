#!/usr/bin/env python3
"""Build an inverted keyword index from nodes.jsonl for O(1) heuristic recall.

Output: memory_system/data/keyword_index.json
Format: {"<word>": ["node_id_1", "node_id_2", ...], ...}

Also stores node metadata for scoring without re-reading nodes.jsonl:
  "_nodes": {"<node_id>": {"type": "...", "scope": "...", "ts": "...", "text_preview": "..."}}

Usage:
  ~/clawd/.venv/bin/python memory_system/tools/build_keyword_index.py
  ~/clawd/.venv/bin/python memory_system/tools/build_keyword_index.py --nodes /path/to/nodes.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set


def repo_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def tokenize_text(text: str) -> Set[str]:
    """Extract unique lowercase tokens (3+ chars) from text."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9_\-\s]", " ", text)
    return {t for t in text.split() if len(t) >= 3}


def build_index(nodes_path: Path) -> Dict[str, Any]:
    """Build inverted keyword index from nodes.jsonl."""
    inverted: Dict[str, List[str]] = defaultdict(list)
    node_meta: Dict[str, Dict[str, Any]] = {}

    with nodes_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                node = json.loads(line)
            except Exception:
                continue
            if not isinstance(node, dict):
                continue

            node_id = str(node.get("id") or "").strip()
            if not node_id:
                continue

            # Collect all searchable text
            parts = [
                str(node.get("id") or ""),
                str(node.get("type") or ""),
                str(node.get("scope") or ""),
                str(node.get("text") or ""),
                " ".join(node.get("tags") or []),
            ]
            meta = node.get("meta")
            if isinstance(meta, dict):
                try:
                    parts.append(json.dumps(meta, ensure_ascii=False))
                except Exception:
                    pass

            tokens = tokenize_text(" ".join(parts))
            for tok in tokens:
                inverted[tok].append(node_id)

            # Store minimal metadata for scoring
            text = str(node.get("text") or "").strip()
            node_meta[node_id] = {
                "type": node.get("type"),
                "scope": node.get("scope"),
                "ts": node.get("ts"),
                "text_preview": text[:180] if text else "",
                "tags": node.get("tags") or [],
            }

    # Sort posting lists by node_id for determinism
    result: Dict[str, Any] = {}
    for tok in sorted(inverted):
        result[tok] = sorted(set(inverted[tok]))

    result["_nodes"] = node_meta
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--nodes",
        default=None,
        help="Path to nodes.jsonl (overrides --project and default)",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="Output path (auto-derived if --project is used)",
    )
    ap.add_argument(
        "--project",
        default=None,
        help="Build index for a specific project store in memory_db/<slug>/",
    )
    args = ap.parse_args()

    root = repo_root()
    if args.project:
        project_dir = Path(root) / "memory_system" / "data" / "stores" / args.project
        nodes_path = Path(args.nodes) if args.nodes else project_dir / "nodes.jsonl"
        out_path = Path(args.out) if args.out else project_dir / "keyword_index.json"
    else:
        nodes_path = Path(args.nodes) if args.nodes else Path(root) / "memory_system" / "data" / "nodes.jsonl"
        out_path = Path(args.out) if args.out else Path(root) / "memory_system" / "data" / "keyword_index.json"
    if not nodes_path.exists():
        print(f"nodes.jsonl not found: {nodes_path}", file=sys.stderr)
        return 2

    index = build_index(nodes_path)
    n_words = len([k for k in index if k != "_nodes"])
    n_nodes = len(index.get("_nodes", {}))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)

    print(f"Built keyword index: {n_words} words, {n_nodes} nodes -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
