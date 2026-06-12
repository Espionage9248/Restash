#!/usr/bin/env bash
# Build the Stash plugin SOURCE site into _site/ (index.yml + restash.zip).
#
# Mirrors stashapp/CommunityScripts' build: the zip holds the plugin directory's
# CONTENTS with no top-level folder; version is "<manifest version>-<short git
# hash>"; date is the plugin's last-commit time (UTC); sha256 is of the zip.
#
# Runs on macOS (shasum) and Linux/CI (sha256sum). Needs git history, so in CI
# check out with fetch-depth: 0.
set -euo pipefail

PLUGIN_DIR="restash"
PLUGIN_ID="restash"
PLUGIN_NAME="Restash"
OUT="_site"

cd "$(dirname "$0")/.."   # repo root

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

rm -rf "$OUT"
mkdir -p "$OUT"
zipfile="$(pwd)/$OUT/$PLUGIN_ID.zip"

# Zip the plugin contents, excluding runtime state, caches, and OS cruft.
( cd "$PLUGIN_DIR" && zip -r "$zipfile" . \
    -x 'restash_state.json' \
    -x '*.pyc' \
    -x '__pycache__/*' -x '*/__pycache__/*' \
    -x '.DS_Store' -x '*/.DS_Store' >/dev/null )

ymlVersion=$(grep '^version:' "$PLUGIN_DIR/restash.yml" | head -1 | awk '{print $2}' | tr -d '"')
shortHash=$(git log -n 1 --pretty=format:%h -- "$PLUGIN_DIR")
version="$ymlVersion-$shortHash"
date=$(TZ=UTC0 git log -n 1 --date=format-local:'%Y-%m-%d %H:%M:%S' --pretty=format:%cd -- "$PLUGIN_DIR")
description=$(grep '^description:' "$PLUGIN_DIR/restash.yml" | head -1 | sed 's/^description:[[:space:]]*//')
sha=$(sha256 "$zipfile")

cat > "$OUT/index.yml" <<EOF
- id: $PLUGIN_ID
  name: $PLUGIN_NAME
  metadata:
    description: "$description"
  version: $version
  date: $date
  path: $PLUGIN_ID.zip
  sha256: $sha
EOF

echo "Built $OUT/index.yml + $OUT/$PLUGIN_ID.zip (version $version)"
