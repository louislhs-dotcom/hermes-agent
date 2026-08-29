#!/usr/bin/env bash
# ruflo-memory.sh — Store/query shared memory across all Hermes profiles.
# All profiles share namespace hermes-shared-memory (TencentDB gateway :8420).
#
# Usage:
#   ./ruflo-memory.sh store "<content>" [tag]
#   ./ruflo-memory.sh search "<query>" [limit]      # L1 semantic (may lag new writes)
#   ./ruflo-memory.sh recent "<query>" [limit]      # L0 instant (raw turns)
#   ./ruflo-memory.sh health                         # gateway + auth check

set -euo pipefail

GATEWAY="${TDAI_MEMORY_ENDPOINT:-http://127.0.0.1:8420}"
SERVICE_ID="${TDAI_MEMORY_SERVICE_ID:-hermes-shared-memory}"
KEY_FILE="$HOME/.memory-tencentdb/.gateway-key"

CMD="${1:-}"
shift || true

if [[ -z "$CMD" ]]; then
  echo "Usage: $0 store|search|recent|health ..." >&2
  exit 1
fi

KEY=""
[[ -r "$KEY_FILE" ]] && KEY=$(tr -d '\n' < "$KEY_FILE")

if [[ -z "$KEY" ]]; then
  echo "ERROR: no gateway key at $KEY_FILE" >&2
  exit 1
fi

AUTH=(-H "Authorization: Bearer $KEY" -H "x-tdai-service-id: $SERVICE_ID" -H "Content-Type: application/json")

# POST to the gateway, failing loudly on transport or HTTP errors. Plain
# `curl -s` exits 0 on 401/500, so the JSON parsers below would report an
# expired key or a server error as "(no results)".
api_post() {
  local path="$1" payload="$2" raw status out
  if ! raw=$(curl -sS --max-time 15 -w $'\n%{http_code}' \
              -X POST "$GATEWAY$path" "${AUTH[@]}" -d "$payload"); then
    echo "ERROR: request to $path failed (network error or timeout)" >&2
    return 1
  fi
  status="${raw##*$'\n'}"
  out="${raw%$'\n'*}"
  if [[ "$status" != 2?? ]]; then
    echo "ERROR: $path returned HTTP $status: ${out:0:200}" >&2
    return 1
  fi
  printf '%s' "$out"
}

case "$CMD" in
  store)
    CONTENT="${1:-}"
    TAG="${2:-shared}"
    SESSION="${3:-skill-cli}"
    [[ -z "$CONTENT" ]] && { echo "Usage: $0 store <content> [tag] [session]" >&2; exit 1; }
    BODY=$(python3 - "$TAG" "$CONTENT" "$SESSION" <<'PY'
import json, sys
tag, content, session = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({
    "session_id": session,
    "messages": [{"role": "user", "content": f"[{tag}] {content}"}]
}))
PY
)
    RESP=$(api_post /v2/conversation/add "$BODY")
    echo "$RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("stored ok" if d.get("code")==0 else "ERROR: "+json.dumps(d)[:200])'
    ;;

  search)  # L1 semantic
    QUERY="${1:-}"
    LIMIT="${2:-5}"
    [[ -z "$QUERY" ]] && { echo "Usage: $0 search <query> [limit]" >&2; exit 1; }
    BODY=$(python3 - "$QUERY" "$LIMIT" <<'PY'
import json, sys
print(json.dumps({"query": sys.argv[1], "limit": int(sys.argv[2])}))
PY
)
    RESP=$(api_post /v2/atomic/search "$BODY")
    echo "$RESP" | python3 -c '
import sys, json
d = json.load(sys.stdin)
items = d.get("data", {}).get("items") or d.get("data", {}).get("results") or []
if not items:
    print("(no L1 results)")
for it in items:
    t = it.get("type", "?")
    c = str(it.get("content", ""))[:200]
    print(f"- [{t}] {c}")
'
    ;;

  recent)  # L0 instant
    QUERY="${1:-}"
    LIMIT="${2:-5}"
    [[ -z "$QUERY" ]] && { echo "Usage: $0 recent <query> [limit]" >&2; exit 1; }
    BODY=$(python3 - "$QUERY" "$LIMIT" <<'PY'
import json, sys
print(json.dumps({"query": sys.argv[1], "limit": int(sys.argv[2])}))
PY
)
    RESP=$(api_post /v2/conversation/search "$BODY")
    echo "$RESP" | python3 -c '
import sys, json
d = json.load(sys.stdin)
msgs = d.get("data", {}).get("messages") or []
if not msgs:
    print("(no L0 results)")
for m in msgs:
    role = m.get("role", "?")
    c = str(m.get("content", ""))[:200]
    print(f"- [{role}] {c}")
'
    ;;

  health)
    curl -sS --max-time 5 --fail "$GATEWAY/health" && echo
    ;;
  *)
    echo "Unknown command: $CMD" >&2
    echo "Usage: $0 store|search|recent|health ..." >&2
    exit 1
    ;;
esac
