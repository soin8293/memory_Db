#!/usr/bin/env python3
"""Rebuild data/index.json from data/nodes.jsonl.

Reads all nodes, groups by scope, and writes a fresh index with all node IDs.
Preserves existing project metadata (dossier paths, tags) where possible.
"""

import json
import os
import sys
from collections import defaultdict

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
NODES_PATH = os.path.join(REPO_ROOT, "memory_system", "data", "nodes.jsonl")
INDEX_PATH = os.path.join(REPO_ROOT, "memory_system", "data", "index.json")


def load_nodes():
    nodes = []
    with open(NODES_PATH, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                nodes.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"WARNING: malformed JSON at line {i}: {e}", file=sys.stderr)
    return nodes


def load_existing_index():
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def main():
    nodes = load_nodes()
    existing = load_existing_index()

    # Group nodes by scope
    by_scope = defaultdict(list)
    all_tags_by_scope = defaultdict(set)

    for node in nodes:
        scope = node.get("scope", "global")
        by_scope[scope].append(node["id"])
        for tag in node.get("tags", []):
            all_tags_by_scope[scope].add(tag)

    # Build new index
    new_index = {"projects": {}, "global": {}}

    # Project scopes
    for scope, node_ids in sorted(by_scope.items()):
        if scope == "global":
            continue

        # Preserve existing project metadata
        existing_proj = existing.get("projects", {}).get(scope, {})
        dossier = existing_proj.get("dossier", f"memory_system/projects/{scope}.md")
        tags = sorted(all_tags_by_scope[scope])

        new_index["projects"][scope] = {
            "dossier": dossier,
            "tags": tags,
            "nodes": sorted(set(node_ids)),
        }

    # Global scope
    global_ids = by_scope.get("global", [])
    new_index["global"] = {
        "tags": sorted(all_tags_by_scope.get("global", set())),
        "nodes": sorted(set(global_ids)),
    }

    # Write
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(new_index, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Report
    total = sum(len(v) if isinstance(v, list) else 0
                for proj in new_index["projects"].values()
                for v in [proj.get("nodes", [])])
    total += len(new_index["global"].get("nodes", []))
    proj_count = len(new_index["projects"])

    print(f"Rebuilt index.json: {total} nodes across {proj_count} projects + global")
    print(f"  Global: {len(new_index['global']['nodes'])} nodes")
    for scope, data in sorted(new_index["projects"].items()):
        print(f"  {scope}: {len(data['nodes'])} nodes")


if __name__ == "__main__":
    main()
