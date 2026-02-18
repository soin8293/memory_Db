import json
import os
import tempfile
import unittest
from pathlib import Path

from memory_system.memorydb import MemoryDB


class MemoryDBObjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store_path = Path(self.tmp.name) / "my_project_memory"
        self.project = "unitproj"
        self.db = MemoryDB(project=self.project, store_path=str(self.store_path))

    def test_bootstrap_and_layout_files(self) -> None:
        self.db._ensure_project_layout()
        self.assertTrue((self.store_path / "daily").exists())
        self.assertTrue((self.store_path / "embeddings").exists())
        self.assertTrue((self.store_path / "tags.json").exists())
        self.assertTrue((self.store_path / "index.json").exists())
        self.assertTrue((self.store_path / "dossier.md").exists())

    def test_jot_lookup_and_working_set(self) -> None:
        self.db._ensure_project_layout()
        first = self.db.jot("token refresh is 15 minutes")
        second = self.db.jot("token refresh is 15 minutes")
        self.assertIn("id", first)
        self.assertEqual(second.get("status"), "SKIP_DUPLICATE_FACT")

        batch = self.db.jot_batch(
            ["api uses jwt auth", "rate limit is 100/min", "api uses jwt auth"]
        )
        self.assertEqual(len(batch), 3)

        hits = self.db.lookup("jwt auth")
        self.assertTrue(any("jwt" in h.lower() for h in hits))

        ws = self.db.working_set(n=5)
        self.assertGreaterEqual(len(ws), 2)
        self.assertTrue(all("text" in row for row in ws))

    def test_add_node_and_recall_smoke(self) -> None:
        self.db._ensure_project_layout()
        node = self.db.add_node(
            node_id="decision:auth-provider",
            node_type="decision",
            text="Use OAuth2 PKCE for browser clients",
            tags=["decision", self.project],
        )
        self.assertEqual(node["type"], "decision")

        nodes_file = self.store_path / "nodes.jsonl"
        self.assertTrue(nodes_file.exists())
        lines = [json.loads(x) for x in nodes_file.read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertTrue(any(x.get("id") == "decision:auth-provider" for x in lines))

        recalled = self.db.recall("OAuth2")
        parsed = json.loads(recalled)
        self.assertIsInstance(parsed, list)


if __name__ == "__main__":
    unittest.main()
