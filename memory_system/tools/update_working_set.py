#!/usr/bin/env python3
"""Update memory/WORKING_SET.md safely.

Design goals:
- Safe by default: only touches WORKING_SET.md (+ optional backup).
- Deterministic, small output: keep under ~100 lines.
- Pulls from:
  - MEMORY.md (identity + hard rules)
  - memory/policy/core.md (always-on policy)
  - memory/state.json (operational state)
  - optional: last N events from memory/events.jsonl

Usage:
  python3 memory/tools/update_working_set.py [--dry-run] [--backup]

Exit codes:
  0 success
  2 missing required files
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEMORY_MD = ROOT / "MEMORY.md"
CORE_MD = ROOT / "memory" / "policy" / "core.md"
STATE_JSON = ROOT / "memory" / "state.json"
EVENTS_JSONL = ROOT / "memory" / "events.jsonl"
WORKING_SET = ROOT / "memory" / "WORKING_SET.md"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _extract_hard_rules_from_memory_md(text: str) -> list[str]:
    # Keep it simple: take bullet lines under "Identity & preferences" that start with "- Hard rule:".
    lines = text.splitlines()
    rules: list[str] = []
    for line in lines:
        s = line.strip()
        if s.lower().startswith("- hard rule:"):
            rules.append(s[len("- hard rule:"):].strip())
    return rules[:8]


def _load_state() -> dict:
    if not STATE_JSON.exists():
        return {}
    try:
        return json.loads(_read_text(STATE_JSON))
    except Exception:
        return {"_error": "failed to parse state.json"}


def _tail_events(max_events: int = 10) -> list[str]:
    if not EVENTS_JSONL.exists():
        return []
    try:
        lines = _read_text(EVENTS_JSONL).splitlines()
        lines = [ln for ln in lines if ln.strip()]
        return lines[-max_events:]
    except Exception:
        return []


def render_working_set(*, memory_md: str, core_md: str, state: dict, events: list[str]) -> str:
    updated = _now_iso()
    hard_rules = _extract_hard_rules_from_memory_md(memory_md)

    mode = state.get("mode", "build")
    blockers = state.get("blockers", []) or []

    def fmt_blockers() -> list[str]:
        out: list[str] = []
        for b in blockers[:5]:
            if isinstance(b, dict):
                t = b.get("type", "blocker")
                detail = b.get("detail", "")
                out.append(f"- ({t}) {detail}".rstrip())
            else:
                out.append(f"- {str(b)}")
        return out

    core_lines = [ln.strip() for ln in core_md.splitlines() if ln.strip().startswith("-")]
    core_lines = core_lines[:8]

    event_lines: list[str] = []
    for ln in events:
        # Avoid dumping huge JSON; just show the first 200 chars
        event_lines.append("- " + (ln[:200] + ("…" if len(ln) > 200 else "")))

    parts: list[str] = []
    parts.append("<!-- GENERATED. DO NOT EDIT. -->")
    parts.append("# WORKING_SET (Global)")
    parts.append("")
    parts.append(f"Updated: {updated}")
    parts.append(f"Mode: {mode}")
    parts.append("")

    parts.append("## Active hard rules (from MEMORY.md)")
    parts.extend([f"- {r}" for r in hard_rules] or ["- (none)"])
    parts.append("")

    parts.append("## Always-on policy (from memory/policy/core.md)")
    parts.extend(core_lines or ["- (none)"])
    parts.append("")

    parts.append("## Blockers (from memory/state.json)")
    parts.extend(fmt_blockers() or ["- (none)"])
    parts.append("")

    parts.append("## Recent events (from memory/events.jsonl)")
    parts.extend(event_lines or ["- (none)"])
    parts.append("")

    # Keep file reasonably small
    text = "\n".join(parts).strip() + "\n"
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backup", action="store_true")
    args = ap.parse_args()

    if not MEMORY_MD.exists() or not CORE_MD.exists():
        print("Missing MEMORY.md or memory/policy/core.md")
        return 2

    memory_md = _read_text(MEMORY_MD)
    core_md = _read_text(CORE_MD)
    state = _load_state()
    events = _tail_events(10)

    out = render_working_set(memory_md=memory_md, core_md=core_md, state=state, events=events)

    if args.dry_run:
        print(out)
        return 0

    if args.backup and WORKING_SET.exists():
        backup = WORKING_SET.with_suffix(f".md.bak.{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        WORKING_SET.replace(backup)

    WORKING_SET.write_text(out, encoding="utf-8")
    print(f"Wrote {WORKING_SET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
