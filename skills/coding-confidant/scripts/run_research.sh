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
INPUT_TOKEN_BUDGET="${OPENAI_INPUT_TOKEN_BUDGET:-120000}"
STYLE="xml"
COMPRESS=0
INCLUDE_PATTERNS=""
IGNORE_PATTERNS=""
REMOTE_BRANCH=""
REPO_TARGET=""
REPOMIX_FILE=""
PROMPT_FILE="${DEFAULT_PROMPT_FILE}"
TASK_TEXT=""
TASK_FILE=""
OUTPUT_JSON=""
OUTPUT_TEXT=""
SAVE_PAYLOAD=""
PRINT_PAYLOAD=0
INCLUDE_LOGS=0
INCLUDE_DIFFS=0
RUN_ID=""
ARTIFACT_DIR=""
OPENAI_LOG_PATH=""
REPOMIX_ARCHIVE_PATH=""
RAW_RESPONSE_PATH=""

timestamp_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  local level="$1"
  shift
  printf '%s %s %s\n' "$(timestamp_utc)" "$level" "$*" >&2
}

estimate_text_tokens() {
  local input_file="$1"
  python3 - "$input_file" <<'PY'
import math
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text()
cjk = 0
ascii_non_ws = 0
other = 0

for ch in text:
    if ch.isspace():
        continue
    code = ord(ch)
    if (
        0x3040 <= code <= 0x30FF
        or 0x3400 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0xAC00 <= code <= 0xD7AF
    ):
        cjk += 1
    elif code < 128:
        ascii_non_ws += 1
    else:
        other += 1

estimated_tokens = math.ceil(cjk * 1.35 + ascii_non_ws / 3.2 + other * 1.1)
print(estimated_tokens)
PY
}

ensure_parent_dir() {
  local target_path="$1"
  mkdir -p "$(dirname "$target_path")"
}

resolve_artifact_base_dir() {
  if [[ -n "$REPO_TARGET" && -e "$REPO_TARGET" ]]; then
    if [[ -d "$REPO_TARGET" ]]; then
      (
        cd "$REPO_TARGET"
        pwd -P
      )
      return
    fi

    (
      cd "$(dirname "$REPO_TARGET")"
      pwd -P
    )
    return
  fi

  pwd -P
}

setup_artifact_dir() {
  local base_dir
  base_dir="$(resolve_artifact_base_dir)"
  RUN_ID="$(date -u +"%Y%m%dT%H%M%SZ")-$$"
  ARTIFACT_DIR="${base_dir}/_docs/_skills/coding-confidant/${RUN_ID}"
  mkdir -p "$ARTIFACT_DIR"

  OPENAI_LOG_PATH="${ARTIFACT_DIR}/openai.jsonl"
}

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/run_research.sh [options]

Input options:
  --repo PATH_OR_GITHUB        Local repository path, GitHub URL, or owner/repo
  --repomix-file FILE          Existing repomix output file

Prompt options:
  --prompt-file FILE           Prompt template file (default: references/default-prompt.md)
  --task TEXT                  Inline task text
  --task-file FILE             File containing task text

Repomix options:
  --compress                   Enable repomix compression
  --include PATTERNS           Comma-separated repomix include patterns
  --ignore PATTERNS            Comma-separated repomix ignore patterns
  --remote-branch NAME         Remote branch, tag, or commit for GitHub targets
  --include-logs               Include recent git logs in repomix output
  --include-diffs              Include uncommitted diffs in repomix output
  --style FORMAT               Repomix output style: xml, markdown, json, plain

Output options:
  --output-json FILE           Copy raw Responses API JSON to an additional file
  --output-text FILE           Copy extracted output_text to an additional file
  --save-payload FILE          Copy request payload JSON to an additional file before the API call
  --print-payload              Print payload JSON and exit without calling the API

