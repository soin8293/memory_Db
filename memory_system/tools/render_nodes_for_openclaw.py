#!/usr/bin/env python3
"""Render nodes.jsonl to individual markdown files for OpenClaw indexing.

Each node becomes a .md file in memory/nodes_rendered/ with YAML frontmatter
and text content. This allows OpenClaw's memory-core plugin to index custom
nodes alongside session summaries.

Usage:
    python3 render_nodes_for_openclaw.py [--nodes-path PATH] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from memory_system.paths import default_nodes_path


def sanitize_filename(node_id: str) -> str:
    """Convert node ID to safe filename."""
    # Replace colons with underscores, remove other unsafe chars
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", node_id)
    return safe[:100]  # Limit length


def render_node_markdown(node: Dict[str, Any]) -> str:
    """Render a single node to markdown with frontmatter."""
    node_id = node.get("id", "unknown")
    node_type = node.get("type", "note")
    ts = node.get("ts", "")
    scope = node.get("scope", "global")
    text = node.get("text", "")
    tags = node.get("tags", [])
    meta = node.get("meta", {})

    # Build YAML frontmatter
    lines = [
        "---",
        f"id: {node_id}",
        f"type: {node_type}",
        f"scope: {scope}",
    ]

    if ts:
        lines.append(f"ts: {ts}")

    if tags:
        if isinstance(tags, list):
            tag_str = ", ".join(str(t) for t in tags)
        else:
            tag_str = str(tags)
        lines.append(f"tags: [{tag_str}]")

    if meta and isinstance(meta, dict):
        if meta.get("priority"):
            lines.append(f"priority: {meta['priority']}")
        if meta.get("source_path"):
            lines.append(f"source: {meta['source_path']}")

    lines.append("---")
    lines.append("")

    # Title from node ID
    title = node_id.replace(":", ": ").replace("-", " ").title()
    lines.append(f"# {title}")
    lines.append("")

    # Main text content
    if text:
        lines.append(text)
        lines.append("")

    # Additional metadata section
    if meta and isinstance(meta, dict):
        extra_meta = {k: v for k, v in meta.items() if k not in ("priority", "source_path")}
        if extra_meta:
            lines.append("## Metadata")
            for k, v in extra_meta.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render nodes to markdown for OpenClaw")
    parser.add_argument(
        "--nodes-path",
        type=Path,
        default=default_nodes_path(),
        help="Path to nodes.jsonl"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_nodes_path().parent.parent / "nodes_rendered",
        help="Output directory for markdown files"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove output directory before rendering"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing"
    )

    args = parser.parse_args()

    nodes_path = args.nodes_path.expanduser()
    output_dir = args.output_dir.expanduser()

    if not nodes_path.exists():
        print(f"Error: nodes file not found: {nodes_path}", file=sys.stderr)
        return 1

    # Clean output directory if requested
    if args.clean and output_dir.exists() and not args.dry_run:
        shutil.rmtree(output_dir)

    # Create output directory
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Process nodes
    node_count = 0
    error_count = 0

    with nodes_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                node = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"Warning: invalid JSON on line {line_num}: {e}", file=sys.stderr)
                error_count += 1
                continue

            if not isinstance(node, dict):
                continue

            node_id = node.get("id", f"node_{line_num}")
            filename = sanitize_filename(node_id) + ".md"
            output_path = output_dir / filename

            markdown = render_node_markdown(node)

            if args.dry_run:
                print(f"Would write: {output_path} ({len(markdown)} bytes)")
            else:
                output_path.write_text(markdown, encoding="utf-8")

            node_count += 1

    # Summary
    action = "Would render" if args.dry_run else "Rendered"
    print(f"{action} {node_count} nodes to {output_dir}")
    if error_count:
        print(f"Errors: {error_count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
