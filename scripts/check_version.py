#!/usr/bin/env python3
"""Release guard (G5): fail if restash.yml `version:` != the git tag being released.

Usage (CI / pre-tag):  python scripts/check_version.py <tag>
Exits 0 on match, 1 on mismatch.
"""
from __future__ import annotations
import sys
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent.parent / "restash" / "restash.yml"


def manifest_version(path: Path = MANIFEST) -> str:
    for line in path.read_text().splitlines():
        if line.strip().startswith("version:"):
            return line.split(":", 1)[1].strip()
    raise ValueError(f"no version: field in {path}")


def matches(version: str, tag: str) -> bool:
    return version == tag.lstrip("v")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_version.py <tag>", file=sys.stderr)
        return 2
    tag = argv[1]
    version = manifest_version()
    if matches(version, tag):
        print(f"OK: restash.yml version {version} matches tag {tag}")
        return 0
    print(f"MISMATCH: restash.yml version {version} != tag {tag}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
