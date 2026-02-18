#!/usr/bin/env python3
"""Append a memory node to memory/nodes.jsonl.

Design goals:
- safe append-only writes
- stable ids
- minimal required fields

Usage examples:
  python memory/tools/add_node.py --type rule --id rule:review-before-submit --scope global \
    --text "Marty can fill applications, but user reviews before submission." --tags job-search

  python memory/tools/add_node.py --type incident --id incident:claude-rate-limit --scope agentoffice \
    --text "Claude Code limit resets 9am Asia/Seoul" --tags ralph-loop rate-limit
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def iso_now_local() -> str:
    # Use local timezone offset if available.
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--id", required=True)
    p.add_argument(
        "--type",
        required=True,
        choices=["project", "rule", "decision", "incident", "note", "pointer", "excerpt"],
    )
    p.add_argument("--scope", default="global")
    p.add_argument("--text", default="")
    p.add_argument("--tags", nargs="*", default=[])
    p.add_argument("--links", nargs="*", default=[])
    p.add_argument("--meta", default=None, help="JSON object string")
    p.add_argument("--ts", default=None, help="ISO8601 timestamp; defaults to now")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    node = {
        "id": args.id,
        "type": args.type,
        "ts": args.ts or iso_now_local(),
    }

    if args.scope:
        node["scope"] = args.scope
    if args.text:
        node["text"] = args.text
    if args.tags:
        node["tags"] = args.tags
    if args.links:
        node["links"] = args.links
    if args.meta:
        node["meta"] = json.loads(args.meta)

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    out_path = os.path.join(repo_root, "memory_system", "data", "nodes.jsonl")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # Dedupe: avoid duplicate IDs and duplicate (type+scope+text)
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as rf:
                for ln in rf:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        existing = json.loads(ln)
                    except Exception:
                        continue
                    if existing.get("id") == node.get("id"):
                        print(f"SKIP_DUPLICATE_ID: {node['id']}")
                        return 0
                    if (
                        existing.get("type") == node.get("type")
                        and existing.get("scope") == node.get("scope")
                        and existing.get("text")
                        and node.get("text")
                        and str(existing.get("text")).strip() == str(node.get("text")).strip()
                    ):
                        print(f"SKIP_DUPLICATE_FACT: {node['type']}::{node.get('scope')}::{node.get('text')}")
                        return 0
        except Exception as e:
            print(f"WARNING: dedup check failed (proceeding with write): {e}", file=sys.stderr)

    line = json.dumps(node, ensure_ascii=False)
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    # Append to WAL for incremental indexing
    wal_path = os.path.join(repo_root, "memory_system", "data", "wal.jsonl")
    try:
        os.makedirs(os.path.dirname(wal_path), exist_ok=True)
        wal_entry = {
            "op": "add",
            "node_id": node["id"],
            "text": node.get("text", ""),
            "ts": node.get("ts"),
        }
        with open(wal_path, "a", encoding="utf-8") as wf:
            wf.write(json.dumps(wal_entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"WARNING: WAL write failed (node saved, indexing may lag): {e}", file=sys.stderr)

    # Keep a Markdown view up to date for Clawdbot memory_search (Markdown-only index).
    render_path = os.path.join(repo_root, "memory", "tools", "render_nodes.py")
    try:
        ret = os.system(f"python3 {render_path} >/dev/null 2>&1")
        if ret != 0:
            print(f"WARNING: render_nodes.py exited {ret} (markdown view may be stale)", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: render_nodes.py failed: {e}", file=sys.stderr)

    # Also render for OpenClaw indexing
    openclaw_render = os.path.join(repo_root, "memory_system", "tools", "render_nodes_for_openclaw.py")
    try:
        ret = os.system(f"python3 {openclaw_render} >/dev/null 2>&1")
        if ret != 0:
            print(f"WARNING: render_nodes_for_openclaw.py exited {ret} (search index may be stale)", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: render_nodes_for_openclaw.py failed: {e}", file=sys.stderr)

    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
