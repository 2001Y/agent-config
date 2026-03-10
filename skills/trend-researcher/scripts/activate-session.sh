#!/usr/bin/env bash
set -euo pipefail

timestamp_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  local level="$1"
  shift
  printf '%s %s %s\n' "$(timestamp_utc)" "$level" "$*" >&2
}

usage() {
  cat <<'USAGE'
Usage:
  source scripts/activate-session.sh <repo-path> [artifacts-dir]

Behavior:
  - Creates or reuses the trend-researcher artifact directory
  - Prepends this skill's scripts directory to PATH
  - Routes future `xurl` calls in the same shell through the logging wrapper

Exports:
  TREND_RESEARCH_DIR
  TREND_RESEARCH_REAL_XURL
USAGE
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  usage >&2
  echo "Error: source this script instead of executing it." >&2
  exit 1
fi

[[ $# -ge 1 ]] || {
  usage >&2
  return 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_PATH="$1"
ARTIFACT_DIR_INPUT="${2:-}"

if [[ ! -e "$REPO_PATH" ]]; then
  echo "Error: repo path not found: $REPO_PATH" >&2
  return 1
fi

if [[ -d "$REPO_PATH" ]]; then
  REPO_ROOT="$(cd "$REPO_PATH" && pwd -P)"
else
  REPO_ROOT="$(cd "$(dirname "$REPO_PATH")" && pwd -P)"
fi

if [[ -n "$ARTIFACT_DIR_INPUT" ]]; then
  TREND_RESEARCH_DIR="$ARTIFACT_DIR_INPUT"
else
  TREND_RESEARCH_DIR="${REPO_ROOT}/_docs/_skills/trend-researcher/$(date -u +"%Y%m%dT%H%M%SZ")-$$"
fi

mkdir -p "$TREND_RESEARCH_DIR"
touch "$TREND_RESEARCH_DIR/queries.jsonl" "$TREND_RESEARCH_DIR/x-search.jsonl" "$TREND_RESEARCH_DIR/notes.md"
if [[ ! -f "$TREND_RESEARCH_DIR/x-search.json" ]]; then
  printf '[]\n' > "$TREND_RESEARCH_DIR/x-search.json"
fi

if [[ -n "${TREND_RESEARCH_REAL_XURL:-}" && -x "${TREND_RESEARCH_REAL_XURL}" ]]; then
  :
else
  mapfile -t XURL_CANDIDATES < <(which -a xurl 2>/dev/null || true)
  for candidate in "${XURL_CANDIDATES[@]}"; do
    if [[ "$candidate" != "${SCRIPT_DIR}/xurl" ]]; then
      TREND_RESEARCH_REAL_XURL="$candidate"
      break
    fi
  done
fi

if [[ -z "${TREND_RESEARCH_REAL_XURL:-}" ]]; then
  echo "Error: could not find the real xurl binary." >&2
  return 1
fi

case ":$PATH:" in
  *":${SCRIPT_DIR}:"*) ;;
  *) export PATH="${SCRIPT_DIR}:$PATH" ;;
esac

export TREND_RESEARCH_DIR
export TREND_RESEARCH_REAL_XURL

log INFO "trend-researcher.session dir=${TREND_RESEARCH_DIR} real_xurl=${TREND_RESEARCH_REAL_XURL}"
