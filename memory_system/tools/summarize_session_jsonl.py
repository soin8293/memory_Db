#!/usr/bin/env python3
"""Summarize a Clawdbot session .jsonl into a compact Markdown file.

Goal: scalable, local-first, no LLM required.
- Parses JSONL line-by-line (streaming)
- Extracts high-signal events: user/assistant messages (truncated), tool calls, errors
- Emits a summary Markdown that *is* indexable by Clawdbot memory_search.

Usage:
  python3 memory_system/tools/summarize_session_jsonl.py \
    --in ~/.clawdbot/agents/main/sessions/<file>.jsonl \
    --out ~/clawd/memory_system/data/summaries/<session>.md \
    --limit-messages 80

Notes:
- This does not replace your curated memory. It's “warm storage.”
- Promote durable items to nodes/dossiers separately.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def clip(s: str, n: int) -> str:
    s = norm(s)
    return s if len(s) <= n else s[: n - 3] + "..."


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="in_path", required=True, help="Input .jsonl session file")
    p.add_argument("--out", dest="out_path", required=True, help="Output markdown")
    p.add_argument("--limit-messages", type=int, default=120)
    p.add_argument("--limit-tools", type=int, default=80)
    p.add_argument("--limit-errors", type=int, default=80)
    p.add_argument("--max-text", type=int, default=220)
    return p.parse_args()


def safe_load(line: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(line)
    except Exception:
        return None


def main() -> int:
    args = parse_args()
    in_path = os.path.expanduser(args.in_path)
    out_path = os.path.expanduser(args.out_path)

    if not os.path.exists(in_path):
        raise SystemExit(f"Input not found: {in_path}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    counts = {
        "lines": 0,
        "messages": 0,
        "tools": 0,
        "errors": 0,
    }

    messages: List[str] = []
    tools: List[str] = []
    errors: List[str] = []

    first_ts: Optional[str] = None
    last_ts: Optional[str] = None

    with open(in_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            counts["lines"] += 1
            obj = safe_load(line)
            if not obj:
                continue

            # Try common timestamp keys
            ts = obj.get("time") or obj.get("ts") or obj.get("createdAt")
            if isinstance(ts, (int, float)):
                # assume ms epoch
                ts = datetime.fromtimestamp(float(ts) / 1000.0).isoformat()
            if isinstance(ts, str):
                first_ts = first_ts or ts
                last_ts = ts

            t = obj.get("type")
            role = obj.get("role")

            # Messages
            if (role in ("user", "assistant")) or (t in ("user", "assistant", "message")):
                if len(messages) < args.limit_messages:
                    text = obj.get("message") or obj.get("text") or obj.get("content")
                    if isinstance(text, list):
                        text = " ".join(str(x) for x in text)
                    if isinstance(text, dict):
                        text = json.dumps(text, ensure_ascii=False)
                    if isinstance(text, str) and text.strip():
                        who = role or t or "message"
                        mid = obj.get("message_id") or obj.get("messageId")
                        mid_s = f" ({mid})" if mid else ""
                        messages.append(f"- **{who}**{mid_s}: {clip(text, args.max_text)}")
                counts["messages"] += 1
                continue

            # Tool calls/results/errors (best-effort)
            if t and "tool" in str(t).lower():
                if len(tools) < args.limit_tools:
                    name = obj.get("tool") or obj.get("name") or obj.get("toolName") or "tool"
                    status = obj.get("status") or obj.get("ok")
                    msg = obj.get("error") or obj.get("message") or obj.get("result")
                    if isinstance(msg, dict):
                        msg = json.dumps(msg, ensure_ascii=False)
                    if isinstance(msg, list):
                        msg = json.dumps(msg, ensure_ascii=False)
                    msg_s = clip(str(msg), args.max_text) if msg is not None else ""
                    tools.append(f"- **{name}**: {msg_s}")
                counts["tools"] += 1
                continue

            # Generic errors
            err = obj.get("error")
            if err:
                if len(errors) < args.limit_errors:
                    if isinstance(err, dict):
                        err = json.dumps(err, ensure_ascii=False)
                    errors.append(f"- {clip(str(err), args.max_text)}")
                counts["errors"] += 1
                continue

    session_name = os.path.basename(in_path)

    md: List[str] = []
    md.append(f"# Session Summary: {session_name}\n\n")
    md.append("## Metadata\n")
    md.append(f"- source: `{in_path}`\n")
    md.append(f"- lines: {counts['lines']}\n")
    md.append(f"- messages_seen: {counts['messages']}\n")
    md.append(f"- tool_events_seen: {counts['tools']}\n")
    md.append(f"- errors_seen: {counts['errors']}\n")
    if first_ts:
        md.append(f"- first_ts: `{first_ts}`\n")
    if last_ts:
        md.append(f"- last_ts: `{last_ts}`\n")
    md.append("\n")

    md.append("## Messages (sampled)\n")
    md.extend([m + "\n" for m in messages] or ["- (none captured)\n"])
    md.append("\n")

    md.append("## Tool activity (sampled)\n")
    md.extend([t + "\n" for t in tools] or ["- (none captured)\n"])
    md.append("\n")

    md.append("## Errors (sampled)\n")
    md.extend([e + "\n" for e in errors] or ["- (none captured)\n"])
    md.append("\n")

    md.append("## Promote to durable memory (manual step)\n")
    md.append("If anything here is durable (rule/decision/incident), append a node via:\n\n")
    md.append("```bash\npython3 memory/tools/add_node.py --type incident --id incident:<slug> --scope <global|project> --text \"...\" --tags ...\n```\n")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("".join(md))

    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
