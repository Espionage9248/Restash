#!/usr/bin/env python3
"""Run a Restash task locally by feeding the same stdin JSON Stash would send.

Usage:
  python restash/tools/run_local.py --url http://192.168.1.5:9999 --mode dry
  python restash/tools/run_local.py --url http://HOST:PORT --api-key KEY --mode dry

Connects to a LIVE Stash. Only run after the user has granted permission (G1).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

PLUGIN_DIR = Path(__file__).resolve().parent.parent  # the restash/ folder


def build_payload(url: str, api_key: str | None, mode: str, limit: int = 0, scene_ids: list | None = None) -> dict:
    parsed = urlparse(url)
    conn = {"Scheme": parsed.scheme or "http",
            "Host": parsed.hostname or "localhost",
            "Port": parsed.port or 9999}
    if api_key:
        conn["ApiKey"] = api_key
    args = {"mode": mode}
    if limit:
        args["write_limit"] = limit
    if scene_ids:
        args["scene_ids"] = scene_ids
    return {"server_connection": conn, "args": args}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://192.168.1.5:9999")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--mode", default="dry")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap entities written (subset-first gate); 0 = all")
    ap.add_argument("--ids", default=None,
                    help="comma-separated scene IDs: full mode writes ONLY these scenes "
                         "(targeted no-clobber verification)")
    args = ap.parse_args()
    if args.limit < 0:
        ap.error("--limit must be >= 0 (0 = all; a positive N caps writes)")
    if args.ids and args.mode != "full":
        ap.error("--ids is only supported with --mode full (dry/clear ignore it)")

    scene_ids = [s.strip() for s in args.ids.split(",") if s.strip()] if args.ids else None
    payload = build_payload(args.url, args.api_key, args.mode, args.limit, scene_ids)
    proc = subprocess.run(
        [sys.executable, str(PLUGIN_DIR / "restash.py")],
        input=json.dumps(payload), text=True, capture_output=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