API options:
  --model NAME                 Responses API model (default: gpt-5 or OPENAI_MODEL)
  --api-connect-timeout SEC    curl --connect-timeout seconds (default: 30 or OPENAI_API_CONNECT_TIMEOUT)
  --api-max-time SEC           curl --max-time seconds (default: 900 or OPENAI_API_MAX_TIME)
  --input-token-budget TOKENS  estimated input token budget before API call (default: 120000 or OPENAI_INPUT_TOKEN_BUDGET)

Environment:
  OPENAI_API_KEY               Required for the API call
  OPENAI_API_URL               Optional override for the Responses API endpoint
  OPENAI_MODEL                 Optional default model override
  OPENAI_API_CONNECT_TIMEOUT   Optional default connect timeout override
  OPENAI_API_MAX_TIME          Optional default total timeout override
  OPENAI_INPUT_TOKEN_BUDGET    Optional estimated input token budget override

Artifacts:
  Local repo runs always archive OpenAI request/response logs under:
    <repo>/_docs/_skills/coding-confidant/<timestamp-pid>/
  OpenAI curl data is stored in:
    openai.jsonl
  Repomix context is stored separately as:
    repomix-output.* or the copied source repomix file name

Examples:
  bash scripts/run_research.sh \
    --repo /path/to/repo \
    --task "技術アドバイザーとしてこのリポジトリをレビューしてください。" \
    --api-max-time 900 \
    --compress

  bash scripts/run_research.sh \
    --repo https://github.com/example/project \
    --task-file task.md \
    --output-text answer.md \
    --output-json answer.json

  bash scripts/run_research.sh \
    --repomix-file repomix-output.xml \
    --print-payload
USAGE
}

