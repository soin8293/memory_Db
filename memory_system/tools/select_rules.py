#!/usr/bin/env python3
"""Select extra rules to inject based on intent buckets.

- Reads nodes.jsonl
- Uses tags + priority
- Excludes rules already in policy core

This is the missing glue between intent gating and rule injection.

Usage:
  python3 memory/tools/select_rules.py --text "..." --max-nodes 3 --max-chars 1200

Output:
- prints a small markdown block with selected rule bullets
- prints JSON stats to stderr
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Set, Tuple


@dataclass
class Rule:
    id: str
    text: str
    priority: int
    tags: Set[str]


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def load_nodes(path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
    return out


def tagset(tags_field: Any) -> Set[str]:
    if tags_field is None:
        return set()
    if isinstance(tags_field, list):
        tags: List[str] = []
        for t in tags_field:
            if t is None:
                continue
            tags.extend([x.strip() for x in str(t).split(",") if x.strip()])
        return set(tags)
    return set([x.strip() for x in str(tags_field).split(",") if x.strip()])


def get_priority(node: Dict[str, Any]) -> int:
    meta = node.get("meta")
    if isinstance(meta, dict):
        try:
            return int(meta.get("priority") or 0)
        except Exception:
            return 0
    return 0


def classify_buckets(text: str) -> Set[str]:
    t = (text or "").strip().lower()
    buckets = {"core"}

    if re.search(r"\b(send|message|dm|text|notify|post|publish|email)\b", t):
        buckets.add("security")
    if re.search(r"\b(config|token|api key|secret|credential|password|rotate)\b", t):
        buckets.add("security")
    if re.search(r"\b(delete|rm\b|wipe|purge|remove job|disable)\b", t):
        buckets.add("security")
    if re.search(r"\b(crash|restart|disconnect|down|gateway|launchagent|launchd|cron)\b", t):
        buckets.add("ops")
    if re.search(r"\b(remember|what did we decide|recall|previous|how did we set)\b", t):
        buckets.add("memory")
    if re.search(r"\b(agentoffice|ralph)\b", t):
        buckets.add("project:agentoffice")

    return buckets


def load_core_rule_ids(core_md_path: str) -> Set[str]:
    ids: Set[str] = set()
    if not os.path.exists(core_md_path):
        return ids
    with open(core_md_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("- (") and ")" in line:
                rid = line.split("(", 1)[1].split(")", 1)[0].strip()
                if rid.startswith("rule:"):
                    ids.add(rid)
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--max-nodes", type=int, default=3)
    ap.add_argument("--max-chars", type=int, default=1200)
    args = ap.parse_args()

    root = repo_root()
    nodes_path = os.path.join(root, "memory", "nodes.jsonl")
    core_path = os.path.join(root, "memory", "policy", "core.md")

    buckets = classify_buckets(args.text)
    core_ids = load_core_rule_ids(core_path)

    # Map buckets to tags
    want_tags: Set[str] = set()
    if "security" in buckets:
        want_tags.add("security")
    if "ops" in buckets:
        want_tags.add("ops")
    if "memory" in buckets:
        want_tags.add("memory")
    if "project:agentoffice" in buckets:
        want_tags.add("agentoffice")

    nodes = load_nodes(nodes_path)
    candidates: List[Rule] = []
    for n in nodes:
        if n.get("type") != "rule":
            continue
        scope = n.get("scope") or "global"
        rid = str(n.get("id") or "").strip()
        if not rid or rid in core_ids:
            continue
        tags = tagset(n.get("tags"))
        # require relevant tag unless it's a global core/policy rule (kept for later)
        if want_tags and len(tags & want_tags) == 0:
            continue
        text = str(n.get("text") or "").strip()
        if not text:
            continue
        candidates.append(Rule(id=rid, text=text, priority=get_priority(n), tags=tags))

    candidates.sort(key=lambda r: (-r.priority, r.id))

    lines: List[str] = []
    used = 0
    kept = 0
    for r in candidates:
        bullet = f"- ({r.id}) {r.text}".strip()
        if len(lines) >= args.max_nodes:
            break
        if used + len(bullet) + 1 > args.max_chars:
            break
        lines.append(bullet)
        used += len(bullet) + 1
        kept += 1

    if lines:
        print("# Selected rules")
        print("(triggered)")
        print()
        print("\n".join(lines))

    stats = {
        "buckets": sorted(buckets),
        "wantTags": sorted(want_tags),
        "candidates": len(candidates),
        "kept": kept,
        "maxNodes": args.max_nodes,
        "maxChars": args.max_chars,
    }
    print(json.dumps(stats, ensure_ascii=False), file=os.sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
