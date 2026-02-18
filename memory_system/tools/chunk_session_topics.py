#!/usr/bin/env python3
"""Chunk a session JSONL into topic buckets and create memory nodes.

Goal: cheap, deterministic topic chunking for session logs.
- No LLM required
- Buckets by keyword map
- Emits per-topic excerpts + creates nodes via add_node.py

Usage:
  python3 memory/tools/chunk_session_topics.py \
    --in ~/.clawdbot/agents/main/sessions/<id>.jsonl \
    --scope applyops \
    --write-nodes \
    --update-index \
    --report-path memory/summaries/chunk_session_topics.md

Optional:
  --topic-config path/to/topics.json
  --dry-run (prints JSON to stdout, no writes)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Tuple

DEFAULT_TOPICS = {
    "applyops_pipeline": ["applyops", "apply ops", "applyops_cli", "job-system/applyops", "triage", "scrape", "package", "human_ready", "apply"],
    "applyops_forms": ["apply-review", "confirm-submit", "handoff", "form_answers", "apply_answers", "form field", "eeo", "compensation"],
    "applyops_resume": ["resume", "cover_letter", "resumeforge", "resume.pdf", "resume.docx", "cover letter"],
    "applyops_policy": ["allowlist", "blocked_policy", "risk flags", "captcha", "login_required", "reason_code"],
    "control_plane_sheets": ["control plane", "sheets", "google sheets", "JOBS", "PACKETS", "WORK_ORDERS", "dashboard"],
    "automation_browser": ["playwright", "chromium", "browser", "automation", "login", "oauth", "captcha"],
    "memory_system": ["memory", "nodes.jsonl", "embeddings", "index", "recall", "nodes", "memory/tools"],
    "agentoffice_ops": ["agentoffice", "ralph", "worker.sh", "PRD.md", "PROMPT.md", "loop"],
    "tests_ci": ["pytest", "unittest", "tests", "passing", "failing", "coverage"],
    "errors_incidents": ["error", "failed", "exception", "traceback", "crash", "timeout", "rate limit"],
    "decisions_changes": ["decision", "changed", "added", "removed", "refactor", "implemented", "updated"],
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="in_path", required=True)
    p.add_argument("--scope", default="global")
    p.add_argument("--topic-config", default=None)
    p.add_argument("--max-snippets", type=int, default=20)
    p.add_argument("--max-text", type=int, default=320)
    p.add_argument("--write-nodes", action="store_true")
    p.add_argument("--update-index", action="store_true")
    p.add_argument("--report-path", default=None)
    p.add_argument("--auto-buckets", action="store_true")
    p.add_argument("--min-bucket-hits", type=int, default=6)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def load_topics(path: str | None) -> Dict[str, List[str]]:
    if not path:
        # try registry first
        reg = os.path.join(repo_root(), "memory", "topics.json")
        if os.path.exists(reg):
            try:
                data = json.load(open(reg, "r", encoding="utf-8"))
                return {k: list(v) for k, v in (data.get("topics") or {}).items()}
            except Exception:
                pass
        return DEFAULT_TOPICS
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: list(v) for k, v in data.items()}


def safe_slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:60] if s else "session"


def extract_text(msg: Dict[str, Any]) -> str:
    parts = []
    for c in (msg.get("content") or []):
        if c.get("type") == "text":
            t = c.get("text") or ""
            if t:
                parts.append(t)
    return "\n".join(parts).strip()


def clip(text: str, n: int) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t if len(t) <= n else t[: n - 3] + "..."


def match_topic(text: str, topics: Dict[str, List[str]]) -> List[str]:
    t = text.lower()
    hits = []
    for topic, keys in topics.items():
        for k in keys:
            if k.lower() in t:
                hits.append(topic)
                break
    return hits


def load_stopwords() -> set:
    path = os.path.join(repo_root(), "memory", "tools", "stopwords_basic.txt")
    if not os.path.exists(path):
        return set()
    return set([ln.strip() for ln in open(path, "r", encoding="utf-8") if ln.strip()])


def collect_unknown_tokens(text: str, topics: Dict[str, List[str]], stopwords: set) -> List[str]:
    t = text.lower()
    # remove known keywords to avoid re-suggesting
    for keys in topics.values():
        for k in keys:
            t = t.replace(k.lower(), " ")
    # tokens of letters only, length>=4, no digits
    toks = re.findall(r"[a-z]{4,}", t)
    toks = [tok for tok in toks if tok not in stopwords]
    return toks


def collect_bigrams(text: str, stopwords: set) -> List[str]:
    t = re.findall(r"[a-z]{4,}", text.lower())
    t = [tok for tok in t if tok not in stopwords]
    bigrams = [f"{t[i]} {t[i+1]}" for i in range(len(t) - 1)]
    return bigrams


def load_messages(path: str) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
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
            msg = obj.get("message") or {}
            role = msg.get("role") or ""
            text = extract_text(msg)
            if not text:
                continue
            ts = obj.get("timestamp") or ""
            out.append((role, ts, text))
    return out


def ensure_index(scope: str, node_ids: List[str]) -> None:
    idx_path = os.path.join(repo_root(), "memory", "index.json")
    if not os.path.exists(idx_path):
        return
    try:
        idx = json.loads(open(idx_path, "r", encoding="utf-8").read())
    except Exception:
        return
    proj = idx.get("projects", {}).get(scope)
    if not proj:
        return
    nodes = proj.get("nodes") or []
    for nid in node_ids:
        if nid not in nodes:
            nodes.append(nid)
    proj["nodes"] = nodes
    idx["projects"][scope] = proj
    with open(idx_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(idx, indent=2))


def main() -> int:
    args = parse_args()
    in_path = os.path.expanduser(args.in_path)
    if not os.path.exists(in_path):
        raise SystemExit(f"Input not found: {in_path}")

    topics = load_topics(args.topic_config)
    messages = load_messages(in_path)

    buckets: Dict[str, List[str]] = {k: [] for k in topics.keys()}
    unknown_counts: Dict[str, int] = {}
    unknown_bigrams: Dict[str, int] = {}
    stopwords = load_stopwords()

    for role, ts, text in messages:
        hits = match_topic(text, topics)
        if not hits:
            # track unknown tokens/bigrams for auto-bucket suggestions
            if args.auto_buckets:
                for tok in collect_unknown_tokens(text, topics, stopwords):
                    unknown_counts[tok] = unknown_counts.get(tok, 0) + 1
                for bg in collect_bigrams(text, stopwords):
                    unknown_bigrams[bg] = unknown_bigrams.get(bg, 0) + 1
            continue
        snippet = f"[{role} @ {ts}] {clip(text, args.max_text)}"
        for h in hits:
            if len(buckets[h]) < args.max_snippets:
                buckets[h].append(snippet)

    session_name = os.path.basename(in_path)
    out = {
        "session": session_name,
        "scope": args.scope,
        "topics": {k: v for k, v in buckets.items() if v},
    }

    if args.dry_run or not args.write_nodes:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    # Write nodes via add_node.py
    add_node = os.path.join(repo_root(), "memory", "tools", "add_node.py")
    created = []
    for topic, snippets in out["topics"].items():
        if not snippets:
            continue
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        sess_slug = safe_slug(session_name.replace('.jsonl',''))
        node_id = f"excerpt:{args.scope}-{topic}-{sess_slug}-{ts[:10].replace('-', '')}"
        text = (
            f"Topic chunk from session {session_name}\n"
            f"- topic: {topic}\n"
            f"- snippets:\n" + "\n".join(f"  - {s}" for s in snippets)
        )
        subprocess.run(
            [
                "python3",
                add_node,
                "--type",
                "excerpt",
                "--id",
                node_id,
                "--scope",
                args.scope,
                "--text",
                text,
                "--tags",
                "session-logs",
                "topic-chunk",
                topic,
            ],
            check=False,
        )
        created.append(node_id)

    if args.update_index and created:
        ensure_index(args.scope, created)

    if args.auto_buckets and (unknown_counts or unknown_bigrams):
        # auto-suggest buckets based on frequent unknown bigrams/tokens
        reg = os.path.join(repo_root(), "memory", "topics.json")
        auto_path = os.path.join(repo_root(), "memory", "summaries", "auto_buckets.md")
        os.makedirs(os.path.dirname(auto_path), exist_ok=True)
        # load registry
        data = {"topics": {}, "auto": {}}
        if os.path.exists(reg):
            try:
                data = json.load(open(reg, "r", encoding="utf-8"))
            except Exception:
                pass
        auto = data.get("auto") or {}
        promoted = []

        # Prefer bigrams (more signal)
        for bg, cnt in sorted(unknown_bigrams.items(), key=lambda x: (-x[1], x[0])):
            if cnt < int(args.min_bucket_hits):
                continue
            bucket = f"auto_{bg.replace(' ', '_')}"
            if bucket not in auto:
                auto[bucket] = {"keywords": [bg], "hits": cnt, "first_seen": session_name}
                promoted.append(bucket)
            if len(promoted) >= 5:
                break

        # Fallback to single tokens if nothing promoted
        if not promoted:
            for tok, cnt in sorted(unknown_counts.items(), key=lambda x: (-x[1], x[0])):
                if cnt < int(args.min_bucket_hits):
                    continue
                bucket = f"auto_{tok}"
                if bucket not in auto:
                    auto[bucket] = {"keywords": [tok], "hits": cnt, "first_seen": session_name}
                    promoted.append(bucket)
                if len(promoted) >= 5:
                    break

        data["auto"] = auto
        try:
            with open(reg, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2))
        except Exception:
            pass
        if promoted:
            with open(auto_path, "a", encoding="utf-8") as rf:
                rf.write(f"## {session_name}\n")
                rf.write(f"- promoted: {', '.join(promoted)}\n")
                rf.write(f"- threshold: {args.min_bucket_hits}\n")
                rf.write("- rule: bigrams first, max 5 per session\n\n")

    if args.report_path:
        report_path = os.path.join(repo_root(), args.report_path)
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "a", encoding="utf-8") as rf:
            rf.write(f"## {session_name}\n")
            rf.write(f"- scope: {args.scope}\n")
            rf.write(f"- topics: {', '.join(out['topics'].keys()) if out['topics'] else '(none)'}\n")
            rf.write(f"- created_nodes: {', '.join(created) if created else '(none)'}\n\n")

    print(json.dumps({"status": "ok", "created": created}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
