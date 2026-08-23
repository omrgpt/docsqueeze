#!/usr/bin/env python3
"""Sync the canonical engine between the repo and installed skill copies.

The repo's docsqueeze/core.py and every installed skill copy
(.agents/skills/docsqueeze/scripts/docsqueeze.py) must be byte-identical;
the test-suite enforces this. Use this tool to install or verify.

Usage:
    python tools/sync_skill.py --to <skills-dir>     # install/update
    python tools/sync_skill.py --check               # verify all known copies
    python tools/sync_skill.py --from-skill          # promote skill copy -> repo
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE = REPO_ROOT / "docsqueeze" / "core.py"
SKILL_REL = Path(".agents") / "skills" / "docsqueeze" / "scripts" / "docsqueeze.py"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sync_skill")
    ap.add_argument("--to", help="install into <dir>%s" % SKILL_REL)
    ap.add_argument("--check", action="store_true", help="verify copies match repo core")
    ap.add_argument("--from-skill", action="store_true", help="copy workspace skill copy over repo core")
    args = ap.parse_args(argv)

    if args.from_skill:
        src = REPO_ROOT.parent / SKILL_REL
        if not src.exists():
            print(f"skill copy not found: {src}", file=sys.stderr)
            return 1
        shutil.copyfile(src, CORE)
        print(f"promoted {src} -> {CORE}")
        return 0

    if not CORE.exists():
        print(f"repo core missing: {CORE}", file=sys.stderr)
        return 1

    if args.check:
        targets = [REPO_ROOT.parent / SKILL_REL]
        rc = 0
        want = sha256(CORE)
        for t in targets:
            if not t.exists():
                print(f"MISSING  {t}")
                rc = 1
                continue
            if sha256(t) == want:
                print(f"OK       {t}")
            else:
                print(f"DRIFTED  {t} (run: python tools/sync_skill.py --to {t.parents[3]})")
                rc = 1
        return rc

    if args.to:
        dest_dir = Path(args.to) / SKILL_REL
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CORE, dest_dir)
        # keep SKILL.md alongside for a complete skill package
        skill_md_src = REPO_ROOT.parent / ".agents" / "skills" / "docsqueeze" / "SKILL.md"
        if not skill_md_src.exists():
            skill_md_src = REPO_ROOT / "SKILL.md"
        if skill_md_src.exists():
            shutil.copyfile(skill_md_src, dest_dir.parent / "SKILL.md")
        print(f"installed engine -> {dest_dir}")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