die() {
  log ERROR "$*"
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

is_github_target() {
  local target="$1"
  [[ "$target" =~ ^https?://github\.com/ ]] || [[ "$target" =~ ^git@github\.com: ]] || [[ "$target" =~ ^[^/[:space:]]+/[^/[:space:]]+$ ]]
}

get_repomix_cmd() {
  if command -v npx >/dev/null 2>&1; then
    REPOMIX_CMD=(npx -y repomix@latest)
    return
  fi

  if command -v repomix >/dev/null 2>&1; then
    REPOMIX_CMD=(repomix)
    return
  fi

  die "repomix was not found and npx is unavailable"
}

read_text_file() {
  local file_path="$1"
  [[ -f "$file_path" ]] || die "file not found: $file_path"
  cat "$file_path"
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

append_openai_log_from_python() {
  local kind="$1"
  local source_path="$2"
  local extra1="${3:-}"
  local extra2="${4:-}"
  local extra3="${5:-}"

  python3 - "$kind" "$source_path" "$OPENAI_LOG_PATH" "$RUN_ID" "$API_URL" "$REPO_TARGET" "$REPOMIX_FILE" "$PROMPT_FILE" "$TASK_FILE" "$TASK_TEXT" "$MODEL" "$SERVICE_TIER" "$API_CONNECT_TIMEOUT" "$API_MAX_TIME" "$extra1" "$extra2" "$extra3" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    kind,
    source_path,
    openai_log_path,
    run_id,
    api_url,
    repo_target,
    repomix_file,
    prompt_file,
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
        "run_id": run_id,
        "api_url": api_url,
        "repo_target": repo_target,
        "repomix_file": repomix_file,
        "prompt_file": prompt_file,
        "task_file": task_file,
        "task_text": task_text,
        "model": model,
        "service_tier": service_tier,
        "api_connect_timeout": int(api_connect_timeout),
        "api_max_time": int(api_max_time),
        "curl_command": extra1,
        "payload": payload,
    }
elif kind == "response":
    response = json.loads(source.read_text())
    record = {
        "kind": "response",
        "recorded_at": recorded_at,
        "run_id": run_id,
        "http_status": int(extra1),
        "duration_seconds": int(extra2),
        "output_text": extra3,
        "response": response,
    }
else:
    raise SystemExit(f"unknown log kind: {kind}")

with Path(openai_log_path).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
PY
}

extract_response_fields() {
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

summary = {
    "output_text": output_text,
    "id": body.get("id") or "",
    "status": body.get("status") or "",
    "service_tier": body.get("service_tier") or "",
    "total_tokens": ((body.get("usage") or {}).get("total_tokens") or ""),
    "input_tokens": ((body.get("usage") or {}).get("input_tokens") or ""),
    "output_tokens": ((body.get("usage") or {}).get("output_tokens") or ""),
    "incomplete_reason": ((body.get("incomplete_details") or {}).get("reason") or ""),
    "error_code": ((body.get("error") or {}).get("code") or ""),
    "error_message": ((body.get("error") or {}).get("message") or ""),
}

for key, value in summary.items():
    print(f"{key}\t{value}")
PY
}

require_positive_integer() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || die "${name} must be a positive integer: ${value}"
}

prepare_repomix_file() {
  if [[ -z "$REPO_TARGET" ]]; then
    [[ -f "$REPOMIX_FILE" ]] || die "repomix file not found: $REPOMIX_FILE"
    REPOMIX_ARCHIVE_PATH="${ARTIFACT_DIR}/$(basename "$REPOMIX_FILE")"
    cp "$REPOMIX_FILE" "$REPOMIX_ARCHIVE_PATH"
    REPOMIX_FILE="$REPOMIX_ARCHIVE_PATH"
    log INFO "repomix.archived path=${REPOMIX_ARCHIVE_PATH}"
    return
  fi

  get_repomix_cmd
  REPOMIX_OUTPUT_PATH="${TMP_DIR}/repomix-output.${STYLE}"
  REPOMIX_ARGS=(-o "$REPOMIX_OUTPUT_PATH" --style "$STYLE")

  if [[ "$COMPRESS" -eq 1 ]]; then
    REPOMIX_ARGS+=(--compress)
  fi

  if [[ -n "$INCLUDE_PATTERNS" ]]; then
    REPOMIX_ARGS+=(--include "$INCLUDE_PATTERNS")
  fi

  if [[ -n "$IGNORE_PATTERNS" ]]; then
    REPOMIX_ARGS+=(--ignore "$IGNORE_PATTERNS")
  fi

  if [[ "$INCLUDE_LOGS" -eq 1 ]]; then
    REPOMIX_ARGS+=(--include-logs)
  fi

  if [[ "$INCLUDE_DIFFS" -eq 1 ]]; then
    REPOMIX_ARGS+=(--include-diffs)
  fi

  if [[ -e "$REPO_TARGET" ]]; then
    REPOMIX_ARGS+=("$REPO_TARGET")
  elif is_github_target "$REPO_TARGET"; then
    REPOMIX_ARGS+=(--remote "$REPO_TARGET")
    if [[ -n "$REMOTE_BRANCH" ]]; then
      REPOMIX_ARGS+=(--remote-branch "$REMOTE_BRANCH")
    fi
  else
    die "--repo must be a local path or GitHub target"
  fi

  REPOMIX_STARTED_EPOCH="$(date +%s)"
  log INFO "repomix.start command=${REPOMIX_CMD[*]} ${REPOMIX_ARGS[*]}"
  "${REPOMIX_CMD[@]}" "${REPOMIX_ARGS[@]}"
  log SUCCESS "repomix.done seconds=$(( $(date +%s) - REPOMIX_STARTED_EPOCH )) output=${REPOMIX_OUTPUT_PATH}"
  REPOMIX_FILE="$REPOMIX_OUTPUT_PATH"
  REPOMIX_ARCHIVE_PATH="${ARTIFACT_DIR}/$(basename "$REPOMIX_FILE")"
  cp "$REPOMIX_FILE" "$REPOMIX_ARCHIVE_PATH"
  REPOMIX_FILE="$REPOMIX_ARCHIVE_PATH"
  log INFO "repomix.archived path=${REPOMIX_ARCHIVE_PATH}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      [[ $# -ge 2 ]] || die "--repo requires a value"
      REPO_TARGET="$2"
      shift 2
      ;;
    --repomix-file)
      [[ $# -ge 2 ]] || die "--repomix-file requires a value"
      REPOMIX_FILE="$2"
      shift 2
      ;;
    --prompt-file)
      [[ $# -ge 2 ]] || die "--prompt-file requires a value"
      PROMPT_FILE="$2"
      shift 2
      ;;
    --task)
      [[ $# -ge 2 ]] || die "--task requires a value"
      TASK_TEXT="$2"
      shift 2
      ;;
    --task-file)
      [[ $# -ge 2 ]] || die "--task-file requires a value"
      TASK_FILE="$2"
      shift 2
      ;;
    --compress)
      COMPRESS=1
      shift
      ;;
    --include)
      [[ $# -ge 2 ]] || die "--include requires a value"
      INCLUDE_PATTERNS="$2"
      shift 2
      ;;
    --ignore)
      [[ $# -ge 2 ]] || die "--ignore requires a value"
      IGNORE_PATTERNS="$2"
      shift 2
      ;;
    --remote-branch)
      [[ $# -ge 2 ]] || die "--remote-branch requires a value"
      REMOTE_BRANCH="$2"
      shift 2
      ;;
    --include-logs)
      INCLUDE_LOGS=1
      shift
      ;;
    --include-diffs)
      INCLUDE_DIFFS=1
      shift
      ;;
    --style)
      [[ $# -ge 2 ]] || die "--style requires a value"
      STYLE="$2"
      shift 2
      ;;
    --output-json)
      [[ $# -ge 2 ]] || die "--output-json requires a value"
      OUTPUT_JSON="$2"
      shift 2
      ;;
    --output-text)
      [[ $# -ge 2 ]] || die "--output-text requires a value"
      OUTPUT_TEXT="$2"
      shift 2
      ;;
    --save-payload)
      [[ $# -ge 2 ]] || die "--save-payload requires a value"
      SAVE_PAYLOAD="$2"
      shift 2
      ;;
    --print-payload)
      PRINT_PAYLOAD=1
      shift
      ;;
    --model)
      [[ $# -ge 2 ]] || die "--model requires a value"
      MODEL="$2"
      shift 2
      ;;
    --api-connect-timeout)
      [[ $# -ge 2 ]] || die "--api-connect-timeout requires a value"
      API_CONNECT_TIMEOUT="$2"
      shift 2
      ;;
    --api-max-time)
      [[ $# -ge 2 ]] || die "--api-max-time requires a value"
      API_MAX_TIME="$2"
      shift 2
      ;;
    --input-token-budget)
      [[ $# -ge 2 ]] || die "--input-token-budget requires a value"
      INPUT_TOKEN_BUDGET="$2"
      shift 2
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

need_cmd curl
require_positive_integer "api connect timeout" "$API_CONNECT_TIMEOUT"
require_positive_integer "api max time" "$API_MAX_TIME"
require_positive_integer "input token budget" "$INPUT_TOKEN_BUDGET"

[[ -n "$REPO_TARGET" || -n "$REPOMIX_FILE" ]] || die "provide either --repo or --repomix-file"
[[ -z "$REPO_TARGET" || -z "$REPOMIX_FILE" ]] || die "use only one of --repo or --repomix-file"
[[ -z "$TASK_TEXT" || -z "$TASK_FILE" ]] || die "use only one of --task or --task-file"
[[ -f "$PROMPT_FILE" ]] || die "prompt file not found: $PROMPT_FILE"

if [[ -n "$TASK_FILE" ]]; then
  TASK_TEXT="$(read_text_file "$TASK_FILE")"
fi

if [[ -z "$TASK_TEXT" ]]; then
  TASK_TEXT="リポジトリ文脈をライブ Web 検索と合わせて分析し、有用な自由形式で回答してください。"
fi

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT
RAW_RESPONSE_PATH="${TMP_DIR}/response.json"
setup_artifact_dir
log INFO "openai.responses.artifacts dir=${ARTIFACT_DIR}"
prepare_repomix_file

PROMPT_TEXT="$(read_text_file "$PROMPT_FILE")"
REPOMIX_TEXT="$(read_text_file "$REPOMIX_FILE")"

INPUT_TEXT="${PROMPT_TEXT}

## User task
${TASK_TEXT}

## Repomix context
${REPOMIX_TEXT}
"

INPUT_TEXT_PATH="${TMP_DIR}/input.txt"
printf '%s' "$INPUT_TEXT" > "$INPUT_TEXT_PATH"

ESTIMATED_INPUT_TOKENS="$(estimate_text_tokens "$INPUT_TEXT_PATH")"
log INFO "openai.responses.input_estimate estimated_tokens=${ESTIMATED_INPUT_TOKENS} budget=${INPUT_TOKEN_BUDGET} compress=${COMPRESS}"

if [[ "$ESTIMATED_INPUT_TOKENS" -gt "$INPUT_TOKEN_BUDGET" && -n "$REPO_TARGET" && "$COMPRESS" -eq 0 ]]; then
  log WARNING "openai.responses.input_estimate_over_budget estimated_tokens=${ESTIMATED_INPUT_TOKENS} budget=${INPUT_TOKEN_BUDGET} action=retry_with_compress"
  COMPRESS=1
  prepare_repomix_file
  PROMPT_TEXT="$(read_text_file "$PROMPT_FILE")"
  REPOMIX_TEXT="$(read_text_file "$REPOMIX_FILE")"
  INPUT_TEXT="${PROMPT_TEXT}

## User task
${TASK_TEXT}

## Repomix context
${REPOMIX_TEXT}
"
  printf '%s' "$INPUT_TEXT" > "$INPUT_TEXT_PATH"
  ESTIMATED_INPUT_TOKENS="$(estimate_text_tokens "$INPUT_TEXT_PATH")"
  log INFO "openai.responses.input_estimate estimated_tokens=${ESTIMATED_INPUT_TOKENS} budget=${INPUT_TOKEN_BUDGET} compress=${COMPRESS}"
fi

if [[ "$ESTIMATED_INPUT_TOKENS" -gt "$INPUT_TOKEN_BUDGET" ]]; then
  die "estimated input tokens ${ESTIMATED_INPUT_TOKENS} exceed budget ${INPUT_TOKEN_BUDGET}; narrow --ignore/--include or raise --input-token-budget"
fi

PAYLOAD="$(build_payload_json "$INPUT_TEXT_PATH")"

CURL_COMMAND="python3 -c \"import json,sys; from pathlib import Path; lines=Path('${OPENAI_LOG_PATH}').read_text().splitlines(); req=next(json.loads(line) for line in lines if json.loads(line).get('kind')=='request'); sys.stdout.write(json.dumps(req['payload'], ensure_ascii=False))\" | curl -sS --connect-timeout ${API_CONNECT_TIMEOUT} --max-time ${API_MAX_TIME} '${API_URL}' -H 'Content-Type: application/json' -H 'Authorization: Bearer \$OPENAI_API_KEY' --data-binary @-"
PAYLOAD_PATH="${TMP_DIR}/payload.json"
printf '%s\n' "$PAYLOAD" > "$PAYLOAD_PATH"
append_openai_log_from_python "request" "$PAYLOAD_PATH" "$CURL_COMMAND"

if [[ -n "$SAVE_PAYLOAD" ]]; then
  ensure_parent_dir "$SAVE_PAYLOAD"
  printf '%s\n' "$PAYLOAD" > "$SAVE_PAYLOAD"
fi

if [[ "$PRINT_PAYLOAD" -eq 1 ]]; then
  log INFO "openai.responses.payload_logged path=${OPENAI_LOG_PATH}"
  printf '%s\n' "$PAYLOAD"
  exit 0
fi

[[ -n "${OPENAI_API_KEY:-}" ]] || die "OPENAI_API_KEY is not set"

STARTED_EPOCH="$(date +%s)"
log INFO "openai.responses.request model=${MODEL} requested_service_tier=${SERVICE_TIER} connect_timeout=${API_CONNECT_TIMEOUT}s max_time=${API_MAX_TIME}s log=${OPENAI_LOG_PATH}"
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
log INFO "openai.responses.duration seconds=${DURATION_SECONDS}"

OUTPUT_TEXT_VALUE=""
RESPONSE_ID=""
RESPONSE_STATUS=""
ACTUAL_SERVICE_TIER=""
TOTAL_TOKENS=""
INPUT_TOKENS=""
OUTPUT_TOKENS=""
INCOMPLETE_REASON=""
ERROR_CODE=""
ERROR_MESSAGE=""

while IFS=$'\t' read -r key value; do
  case "$key" in
    output_text) OUTPUT_TEXT_VALUE="$value" ;;
    id) RESPONSE_ID="$value" ;;
    status) RESPONSE_STATUS="$value" ;;
    service_tier) ACTUAL_SERVICE_TIER="$value" ;;
    total_tokens) TOTAL_TOKENS="$value" ;;
    input_tokens) INPUT_TOKENS="$value" ;;
    output_tokens) OUTPUT_TOKENS="$value" ;;
    incomplete_reason) INCOMPLETE_REASON="$value" ;;
    error_code) ERROR_CODE="$value" ;;
    error_message) ERROR_MESSAGE="$value" ;;
  esac
done < <(extract_response_fields)

append_openai_log_from_python "response" "$RAW_RESPONSE_PATH" "$HTTP_STATUS" "$DURATION_SECONDS" "$OUTPUT_TEXT_VALUE"

if [[ ! "$HTTP_STATUS" =~ ^2 ]]; then
  cat "$RAW_RESPONSE_PATH" >&2 || true
  die "OpenAI API request failed with HTTP status ${HTTP_STATUS}"
fi

log SUCCESS "openai.responses.response id=${RESPONSE_ID:-unknown} status=${RESPONSE_STATUS:-unknown} actual_service_tier=${ACTUAL_SERVICE_TIER:-unknown} input_tokens=${INPUT_TOKENS:-unknown} output_tokens=${OUTPUT_TOKENS:-unknown} total_tokens=${TOTAL_TOKENS:-unknown}"

if [[ "$SERVICE_TIER" == "priority" && -n "$ACTUAL_SERVICE_TIER" && "$ACTUAL_SERVICE_TIER" != "$SERVICE_TIER" ]]; then
  log WARNING "openai.responses.priority_downgrade requested=${SERVICE_TIER} actual=${ACTUAL_SERVICE_TIER}"
fi

if [[ -n "$ERROR_CODE" || -n "$ERROR_MESSAGE" ]]; then
  log ERROR "openai.responses.error code=${ERROR_CODE:-unknown} message=${ERROR_MESSAGE:-unknown}"
  cat "$RAW_RESPONSE_PATH" >&2
  exit 1
fi

case "$RESPONSE_STATUS" in
  failed|incomplete)
    log ERROR "openai.responses.status status=${RESPONSE_STATUS} incomplete_reason=${INCOMPLETE_REASON:-none}"
    cat "$RAW_RESPONSE_PATH" >&2
    exit 1
    ;;
esac

if [[ -n "$OUTPUT_JSON" ]]; then
  ensure_parent_dir "$OUTPUT_JSON"
  cp "$RAW_RESPONSE_PATH" "$OUTPUT_JSON"
fi

if [[ -n "$OUTPUT_TEXT" ]]; then
  ensure_parent_dir "$OUTPUT_TEXT"
  printf '%s\n' "$OUTPUT_TEXT_VALUE" > "$OUTPUT_TEXT"
fi

if [[ -n "$OUTPUT_TEXT_VALUE" ]]; then
  log SUCCESS "openai.responses.archived dir=${ARTIFACT_DIR}"
  printf '%s\n' "$OUTPUT_TEXT_VALUE"
else
  log WARNING "openai.responses.output_text_missing response=${RAW_RESPONSE_PATH}"
  cat "$RAW_RESPONSE_PATH"
fi
