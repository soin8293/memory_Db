#!/usr/bin/env python3
"""Compile a compact, always-on policy bundle from memory nodes.

- Source of truth: memory/nodes.jsonl
- Output: memory/policy/core.md

Design goals:
- Deterministic
- Cheap (hard char budget)
- Backwards-compatible with existing node format

Selection heuristic (v1):
- type == "rule"
- scope == "global"
- include if:
  - tag contains "core" OR "policy" OR "security" OR "ops" OR "style"
  - OR meta.priority >= 50

Ordering:
- priority desc (default 0)
- then id

If budget exceeded:
- truncate silently in core.md (keep core clean)
- write stats to core.stats.json
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Rule:
    id: str
    text: str
    priority: int
    tags: List[str]


def load_nodes(path: str) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return nodes
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                nodes.append(json.loads(ln))
            except Exception:
                # ignore corrupt lines
                continue
    return nodes


def tagset(tags_field: Any) -> List[str]:
    if tags_field is None:
        return []
    if isinstance(tags_field, list):
        out: List[str] = []
        for t in tags_field:
            if t is None:
                continue
            out.extend([x.strip() for x in str(t).split(",") if x.strip()])
        return out
    return [x.strip() for x in str(tags_field).split(",") if x.strip()]


def get_priority(node: Dict[str, Any]) -> int:
    meta = node.get("meta")
    if isinstance(meta, dict):
        p = meta.get("priority")
        try:
            return int(p)
        except Exception:
            return 0
    return 0


def is_core_rule(node: Dict[str, Any]) -> bool:
    if node.get("type") != "rule":
        return False
    if node.get("scope") not in (None, "global"):
        return False
    tags = set(tagset(node.get("tags")))
    p = get_priority(node)
    key_tags = {"core", "policy", "security", "ops", "style"}
    return (len(tags & key_tags) > 0) or (p >= 50)


def compile_md(rules: List[Rule], budget_chars: int) -> str:
    lines: List[str] = []
    lines.append("# Policy Core (compiled)")
    lines.append("")
    lines.append("This file is auto-generated from `memory/nodes.jsonl`.")
    lines.append("- Goal: a tiny, always-on behavior constitution")
    lines.append("- Budget: max %d chars" % budget_chars)
    lines.append("")

    used = sum(len(l) + 1 for l in lines)
    kept: List[Rule] = []
    for r in rules:
        bullet = f"- ({r.id}) {r.text}".strip()
        if used + len(bullet) + 1 > budget_chars:
            break
        kept.append(r)
        lines.append(bullet)
        used += len(bullet) + 1

    # Keep core clean: truncate silently here. Write stats separately.
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default=os.path.expanduser("~/clawd"))
    ap.add_argument("--budget-chars", type=int, default=900)
    args = ap.parse_args()

    ws = os.path.abspath(os.path.expanduser(args.workspace))
    nodes_path = os.path.join(ws, "memory", "nodes.jsonl")
    out_dir = os.path.join(ws, "memory", "policy")
    out_path = os.path.join(out_dir, "core.md")
    stats_path = os.path.join(out_dir, "core.stats.json")

    nodes = load_nodes(nodes_path)
    rules: List[Rule] = []
    for n in nodes:
        if not is_core_rule(n):
            continue
        rid = str(n.get("id") or "").strip()
        text = str(n.get("text") or "").strip()
        if not rid or not text:
            continue
        rules.append(Rule(id=rid, text=text, priority=get_priority(n), tags=tagset(n.get("tags"))))

    rules.sort(key=lambda r: (-r.priority, r.id))

    os.makedirs(out_dir, exist_ok=True)
    md = compile_md(rules, budget_chars=args.budget_chars)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    # Stats (kept vs candidates) without polluting core.md
    kept_count = sum(1 for line in md.splitlines() if line.startswith("- (rule:"))
    stats = {
        "generatedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "budgetChars": args.budget_chars,
        "candidates": len(rules),
        "kept": kept_count,
        "outPath": out_path,
    }
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"Wrote {out_path} ({len(md)} chars, kept {kept_count}/{len(rules)}).")
    print(f"Wrote {stats_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
