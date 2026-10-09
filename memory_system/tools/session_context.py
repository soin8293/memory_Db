#!/usr/bin/env python3
"""Generate context injection block for session start.

Reads the active project scope(s) and outputs the top-N most relevant
rules, decisions, and constraints as a compact markdown block suitable
for pasting into a system prompt or AGENTS.md startup.

Usage:
  python session_context.py                          # all scopes
  python session_context.py --scope applyops         # specific project
  python session_context.py --scope applyops --top 10
  python session_context.py --format json            # machine-readable

Output goes to stdout. Intended to be called at session start by the
agent or a startup hook.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from memory_system.paths import default_nodes_path

# Optional override retained for callers; otherwise resolve current configuration.
NODES_PATH = None

# Node types worth injecting at session start (ordered by priority)
INJECT_TYPES = {"rule", "decision", "constraint"}
# Fallback: also include notes tagged with these high-signal tags
HIGH_SIGNAL_TAGS = {"constraint", "risk", "decision", "rule", "next-step"}


def load_nodes() -> List[Dict[str, Any]]:
    nodes = []
    nodes_path = NODES_PATH or default_nodes_path()
    if not os.path.exists(nodes_path):
        return nodes
    with open(nodes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                node = json.loads(line)
                if isinstance(node, dict):
                    nodes.append(node)
            except json.JSONDecodeError:
                continue
    return nodes


def score_node(node: Dict[str, Any]) -> float:
    """Higher score = more important for context injection."""
    s = 0.0
    ntype = node.get("type", "")
    tags = set(node.get("tags", []))

    # Type-based priority
    if ntype == "rule":
        s += 10
    elif ntype == "decision":
        s += 8
    elif ntype == "constraint":
        s += 9
    elif ntype == "note" and tags & HIGH_SIGNAL_TAGS:
        s += 5
    else:
        s += 1  # excerpts, pointers, generic notes

    # Tag signal boost
    s += len(tags & HIGH_SIGNAL_TAGS) * 2

    # Recency boost (parse ts, newer = higher)
    ts = node.get("ts", "")
    if ts:
        # Simple lexicographic comparison works for ISO8601
        # Normalize to just the date part for scoring
        date_part = ts[:10]  # YYYY-MM-DD
        try:
            from datetime import date
            node_date = date.fromisoformat(date_part)
            today = date.today()
            days_old = (today - node_date).days
            s += max(0, 5 - days_old * 0.1)  # up to 5 points for recent
        except (ValueError, TypeError):
            pass

    return s


def active_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Resolve explicit same-scope supersession; retain cycles for human review.

    Generic links are references, not supersession. No ledger data is deleted.
    """
    by_key = {(n.get("scope"), n.get("id")): n for n in nodes if n.get("id")}
    edges = {}
    for key, node in by_key.items():
        meta = node.get("meta")
        supersedes = meta.get("supersedes", []) if isinstance(meta, dict) else []
        if isinstance(supersedes, str):
            supersedes = [supersedes]
        if not isinstance(supersedes, list):
            supersedes = []
        edges[key] = {(key[0], old) for old in supersedes
                      if isinstance(old, str) and (key[0], old) in by_key}

    def reaches(start, goal):
        pending, seen = [start], set()
        while pending:
            current = pending.pop()
            if current == goal:
                return True
            if current not in seen:
                seen.add(current)
                pending.extend(edges.get(current, ()))
        return False

    superseded = {target for source, targets in edges.items() for target in targets
                  if not reaches(target, source)}
    return [n for n in nodes if (n.get("scope"), n.get("id")) not in superseded]


def get_context(scope: str | None = None, top: int = 5) -> List[Dict[str, Any]]:
    nodes = load_nodes()

    # Filter by scope
    if scope:
        nodes = [n for n in nodes if n.get("scope") == scope or n.get("scope") == "global"]

    nodes = active_nodes(nodes)

    # Filter to injectable types + high-signal notes
    injectable = []
    for n in nodes:
        ntype = n.get("type", "")
        tags = set(n.get("tags", []))
        if ntype in INJECT_TYPES or (ntype == "note" and tags & HIGH_SIGNAL_TAGS):
            injectable.append(n)

    # Score and rank
    injectable.sort(key=lambda n: score_node(n), reverse=True)

    return injectable[:top]


def format_markdown(nodes: List[Dict[str, Any]]) -> str:
    if not nodes:
        return "No active constraints or rules found."

    lines = ["## Active Context (auto-injected)", ""]
    for n in nodes:
        ntype = n.get("type", "note").upper()
        nid = n.get("id", "?")
        text = n.get("text", "")
        scope = n.get("scope", "global")
        lines.append(f"- **[{ntype}]** `{nid}` ({scope}): {text}")

    lines.append("")
    lines.append(f"_({len(nodes)} nodes injected at session start)_")
    return "\n".join(lines)


def format_json(nodes: List[Dict[str, Any]]) -> str:
    return json.dumps(nodes, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="Generate session context injection")
    parser.add_argument("--scope", default=None, help="Project scope (default: all)")
    parser.add_argument("--top", type=int, default=5, help="Number of nodes to inject")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    nodes = get_context(scope=args.scope, top=args.top)

    if args.format == "json":
        print(format_json(nodes))
    else:
        print(format_markdown(nodes))


if __name__ == "__main__":
    main()
