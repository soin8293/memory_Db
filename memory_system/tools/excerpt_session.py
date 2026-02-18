#!/usr/bin/env python3
"""Create a deterministic, AI-friendly excerpt from Clawdbot session logs.

This is the implementation of the hands-off "session-log recall → persisted excerpt" policy.

Design:
- Source of truth remains immutable: ~/.clawdbot/agents/<agentId>/sessions/*.jsonl
- We generate derived artifacts:
  - a node in memory/nodes.jsonl (type=excerpt) with provenance + hash + TTL
  - a markdown file in memory/excerpts/<id>.md (redacted) for human browsing + memory_search

Defaults:
- include roles: user + assistant
- exclude toolResult messages unless --include-tool is passed
- adaptive window: start ±3, expand up to ±10, stop when added context isn't adding query signal
- TTL: 30 days (unless --pin)

Usage:
  python3 memory/tools/excerpt_session.py --query "SORBARIKOR INENE (303)" --out-id excerpt:resume-neighborhood

If --out-id is omitted, an id is generated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


def iso_now_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_iso(ts: str) -> datetime:
    # Python 3.11+ supports fromisoformat with timezone offsets.
    return datetime.fromisoformat(ts)


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def sessions_dir(agent_id: str) -> str:
    return os.path.expanduser(f"~/.clawdbot/agents/{agent_id}/sessions")


TOKEN_RE = re.compile(r"[^a-z0-9]+")


def tokenize(text: str) -> List[str]:
    text = text.lower()
    toks = [t for t in TOKEN_RE.split(text) if len(t) >= 3]
    # de-dupe while preserving order
    seen = set()
    out = []
    for t in toks:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:30]


def redact_secrets(text: str) -> str:
    # Purposefully conservative: redact high-risk secrets without destroying resumes.
    patterns = [
        # Bearer tokens
        (re.compile(r"(?i)(authorization\s*:\s*bearer)\s+[^\s]+"), r"\\1 ***REDACTED***"),
        # OpenAI-style keys
        (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "sk-***REDACTED***"),
        # Generic API key fields
        (re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)[^\"\s]+"), r"\\1***REDACTED***"),
        (re.compile(r"(?i)(gatewayToken\"?\s*[:=]\s*\"?)[^\"\s]+"), r"\\1***REDACTED***"),
        (re.compile(r"(?i)(token\"?\s*[:=]\s*\"?)[^\"\s]{20,}"), r"\\1***REDACTED***"),
    ]
    out = text
    for rx, repl in patterns:
        out = rx.sub(repl, out)
    return out


@dataclass
class Msg:
    id: str
    ts: str
    role: str
    text: str


def extract_text(message: Dict[str, Any]) -> str:
    parts = []
    for c in (message.get("content") or []):
        if c.get("type") == "text":
            t = c.get("text") or ""
            if t:
                parts.append(t)
    return "\n".join(parts).strip()


def load_session_messages(path: str, include_tool: bool) -> List[Msg]:
    msgs: List[Msg] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != "message":
                continue
            m = obj.get("message") or {}
            role = m.get("role") or ""
            if (role == "toolResult") and not include_tool:
                continue
            text = extract_text(m)
            if not text:
                continue
            msgs.append(Msg(id=obj.get("id") or "", ts=obj.get("timestamp") or "", role=role, text=text))
    return msgs


def score_anchor(msg: Msg, query: str, q_toks: List[str]) -> Tuple[int, int, int, int]:
    """Return a sortable score tuple.

    Order matters; higher is better.
    """
    t = msg.text.lower()
    q = query.lower()

    exact = t.count(q) if q else 0
    tok_hits = sum(1 for tok in q_toks if tok in t)
    role_bonus = 2 if msg.role == "user" else (1 if msg.role == "assistant" else 0)
    length_bonus = min(20000, len(msg.text))  # cap so giant messages don't dominate alone

    # Primary: exact phrase matches; then token hits; then role; then length
    return (exact, tok_hits, role_bonus, length_bonus)


def pick_anchor(sessions: List[str], query: str, q_toks: List[str], include_tool: bool) -> Tuple[str, int, Msg]:
    best: Tuple[Tuple[int, int, int, int], str, int, Msg] | None = None

    for p in sessions:
        msgs = load_session_messages(p, include_tool=include_tool)
        for i, m in enumerate(msgs):
            t = m.text.lower()
            q = query.lower()
            if q and q not in t:
                # fallback: token hit (looser)
                if not any(tok in t for tok in q_toks):
                    continue
            s = score_anchor(m, query=query, q_toks=q_toks)
            if s[0] == 0 and s[1] == 0:
                continue
            # break ties by timestamp recency only at the end
            if best is None or s > best[0] or (s == best[0] and m.ts > best[3].ts):
                best = (s, p, i, m)

    if best is None:
        raise SystemExit("NO_MATCH: could not find query in any session logs")

    _, path, idx, msg = best
    return path, idx, msg


def window_has_signal(msgs: List[Msg], q_toks: List[str]) -> bool:
    text = "\n".join(m.text.lower() for m in msgs)
    return any(tok in text for tok in q_toks)


def build_excerpt_window(
    all_msgs: List[Msg],
    anchor_idx: int,
    q_toks: List[str],
    start: int,
    max_w: int,
    max_chars: int,
) -> Tuple[int, int, List[Msg]]:
    """Build a message-bounded excerpt around an anchor.

    Guarantees:
    - Includes the anchor message.
    - Does not exceed max_chars by shrinking if necessary.
    """

    def slice_window(b: int, a: int) -> List[Msg]:
        lo = max(0, anchor_idx - b)
        hi = min(len(all_msgs), anchor_idx + a + 1)
        return all_msgs[lo:hi]

    def excerpt_len(ms: List[Msg]) -> int:
        return sum(len(m.text) for m in ms)

    def shrink_to_cap(b: int, a: int) -> Tuple[int, int, List[Msg]]:
        """Shrink symmetrically-ish from ends until within cap (never drops anchor)."""
        bb, aa = b, a
        while bb >= 0 and aa >= 0:
            ms = slice_window(bb, aa)
            if excerpt_len(ms) <= max_chars:
                return bb, aa, ms
            # Prefer dropping tool-heavy outer context first by trimming the larger side
            if bb >= aa and bb > 0:
                bb -= 1
            elif aa > 0:
                aa -= 1
            else:
                break
        # Worst case: anchor alone (may still exceed cap; we'll truncate on write)
        return 0, 0, [all_msgs[anchor_idx]]

    # Start with a symmetric window.
    best_b, best_a, best_msgs = shrink_to_cap(start, start)

    # Expand gradually until we stop adding signal or we hit caps.
    no_gain_steps = 0
    for w in range(start + 1, max_w + 1):
        cand_b, cand_a, cand = shrink_to_cap(w, w)
        # If even the shrunken candidate equals our current, no point continuing.
        if cand_b == best_b and cand_a == best_a:
            break

        prev_sig = window_has_signal(best_msgs, q_toks)
        cand_sig = window_has_signal(cand, q_toks)

        if cand_sig and (not prev_sig or excerpt_len(cand) >= excerpt_len(best_msgs)):
            best_msgs = cand
            best_b = cand_b
            best_a = cand_a
            no_gain_steps = 0
        else:
            no_gain_steps += 1

        if no_gain_steps >= 2:
            break

    return best_b, best_a, best_msgs


def canonical_hash(session_file: str, msg_ids: List[str], extracted: Dict[str, str]) -> str:
    payload = {
        "sessionFile": session_file,
        "messageIds": msg_ids,
        "extracted": extracted,
    }
    canon = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def find_existing_excerpt_by_hash(nodes: List[Dict[str, Any]], h: str) -> Optional[Dict[str, Any]]:
    for n in nodes:
        if n.get("type") != "excerpt":
            continue
        meta = n.get("meta") or {}
        if meta.get("hash") == h:
            return n
    return None


def load_nodes() -> List[Dict[str, Any]]:
    p = os.path.join(repo_root(), "memory", "nodes.jsonl")
    if not os.path.exists(p):
        return []
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def safe_slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    if not s:
        s = "excerpt"
    return s[:60]


def write_excerpt_md(out_path: str, meta: Dict[str, Any], msgs: List[Msg], max_chars: int) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # Frontmatter
    fm = {"excerpt": meta}
    lines = ["---\n", json.dumps(fm, ensure_ascii=False, indent=2), "\n---\n\n"]

    lines.append("# Excerpt\n\n")
    lines.append("## Transcript\n\n")

    remaining = max_chars
    for m in msgs:
        raw = redact_secrets(m.text)
        # Ensure we never write an enormous blob; truncate per-message.
        if len(raw) > remaining:
            raw = raw[: max(0, remaining)]
            raw = raw.rstrip() + "\n\n[TRUNCATED: excerpt max_chars budget reached; re-extract from session logs if needed.]\n"
            remaining = 0
        else:
            remaining -= len(raw)

        lines.append(f"### {m.role} · {m.ts} · {m.id}\n\n")
        lines.append(raw)
        lines.append("\n\n---\n\n")

        if remaining <= 0:
            break

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("".join(lines))


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--agent-id", default="main")
    ap.add_argument("--auto-include-tool", action="store_true", default=True, help="Default behavior: include toolResult messages")
    ap.add_argument("--out-id", default=None, help="node id like excerpt:resume-neighborhood")
    ap.add_argument("--scope", default="global")
    ap.add_argument("--include-tool", action="store_true", help="Include toolResult messages")
    ap.add_argument("--start", type=int, default=3)
    ap.add_argument("--max-window", type=int, default=10)
    ap.add_argument("--max-chars", type=int, default=20000)
    ap.add_argument("--ttl-days", type=int, default=30)
    ap.add_argument("--pin", action="store_true")
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    include_tool = True
    # Allow explicit override: if user passes --include-tool, keep True; if they ever add
    # a --no-include-tool later, it should override here.
    if hasattr(args, "auto_include_tool"):
        include_tool = bool(args.auto_include_tool)
    if getattr(args, "include_tool", False):
        include_tool = True

    sess_dir = sessions_dir(args.agent_id)
    if not os.path.isdir(sess_dir):
        raise SystemExit(f"NO_SESSIONS_DIR: {sess_dir}")

    sessions = [
        os.path.join(sess_dir, f)
        for f in os.listdir(sess_dir)
        if f.endswith(".jsonl") and not f.endswith(".lock")
    ]

    # Search newest sessions first (best guess). If tie, content scoring wins.
    sessions.sort(key=lambda p: os.path.getmtime(p), reverse=True)

    query = args.query
    q_toks = tokenize(query)

    anchor_path, anchor_idx, anchor = pick_anchor(sessions, query=query, q_toks=q_toks, include_tool=include_tool)

    all_msgs = load_session_messages(anchor_path, include_tool=include_tool)

    before, after, excerpt_msgs = build_excerpt_window(
        all_msgs,
        anchor_idx=anchor_idx,
        q_toks=q_toks,
        start=max(1, args.start),
        max_w=max(args.start, args.max_window),
        max_chars=args.max_chars,
    )

    msg_ids = [m.id for m in excerpt_msgs]
    extracted = {m.id: m.text for m in excerpt_msgs}
    h = canonical_hash(os.path.basename(anchor_path), msg_ids, extracted)

    nodes = load_nodes()
    existing = find_existing_excerpt_by_hash(nodes, h)
    if existing:
        print(json.dumps({"status": "deduped", "existing": existing.get("id"), "hash": h}, ensure_ascii=False))
        return 0

    out_id = args.out_id
    if not out_id:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_id = f"excerpt:{stamp}-{safe_slug(q_toks[0] if q_toks else 'log')}"

    expires_at = None
    if not args.pin:
        expires_at = (datetime.now().astimezone() + timedelta(days=args.ttl_days)).isoformat(timespec="seconds")

    meta = {
        "query": query,
        "sessionFile": os.path.basename(anchor_path),
        "sessionPath": anchor_path,
        "anchorMessageId": anchor.id,
        "anchorMessageIndex": anchor_idx,
        "window": {"before": before, "after": after},
        "includeTool": bool(include_tool),
        "hash": h,
        "pinned": bool(args.pin),
        "expiresAt": expires_at,
    }

    md_rel = os.path.join("memory", "excerpts", f"{out_id.replace(':', '_')}.md")
    md_abs = os.path.join(repo_root(), md_rel)
    meta["excerptMarkdown"] = md_rel

    write_excerpt_md(md_abs, meta=meta, msgs=excerpt_msgs, max_chars=args.max_chars)

    # Append node
    add_node = os.path.join(repo_root(), "memory", "tools", "add_node.py")
    node_text = (
        f"Excerpt for query: {query}\n"
        f"- session: {os.path.basename(anchor_path)}\n"
        f"- anchor: {anchor.id} ({anchor.ts})\n"
        f"- window: -{before} / +{after}\n"
        f"- md: {md_rel}\n"
    )

    import subprocess

    subprocess.run(
        [
            "python3",
            add_node,
            "--type",
            "excerpt",
            "--id",
            out_id,
            "--scope",
            args.scope,
            "--text",
            node_text,
            "--meta",
            json.dumps(meta, ensure_ascii=False),
            "--tags",
            "memory",
            "excerpts",
            "session-logs",
        ],
        check=False,
    )

    print(json.dumps({"status": "created", "id": out_id, "hash": h, "md": md_rel}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
