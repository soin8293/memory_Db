#!/usr/bin/env python3
"""Prune expired excerpt markdown files.

We keep nodes.jsonl append-only. Garbage collection applies to derived artifacts
(Markdown excerpt files), which are safe to delete because they can be regenerated
from the immutable session logs.

Policy:
- If node.type != "excerpt": ignore
- If meta.pinned is true: keep
- If meta.expiresAt is set and < now: delete markdown file if present

Run:
  python3 memory/tools/prune_excerpts.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def load_nodes(path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def main() -> int:
    root = repo_root()
    nodes_path = os.path.join(root, "memory", "nodes.jsonl")
    nodes = load_nodes(nodes_path)

    now = datetime.now().astimezone()

    deleted = 0
    kept = 0
    missing = 0

    for n in nodes:
        if n.get("type") != "excerpt":
            continue
        meta = n.get("meta") or {}
        if meta.get("pinned") is True:
            kept += 1
            continue
        exp = meta.get("expiresAt")
        if not exp:
            kept += 1
            continue
        try:
            exp_dt = datetime.fromisoformat(exp)
        except Exception:
            kept += 1
            continue
        if exp_dt >= now:
            kept += 1
            continue

        md_rel = meta.get("excerptMarkdown")
        if not md_rel:
            missing += 1
            continue

        md_abs = os.path.join(root, md_rel)
        try:
            if os.path.exists(md_abs):
                os.remove(md_abs)
                deleted += 1
            else:
                missing += 1
        except Exception:
            # best-effort only
            pass

    print(
        json.dumps(
            {
                "ts": now.isoformat(timespec="seconds"),
                "deleted": deleted,
                "kept": kept,
                "missing": missing,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
