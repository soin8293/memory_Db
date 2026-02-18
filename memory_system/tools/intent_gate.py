#!/usr/bin/env python3
"""Deterministic intent classification for recall + policy selection.

This avoids relying on embeddings for basic routing.

Output JSON:
{
  "intents": ["security.external_action", ...],
  "buckets": ["core", "security", "ops", "project:agentoffice"],
  "notes": ["..."],
}
"""

from __future__ import annotations

import argparse
import json
import re


def classify(text: str):
    t = (text or "").strip().lower()

    intents = set()
    buckets = {"core"}
    notes = []

    # External actions / high risk
    if re.search(r"\b(send|message|dm|text|notify|post|publish|email)\b", t):
        intents.add("security.external_action")
        buckets.add("security")
        notes.append("Potential outbound action")

    if re.search(r"\b(config|token|api key|secret|credential|password|rotate)\b", t):
        intents.add("security.credentials")
        buckets.add("security")
        notes.append("Sensitive config/credentials")

    if re.search(r"\b(delete|rm\b|wipe|purge|remove job|disable)\b", t):
        intents.add("security.destructive")
        buckets.add("security")
        notes.append("Potentially destructive")

    # Ops / reliability
    if re.search(r"\b(crash|restart|disconnect|down|not responding|gateway|launchagent|launchd|cron)\b", t):
        intents.add("ops.runtime")
        buckets.add("ops")

    # Explicit memory recall
    if re.search(r"\b(remember|what did we decide|recall|last time|previous|how did we set)\b", t):
        intents.add("memory.recall")
        buckets.add("memory")

    # Project scoping
    if re.search(r"\b(agentoffice|ralph)\b", t):
        intents.add("project.agentoffice")
        buckets.add("project:agentoffice")

    if re.search(r"\b(applyops|apply.?ops|job.?system|job.?pipeline)\b", t):
        intents.add("project.applyops")
        buckets.add("project:applyops")

    return {
        "intents": sorted(intents),
        "buckets": sorted(buckets),
        "notes": notes,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="*", help="text to classify")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    text = " ".join(args.text).strip()
    out = classify(text)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
