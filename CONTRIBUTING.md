# Contributing

Thanks for contributing to AmirahCo `memory_Db`.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -e .
```

Optional semantic dependencies:

```bash
python3 -m pip install -e '.[semantic]'
```

## Repo conventions

- Keep `memory_system/data/`, `memory_system/daily/`, `memory_system/projects/`, and `memory_system/nodes_rendered/` out of commits.
- Preserve append-only behavior for `nodes.jsonl`.
- Prefer backward-compatible CLI changes.
- Do not hardcode machine-specific paths.

## Validation before PR

```bash
python3 -m py_compile memory_system/memorydb.py memory_system/paths.py
python3 -m memory_system.memorydb --help
python3 memory_system/tools/recall.py --help
bash memory_system/tests/run_all.sh
```

## Pull requests

Include:
- what changed
- why it changed
- migration notes (if any)
- test/verification commands run
