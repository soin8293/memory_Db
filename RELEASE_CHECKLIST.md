# Release Checklist

## Repository

- [ ] `README.md` reflects current CLI and install paths
- [ ] ownership/maintainer is AmirahCo
- [ ] `LICENSE` present (MIT)
- [ ] `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md` present
- [ ] no private runtime data committed

## Packaging

- [ ] `python3 -m pip install -e .` succeeds
- [ ] `python3 -m memory_system.memorydb --help` succeeds
- [ ] `python3 memory_system/tools/recall.py --help` succeeds
- [ ] `bash memory_system/tests/run_all.sh` succeeds
- [ ] `python3 -m build --sdist --wheel` succeeds

## Data safety

- [ ] `memory_system/data/` excluded by `.gitignore`
- [ ] no machine-specific absolute paths in public docs used for onboarding

## Tag/Publish

- [ ] commit release prep
- [ ] create version tag (`v0.1.0`)
- [ ] push branch and tag
- [ ] create GitHub release notes from `CHANGELOG.md`
