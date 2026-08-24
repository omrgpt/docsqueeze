#!/usr/bin/env python3
"""Install docsqueeze integrations from the repo (canonical source).

The repo now ships everything:
    docsqueeze/core.py                     the engine
    integrations/skill/SKILL.md            agent skill instructions
    integrations/opencode-plugin/docsqueeze.ts   opencode auto-activation

Usage:
    python tools/sync_skill.py --to <dir>          # engine+skill -> <dir>/.agents/skills/docsqueeze
    python tools/sync_skill.py --plugin-to <proj>  # plugin -> <proj>/.opencode/plugins/
    python tools/sync_skill.py --check             # verify external copies match repo
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE = REPO_ROOT / "docsqueeze" / "core.py"
SKILL_MD = REPO_ROOT / "integrations" / "skill" / "SKILL.md"
PLUGIN = REPO_ROOT / "integrations" / "opencode-plugin" / "docsqueeze.ts"
SKILL_REL = Path(".agents") / "skills" / "docsqueeze"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sync_skill")
    ap.add_argument("--to", help="install engine+SKILL.md into <dir>%s" % SKILL_REL)
    ap.add_argument("--plugin-to", help="install plugin into <dir>/.opencode/plugins/")
    ap.add_argument("--check", action="store_true", help="verify installed copies match repo")
    args = ap.parse_args(argv)

    for src in (CORE, SKILL_MD, PLUGIN):
        if not src.exists():
            print(f"repo file missing: {src}", file=sys.stderr)
            return 1

    rc = 0
    if args.to:
        dest_dir = Path(args.to) / SKILL_REL / "scripts"
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CORE, dest_dir / "docsqueeze.py")
        shutil.copyfile(SKILL_MD, dest_dir.parent / "SKILL.md")
        print(f"installed skill -> {dest_dir.parent}")
    if args.plugin_to:
        dest = Path(args.plugin_to) / ".opencode" / "plugins" / "docsqueeze.ts"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PLUGIN, dest)
        print(f"installed plugin -> {dest}")

    if args.check:
        candidates = [
            ("engine", CORE,
             [REPO_ROOT.parent / SKILL_REL / "scripts" / "docsqueeze.py"]),
            ("skill", SKILL_MD,
             [REPO_ROOT.parent / SKILL_REL / "SKILL.md"]),
        ]
        want_engine = sha256(CORE)
        for label, src, copies in candidates:
            want = sha256(src)
            for t in copies:
                if not t.exists():
                    print(f"MISSING  {label}: {t}")
                    rc = 1
                    continue
                if sha256(t) == want:
                    print(f"OK       {label}: {t}")
                else:
                    print(f"DRIFTED  {label}: {t} (re-run --to)")
                    rc = 1

    if not args.to and not args.plugin_to and not args.check:
        ap.print_help()
        return 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
