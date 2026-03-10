#!/usr/bin/env python3
"""Generate Codex usage insights from session logs."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from statistics import mean
from typing import Any

KNOWN_TOP_LEVEL_TYPES = {
    "session_meta",
    "response_item",
    "event_msg",
    "turn_context",
    "compacted",
    "compaction",
    "context_compacted",
}
SLASH_COMMAND_RE = re.compile(r"(?m)^\s*/([a-zA-Z][\w.-]*)\b")
EXIT_CODE_RE = re.compile(r"(?i)\bexit code:\s*(-?\d+)")
ERROR_LINE_RE = re.compile(
    r"(?i)(\berror\s*[:\-]\s*|\berror code\b|\bfailed\b|\bexception\b|\btraceback\b|\bpanic\b|\bnpm err!\b)"
)
PATH_DATE_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")
LEGACY_RESPONSE_ITEM_TYPES = {
    "message",
    "reasoning",
    "function_call",
    "function_call_output",
    "custom_tool_call",
    "custom_tool_call_output",
}


class InsightsError(RuntimeError):
    """Raised when logs are invalid or analysis cannot proceed."""


@dataclass
class SessionSummary:
    """Aggregated metrics for one session log file."""

    session_id: str
    file_path: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    cwd: str | None = None
    cli_version: str | None = None
    source: str | None = None
    model_provider: str | None = None
    model_counts: Counter[str] = field(default_factory=Counter)
    user_commands: Counter[str] = field(default_factory=Counter)
    tool_calls: Counter[str] = field(default_factory=Counter)
    hour_activity: Counter[int] = field(default_factory=Counter)
    error_signatures: Counter[str] = field(default_factory=Counter)
    command_attempts: Counter[str] = field(default_factory=Counter)
    command_failures: Counter[str] = field(default_factory=Counter)
    token_input: int = 0
    token_output: int = 0
    token_reasoning: int = 0
    token_total: int = 0
    call_attempts: int = 0
    call_successes: int = 0
    call_failures: int = 0
    call_id_to_name: dict[str, str] = field(default_factory=dict)

    def observe_timestamp(self, timestamp: datetime) -> None:
        if self.started_at is None or timestamp < self.started_at:
            self.started_at = timestamp
        if self.ended_at is None or timestamp > self.ended_at:
            self.ended_at = timestamp
        self.hour_activity[timestamp.hour] += 1


class RunLogger:
    """JSONL logger with required observability fields."""

    def __init__(self, log_path: Path, run_id: str) -> None:
        self.log_path = log_path
        self.run_id = run_id
        self.started_at = datetime.now(timezone.utc)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.log_path.open("w", encoding="utf-8")

    def log(
        self,
        level: str,
        phase: str,
        message: str,
        input_digest: dict[str, Any] | None = None,
        output_digest: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "timestamp": isoformat_z(now),
            "elapsed_ms": int((now - self.started_at).total_seconds() * 1000),
            "run_id": self.run_id,
            "level": level,
            "phase": phase,
            "message": message,
            "input_digest": input_digest or {},
            "output_digest": output_digest or {},
        }
        if extra:
            payload["extra"] = extra
        self.handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()


def isoformat_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(raw_value: Any, context: str) -> datetime:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InsightsError(f"invalid timestamp in {context}: {raw_value!r}")
    normalized = raw_value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise InsightsError(f"cannot parse timestamp in {context}: {raw_value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_int(raw_value: Any, default: int = 0) -> int:
    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(raw_value)
    if isinstance(raw_value, str) and raw_value.strip().lstrip("-").isdigit():
        return int(raw_value.strip())
    raise InsightsError(f"expected numeric value, got: {raw_value!r}")


def infer_path_date(log_path: Path) -> datetime | None:
    match = PATH_DATE_RE.search(str(log_path))
    if not match:
        return None
    year, month, day = match.groups()
    try:
        return datetime(int(year), int(month), int(day), tzinfo=timezone.utc)
    except ValueError as exc:
        raise InsightsError(f"invalid date segments in log path: {log_path}") from exc


def list_log_files(log_dir: Path, range_cutoff: datetime) -> list[Path]:
    if not log_dir.exists():
        raise InsightsError(f"log directory does not exist: {log_dir}")
    if not log_dir.is_dir():
        raise InsightsError(f"log directory is not a directory: {log_dir}")

    files: list[Path] = []
    cutoff_date = range_cutoff.date()
    for candidate in sorted(log_dir.rglob("*")):
        if not candidate.is_file():
            continue
        suffix = candidate.suffix.lower()
        if suffix in {".jsonl", ".json"}:
            inferred_date = infer_path_date(candidate)
            if inferred_date is not None and inferred_date.date() < cutoff_date:
                continue
            files.append(candidate)

    if not files:
        raise InsightsError(f"no .json/.jsonl files found under: {log_dir}")
    return files


def iter_log_records(log_file: Path) -> list[tuple[int, dict[str, Any]]]:
    suffix = log_file.suffix.lower()
    if suffix == ".jsonl":
        records: list[tuple[int, dict[str, Any]]] = []
        with log_file.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    raise InsightsError(f"empty line is not allowed: {log_file}:{line_number}")
                try:
                    parsed = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise InsightsError(
                        f"invalid JSONL line in {log_file}:{line_number}: {exc.msg}"
                    ) from exc
                if not isinstance(parsed, dict):
                    raise InsightsError(f"line is not a JSON object: {log_file}:{line_number}")
                records.append((line_number, parsed))
        return records

    with log_file.open("r", encoding="utf-8") as handle:
        try:
            parsed_json = json.load(handle)
        except json.JSONDecodeError as exc:
            raise InsightsError(f"invalid JSON file {log_file}: {exc.msg}") from exc

    if isinstance(parsed_json, dict):
        return [(1, parsed_json)]
    if isinstance(parsed_json, list):
        records = []
        for index, item in enumerate(parsed_json, start=1):
            if not isinstance(item, dict):
                raise InsightsError(f"JSON array item is not object: {log_file}:{index}")
            records.append((index, item))
        return records
    raise InsightsError(f"unsupported JSON root type in {log_file}: {type(parsed_json).__name__}")


def normalize_error_line(raw_line: str) -> str:
    line = raw_line.strip()
    if not line:
        return ""
    line = re.sub(r"\s+", " ", line)
    line = re.sub(r"(/[A-Za-z0-9._\-\\/]+)", "<path>", line)
    line = re.sub(r"\b\d+\b", "<num>", line)
    line = line.lower()
    if len(line) > 180:
        line = line[:180]
    return line


def extract_error_signatures(text: str) -> list[str]:
    signatures: list[str] = []
    seen: set[str] = set()

    for match in EXIT_CODE_RE.finditer(text):
        exit_code = parse_int(match.group(1))
        if exit_code != 0:
            signature = f"exit_code_{exit_code}"
            if signature not in seen:
                signatures.append(signature)
                seen.add(signature)

    for line in text.splitlines():
        if len(line) > 240:
            continue
        if "\"result\":" in line:
            continue
        if not ERROR_LINE_RE.search(line):
            continue
        normalized = normalize_error_line(line)
        if not normalized:
            continue
        if normalized not in seen:
            signatures.append(normalized)
            seen.add(normalized)

    return signatures


def classify_tool_output(raw_output: Any) -> tuple[bool, list[str]]:
    if raw_output is None:
        return True, []
    if isinstance(raw_output, str):
        output_text = raw_output
    else:
        output_text = json.dumps(raw_output, ensure_ascii=False)

    signatures = extract_error_signatures(output_text)
    exit_match = EXIT_CODE_RE.search(output_text)
    if exit_match:
        return parse_int(exit_match.group(1)) == 0, signatures
    return len(signatures) == 0, signatures


def extract_user_texts(payload: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    content = payload.get("content")
    if not isinstance(content, list):
        return texts

    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            texts.append(text)
    return texts


def extract_slash_commands(text: str) -> list[str]:
    commands: list[str] = []
    for match in SLASH_COMMAND_RE.finditer(text):
        commands.append(f"/{match.group(1).lower()}")
    return commands


def handle_response_item(
    session: SessionSummary,
    payload: Any,
    context: str,
) -> None:
    if not isinstance(payload, dict):
        raise InsightsError(f"payload must be object in {context}")

    payload_type = payload.get("type")
    if not isinstance(payload_type, str):
        raise InsightsError(f"response_item payload.type must be string in {context}")

    if payload_type in {"function_call", "custom_tool_call"}:
        command_name = payload.get("name")
        if not isinstance(command_name, str) or not command_name:
            command_name = "unknown_tool"

        session.tool_calls[command_name] += 1
        session.command_attempts[command_name] += 1
        session.call_attempts += 1

        call_id = payload.get("call_id")
        if isinstance(call_id, str) and call_id:
            session.call_id_to_name[call_id] = command_name
        return

    if payload_type in {"function_call_output", "custom_tool_call_output"}:
        call_id = payload.get("call_id")
        command_name = (
            session.call_id_to_name.get(call_id, "unknown_tool")
            if isinstance(call_id, str)
            else "unknown_tool"
        )
        success, error_signatures = classify_tool_output(payload.get("output"))
        if success:
            session.call_successes += 1
        else:
            session.call_failures += 1
            session.command_failures[command_name] += 1
            for signature in error_signatures:
                session.error_signatures[signature] += 1
        return

    if payload_type == "message":
        role = payload.get("role")
        if role == "user":
            for user_text in extract_user_texts(payload):
                for command in extract_slash_commands(user_text):
                    session.user_commands[command] += 1
        return


def handle_event_msg(session: SessionSummary, payload: Any, context: str) -> None:
    if not isinstance(payload, dict):
        raise InsightsError(f"payload must be object in {context}")

    payload_type = payload.get("type")
    if payload_type == "token_count":
        info = payload.get("info")
        if not isinstance(info, dict):
            session.error_signatures["token_count_info_missing"] += 1
            return

        total_usage = info.get("total_token_usage")
        last_usage = info.get("last_token_usage")
        usage = total_usage if isinstance(total_usage, dict) else last_usage
        if not isinstance(usage, dict):
            session.error_signatures["token_usage_missing"] += 1
            return

        session.token_input = max(session.token_input, parse_int(usage.get("input_tokens"), 0))
        session.token_output = max(session.token_output, parse_int(usage.get("output_tokens"), 0))
        session.token_reasoning = max(
            session.token_reasoning,
            parse_int(usage.get("reasoning_output_tokens"), 0),
        )
        session.token_total = max(session.token_total, parse_int(usage.get("total_tokens"), 0))
        return

    message_text = payload.get("text")
    if isinstance(message_text, str):
        for signature in extract_error_signatures(message_text):
            session.error_signatures[signature] += 1


def normalize_record(record: dict[str, Any], context: str) -> dict[str, Any] | None:
    if "type" not in record:
        legacy_type = record.get("record_type")
        if legacy_type == "state":
            return None
        if "id" in record and "timestamp" in record:
            return {
                "timestamp": record["timestamp"],
                "type": "session_meta",
                "payload": record,
            }
        raise InsightsError(f"record.type missing in {context}")

    record_type = record["type"]
    if not isinstance(record_type, str):
        raise InsightsError(f"record.type must be string in {context}")

    if record_type in KNOWN_TOP_LEVEL_TYPES:
        return record

    if record_type in LEGACY_RESPONSE_ITEM_TYPES:
        payload = dict(record)
        timestamp = payload.pop("timestamp", None)
        return {
            "timestamp": timestamp,
            "type": "response_item",
            "payload": payload,
        }

    if record_type == "token_count":
        payload = dict(record)
        timestamp = payload.pop("timestamp", None)
        return {
            "timestamp": timestamp,
            "type": "event_msg",
            "payload": payload,
        }

    if record_type == "state":
        return None

    raise InsightsError(f"unknown top-level record type in {context}: {record_type}")


def process_record(
    session: SessionSummary,
    record: dict[str, Any],
    context: str,
) -> None:
    normalized = normalize_record(record, context)
    if normalized is None:
        return

    record_type = normalized["type"]
    timestamp_raw = normalized.get("timestamp")
    if timestamp_raw is None:
        if session.ended_at is None:
            raise InsightsError(f"missing timestamp in {context} and no prior session timestamp")
        timestamp = session.ended_at
    else:
        timestamp = parse_timestamp(timestamp_raw, context)
    session.observe_timestamp(timestamp)
    payload = normalized.get("payload")

    if record_type == "session_meta":
        if not isinstance(payload, dict):
            raise InsightsError(f"session_meta payload must be object in {context}")
        meta_session_id = payload.get("id")
        if isinstance(meta_session_id, str) and meta_session_id:
            session.session_id = meta_session_id
        meta_timestamp = payload.get("timestamp")
        if meta_timestamp is not None:
            session.observe_timestamp(parse_timestamp(meta_timestamp, f"{context}.payload.timestamp"))
        if isinstance(payload.get("cwd"), str):
            session.cwd = payload["cwd"]
        if isinstance(payload.get("cli_version"), str):
            session.cli_version = payload["cli_version"]
        if isinstance(payload.get("source"), str):
            session.source = payload["source"]
        if isinstance(payload.get("model_provider"), str):
            session.model_provider = payload["model_provider"]
        if isinstance(payload.get("model"), str):
            session.model_counts[payload["model"]] += 1
        return

    if record_type == "turn_context":
        if not isinstance(payload, dict):
            raise InsightsError(f"turn_context payload must be object in {context}")
        model = payload.get("model")
        if isinstance(model, str) and model:
            session.model_counts[model] += 1
        return

    if record_type == "response_item":
        handle_response_item(session, payload, context)
        return

    if record_type == "event_msg":
        handle_event_msg(session, payload, context)
        return


def collect_sessions(log_files: list[Path], logger: RunLogger) -> list[SessionSummary]:
    sessions: list[SessionSummary] = []
    logger.log(
        "INFO",
        "collect",
        "starting log collection",
        input_digest={"file_count": len(log_files)},
        output_digest={},
    )

    for log_file in log_files:
        session = SessionSummary(session_id=log_file.stem, file_path=str(log_file))
        records = iter_log_records(log_file)
        for line_or_index, record in records:
            context = f"{log_file}:{line_or_index}"
            process_record(session, record, context)
        if session.started_at is None:
            raise InsightsError(f"session has no timestamps: {log_file}")
        sessions.append(session)

    logger.log(
        "SUCCRSS",
        "collect",
        "log collection completed",
        input_digest={"file_count": len(log_files)},
        output_digest={"session_count": len(sessions)},
    )
    return sessions


def sort_weighted_counter(counter_map: dict[str, float], limit: int = 10) -> list[dict[str, float]]:
    ranked = sorted(counter_map.items(), key=lambda item: item[1], reverse=True)
    output: list[dict[str, float]] = []
    for name, value in ranked[:limit]:
        output.append({"name": name, "value": round(float(value), 3)})
    return output


def build_suggestions(
    failure_rate: float,
    avg_tokens_per_session: float,
    slash_command_count: int,
    top_action_share: float,
    repeated_error_count: int,
) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []

    if failure_rate >= 0.2:
        suggestions.append(
            {
                "problem": "Tool call failures are high",
                "reason": f"Failure rate is {failure_rate:.1%}, which indicates repeated retries.",
                "action": "Add preflight checks before shell/tool calls and stop after first deterministic failure.",
                "impact": "Lower retry loops and faster time-to-fix.",
            }
        )

    if avg_tokens_per_session >= 80000:
        suggestions.append(
            {
                "problem": "Token usage per session is expensive",
                "reason": f"Average total tokens per session is {avg_tokens_per_session:,.0f}.",
                "action": "Split long tasks into smaller milestones and summarize context every major step.",
                "impact": "Lower token cost and reduced context drift.",
            }
        )

    if slash_command_count == 0:
        suggestions.append(
            {
                "problem": "Slash commands are not used",
                "reason": "No reusable command workflow was detected.",
                "action": "Create small command templates in skills to standardize repetitive actions.",
                "impact": "More consistent execution and less prompt overhead.",
            }
        )

    if top_action_share >= 60.0:
        suggestions.append(
            {
                "problem": "Workflow concentration is high",
                "reason": f"Top action share is {top_action_share:.1f}%.",
                "action": "Introduce a secondary workflow for debugging/review to avoid single-path bottlenecks.",
                "impact": "Better task coverage and lower friction on edge cases.",
            }
        )

    if repeated_error_count >= 5:
        suggestions.append(
            {
                "problem": "Same error patterns keep repeating",
                "reason": f"{repeated_error_count} repeated error signatures were detected.",
                "action": "Build a short runbook mapping each recurring error to a first-response command.",
                "impact": "Faster recovery and less trial-and-error.",
            }
        )

    return suggestions[:5]


def build_upcoming_features(
    failure_rate: float,
    avg_tokens_per_session: float,
    has_parallel_tool_use: bool,
) -> list[dict[str, str]]:
    features: list[dict[str, str]] = []

    if failure_rate >= 0.2:
        features.append(
            {
                "theme": "Guarded execution presets",
                "when_to_use": "When command failures repeat in the same area.",
                "adoption_cost": "Low: add one reusable preflight block.",
                "expected_effect": "Fewer broken runs and cleaner logs.",
            }
        )

    if avg_tokens_per_session >= 80000:
        features.append(
            {
                "theme": "Context compaction checkpoints",
                "when_to_use": "For long-running tasks with broad context.",
                "adoption_cost": "Low: add periodic summary checkpoints.",
                "expected_effect": "Reduced cost without losing task continuity.",
            }
        )

    if not has_parallel_tool_use:
        features.append(
            {
                "theme": "Parallel exploration batches",
                "when_to_use": "When collecting data from multiple files or logs.",
                "adoption_cost": "Medium: structure independent checks in parallel.",
                "expected_effect": "Shorter diagnostic lead time.",
            }
        )
    else:
        features.append(
            {
                "theme": "Parallel-first diagnostics",
                "when_to_use": "When multiple hypotheses can be tested independently.",
                "adoption_cost": "Low: keep existing parallel pattern and tighten result aggregation.",
                "expected_effect": "Higher throughput with stable quality.",
            }
        )

    while len(features) < 3:
        features.append(
            {
                "theme": "Reusable investigation templates",
                "when_to_use": "For recurring production issues.",
                "adoption_cost": "Low: one template per issue family.",
                "expected_effect": "Lower setup overhead per investigation.",
            }
        )

    return features[:3]


def build_effort_controls(
    failure_rate: float,
    avg_tokens_per_session: float,
    sessions_count: int,
) -> dict[str, Any]:
    speed_score = max(0.0, min(100.0, 90.0 - (failure_rate * 70.0) + min(12.0, sessions_count * 0.8)))
    quality_score = max(0.0, min(100.0, 92.0 - (failure_rate * 80.0)))
    cost_score = max(0.0, min(100.0, 95.0 - min(85.0, avg_tokens_per_session / 1800.0)))

    recommendations: list[str] = []
    if speed_score < 70:
        recommendations.append("Speed: reduce retries by introducing strict preflight validation.")
    if quality_score < 70:
        recommendations.append("Quality: add deterministic checks after each high-risk command.")
    if cost_score < 70:
        recommendations.append("Cost: compact context and split broad tasks into staged runs.")
    if not recommendations:
        recommendations.append("Current speed/quality/cost balance is stable. Keep the same guardrails.")

    return {
        "scores": {
            "speed": round(speed_score, 1),
            "quality": round(quality_score, 1),
            "cost": round(cost_score, 1),
        },
        "recommendations": recommendations,
    }


def analyze_sessions(
    sessions: list[SessionSummary],
    now_utc: datetime,
    range_days: int,
    recent_days: int,
    logger: RunLogger,
) -> dict[str, Any]:
    analyze_started = datetime.now(timezone.utc)
    range_cutoff = now_utc - timedelta(days=range_days)
    recent_cutoff = now_utc - timedelta(days=recent_days)

    in_range: list[SessionSummary] = []
    for session in sessions:
        if session.started_at is None:
            raise InsightsError(f"session missing started_at: {session.file_path}")
        if session.started_at >= range_cutoff:
            in_range.append(session)

    if not in_range:
        raise InsightsError(
            f"no sessions found in last {range_days} days (cutoff={isoformat_z(range_cutoff)})"
        )

    weighted_actions: defaultdict[str, float] = defaultdict(float)
    weighted_models: defaultdict[str, float] = defaultdict(float)
    weighted_hours: defaultdict[int, float] = defaultdict(float)
    weighted_error_signatures: defaultdict[str, float] = defaultdict(float)
    weighted_command_attempts: defaultdict[str, float] = defaultdict(float)
    weighted_command_failures: defaultdict[str, float] = defaultdict(float)
    daily_tokens: defaultdict[str, int] = defaultdict(int)

    sessions_count = len(in_range)
    recent_sessions = 0
    active_days: set[str] = set()
    all_tokens: list[int] = []
    total_attempts = 0
    total_failures = 0
    total_successes = 0
    slash_command_count = 0
    has_parallel_tool_use = False

    for session in in_range:
        assert session.started_at is not None
        weight = 1.0 if session.started_at >= recent_cutoff else 0.5
        if weight == 1.0:
            recent_sessions += 1

        active_days.add(session.started_at.date().isoformat())
        daily_tokens[session.started_at.date().isoformat()] += session.token_total
        all_tokens.append(session.token_total)
        total_attempts += session.call_attempts
        total_failures += session.call_failures
        total_successes += session.call_successes
        slash_command_count += sum(session.user_commands.values())

        if len(session.tool_calls) >= 2:
            has_parallel_tool_use = True

        for action, count in session.tool_calls.items():
            weighted_actions[action] += count * weight
        for command, count in session.user_commands.items():
            weighted_actions[command] += count * weight
        for model, count in session.model_counts.items():
            weighted_models[model] += count * weight
        for hour, count in session.hour_activity.items():
            weighted_hours[hour] += count * weight
        for signature, count in session.error_signatures.items():
            weighted_error_signatures[signature] += count * weight
        for command, count in session.command_attempts.items():
            weighted_command_attempts[command] += count * weight
        for command, count in session.command_failures.items():
            weighted_command_failures[command] += count * weight

    total_tokens = sum(all_tokens)
    avg_tokens_per_session = mean(all_tokens) if all_tokens else 0.0
    failure_rate = (total_failures / total_attempts) if total_attempts else 0.0

    sorted_actions = sort_weighted_counter(dict(weighted_actions), limit=20)
    sorted_models = sort_weighted_counter(dict(weighted_models), limit=10)
    sorted_errors = sort_weighted_counter(dict(weighted_error_signatures), limit=15)

    top_action_name = sorted_actions[0]["name"] if sorted_actions else "none"
    top_action_value = sorted_actions[0]["value"] if sorted_actions else 0.0
    action_total_weight = sum(item["value"] for item in sorted_actions) or 1.0
    top_action_share = (top_action_value / action_total_weight) * 100.0 if sorted_actions else 0.0

    top_model_name = sorted_models[0]["name"] if sorted_models else "none"
    top_model_value = sorted_models[0]["value"] if sorted_models else 0.0
    model_total_weight = sum(item["value"] for item in sorted_models) or 1.0
    top_model_share = (top_model_value / model_total_weight) * 100.0 if sorted_models else 0.0

    summary_lines = [
        f"Sessions analyzed: {sessions_count} (recent {recent_days}d: {recent_sessions}).",
        f"Active days: {len(active_days)}. Average tokens/session: {avg_tokens_per_session:,.0f}.",
        f"Top action: {top_action_name} ({top_action_share:.1f}% weighted share).",
        f"Primary model: {top_model_name} ({top_model_share:.1f}% weighted share).",
        f"Tool call failure rate: {failure_rate:.1%}.",
    ]

    friction_items: list[dict[str, str]] = []
    for item in sorted_errors[:5]:
        friction_items.append(
            {
                "reproduction": "Run the same workflow that produced this signature.",
                "frequency": f"{item['value']:.1f} weighted hits",
                "impact": "Retry loops and lower confidence in outputs.",
                "short_fix": "Create a deterministic first-response command for this signature.",
                "signature": item["name"],
            }
        )

    for command, attempts in sorted(
        weighted_command_attempts.items(), key=lambda pair: pair[1], reverse=True
    ):
        if attempts < 3:
            continue
        failures = weighted_command_failures.get(command, 0.0)
        command_failure_rate = failures / attempts if attempts else 0.0
        if command_failure_rate < 0.30:
            continue
        friction_items.append(
            {
                "reproduction": f"Trigger command `{command}` in the same task context.",
                "frequency": f"{attempts:.1f} attempts / {failures:.1f} failures",
                "impact": "High interruption rate and repeated recovery overhead.",
                "short_fix": "Add argument validation and stop after first deterministic failure.",
                "signature": f"command:{command}",
            }
        )
        if len(friction_items) >= 8:
            break

    suggestions = build_suggestions(
        failure_rate=failure_rate,
        avg_tokens_per_session=avg_tokens_per_session,
        slash_command_count=slash_command_count,
        top_action_share=top_action_share,
        repeated_error_count=len(sorted_errors),
    )

    upcoming_features = build_upcoming_features(
        failure_rate=failure_rate,
        avg_tokens_per_session=avg_tokens_per_session,
        has_parallel_tool_use=has_parallel_tool_use,
    )

    effort_controls = build_effort_controls(
        failure_rate=failure_rate,
        avg_tokens_per_session=avg_tokens_per_session,
        sessions_count=sessions_count,
    )

    daily_tokens_series = [
        {"date": date_key, "tokens": token_value}
        for date_key, token_value in sorted(daily_tokens.items(), key=lambda item: item[0])
    ]
    hourly_activity_series = [
        {"hour": hour, "activity": round(weighted_hours.get(hour, 0.0), 3)}
        for hour in range(24)
    ]

    report: dict[str, Any] = {
        "generated_at": isoformat_z(now_utc),
        "stats": {
            "sessions_count": sessions_count,
            "recent_sessions_count": recent_sessions,
            "active_days": len(active_days),
            "total_tokens": total_tokens,
            "avg_tokens_per_session": round(avg_tokens_per_session, 2),
            "tool_call_attempts": total_attempts,
            "tool_call_successes": total_successes,
            "tool_call_failures": total_failures,
            "tool_call_failure_rate": round(failure_rate, 4),
            "top_action": top_action_name,
            "top_action_share_percent": round(top_action_share, 2),
            "top_model": top_model_name,
            "top_model_share_percent": round(top_model_share, 2),
        },
        "insights": {
            "summary": summary_lines,
            "suggestions": suggestions,
            "friction_analysis": friction_items,
            "upcoming_features_briefing": upcoming_features,
            "effort_controls": effort_controls,
        },
        "datasets": {
            "daily_tokens": daily_tokens_series,
            "hourly_activity": hourly_activity_series,
            "top_actions": sorted_actions,
            "model_usage": sorted_models,
            "error_signatures": sorted_errors,
        },
    }

    logger.log(
        "SUCCRSS",
        "analyze",
        "analysis completed",
        input_digest={
            "range_days": range_days,
            "recent_days": recent_days,
            "sessions_in_range": sessions_count,
        },
        output_digest={
            "total_tokens": total_tokens,
            "failure_rate": round(failure_rate, 4),
            "elapsed_ms": int((datetime.now(timezone.utc) - analyze_started).total_seconds() * 1000),
        },
    )
    return report


def render_line_chart(points: list[dict[str, Any]], label_key: str, value_key: str, title: str) -> str:
    if not points:
        return "<div class='chart-empty'>No data</div>"

    width = 860
    height = 280
    margin_left = 52
    margin_right = 20
    margin_top = 24
    margin_bottom = 44
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    values = [float(item[value_key]) for item in points]
    min_value = min(values)
    max_value = max(values)
    if math.isclose(max_value, min_value):
        max_value = min_value + 1.0

    step_x = plot_width / max(1, len(points) - 1)
    path_commands: list[str] = []
    circles: list[str] = []

    for index, item in enumerate(points):
        x = margin_left + (index * step_x)
        y_ratio = (float(item[value_key]) - min_value) / (max_value - min_value)
        y = margin_top + (plot_height - (y_ratio * plot_height))
        command = "M" if index == 0 else "L"
        path_commands.append(f"{command}{x:.2f},{y:.2f}")
        circles.append(f"<circle cx='{x:.2f}' cy='{y:.2f}' r='2.5'></circle>")

    labels: list[str] = []
    label_indexes = {0, len(points) // 2, len(points) - 1}
    for label_index in sorted(label_indexes):
        item = points[label_index]
        x = margin_left + (label_index * step_x)
        labels.append(
            "<text class='axis-label' x='{x:.2f}' y='{y:.2f}' text-anchor='middle'>{label}</text>".format(
                x=x,
                y=height - 14,
                label=escape(str(item[label_key])),
            )
        )

    return """
    <figure class='chart'>
      <figcaption>{title}</figcaption>
      <svg viewBox='0 0 {width} {height}' role='img' aria-label='{title_aria}'>
        <line class='axis' x1='{ml}' y1='{mt}' x2='{ml}' y2='{hb}'></line>
        <line class='axis' x1='{ml}' y1='{hb}' x2='{wr}' y2='{hb}'></line>
        <path class='line' d='{path}'></path>
        {circles}
        {labels}
      </svg>
    </figure>
    """.format(
        title=escape(title),
        title_aria=escape(title),
        width=width,
        height=height,
        ml=margin_left,
        mt=margin_top,
        hb=height - margin_bottom,
        wr=width - margin_right,
        path=" ".join(path_commands),
        circles="".join(circles),
        labels="".join(labels),
    )


def render_bar_chart(items: list[dict[str, Any]], title: str, limit: int = 12) -> str:
    if not items:
        return "<div class='chart-empty'>No data</div>"

    selected = items[:limit]
    max_value = max(float(item["value"]) for item in selected) or 1.0
    rows: list[str] = []
    for item in selected:
        value = float(item["value"])
        width = (value / max_value) * 100.0
        rows.append(
            """
            <div class='bar-row'>
              <div class='bar-label'>{label}</div>
              <div class='bar-track'><div class='bar-fill' style='width:{width:.2f}%'></div></div>
              <div class='bar-value'>{value:.2f}</div>
            </div>
            """.format(
                label=escape(str(item["name"])),
                width=width,
                value=value,
            )
        )

    return """
    <section class='bar-chart'>
      <h3>{title}</h3>
      {rows}
    </section>
    """.format(
        title=escape(title),
        rows="".join(rows),
    )


def render_hour_heatmap(hourly_activity: list[dict[str, Any]]) -> str:
    if not hourly_activity:
        return "<div class='chart-empty'>No data</div>"

    max_activity = max(float(item["activity"]) for item in hourly_activity) or 1.0
    cells: list[str] = []
    for item in hourly_activity:
        hour = parse_int(item["hour"])
        value = float(item["activity"])
        intensity = value / max_activity
        alpha = 0.12 + (0.78 * intensity)
        color = f"rgba(31, 111, 235, {alpha:.3f})"
        cells.append(
            """
            <div class='hour-cell' style='background:{color}'>
              <span class='hour-label'>{hour:02d}</span>
              <span class='hour-value'>{value:.1f}</span>
            </div>
            """.format(
                color=color,
                hour=hour,
                value=value,
            )
        )
    return "<section class='hour-grid'>{}</section>".format("".join(cells))


def render_report_html(report: dict[str, Any], run_id: str, config: dict[str, Any]) -> str:
    stats = report["stats"]
    insights = report["insights"]
    datasets = report["datasets"]

    summary_items = "".join(f"<li>{escape(line)}</li>" for line in insights["summary"])

    suggestion_items = []
    for suggestion in insights["suggestions"]:
        suggestion_items.append(
            """
            <li>
              <strong>{problem}</strong><br>
              Reason: {reason}<br>
              Action: {action}<br>
              Expected effect: {impact}
            </li>
            """.format(
                problem=escape(suggestion["problem"]),
                reason=escape(suggestion["reason"]),
                action=escape(suggestion["action"]),
                impact=escape(suggestion["impact"]),
            )
        )
    suggestions_html = "<ul>{}</ul>".format("".join(suggestion_items)) if suggestion_items else "<p>No suggestions.</p>"

    friction_items = []
    for friction in insights["friction_analysis"]:
        friction_items.append(
            """
            <li>
              <strong>{signature}</strong><br>
              Reproduction: {reproduction}<br>
              Frequency: {frequency}<br>
              Impact: {impact}<br>
              Short fix: {short_fix}
            </li>
            """.format(
                signature=escape(friction["signature"]),
                reproduction=escape(friction["reproduction"]),
                frequency=escape(friction["frequency"]),
                impact=escape(friction["impact"]),
                short_fix=escape(friction["short_fix"]),
            )
        )
    friction_html = "<ul>{}</ul>".format("".join(friction_items)) if friction_items else "<p>No friction patterns detected.</p>"

    feature_items = []
    for feature in insights["upcoming_features_briefing"]:
        feature_items.append(
            """
            <li>
              <strong>{theme}</strong><br>
              When: {when_to_use}<br>
              Cost: {adoption_cost}<br>
              Effect: {expected_effect}
            </li>
            """.format(
                theme=escape(feature["theme"]),
                when_to_use=escape(feature["when_to_use"]),
                adoption_cost=escape(feature["adoption_cost"]),
                expected_effect=escape(feature["expected_effect"]),
            )
        )
    features_html = "<ul>{}</ul>".format("".join(feature_items))

    effort = insights["effort_controls"]
    effort_score_lines = "".join(
        "<li>{name}: {value:.1f}</li>".format(name=escape(score_name), value=float(score_value))
        for score_name, score_value in effort["scores"].items()
    )
    effort_reco_lines = "".join(f"<li>{escape(text)}</li>" for text in effort["recommendations"])

    line_chart = render_line_chart(
        datasets["daily_tokens"],
        label_key="date",
        value_key="tokens",
        title="Daily total tokens",
    )
    action_chart = render_bar_chart(datasets["top_actions"], title="Top actions (weighted)")
    model_chart = render_bar_chart(datasets["model_usage"], title="Model usage (weighted)")
    heatmap_chart = render_hour_heatmap(datasets["hourly_activity"])

    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex Insights Report</title>
  <style>
    :root {{
      --bg: #f6f8fc;
      --card: #ffffff;
      --ink: #172033;
      --muted: #5b667a;
      --line: #d7deea;
      --accent: #1f6feb;
      --accent-soft: #e8f0ff;
      --ok: #0c9b6d;
      --warn: #bc8a00;
      --bad: #ca3a3a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 24px;
      font-family: "SF Pro Text", "Segoe UI", -apple-system, sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at top right, #edf3ff, var(--bg));
      line-height: 1.5;
    }}
    .wrap {{ max-width: 1200px; margin: 0 auto; }}
    .header {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 20px;
      box-shadow: 0 8px 28px rgba(15, 29, 54, 0.06);
      margin-bottom: 16px;
    }}
    .meta {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      margin-top: 14px;
    }}
    .meta-card {{
      background: var(--accent-soft);
      border: 1px solid #cfe0ff;
      border-radius: 10px;
      padding: 10px 12px;
    }}
    .meta-label {{ display: block; font-size: 12px; color: var(--muted); }}
    .meta-value {{ display: block; font-size: 18px; font-weight: 650; }}
    .panel {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 18px;
      box-shadow: 0 6px 18px rgba(15, 29, 54, 0.05);
      margin-bottom: 14px;
    }}
    details > summary {{
      cursor: pointer;
      font-weight: 650;
      margin-bottom: 10px;
    }}
    ul {{ margin-top: 8px; }}
    .grid {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      align-items: start;
    }}
    .chart figcaption {{
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 14px;
    }}
    .chart svg {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fff;
    }}
    .axis {{ stroke: #9fafc8; stroke-width: 1; }}
    .line {{ stroke: var(--accent); stroke-width: 2.4; fill: none; }}
    .chart circle {{ fill: var(--accent); }}
    .axis-label {{ fill: #5f6f89; font-size: 11px; }}
    .bar-chart h3 {{ margin: 0 0 10px 0; }}
    .bar-row {{
      display: grid;
      grid-template-columns: minmax(120px, 180px) 1fr 66px;
      gap: 8px;
      align-items: center;
      margin: 6px 0;
    }}
    .bar-label {{ font-size: 12px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .bar-track {{ background: #eef3ff; border-radius: 999px; height: 12px; border: 1px solid #d8e3ff; }}
    .bar-fill {{ background: linear-gradient(90deg, #2a79ff, #1f6feb); height: 100%; border-radius: 999px; }}
    .bar-value {{ text-align: right; font-variant-numeric: tabular-nums; font-size: 12px; color: var(--muted); }}
    .hour-grid {{
      display: grid;
      grid-template-columns: repeat(6, minmax(70px, 1fr));
      gap: 8px;
      margin-top: 8px;
    }}
    .hour-cell {{
      border-radius: 8px;
      padding: 7px;
      color: #0d1f3e;
      border: 1px solid rgba(31, 111, 235, 0.22);
      display: flex;
      justify-content: space-between;
      font-size: 11px;
    }}
    .footer {{
      margin-top: 8px;
      font-size: 12px;
      color: var(--muted);
    }}
    .chip {{
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      margin-right: 6px;
      color: var(--muted);
      background: #fafcff;
    }}
    .chart-empty {{
      border: 1px dashed var(--line);
      border-radius: 10px;
      padding: 18px;
      color: var(--muted);
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="header">
      <h1>Codex Insights Report</h1>
      <div>
        <span class="chip">Generated: {generated_at}</span>
        <span class="chip">Run ID: {run_id}</span>
        <span class="chip">Range: {range_days} days</span>
        <span class="chip">Recent weight: {recent_days} days</span>
      </div>
      <div class="meta">
        <div class="meta-card"><span class="meta-label">Sessions</span><span class="meta-value">{sessions_count}</span></div>
        <div class="meta-card"><span class="meta-label">Active Days</span><span class="meta-value">{active_days}</span></div>
        <div class="meta-card"><span class="meta-label">Total Tokens</span><span class="meta-value">{total_tokens}</span></div>
        <div class="meta-card"><span class="meta-label">Failure Rate</span><span class="meta-value">{failure_rate}</span></div>
      </div>
    </section>

    <section class="panel">
      <details open>
        <summary>At-a-glance summary</summary>
        <ul>{summary_items}</ul>
      </details>
    </section>

    <section class="grid">
      <section class="panel">
        <details open>
          <summary>Suggestions</summary>
          {suggestions_html}
        </details>
      </section>
      <section class="panel">
        <details open>
          <summary>Friction analysis</summary>
          {friction_html}
        </details>
      </section>
    </section>

    <section class="grid">
      <section class="panel">
        <details open>
          <summary>Upcoming features briefing</summary>
          {features_html}
        </details>
      </section>
      <section class="panel">
        <details open>
          <summary>Effort controls</summary>
          <ul>{effort_score_lines}</ul>
          <h4>Actions</h4>
          <ul>{effort_reco_lines}</ul>
        </details>
      </section>
    </section>

    <section class="panel">
      <details open>
        <summary>Charts</summary>
        {line_chart}
        {action_chart}
        {model_chart}
        <h3>Hourly activity heatmap</h3>
        {heatmap_chart}
      </details>
    </section>

    <div class="footer">
      Source log dir: {log_dir}
    </div>
  </div>
</body>
</html>
""".format(
        generated_at=escape(str(report["generated_at"])),
        run_id=escape(run_id),
        range_days=escape(str(config["range_days"])),
        recent_days=escape(str(config["recent_days"])),
        sessions_count=escape(str(stats["sessions_count"])),
        active_days=escape(str(stats["active_days"])),
        total_tokens=escape(f"{stats['total_tokens']:,}"),
        failure_rate=escape(f"{stats['tool_call_failure_rate']:.1%}"),
        summary_items=summary_items,
        suggestions_html=suggestions_html,
        friction_html=friction_html,
        features_html=features_html,
        effort_score_lines=effort_score_lines,
        effort_reco_lines=effort_reco_lines,
        line_chart=line_chart,
        action_chart=action_chart,
        model_chart=model_chart,
        heatmap_chart=heatmap_chart,
        log_dir=escape(str(config["log_dir"])),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Codex insights report from session logs.")
    parser.add_argument("--log-dir", default="~/.codex/sessions", help="Root directory of Codex logs.")
    parser.add_argument("--range-days", type=int, default=30, help="Analysis window in days.")
    parser.add_argument(
        "--recent-days",
        type=int,
        default=7,
        help="Recent sessions with full weight (older sessions use 0.5 weight).",
    )
    parser.add_argument("--output-dir", default="~/.codex/usage-data", help="Output directory.")
    parser.add_argument("--output-html", default="report.html", help="HTML report filename.")
    parser.add_argument("--output-json", default="insights.json", help="Machine-readable JSON filename.")
    parser.add_argument("--output-log", default="insights.log", help="Execution log filename.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.range_days <= 0:
        raise InsightsError("--range-days must be > 0")
    if args.recent_days <= 0:
        raise InsightsError("--recent-days must be > 0")
    if args.recent_days > args.range_days:
        raise InsightsError("--recent-days must be <= --range-days")

    log_dir = Path(args.log_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = uuid.uuid4().hex
    log_path = output_dir / args.output_log
    json_path = output_dir / args.output_json
    html_path = output_dir / args.output_html
    logger = RunLogger(log_path=log_path, run_id=run_id)

    try:
        config = {
            "log_dir": str(log_dir),
            "range_days": args.range_days,
            "recent_days": args.recent_days,
            "output_dir": str(output_dir),
            "output_html": args.output_html,
            "output_json": args.output_json,
            "output_log": args.output_log,
        }
        logger.log(
            "INFO",
            "init",
            "insights generation started",
            input_digest=config,
            output_digest={"run_id": run_id},
        )

        now_utc = datetime.now(timezone.utc)
        range_cutoff = now_utc - timedelta(days=args.range_days)
        log_files = list_log_files(log_dir, range_cutoff)
        logger.log(
            "DEBUG",
            "collect",
            "log files discovered",
            input_digest={"log_dir": str(log_dir)},
            output_digest={"file_count": len(log_files)},
        )

        sessions = collect_sessions(log_files, logger)
        report = analyze_sessions(
            sessions=sessions,
            now_utc=now_utc,
            range_days=args.range_days,
            recent_days=args.recent_days,
            logger=logger,
        )
        report["run_id"] = run_id
        report["config"] = config

        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        html = render_report_html(report=report, run_id=run_id, config=config)
        html_path.write_text(html, encoding="utf-8")

        logger.log(
            "SUCCRSS",
            "render",
            "output files written",
            input_digest={
                "json_path": str(json_path),
                "html_path": str(html_path),
                "log_path": str(log_path),
            },
            output_digest={
                "json_size_bytes": json_path.stat().st_size,
                "html_size_bytes": html_path.stat().st_size,
                "log_size_bytes": log_path.stat().st_size,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.log(
            "ERROR",
            "fatal",
            str(exc),
            input_digest={"log_dir": str(log_dir), "output_dir": str(output_dir)},
            output_digest={"exception_type": type(exc).__name__},
            extra={"traceback": repr(exc)},
        )
        logger.close()
        if isinstance(exc, InsightsError):
            print(f"ERROR: {exc}", file=sys.stderr)
        else:
            print(f"ERROR: unexpected failure: {exc}", file=sys.stderr)
        return 1

    logger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
