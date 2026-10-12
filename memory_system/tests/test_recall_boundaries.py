import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from memory_system.tools import recall


class RecallBoundaryTests(unittest.TestCase):
    def invoke(self, extra, sources):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            argv = ["recall", "--query", "fixture", "--db", str(Path(tmp) / "missing.sqlite"), *extra]
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(patch.object(recall.sqlite3, "connect", side_effect=AssertionError("No database expected")))
            for name in ("query_openclaw", "faiss_fallback", "heuristic_fallback"):
                stack.enter_context(patch.object(recall, name, return_value=sources.get(name, [])))
            stack.enter_context(patch("memory_system.tools.hierarchical_recall.hierarchical_search", return_value=sources.get("hierarchical", [])))
            with contextlib.redirect_stdout(output):
                recall.main()
        return json.loads(output.getvalue())

    def test_every_route_rejects_foreign_and_unknown_scope(self):
        hits = [{"node_id": "foreign", "project_id": "beta"}, {"node_id": "unknown"},
                {"node_id": "local", "project_id": "alpha", "source_path": "fixture.jsonl"}]
        for route in ("query_openclaw", "faiss_fallback", "heuristic_fallback", "hierarchical"):
            for strict in ([], ["--strict-provenance"]):
                with self.subTest(route=route, strict=strict):
                    extra = ["--project-id", "alpha", *strict]
                    if route == "hierarchical":
                        extra.append("--hierarchical")
                    self.assertEqual([r["node_id"] for r in self.invoke(extra, {route: hits})], ["local"])

    def test_empty_filtered_backend_falls_through(self):
        sources = {"query_openclaw": [{"project_id": "beta"}],
                   "heuristic_fallback": [{"node_id": "local", "project_id": "alpha"}]}
        self.assertEqual(self.invoke(["--project-id", "alpha"], sources)[0]["node_id"], "local")

    def test_global_is_explicit_and_strict_provenance_still_applies(self):
        hits = [{"node_id": "unattributed", "project_id": "beta", "provenance_status": "ok"},
                {"node_id": "sourced", "source_path": "fixture.jsonl"}]
        self.assertEqual(len(self.invoke(["--global"], {"query_openclaw": hits})), 2)
        self.assertEqual(self.invoke(["--global", "--strict-provenance"], {"query_openclaw": hits}), [hits[1]])

    def test_explicit_mixed_ledger_filters_before_topk(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "nodes.jsonl"
            ledger.write_text("\n".join(json.dumps(n) for n in [
                {"id": "foreign", "scope": "beta", "type": "rule", "text": "fixture"},
                {"id": "local", "scope": "alpha", "text": "fixture"}]), encoding="utf-8")
            output = io.StringIO()
            with patch.object(sys, "argv", ["recall", "--query", "fixture", "--nodes", str(ledger), "--project-id", "alpha", "--topk", "1"]), contextlib.redirect_stdout(output):
                recall.main()
            self.assertEqual([r["node_id"] for r in json.loads(output.getvalue())], ["local"])
            with patch.object(sys, "argv", ["recall", "--query", "fixture", "--nodes", str(ledger)]):
                with self.assertRaises(SystemExit):
                    recall.main()

    def test_rejected_hybrid_session_triggers_ledger_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "mock-index.marker"
            marker.touch()  # Existence fixture only; no SQLite file is opened.
            connection = MagicMock()
            cursor = connection.cursor.return_value
            cursor.execute.return_value = cursor
            cursor.fetchall.side_effect = [[("stale", "chunk", "alpha", "note", "fixture", 0)], []]
            cursor.fetchone.return_value = ("alpha", "note", "", "fixture.jsonl", "old-session", None, "fixture")
            embedder = MagicMock()
            embedder.embed_texts.return_value.vectors = [[1.0]]
            hit = {"node_id": "current", "project_id": "alpha", "session_id": "current-session", "source_path": "fixture.jsonl"}
            output = io.StringIO()
            with patch.object(sys, "argv", ["recall", "--query", "fixture", "--project-id", "alpha", "--session-id", "current-session", "--db", str(marker)]), \
                 patch.object(recall, "query_openclaw", return_value=[]), \
                 patch.object(recall, "faiss_fallback", return_value=[]), \
                 patch.object(recall.sqlite3, "connect", return_value=connection), \
                 patch("memory_system.embeddings.factory.get_embedder", return_value=embedder), \
                 patch.object(recall, "heuristic_fallback", return_value=[hit]) as fallback, \
                 contextlib.redirect_stdout(output):
                recall.main()
            fallback.assert_called_once()
            self.assertEqual(json.loads(output.getvalue()), [hit])
