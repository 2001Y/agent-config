# Response Inspection

## HTTP failure handling

Treat any non-2xx HTTP status as a hard failure.

```bash
case "$http_status" in
  2*)
    ;;
  *)
    ended_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    duration_seconds="$(( $(date +%s) - started_epoch ))"
    printf '%s ERROR openai.responses.http status=%s body_file=%s\n' \
      "$ended_at" "$http_status" "$body_file" >&2
    printf '%s ERROR openai.responses.duration seconds=%s\n' \
      "$ended_at" "$duration_seconds" >&2
    cat "$body_file" >&2
    exit 1
    ;;
esac
```

## Structured response summary

Use Python from the standard library instead of depending on `jq`.

```bash
ended_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
duration_seconds="$(( $(date +%s) - started_epoch ))"

python3 - "$body_file" <<'PY'
import json
import sys
from pathlib import Path

body = json.loads(Path(sys.argv[1]).read_text())
usage = body.get("usage") or {}
error = body.get("error") or {}
incomplete = body.get("incomplete_details") or {}
status = body.get("status")

summary = {
    "id": body.get("id"),
    "status": status,
    "service_tier": body.get("service_tier"),
    "input_tokens": usage.get("input_tokens"),
    "output_tokens": usage.get("output_tokens"),
    "total_tokens": usage.get("total_tokens"),
    "error_code": error.get("code"),
    "error_message": error.get("message"),
    "incomplete_reason": incomplete.get("reason"),
}

for key, value in summary.items():
    print(f"{key}={value}")

output_text = body.get("output_text")
if output_text:
    print("--- output_text ---")
    print(output_text)

if status in {"failed", "incomplete"}:
    sys.exit(1)
PY

status_exit="$?"
printf '%s INFO openai.responses.duration seconds=%s\n' \
  "$ended_at" "$duration_seconds"

if [ "$status_exit" -ne 0 ]; then
  printf '%s ERROR openai.responses.status body_file=%s\n' \
    "$ended_at" "$body_file" >&2
  exit "$status_exit"
fi
```

## Status handling

Treat these as failure paths even when the HTTP status is 2xx:

- `status=failed`
- `status=incomplete`

Inspect these fields before reporting success:

- `error.code`
- `error.message`
- `incomplete_details.reason`
- `service_tier`

## Log line examples

```text
2026-03-06T12:34:56Z INFO openai.responses.request model=gpt-5.2 requested_service_tier=priority payload_file=/var/folders/.../tmp.a1b2c3
2026-03-06T12:35:04Z INFO openai.responses.duration seconds=8
2026-03-06T12:35:04Z SUCCESS openai.responses.response id=resp_123 status=completed actual_service_tier=default total_tokens=1842
2026-03-06T12:35:04Z WARNING openai.responses.priority_downgrade requested=priority actual=default
2026-03-06T12:35:04Z ERROR openai.responses.incomplete reason=max_output_tokens
```
