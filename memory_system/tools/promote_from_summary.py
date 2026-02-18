#!/usr/bin/env python3
"""Promote durable memory candidates from a session summary Markdown.

Two outputs:
1) Proposal file (always): memory/proposals/<name>.md
2) Optional apply mode: append confirmed nodes via memory/tools/add_node.py

Design:
- Local-first heuristics (no LLM)
- Ask-first by default when applying
- Deterministic, auditable outputs

Usage:
  # Generate a proposal only
  python3 memory_system/tools/promote_from_summary.py --in ~/clawd/memory_system/data/summaries/<session>.md --workspace ~/clawd

  # Apply interactively (asks y/n per node)
  python3 memory/tools/promote_from_summary.py --in ... --workspace ... --apply

  # Apply non-interactively (dangerous)
  python3 memory/tools/promote_from_summary.py --in ... --workspace ... --apply --yes
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional


@dataclass
class Candidate:
    type: str  # rule|decision|incident|note
    scope: str
    id: str
    text: str
    tags: List[str]
    links: List[str]


def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "item"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", required=True, help="Input summary markdown")
    ap.add_argument("--workspace", default=os.path.expanduser("~/clawd"))
    ap.add_argument("--project", default=None, help="Force project scope slug (e.g., agentoffice)")
    ap.add_argument("--apply", action="store_true", help="Append confirmed nodes via add_node.py")
    ap.add_argument("--yes", action="store_true", help="Auto-confirm all nodes (no prompts)")
    ap.add_argument("--max", type=int, default=12, help="Max candidates")
    return ap.parse_args()


def extract_candidates(text: str, default_scope: str) -> List[Candidate]:
    # Heuristic triggers
    triggers = [
        ("incident", ["rate limit", "hit your limit", "resets", "trust the files", "error", "failed", "timeout"]),
        ("decision", ["we decided", "new rule", "starting now", "we will", "must", "policy"]),
        ("rule", ["rule:", "always", "never", "ask-first", "must", "do not"]),
    ]

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    hits: List[Candidate] = []

    def add(type_: str, seed: str, scope: str, tags: List[str]):
        sid = f"{type_}:{slugify(seed)[:48]}"
        hits.append(
            Candidate(
                type=type_,
                scope=scope,
                id=sid,
                text=seed,
                tags=sorted(set(tags)),
                links=[],
            )
        )

    # Prefer explicit, human-meaningful statements. Avoid dumping raw JSON/tool blobs.
    skip_prefixes = (
        "- **message**:",
        "- errors_seen:",
        "## errors",
        "## tool",
        "## messages",
        "# session summary",
    )

    for ln in lines:
        low = ln.lower()

        # Skip obvious non-signal lines
        if low.startswith(skip_prefixes):
            continue
        if low.startswith("```") or low.startswith("{") or low.startswith("["):
            continue
        # Skip very long lines (usually JSON dumps)
        if len(ln) > 320:
            continue

        # Candidate scope guess
        scope = default_scope
        if "agentoffice" in low or "ralph" in low:
            scope = "agentoffice"

        # High-signal incident patterns (strict)
        if any(k in low for k in [
            "you've hit your limit",
            "hit your limit",
            "resets 9am",
            "do you trust the files",
            "trust the files in this folder",
            "database is not open",
        ]):
            add("incident", ln, scope, ["session", "incident"])
            continue

        # High-signal rule/decision patterns (strict)
        if "new rule" in low or low.startswith("rule:"):
            add("rule", ln, scope, ["session", "rule"])
            continue
        if low.startswith("decision:") or "we decided" in low:
            add("decision", ln, scope, ["session", "decision"])
            continue

        # Generic triggers (conservative)
        for ttype, keys in triggers:
            if ttype == "incident":
                continue  # keep incidents strict
            if any(k in low for k in keys):
                add(ttype, ln, scope, ["session"])
                break

    # De-dupe by (type,text)
    uniq = []
    seen = set()
    for c in hits:
        key = (c.type, c.text)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    # Keep strongest first: incidents, decisions, rules
    order = {"incident": 0, "decision": 1, "rule": 2, "note": 3, "pointer": 4, "project": 5}
    uniq.sort(key=lambda c: (order.get(c.type, 9), len(c.text)))

    return uniq


def write_proposal(path: Path, summary_path: str, candidates: List[Candidate]) -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    md = []
    md.append(f"# Promotion Proposal ({now})\n\n")
    md.append(f"Source summary: `{summary_path}`\n\n")

    if not candidates:
        md.append("No candidates detected.\n")
    else:
        md.append("## Candidate nodes\n")
        for c in candidates:
            md.append(f"- **{c.type}** `{c.id}` scope=`{c.scope}` tags={c.tags}\n")
            md.append(f"  - {c.text}\n")

    md.append("\n## Apply\n")
    md.append("To apply interactively:\n\n")
    md.append("```bash\npython3 memory/tools/promote_from_summary.py --in <summary.md> --workspace <workspace> --apply\n```\n")

    path.write_text("".join(md), encoding="utf-8")


def run_add_node(workspace: str, c: Candidate) -> int:
    add_node = os.path.join(workspace, "memory", "tools", "add_node.py")
    cmd = [
        "python3",
        add_node,
        "--type",
        c.type,
        "--id",
        c.id,
        "--scope",
        c.scope,
        "--text",
        c.text,
    ]
    if c.tags:
        cmd += ["--tags", *c.tags]
    if c.links:
        cmd += ["--links", *c.links]

    p = subprocess.run(cmd)
    return p.returncode


def main() -> int:
    args = parse_args()

    in_path = os.path.expanduser(args.in_path)
    ws = os.path.expanduser(args.workspace)

    if not os.path.exists(in_path):
        raise SystemExit(f"Input summary not found: {in_path}")

    default_scope = args.project or "global"

    text = Path(in_path).read_text(encoding="utf-8", errors="replace")
    candidates = extract_candidates(text, default_scope)[: args.max]

    proposals_dir = Path(ws) / "memory" / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    base = slugify(Path(in_path).stem)
    proposal_path = proposals_dir / f"{base}.md"

    write_proposal(proposal_path, in_path, candidates)
    print(f"Wrote proposal: {proposal_path}")

    if not args.apply:
        return 0

    if not candidates:
        print("No candidates to apply.")
        return 0

    # Apply with ask-first
    for c in candidates:
        if not args.yes:
            print()
            print(f"Apply node? type={c.type} id={c.id} scope={c.scope} tags={c.tags}")
            print(f"  text: {c.text}")
            ans = input("Apply? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                continue

        rc = run_add_node(ws, c)
        if rc != 0:
            print(f"Failed to append node: {c.id} (rc={rc})")

    print("Done applying nodes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
