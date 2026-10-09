import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from memory_system.tools import recall, session_context

ROOT = Path(__file__).resolve().parents[2]


class ContextRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write_nodes(self, path, nodes):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(n) + "\n" for n in nodes), encoding="utf-8")

    def node(self, key, scope="a", **extra):
        return dict(id=key, type="decision", scope=scope, text=key, tags=[], **extra)

    def test_explicit_store_cannot_return_default_index_hits(self):
        local = self.root / "local" / "nodes.jsonl"
        default = self.root / "default" / "nodes.jsonl"
        self.write_nodes(local, [self.node("local-needle")])
        self.write_nodes(default, [self.node("foreign-needle", scope="b")])
        (default.parent / "keyword_index.json").write_text(json.dumps({"needle": ["foreign-needle"], "_nodes": {"foreign-needle": {"scope": "b", "text_preview": "foreign"}}}))
        with patch.object(recall, "default_nodes_path", return_value=default):
            hits = recall.heuristic_fallback("needle", 10, local)
            self.assertEqual([h["node_id"] for h in hits], ["local-needle"])

    def test_explicit_missing_store_returns_no_foreign_hits(self):
        default = self.root / "nodes.jsonl"
        self.write_nodes(default, [])
        (self.root / "keyword_index.json").write_text(json.dumps({"needle": ["foreign"], "_nodes": {"foreign": {"scope": "b"}}}))
        with patch.object(recall, "default_nodes_path", return_value=default):
            self.assertEqual(recall.heuristic_fallback("needle", 10, self.root / "missing.jsonl"), [])

    def context(self, nodes, scope="a"):
        with patch.object(session_context, "load_nodes", return_value=nodes):
            return [n["id"] for n in session_context.get_context(scope=scope, top=20)]

    def test_explicit_supersession_retains_only_current_decision(self):
        self.assertEqual(self.context([self.node("old"), self.node("new", meta={"supersedes": "old"})]), ["new"])

    def test_supersession_chain_and_list(self):
        self.assertEqual(self.context([self.node("old"), self.node("middle", meta={"supersedes": "old"}), self.node("new", meta={"supersedes": ["middle"]})]), ["new"])

    def test_unrelated_scope_and_generic_link_cannot_hide_a_decision(self):
        ids = self.context([self.node("old"), self.node("foreign", scope="b", meta={"supersedes": "old"}), self.node("reference", links=["old"])])
        self.assertEqual(set(ids), {"old", "reference"})

    def test_global_rule_is_not_superseded_by_project_decision(self):
        ids = self.context([self.node("old", scope="global"), self.node("new", meta={"supersedes": "old"})])
        self.assertEqual(set(ids), {"old", "new"})

    def test_cycles_remain_visible_as_unresolved(self):
        ids = self.context([self.node("one", meta={"supersedes": "two"}), self.node("two", meta={"supersedes": "one"})])
        self.assertEqual(set(ids), {"one", "two"})

    def test_startup_respects_configured_store(self):
        nodes = self.root / "data" / "nodes.jsonl"
        self.write_nodes(nodes, [self.node("configured")])
        with patch.dict(os.environ, {"MEMORY_SYSTEM_DATA_DIR": str(nodes.parent)}):
            self.assertEqual([n["id"] for n in session_context.load_nodes()], ["configured"])

    def test_summary_keeps_late_correction_with_bounded_recent_sample(self):
        source = self.root / "session.jsonl"
        target = self.root / "summary.md"
        self.write_nodes(source, [{"role": "user", "text": "earlier " + str(i)} for i in range(3)] + [{"role": "user", "text": "Correction: thresholds remain exploratory."}])
        subprocess.run([sys.executable, str(ROOT / "memory_system/tools/summarize_session_jsonl.py"), "--in", str(source), "--out", str(target), "--limit-messages", "3"], check=True, capture_output=True)
        result = target.read_text(encoding="utf-8")
        self.assertIn("Correction: thresholds remain exploratory.", result)
        self.assertIn("messages_omitted: 1", result)
        self.assertEqual(result.count("- **user**"), 3)
