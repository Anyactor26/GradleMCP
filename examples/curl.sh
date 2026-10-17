#!/bin/sh
# Requires curl and jq. Provide a reviewed ZIP with the build at its root.
set -eu
: "${GRADLEMCP_TOKEN:?set bearer token}"
BASE="${GRADLEMCP_URL:-http://127.0.0.1:8000}"
ZIP="${1:?usage: sh examples/curl.sh project.zip}"
api() {
    # Feed authorization via stdin, not process argv or a permanent file.
    printf 'header = "Authorization: Bearer %s"\n' "$GRADLEMCP_TOKEN" | curl --config - --fail-with-body -sS "$@"
}
api "$BASE/api/v1/capabilities" | jq .
PROJECT=$(api -H 'Content-Type: application/zip' --data-binary "@$ZIP" "$BASE/api/v1/projects" | jq -r .project_id)
KEY=$(python -c 'import uuid; print(uuid.uuid4())')
REQUEST=$(jq -nc --arg project "$PROJECT" --arg key "$KEY" '{project_id:$project,tasks:["build"],idempotency_key:$key}')
JOB=$(api -H 'Content-Type: application/json' -d "$REQUEST" "$BASE/api/v1/builds" | jq -r .id)
printf 'Save job ID: %s\n' "$JOB"
COUNT=0
while [ "$COUNT" -lt 900 ]; do
    STATUS=$(api "$BASE/api/v1/builds/$JOB")
    STATE=$(printf '%s' "$STATUS" | jq -r .state)
    printf '%s\n' "$STATE"
    case "$STATE" in
        succeeded|failed|cancelled|timed_out|resource_limit_exceeded) break ;;
    esac
    sleep 3
    COUNT=$((COUNT + 1))
done
api "$BASE/api/v1/builds/$JOB/logs?limit=65536" | jq -r .text
api "$BASE/api/v1/builds/$JOB/artifacts" | jq .
# Download any listed opaque artifact ID separately:
# api "$BASE/api/v1/builds/$JOB/artifacts/$ARTIFACT_ID" -o artifact.bin
[ "$STATE" = succeeded ]
