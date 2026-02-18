import json
import os
import tempfile
import unittest
from pathlib import Path

from memory_system import paths


class PathsAndConfigTests(unittest.TestCase):
    def test_memory_system_data_dir_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old = os.environ.get("MEMORY_SYSTEM_DATA_DIR")
            os.environ["MEMORY_SYSTEM_DATA_DIR"] = td
            try:
                self.assertEqual(paths.default_data_dir(), Path(td).resolve())
                self.assertEqual(paths.default_nodes_path(), Path(td).resolve() / "nodes.jsonl")
                self.assertEqual(paths.default_wal_path(), Path(td).resolve() / "wal.jsonl")
            finally:
                if old is None:
                    os.environ.pop("MEMORY_SYSTEM_DATA_DIR", None)
                else:
                    os.environ["MEMORY_SYSTEM_DATA_DIR"] = old

    def test_memory_system_home_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_home = os.environ.get("MEMORY_SYSTEM_HOME")
            old_data = os.environ.get("MEMORY_SYSTEM_DATA_DIR")
            os.environ["MEMORY_SYSTEM_HOME"] = td
            os.environ.pop("MEMORY_SYSTEM_DATA_DIR", None)
            try:
                self.assertEqual(paths.default_home_dir(), Path(td).resolve())
                self.assertEqual(paths.default_data_dir(), Path(td).resolve() / "data")
            finally:
                if old_home is None:
                    os.environ.pop("MEMORY_SYSTEM_HOME", None)
                else:
                    os.environ["MEMORY_SYSTEM_HOME"] = old_home
                if old_data is None:
                    os.environ.pop("MEMORY_SYSTEM_DATA_DIR", None)
                else:
                    os.environ["MEMORY_SYSTEM_DATA_DIR"] = old_data

    def test_config_has_multi_agent_session_roots(self) -> None:
        cfg = Path(__file__).resolve().parents[1] / "config.json"
        obj = json.loads(cfg.read_text(encoding="utf-8"))
        roots = obj.get("sessionRoots", [])
        self.assertIn("~/.openclaw/agents/main/sessions", roots)
        self.assertIn("~/.codex/sessions", roots)
        self.assertIn("~/.claude/sessions", roots)
        self.assertIn("~/.claude/projects", roots)


if __name__ == "__main__":
    unittest.main()
