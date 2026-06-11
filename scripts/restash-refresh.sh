#!/usr/bin/env bash
# Trigger Restash "Quick Refresh" via the Stash GraphQL API.
#
# Config via environment:
#   STASH_URL      default http://localhost:9999
#   STASH_API_KEY  optional; sent as the ApiKey header when set
#   PLUGIN_ID      default restash      (the plugin directory name)
#   TASK_NAME      default "Quick Refresh"
set -euo pipefail

STASH_URL="${STASH_URL:-http://localhost:9999}"
PLUGIN_ID="${PLUGIN_ID:-restash}"
TASK_NAME="${TASK_NAME:-Quick Refresh}"

query='mutation($plugin_id: ID!, $task_name: String) { runPluginTask(plugin_id: $plugin_id, task_name: $task_name) }'
payload=$(printf '{"query":"%s","variables":{"plugin_id":"%s","task_name":"%s"}}' \
  "$query" "$PLUGIN_ID" "$TASK_NAME")

headers=(-H "Content-Type: application/json")
if [[ -n "${STASH_API_KEY:-}" ]]; then
  headers+=(-H "ApiKey: ${STASH_API_KEY}")
fi

curl -fsS "${headers[@]}" -X POST --data "$payload" "${STASH_URL%/}/graphql"
echo
