#!/usr/bin/env python3
"""MemoryDB facade with pluggable stores (global + per-project).

Usage:
  from memory_system.memorydb import MemoryDB
  db = MemoryDB(project="polymarket-alpha")
  db.add_node(...)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional

try:
    from .paths import default_data_dir, default_nodes_path, default_store_root, default_wal_path
except ImportError:
    from paths import default_data_dir, default_nodes_path, default_store_root, default_wal_path

JOT_TYPE = "note"
JOT_TAG = "jot"

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(PACKAGE_DIR, ".."))
DATA_DIR = str(default_data_dir())
GLOBAL_NODES = str(default_nodes_path())
GLOBAL_WAL = str(default_wal_path())
PROJECT_ROOT = str(default_store_root())

BASE_TAGS = {
    "decision",
    "constraint",
    "source",
    "insight",
    "risk",
    "next-step",
    "contact",
}


def _python_tool_command(tool_name: str, *args: str) -> List[str]:
    """Build a tool command using the interpreter running MemoryDB."""
    return [sys.executable, os.path.join(PACKAGE_DIR, "tools", tool_name), *args]


def _run_tool_silently(tool_name: str, *args: str) -> None:
    """Run a bundled maintenance tool without platform-specific shell syntax."""
    subprocess.run(
        _python_tool_command(tool_name, *args),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

OPTIONAL_TAGS = {
    "metric",
    "deadline",
    "process",
    "tool",
    "assumption",
}


def iso_now_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class MemoryDB:
    project: Optional[str] = None
    enforce_tags: bool = True
    store_path: Optional[str] = None  # Direct path to project store dir (bypasses central PROJECT_ROOT)

    @property
    def is_global(self) -> bool:
        return not self.project

    @property
    def project_dir(self) -> str:
        if self.store_path:
            return os.path.abspath(self.store_path)
        if not self.project:
            raise ValueError("project is required for project-scoped store")
        return os.path.join(PROJECT_ROOT, self.project)

    def _ensure_project_layout(self) -> None:
        if self.is_global:
            return
        os.makedirs(self.project_dir, exist_ok=True)
        os.makedirs(os.path.join(self.project_dir, "daily"), exist_ok=True)
        os.makedirs(os.path.join(self.project_dir, "embeddings"), exist_ok=True)
        tags_path = os.path.join(self.project_dir, "tags.json")
        if not os.path.exists(tags_path):
            tags_payload = {
                "required_base_tags": sorted(BASE_TAGS),
                "optional_tags": sorted(OPTIONAL_TAGS),
                "project_tags": [self.project],
            }
            with open(tags_path, "w", encoding="utf-8") as wf:
                json.dump(tags_payload, wf, indent=2)
        index_path = os.path.join(self.project_dir, "index.json")
        if not os.path.exists(index_path):
            with open(index_path, "w", encoding="utf-8") as wf:
                json.dump({"project": self.project, "nodes": []}, wf, indent=2)

        dossier = os.path.join(self.project_dir, "dossier.md")
        if not os.path.exists(dossier):
            with open(dossier, "w", encoding="utf-8") as wf:
                wf.write(f"# {self.project}\n\n## Scope\n- Mission:\n- Owner:\n- Constraints:\n- KPIs:\n\n## Current Objective (6–12 weeks)\n- Objective:\n- Success criteria:\n- Deadline:\n\n## Decisions\n- \n\n## Constraints\n- \n\n## Research Index\n- Sources:\n- Key insights:\n- Risks:\n- Next steps:\n")

    def _load_tag_whitelist(self) -> Optional[set]:
        if self.is_global:
            return None
        tags_path = os.path.join(self.project_dir, "tags.json")
        if not os.path.exists(tags_path):
            return None
        try:
            with open(tags_path, "r", encoding="utf-8") as rf:
                data = json.load(rf)
            allowed = set(data.get("required_base_tags", [])) | set(data.get("optional_tags", [])) | set(
                data.get("project_tags", [])
            )
            return allowed
        except Exception:
            return None

    def _validate_tags(self, tags: List[str]) -> None:
        if not self.enforce_tags:
            return
        if not tags:
            raise ValueError("tags are required")
        allowed = self._load_tag_whitelist()
        if allowed is None:
            # fallback to base+optional if no whitelist exists
            allowed = BASE_TAGS | OPTIONAL_TAGS | ({self.project} if self.project else set())
        unknown = [t for t in tags if t not in allowed]
        if unknown:
            raise ValueError(f"unknown tags: {', '.join(unknown)}")
        # must include at least one base tag
        if not any(t in BASE_TAGS for t in tags):
            raise ValueError("must include at least one base tag")

    def add_node(
        self,
        *,
        node_id: str,
        node_type: str,
        text: str = "",
        tags: Optional[List[str]] = None,
        links: Optional[List[str]] = None,
        meta: Optional[dict] = None,
        ts: Optional[str] = None,
    ) -> dict:
        tags = tags or []
        links = links or []
        if not self.is_global:
            self._ensure_project_layout()
            self._validate_tags(tags)
        node = {
            "id": node_id,
            "type": node_type,
            "ts": ts or iso_now_local(),
        }
        if self.project:
            node["scope"] = self.project
        if text:
            node["text"] = text
        if tags:
            node["tags"] = tags
        if links:
            node["links"] = links
        if meta:
            node["meta"] = meta

        if self.is_global:
            out_path = GLOBAL_NODES
            wal_path = GLOBAL_WAL
        else:
            out_path = os.path.join(self.project_dir, "nodes.jsonl")
            wal_path = os.path.join(self.project_dir, "wal.jsonl")

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
                            return {"status": "SKIP_DUPLICATE_ID", "id": node_id}
                        if (
                            existing.get("type") == node.get("type")
                            and existing.get("scope") == node.get("scope")
                            and existing.get("text")
                            and node.get("text")
                            and str(existing.get("text")).strip() == str(node.get("text")).strip()
                        ):
                            return {"status": "SKIP_DUPLICATE_FACT", "id": node_id}
            except Exception:
                pass

        line = json.dumps(node, ensure_ascii=False)
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        # WAL (optional)
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
        except Exception:
            pass

        # Update project index
        if not self.is_global:
            index_path = os.path.join(self.project_dir, "index.json")
            try:
                if os.path.exists(index_path):
                    with open(index_path, "r", encoding="utf-8") as rf:
                        data = json.load(rf)
                else:
                    data = {"project": self.project, "nodes": []}
                if node["id"] not in data.get("nodes", []):
                    data.setdefault("nodes", []).append(node["id"])
                with open(index_path, "w", encoding="utf-8") as wf:
                    json.dump(data, wf, indent=2)
            except Exception:
                pass

        # Render global views only for global ledger
        if self.is_global:
            try:
                _run_tool_silently("render_nodes.py")
            except Exception:
                pass
            try:
                _run_tool_silently("render_nodes_for_openclaw.py")
            except Exception:
                pass

        return node

    def recall(self, query: str) -> str:
        if self.is_global:
            cmd = _python_tool_command("recall.py", "--query", query, "--global")
        else:
            cmd = _python_tool_command(
                "recall.py",
                "--query",
                query,
                "--nodes",
                os.path.join(self.project_dir, "nodes.jsonl"),
            )
        return subprocess.check_output(cmd, text=True)

    def query(self, scope: Optional[str] = None, node_type: Optional[str] = None) -> str:
        args = _python_tool_command("query_nodes.py")
        if self.is_global:
            args += ["--nodes", GLOBAL_NODES]
        else:
            args += ["--nodes", os.path.join(self.project_dir, "nodes.jsonl")]
        if scope:
            args += ["--scope", scope]
        if node_type:
            args += ["--type", node_type]
        return subprocess.check_output(args, text=True)


    # ── Fast-path jot API ──────────────────────────────────────────────

    def jot(self, text: str, *, tags: Optional[List[str]] = None, rebuild_index: bool = False) -> dict:
        """One-liner note capture. Auto-generates ID, skips tag validation.

        Args:
            text: The note text (required).
            tags: Extra tags to append alongside ["jot"].
            rebuild_index: If True, rebuild per-project keyword index after write.

        Returns:
            The written node dict, or a SKIP_DUPLICATE dict.
        """
        if not self.project:
            raise ValueError("jot() requires a project scope")

        self._ensure_project_layout()
        ts = iso_now_local()

        hash_input = f"{ts}:{text}"
        short_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:8]
        node_id = f"jot:{self.project}-{short_hash}"

        all_tags = [JOT_TAG] + (tags or [])

        node = {
            "id": node_id,
            "type": JOT_TYPE,
            "scope": self.project,
            "ts": ts,
            "text": text,
            "tags": all_tags,
        }

        out_path = os.path.join(self.project_dir, "nodes.jsonl")

        # Lightweight dedup: only check exact text match among jots
        if os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8") as rf:
                for ln in rf:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        existing = json.loads(ln)
                    except Exception:
                        continue
                    if (
                        JOT_TAG in (existing.get("tags") or [])
                        and existing.get("text", "").strip() == text.strip()
                    ):
                        return {"status": "SKIP_DUPLICATE_FACT", "id": node_id}

        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")

        # Update project index
        self._update_project_index([node_id])

        if rebuild_index:
            self._rebuild_project_keyword_index()

        return node

    def jot_batch(self, texts: List[str], *, rebuild_index: bool = False) -> List[dict]:
        """Write N jot notes in one call. Single dedup pass, single file open.

        Args:
            texts: List of note strings.
            rebuild_index: If True, rebuild per-project keyword index after write.

        Returns:
            List of written node dicts (or SKIP dicts for dupes).
        """
        if not self.project:
            raise ValueError("jot_batch() requires a project scope")

        self._ensure_project_layout()
        out_path = os.path.join(self.project_dir, "nodes.jsonl")

        # Load existing jot texts for dedup (single scan)
        existing_texts: set = set()
        if os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8") as rf:
                for ln in rf:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        existing = json.loads(ln)
                    except Exception:
                        continue
                    if JOT_TAG in (existing.get("tags") or []):
                        existing_texts.add(existing.get("text", "").strip())

        ts = iso_now_local()
        results: List[dict] = []
        new_lines: List[str] = []
        new_ids: List[str] = []

        for i, text in enumerate(texts):
            text_stripped = text.strip()
            if text_stripped in existing_texts:
                results.append({"status": "SKIP_DUPLICATE_FACT", "id": f"jot:{self.project}-dup"})
                continue

            hash_input = f"{ts}:{i}:{text}"
            short_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:8]
            node_id = f"jot:{self.project}-{short_hash}"

            node = {
                "id": node_id,
                "type": JOT_TYPE,
                "scope": self.project,
                "ts": ts,
                "text": text,
                "tags": [JOT_TAG],
            }

            new_lines.append(json.dumps(node, ensure_ascii=False))
            new_ids.append(node_id)
            existing_texts.add(text_stripped)  # Prevent intra-batch dupes
            results.append(node)

        if new_lines:
            with open(out_path, "a", encoding="utf-8") as f:
                f.write("\n".join(new_lines) + "\n")
            self._update_project_index(new_ids)

        if rebuild_index:
            self._rebuild_project_keyword_index()

        return results

    def lookup(self, query: str, *, limit: int = 10) -> List[str]:
        """Fast keyword search scoped to this project's nodes.

        Returns list of matching text strings (not full node dicts).
        Uses per-project keyword_index.json if available, else O(n) scan.
        """
        if not self.project:
            raise ValueError("lookup() requires a project scope")

        q = query.lower()
        q = re.sub(r"[^a-z0-9_\-\s]", " ", q)
        toks = [t for t in q.split() if len(t) >= 3]
        if not toks:
            return []

        # Fast path: per-project keyword index
        kw_index_path = os.path.join(self.project_dir, "keyword_index.json")
        if os.path.exists(kw_index_path):
            try:
                with open(kw_index_path, "r", encoding="utf-8") as rf:
                    kw_index = json.load(rf)
                node_meta = kw_index.get("_nodes", {})

                node_scores: Dict[str, int] = {}
                for tok in toks:
                    for nid in kw_index.get(tok, []):
                        node_scores[nid] = node_scores.get(nid, 0) + 1

                if node_scores:
                    ranked = sorted(
                        node_scores.items(),
                        key=lambda x: (x[1], node_meta.get(x[0], {}).get("ts", "")),
                        reverse=True,
                    )
                    return [
                        node_meta[nid]["text_preview"]
                        for nid, _ in ranked[:limit]
                        if nid in node_meta and node_meta[nid].get("text_preview")
                    ]
            except Exception:
                pass

        # Fallback: O(n) scan
        nodes_path = os.path.join(self.project_dir, "nodes.jsonl")
        if not os.path.exists(nodes_path):
            return []

        scored: List[tuple] = []
        with open(nodes_path, "r", encoding="utf-8") as rf:
            for ln in rf:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    node = json.loads(ln)
                except Exception:
                    continue
                text = str(node.get("text") or "")
                searchable = " ".join([
                    str(node.get("id") or ""),
                    text,
                    " ".join(node.get("tags") or []),
                ]).lower()
                hits = sum(1 for t in toks if t in searchable)
                if hits > 0:
                    scored.append((hits, node.get("ts", ""), text))

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [text for _, _, text in scored[:limit] if text]

    def working_set(self, n: int = 20) -> List[dict]:
        """Return the last N jots from this project, newest first.

        Returns lightweight dicts with id, ts, and text only.
        """
        if not self.project:
            raise ValueError("working_set() requires a project scope")

        nodes_path = os.path.join(self.project_dir, "nodes.jsonl")
        if not os.path.exists(nodes_path):
            return []

        jots: List[dict] = []
        with open(nodes_path, "r", encoding="utf-8") as rf:
            for ln in rf:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    node = json.loads(ln)
                except Exception:
                    continue
                if JOT_TAG in (node.get("tags") or []):
                    jots.append({
                        "id": node.get("id", ""),
                        "ts": node.get("ts", ""),
                        "text": node.get("text", ""),
                    })

        return list(reversed(jots[-n:]))

    def _update_project_index(self, node_ids: List[str]) -> None:
        """Add node IDs to the project index.json."""
        if self.is_global or not node_ids:
            return
        index_path = os.path.join(self.project_dir, "index.json")
        try:
            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as rf:
                    data = json.load(rf)
            else:
                data = {"project": self.project, "nodes": []}
            existing = set(data.get("nodes", []))
            for nid in node_ids:
                if nid not in existing:
                    data.setdefault("nodes", []).append(nid)
            with open(index_path, "w", encoding="utf-8") as wf:
                json.dump(data, wf, indent=2)
        except Exception:
            pass

    @staticmethod
    def _build_index_inline(nodes_path) -> dict:
        """Inline keyword index builder (no external imports needed)."""
        from collections import defaultdict
        inverted = defaultdict(list)
        node_meta = {}
        with open(str(nodes_path), "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    node = json.loads(line)
                except Exception:
                    continue
                if not isinstance(node, dict):
                    continue
                node_id = str(node.get("id") or "").strip()
                if not node_id:
                    continue
                parts = [
                    str(node.get("id") or ""),
                    str(node.get("type") or ""),
                    str(node.get("scope") or ""),
                    str(node.get("text") or ""),
                    " ".join(node.get("tags") or []),
                ]
                text_lower = " ".join(parts).lower()
                text_lower = re.sub(r"[^a-z0-9_\-\s]", " ", text_lower)
                tokens = {t for t in text_lower.split() if len(t) >= 3}
                for tok in tokens:
                    inverted[tok].append(node_id)
                text = str(node.get("text") or "").strip()
                node_meta[node_id] = {
                    "type": node.get("type"),
                    "scope": node.get("scope"),
                    "ts": node.get("ts"),
                    "text_preview": text[:180] if text else "",
                    "tags": node.get("tags") or [],
                }
        result = {}
        for tok in sorted(inverted):
            result[tok] = sorted(set(inverted[tok]))
        result["_nodes"] = node_meta
        return result

    def _rebuild_project_keyword_index(self) -> None:
        """Rebuild the per-project keyword index."""
        if self.is_global:
            return
        nodes_path = os.path.join(self.project_dir, "nodes.jsonl")
        if not os.path.exists(nodes_path):
            return
        from pathlib import Path
        try:
            from memory_system.tools.build_keyword_index import build_index
        except ImportError:
            build_index = self._build_index_inline
        index = build_index(Path(nodes_path))
        out_path = os.path.join(self.project_dir, "keyword_index.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)


def _add_store_path_arg(parser: argparse.ArgumentParser) -> None:
    """Add --store-path to a subparser."""
    parser.add_argument("--store-path", default=None, help="Direct path to project store directory")


def _make_db(args: argparse.Namespace, **kwargs) -> MemoryDB:
    """Build a MemoryDB from parsed CLI args."""
    return MemoryDB(
        project=getattr(args, "project", None),
        store_path=getattr(args, "store_path", None),
        **kwargs,
    )


def cli() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add")
    add.add_argument("--project", default=None)
    _add_store_path_arg(add)
    add.add_argument("--id", required=True)
    add.add_argument("--type", required=True)
    add.add_argument("--text", default="")
    add.add_argument("--tags", nargs="*", default=[])
    add.add_argument("--links", nargs="*", default=[])
    add.add_argument("--meta", default=None)
    add.add_argument("--ts", default=None)
    add.add_argument("--no-tag-validate", action="store_true")

    recall = sub.add_parser("recall")
    recall.add_argument("--project", default=None)
    _add_store_path_arg(recall)
    recall.add_argument("query")

    query = sub.add_parser("query")
    query.add_argument("--project", default=None)
    _add_store_path_arg(query)
    query.add_argument("--scope", default=None)
    query.add_argument("--type", default=None)

    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("--project", required=True)
    _add_store_path_arg(bootstrap)

    tags = sub.add_parser("tags")
    tags_sub = tags.add_subparsers(dest="tags_cmd", required=True)
    tags_add = tags_sub.add_parser("add")
    tags_add.add_argument("--project", required=True)
    _add_store_path_arg(tags_add)
    tags_add.add_argument("--tag", action="append", default=[])

    tags_list = tags_sub.add_parser("list")
    tags_list.add_argument("--project", required=True)
    _add_store_path_arg(tags_list)

    jot_p = sub.add_parser("jot")
    jot_p.add_argument("--project", required=True)
    _add_store_path_arg(jot_p)
    jot_p.add_argument("text")
    jot_p.add_argument("--tags", nargs="*", default=[])
    jot_p.add_argument("--rebuild-index", action="store_true", default=False)

    jot_batch_p = sub.add_parser("jot-batch")
    jot_batch_p.add_argument("--project", required=True)
    _add_store_path_arg(jot_batch_p)
    jot_batch_p.add_argument("texts", nargs="+")
    jot_batch_p.add_argument("--rebuild-index", action="store_true", default=False)

    lookup_p = sub.add_parser("lookup")
    lookup_p.add_argument("--project", required=True)
    _add_store_path_arg(lookup_p)
    lookup_p.add_argument("query")
    lookup_p.add_argument("--limit", type=int, default=10)

    ws_p = sub.add_parser("ws")
    ws_p.add_argument("--project", required=True)
    _add_store_path_arg(ws_p)
    ws_p.add_argument("-n", type=int, default=20)

    args = p.parse_args()

    if args.cmd == "bootstrap":
        db = _make_db(args)
        db._ensure_project_layout()
        print(f"Bootstrapped: {db.project_dir}")
        return 0

    if args.cmd == "tags":
        db = _make_db(args)
        db._ensure_project_layout()
        tags_path = os.path.join(db.project_dir, "tags.json")
        if args.tags_cmd == "list":
            with open(tags_path, "r", encoding="utf-8") as rf:
                print(rf.read())
            return 0
        if args.tags_cmd == "add":
            if not args.tag:
                raise SystemExit("--tag is required")
            with open(tags_path, "r", encoding="utf-8") as rf:
                data = json.load(rf)
            existing = set(data.get("project_tags", []))
            for t in args.tag:
                if t and t not in existing:
                    existing.add(t)
            data["project_tags"] = sorted(existing)
            with open(tags_path, "w", encoding="utf-8") as wf:
                json.dump(data, wf, indent=2)
            print(json.dumps(data, ensure_ascii=False))
            return 0

    db = _make_db(args, enforce_tags=not getattr(args, "no_tag_validate", False))

    if args.cmd == "add":
        meta = json.loads(args.meta) if args.meta else None
        node = db.add_node(
            node_id=args.id,
            node_type=args.type,
            text=args.text,
            tags=args.tags,
            links=args.links,
            meta=meta,
            ts=args.ts,
        )
        print(json.dumps(node, ensure_ascii=False))
        return 0

    if args.cmd == "recall":
        print(db.recall(args.query))
        return 0

    if args.cmd == "query":
        print(db.query(scope=args.scope, node_type=args.type))
        return 0

    if args.cmd == "jot":
        result = db.jot(args.text, tags=args.tags or None, rebuild_index=args.rebuild_index)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if args.cmd == "jot-batch":
        results = db.jot_batch(args.texts, rebuild_index=args.rebuild_index)
        print(json.dumps(results, ensure_ascii=False))
        return 0

    if args.cmd == "lookup":
        results = db.lookup(args.query, limit=args.limit)
        for text in results:
            print(text)
        return 0

    if args.cmd == "ws":
        jots = db.working_set(n=args.n)
        for j in jots:
            print(f"{j['ts']}\t{j['id']}\t{j['text']}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(cli())
