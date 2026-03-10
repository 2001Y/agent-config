#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_PROMPT_FILE="${ROOT_DIR}/references/default-prompt.md"
API_URL="${OPENAI_API_URL:-https://api.openai.com/v1/responses}"
MODEL="${OPENAI_MODEL:-gpt-5}"
SERVICE_TIER="priority"
API_CONNECT_TIMEOUT="${OPENAI_API_CONNECT_TIMEOUT:-30}"
API_MAX_TIME="${OPENAI_API_MAX_TIME:-900}"
ARTIFACT_DIR=""
TASK_TEXT=""
TASK_FILE=""
PROMPT_FILE="${DEFAULT_PROMPT_FILE}"
PRINT_PAYLOAD=0

timestamp_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  local level="$1"
  shift
  printf '%s %s %s\n' "$(timestamp_utc)" "$level" "$*" >&2
}

die() {
  log ERROR "$*"
  exit 1
}

read_text_file() {
  local file_path="$1"
  [[ -f "$file_path" ]] || die "file not found: $file_path"
  cat "$file_path"
}

append_openai_log() {
  local kind="$1"
  local source_path="$2"
  local extra1="${3:-}"
  local extra2="${4:-}"
  local extra3="${5:-}"

  python3 - "$kind" "$source_path" "$OPENAI_LOG_PATH" "$API_URL" "$ARTIFACT_DIR" "$TASK_FILE" "$TASK_TEXT" "$MODEL" "$SERVICE_TIER" "$API_CONNECT_TIMEOUT" "$API_MAX_TIME" "$extra1" "$extra2" "$extra3" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    kind,
    source_path,
    openai_log_path,
    api_url,
    artifact_dir,
    task_file,
    task_text,
    model,
    service_tier,
    api_connect_timeout,
    api_max_time,
    extra1,
    extra2,
    extra3,
) = sys.argv[1:]

recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
source = Path(source_path)

if kind == "request":
    payload = json.loads(source.read_text())
    record = {
        "kind": "request",
        "recorded_at": recorded_at,
        "artifact_dir": artifact_dir,
        "task_file": task_file,
        "task_text": task_text,
        "api_url": api_url,
        "model": model,
        "service_tier": service_tier,
        "api_connect_timeout": int(api_connect_timeout),
        "api_max_time": int(api_max_time),
        "curl_command": extra1,
        "payload": payload,
    }
else:
    response = json.loads(source.read_text())
    record = {
        "kind": "response",
        "recorded_at": recorded_at,
        "artifact_dir": artifact_dir,
        "http_status": int(extra1),
        "duration_seconds": int(extra2),
        "output_text": extra3,
        "response": response,
    }

with Path(openai_log_path).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
PY
}

build_payload_json() {
  local input_file="$1"
  python3 - "$MODEL" "$SERVICE_TIER" "$input_file" <<'PY'
import json
import sys
from pathlib import Path

model = sys.argv[1]
service_tier = sys.argv[2]
input_text = Path(sys.argv[3]).read_text()

payload = {
    "model": model,
    "store": True,
    "service_tier": service_tier,
    "tools": [{"type": "web_search"}],
    "include": ["web_search_call.action.sources"],
    "tool_choice": "auto",
    "input": input_text,
}

print(json.dumps(payload, ensure_ascii=False))
PY
}

extract_output_text() {
  python3 - "$RAW_RESPONSE_PATH" <<'PY'
import json
import sys
from pathlib import Path

body = json.loads(Path(sys.argv[1]).read_text())

output_text = body.get("output_text") or ""
if not output_text:
    parts = []
    for item in body.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])
    output_text = "\n\n".join(parts)

status = body.get("status") or ""
error = body.get("error") or {}
incomplete = body.get("incomplete_details") or {}

print(f"output_text\t{output_text}")
print(f"status\t{status}")
print(f"error_code\t{error.get('code') or ''}")
print(f"error_message\t{error.get('message') or ''}")
print(f"incomplete_reason\t{incomplete.get('reason') or ''}")
PY
}

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/generate-report.sh --artifacts-dir DIR [--task TEXT | --task-file FILE] [--print-payload]
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifacts-dir)
      ARTIFACT_DIR="$2"
      shift 2
      ;;
    --task)
      TASK_TEXT="$2"
      shift 2
      ;;
    --task-file)
      TASK_FILE="$2"
      shift 2
      ;;
    --prompt-file)
      PROMPT_FILE="$2"
      shift 2
      ;;
    --print-payload)
      PRINT_PAYLOAD=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ -n "$ARTIFACT_DIR" ]] || die "--artifacts-dir is required"
[[ -d "$ARTIFACT_DIR" ]] || die "artifacts dir not found: $ARTIFACT_DIR"
[[ -z "$TASK_TEXT" || -z "$TASK_FILE" ]] || die "use only one of --task or --task-file"

if [[ -n "$TASK_FILE" ]]; then
  TASK_TEXT="$(read_text_file "$TASK_FILE")"
fi

if [[ -z "$TASK_TEXT" ]]; then
  TASK_TEXT="X 上の技術トレンドを整理し、観測と解釈を分けて Markdown レポートを作成してください。"
