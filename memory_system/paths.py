from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def default_home_dir() -> Path:
    """Base directory for memory-system runtime files.

    Priority:
    1) MEMORY_SYSTEM_HOME
    2) package-local dir (when running from source checkout)
    3) ~/.openclaw/memorydb (portable install fallback)
    """
    env_home = os.environ.get("MEMORY_SYSTEM_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()

    package_data = PACKAGE_DIR / "data"
    if package_data.exists():
        return PACKAGE_DIR

    return (Path.home() / ".openclaw" / "memorydb").resolve()


def default_data_dir() -> Path:
    env_data = os.environ.get("MEMORY_SYSTEM_DATA_DIR")
    if env_data:
        return Path(env_data).expanduser().resolve()
    return default_home_dir() / "data"


def default_nodes_path() -> Path:
    return default_data_dir() / "nodes.jsonl"


def default_wal_path() -> Path:
    return default_data_dir() / "wal.jsonl"


def default_embeddings_db_path() -> Path:
    return default_data_dir() / "embeddings.sqlite"


def default_embeddings_faiss_path() -> Path:
    return default_data_dir() / "embeddings.faiss"


def default_models_cache_dir() -> Path:
    return default_data_dir() / "models" / "fastembed"


def default_store_root() -> Path:
    return default_data_dir() / "stores"
