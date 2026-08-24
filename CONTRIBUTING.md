# Contributing to docsqueeze

Thanks for helping make document reading cheaper and safer for agents.

## Ground rules

1. **Zero runtime dependencies.** The engine (`docsqueeze/core.py`) may only
   import from the Python standard library. Optional accelerators (pypdf,
   PyMuPDF) are imported defensively and must be strictly optional.
2. **No network. No subprocesses.** Any PR adding either will be rejected.
3. **Every parser assumes hostile input.** If you touch a parser, add at
   least one adversarial test (bomb, traversal, ReDoS probe, or fuzz-ish
   timing bound) to `tests/test_core.py`.
4. **Both copies must stay identical**: `docsqueeze/core.py` and the skill
   copy under `.agents/skills/docsqueeze/scripts/docsqueeze.py`. Run
   `python tools/sync_skill.py --check`; CI enforces it.

## Workflow

```bash
git clone <your-fork>
cd docsqueeze-repo
python -m unittest discover -s tests -v     # must be green
python tools/benchmark.py                   # no regressions in output shape
```

## Security issues

Do NOT open public issues for exploitable bugs. See SECURITY.md for
responsible disclosure expectations. Fixes should include a regression test
derived from a minimized reproducer generator script (never attach live
malware samples).

## Style

- Standard library only; Python >= 3.10 compatible.
- Type hints on public functions.
- Error messages tell the user what to do next, not just what broke.