fi

OPENAI_LOG_PATH="${ARTIFACT_DIR}/openai.jsonl"
QUERY_LOG_PATH="${ARTIFACT_DIR}/queries.jsonl"
SEARCH_LOG_PATH="${ARTIFACT_DIR}/x-search.jsonl"
SEARCH_JSON_PATH="${ARTIFACT_DIR}/x-search.json"
NOTES_PATH="${ARTIFACT_DIR}/notes.md"
REPORT_PATH="${ARTIFACT_DIR}/report.md"
RAW_RESPONSE_PATH="$(mktemp)"
PAYLOAD_PATH="$(mktemp)"
INPUT_PATH="$(mktemp)"

cleanup() {
  rm -f "$RAW_RESPONSE_PATH" "$PAYLOAD_PATH" "$INPUT_PATH"
}
trap cleanup EXIT

PROMPT_TEXT="$(read_text_file "$PROMPT_FILE")"
QUERIES_TEXT="$(read_text_file "$QUERY_LOG_PATH")"
if [[ -f "$SEARCH_JSON_PATH" ]]; then
  SEARCH_TEXT="$(read_text_file "$SEARCH_JSON_PATH")"
else
  SEARCH_TEXT="$(read_text_file "$SEARCH_LOG_PATH")"
fi
NOTES_TEXT=""
if [[ -f "$NOTES_PATH" ]]; then
  NOTES_TEXT="$(read_text_file "$NOTES_PATH")"
fi

cat > "$INPUT_PATH" <<EOF
${PROMPT_TEXT}

## Research task
${TASK_TEXT}

## Query log
${QUERIES_TEXT}

## X search evidence
${SEARCH_TEXT}

## Notes
${NOTES_TEXT}
EOF

PAYLOAD="$(build_payload_json "$INPUT_PATH")"
printf '%s\n' "$PAYLOAD" > "$PAYLOAD_PATH"
CURL_COMMAND="python3 -c \"import json,sys; from pathlib import Path; lines=Path('${OPENAI_LOG_PATH}').read_text().splitlines() if Path('${OPENAI_LOG_PATH}').exists() else []; req=next((json.loads(line) for line in lines if json.loads(line).get('kind')=='request'), None); sys.stdout.write(json.dumps(req['payload'], ensure_ascii=False) if req else '')\" | curl -sS --connect-timeout ${API_CONNECT_TIMEOUT} --max-time ${API_MAX_TIME} '${API_URL}' -H 'Content-Type: application/json' -H 'Authorization: Bearer \$OPENAI_API_KEY' --data-binary @-"
append_openai_log "request" "$PAYLOAD_PATH" "$CURL_COMMAND"

if [[ "$PRINT_PAYLOAD" -eq 1 ]]; then
  log INFO "trend-researcher.payload_logged path=${OPENAI_LOG_PATH}"
  printf '%s\n' "$PAYLOAD"
  exit 0
fi

[[ -n "${OPENAI_API_KEY:-}" ]] || die "OPENAI_API_KEY is not set"

STARTED_EPOCH="$(date +%s)"
HTTP_STATUS="$(curl -sS \
  -o "$RAW_RESPONSE_PATH" \
  -w '%{http_code}' \
  --connect-timeout "$API_CONNECT_TIMEOUT" \
  --max-time "$API_MAX_TIME" \
  "$API_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${OPENAI_API_KEY}" \
  --data-binary "$PAYLOAD")"
DURATION_SECONDS="$(( $(date +%s) - STARTED_EPOCH ))"

OUTPUT_TEXT=""
STATUS=""
ERROR_CODE=""
ERROR_MESSAGE=""
INCOMPLETE_REASON=""
while IFS=$'\t' read -r key value; do
  case "$key" in
    output_text) OUTPUT_TEXT="$value" ;;
    status) STATUS="$value" ;;
    error_code) ERROR_CODE="$value" ;;
    error_message) ERROR_MESSAGE="$value" ;;
    incomplete_reason) INCOMPLETE_REASON="$value" ;;
  esac
done < <(extract_output_text)

append_openai_log "response" "$RAW_RESPONSE_PATH" "$HTTP_STATUS" "$DURATION_SECONDS" "$OUTPUT_TEXT"

if [[ ! "$HTTP_STATUS" =~ ^2 ]]; then
  cat "$RAW_RESPONSE_PATH" >&2 || true
  die "OpenAI API request failed with HTTP status ${HTTP_STATUS}"
fi

case "$STATUS" in
  failed|incomplete)
    cat "$RAW_RESPONSE_PATH" >&2 || true
    die "OpenAI response status=${STATUS} incomplete_reason=${INCOMPLETE_REASON:-none} error_code=${ERROR_CODE:-none} error_message=${ERROR_MESSAGE:-none}"
    ;;
esac

printf '%s\n' "$OUTPUT_TEXT" > "$REPORT_PATH"
log INFO "trend-researcher.report path=${REPORT_PATH}"
printf '%s\n' "$OUTPUT_TEXT"
