#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: ./install.sh [--agents-only|--skills-only] [--dry-run] [--target DIR]
USAGE
}

log() {
  printf '[install] %s\n' "$*"
}

run_cmd() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run]'
    for arg in "$@"; do
      printf ' %q' "$arg"
    done
    printf '\n'
  else
    "$@"
  fi
}

abspath() {
  local path="$1"
  if [[ -d "$path" ]]; then
    (
      cd "$path" >/dev/null 2>&1
      pwd
    )
  else
    (
      cd "$(dirname "$path")" >/dev/null 2>&1
      printf '%s/%s\n' "$(pwd)" "$(basename "$path")"
    )
  fi
}

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="${CODEX_HOME:-$HOME/.codex}"
TIMESTAMP="$(date +%Y%m%dT%H%M%S)"
INSTALL_AGENTS=1
INSTALL_SKILLS=1
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agents-only)
      INSTALL_SKILLS=0
      ;;
    --skills-only)
      INSTALL_AGENTS=0
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    --target)
      shift
      [[ $# -gt 0 ]] || { usage >&2; exit 1; }
      TARGET_DIR="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 1
      ;;
  esac
  shift
done

ROOT_ABS="$(abspath "$ROOT_DIR")"
TARGET_ABS="$(abspath "$TARGET_DIR")"

if [[ "$ROOT_ABS" == "$TARGET_ABS" ]]; then
  printf 'error: source repo and install target are the same: %s\n' "$ROOT_ABS" >&2
  printf 'hint: clone this repo outside CODEX_HOME, or pass --target to a different path.\n' >&2
  exit 1
fi

backup_if_exists() {
  local path="$1"
  if [[ -e "$path" ]]; then
    run_cmd mv "$path" "$path.bak.$TIMESTAMP"
  fi
}

copy_file() {
  local src="$1"
  local dst="$2"
  backup_if_exists "$dst"
  run_cmd mkdir -p "$(dirname "$dst")"
  run_cmd cp "$src" "$dst"
}

copy_skill_dir() {
  local src_dir="$1"
  local dst_dir="$2"
  backup_if_exists "$dst_dir"
  run_cmd mkdir -p "$(dirname "$dst_dir")"
  run_cmd cp -R "$src_dir" "$dst_dir"
}

if [[ "$INSTALL_AGENTS" == "1" ]]; then
  log "installing AGENTS.md -> $TARGET_DIR/AGENTS.md"
  copy_file "$ROOT_DIR/AGENTS.md" "$TARGET_DIR/AGENTS.md"
fi

if [[ "$INSTALL_SKILLS" == "1" ]]; then
  log "installing skills -> $TARGET_DIR/skills"
  run_cmd mkdir -p "$TARGET_DIR/skills"
  while IFS= read -r skill_dir; do
    skill_name="$(basename "$skill_dir")"
    [[ "$skill_name" == ".system" ]] && continue
    copy_skill_dir "$skill_dir" "$TARGET_DIR/skills/$skill_name"
  done < <(find "$ROOT_DIR/skills" -mindepth 1 -maxdepth 1 -type d | sort)
fi

log "done"
