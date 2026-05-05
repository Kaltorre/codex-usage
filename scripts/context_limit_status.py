#!/usr/bin/env python3
"""Report Codex context and rate-limit status from local rollout logs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REVERSE_READ_BYTES = 8 * 1024 * 1024
THREAD_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@dataclass
class StatusSource:
    codex_home: Path
    session_file: Path
    thread_id: str | None


class StatusError(RuntimeError):
    pass


def default_codex_home() -> Path:
    env_home = os.environ.get("CODEX_HOME")
    if env_home:
        return Path(env_home).expanduser()
    return Path.home() / ".codex"


def find_session_file(codex_home: Path, thread_id: str | None = None) -> Path:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.exists():
        raise StatusError(f"Codex sessions directory not found: {sessions_dir}")

    resolved_thread = thread_id or os.environ.get("CODEX_THREAD_ID")
    files: list[Path]
    if resolved_thread:
        files = list(sessions_dir.rglob(f"*{resolved_thread}.jsonl"))
        if not files:
            raise StatusError(f"No rollout session found for thread id: {resolved_thread}")
    else:
        files = list(sessions_dir.rglob("rollout-*.jsonl"))
        if not files:
            raise StatusError(f"No rollout sessions found under: {sessions_dir}")

    return max(files, key=lambda path: path.stat().st_mtime)


def read_recent_lines(path: Path, max_bytes: int = DEFAULT_REVERSE_READ_BYTES) -> list[str]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
            handle.readline()
        data = handle.read()
    return data.decode("utf-8", errors="replace").splitlines()


def latest_token_count_event(session_file: Path) -> dict[str, Any]:
    lines = read_recent_lines(session_file)
    for line in reversed(lines):
        if "token_count" not in line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = event.get("payload") or {}
        if payload.get("type") == "token_count":
            return event

    # Fallback to a full scan if the most recent log chunk did not contain the event.
    latest: dict[str, Any] | None = None
    with session_file.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "token_count" not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = event.get("payload") or {}
            if payload.get("type") == "token_count":
                latest = event
    if latest is None:
        raise StatusError(f"No token_count event found in: {session_file}")
    return latest


def thread_id_from_path(session_file: Path) -> str | None:
    matches = THREAD_ID_RE.findall(session_file.name)
    return matches[-1] if matches else None


def session_meta(session_file: Path) -> dict[str, Any]:
    try:
        with session_file.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index > 50:
                    break
                if "session_meta" not in line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "session_meta":
                    payload = event.get("payload")
                    return payload if isinstance(payload, dict) else {}
    except OSError:
        return {}
    return {}


def thread_name_from_index(codex_home: Path, thread_id: str | None) -> str | None:
    if not thread_id:
        return None
    index_path = codex_home / "session_index.jsonl"
    if not index_path.exists():
        return None
    found: str | None = None
    try:
        with index_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if thread_id not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("id") == thread_id:
                    found = row.get("thread_name") or found
    except OSError:
        return None
    return found


def unix_to_local(value: int | float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value)).astimezone().isoformat(timespec="seconds")


def event_timestamp_epoch(event: dict[str, Any], fallback: float = 0) -> float:
    timestamp = event.get("timestamp")
    if isinstance(timestamp, str) and timestamp:
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


def seconds_until(value: int | float | None) -> str | None:
    if value is None:
        return None
    delta = max(0, int(float(value) - time.time()))
    days, rem = divmod(delta, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def percent(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.1f}%"


def token_count(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,}".replace(",", " ")


def limit_summary(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    used = raw.get("used_percent")
    return {
        "used_percent": used,
        "remaining_percent": None if used is None else max(0.0, 100.0 - float(used)),
        "window_minutes": raw.get("window_minutes"),
        "resets_at": raw.get("resets_at"),
        "resets_at_local": unix_to_local(raw.get("resets_at")),
        "resets_in": seconds_until(raw.get("resets_at")),
    }


def rate_limit_summary(raw: dict[str, Any] | None) -> dict[str, Any]:
    rate_limits = raw or {}
    return {
        "limit_id": rate_limits.get("limit_id"),
        "plan_type": rate_limits.get("plan_type"),
        "primary_5h": limit_summary(rate_limits.get("primary")),
        "secondary_weekly": limit_summary(rate_limits.get("secondary")),
        "rate_limit_reached_type": rate_limits.get("rate_limit_reached_type"),
        "credits": rate_limits.get("credits"),
    }


def latest_global_token_count_event(codex_home: Path, max_files: int = 200) -> tuple[dict[str, Any], Path]:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.exists():
        raise StatusError(f"Codex sessions directory not found: {sessions_dir}")

    files = sorted(sessions_dir.rglob("rollout-*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    best_event: dict[str, Any] | None = None
    best_file: Path | None = None
    best_time = 0.0

    for session_file in files[:max_files]:
        try:
            event = latest_token_count_event(session_file)
        except (OSError, StatusError):
            continue
        event_time = event_timestamp_epoch(event, session_file.stat().st_mtime)
        if best_event is None or event_time > best_time:
            best_event = event
            best_file = session_file
            best_time = event_time

    if best_event is None or best_file is None:
        raise StatusError(f"No token_count event found under: {sessions_dir}")
    return best_event, best_file


def build_status_for_session(
    codex_home: Path,
    session_file: Path,
    requested_thread_id: str | None = None,
    selection: str = "latest session",
    rate_limit_snapshot: tuple[dict[str, Any], Path] | None = None,
) -> dict[str, Any]:
    event = latest_token_count_event(session_file)
    meta = session_meta(session_file)
    resolved_thread_id = requested_thread_id or meta.get("id") or thread_id_from_path(session_file)
    cwd = meta.get("cwd")
    cwd_path = Path(cwd) if isinstance(cwd, str) and cwd else None
    payload = event.get("payload") or {}
    info = payload.get("info") or {}
    if rate_limit_snapshot is None:
        try:
            rate_event, rate_session_file = latest_global_token_count_event(codex_home)
        except StatusError:
            rate_event, rate_session_file = event, session_file
    else:
        rate_event, rate_session_file = rate_limit_snapshot
    rate_payload = rate_event.get("payload") or {}
    rate_limits = rate_payload.get("rate_limits") or {}

    last_usage = info.get("last_token_usage") or {}
    total_usage = info.get("total_token_usage") or {}
    window = info.get("model_context_window")
    input_tokens = last_usage.get("input_tokens")
    context_used_percent = None
    context_remaining_tokens = None
    if isinstance(window, int) and window > 0 and isinstance(input_tokens, int):
        context_used_percent = input_tokens / window * 100
        context_remaining_tokens = max(0, window - input_tokens)

    return {
        "status_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "event_timestamp": event.get("timestamp"),
        "source": {
            "codex_home": str(codex_home),
            "session_file": str(session_file),
            "thread_id": resolved_thread_id,
            "thread_name": thread_name_from_index(codex_home, resolved_thread_id),
            "cwd": cwd,
            "project_name": cwd_path.name if cwd_path else None,
            "selection": selection,
            "session_mtime": session_file.stat().st_mtime,
            "session_mtime_local": datetime.fromtimestamp(session_file.stat().st_mtime).astimezone().isoformat(
                timespec="seconds"
            ),
        },
        "context": {
            "used_percent": context_used_percent,
            "input_tokens": input_tokens,
            "remaining_tokens": context_remaining_tokens,
            "model_context_window": window,
            "last_total_tokens": last_usage.get("total_tokens"),
            "last_output_tokens": last_usage.get("output_tokens"),
            "last_reasoning_output_tokens": last_usage.get("reasoning_output_tokens"),
        },
        "rate_limits": rate_limit_summary(rate_limits),
        "rate_limit_source": {
            "session_file": str(rate_session_file),
            "event_timestamp": rate_event.get("timestamp"),
            "session_mtime": rate_session_file.stat().st_mtime,
            "session_mtime_local": datetime.fromtimestamp(rate_session_file.stat().st_mtime).astimezone().isoformat(
                timespec="seconds"
            ),
            "thread_id": thread_id_from_path(rate_session_file),
        },
        "usage_totals": total_usage,
    }


def build_status(codex_home: Path, thread_id: str | None = None) -> dict[str, Any]:
    env_thread_id = os.environ.get("CODEX_THREAD_ID")
    requested_thread_id = thread_id or env_thread_id
    session_file = find_session_file(codex_home, requested_thread_id)
    selection = "current thread" if requested_thread_id else "latest session"
    return build_status_for_session(codex_home, session_file, requested_thread_id, selection)


def list_project_statuses(codex_home: Path, hours: float = 24, limit: int = 20) -> list[dict[str, Any]]:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.exists():
        raise StatusError(f"Codex sessions directory not found: {sessions_dir}")

    cutoff = time.time() - (hours * 3600)
    files = sorted(sessions_dir.rglob("rollout-*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    statuses_by_cwd: dict[str, dict[str, Any]] = {}
    try:
        rate_limit_snapshot = latest_global_token_count_event(codex_home)
    except StatusError:
        rate_limit_snapshot = None

    for session_file in files:
        if session_file.stat().st_mtime < cutoff:
            continue
        try:
            status = build_status_for_session(
                codex_home,
                session_file,
                selection="active project",
                rate_limit_snapshot=rate_limit_snapshot,
            )
        except StatusError:
            continue
        source = status.get("source") or {}
        cwd = source.get("cwd") or str(session_file)
        if cwd in statuses_by_cwd:
            continue
        statuses_by_cwd[cwd] = status
        if len(statuses_by_cwd) >= limit:
            break

    return sorted(
        statuses_by_cwd.values(),
        key=lambda status: (status.get("source") or {}).get("session_mtime") or 0,
        reverse=True,
    )


def format_markdown(status: dict[str, Any]) -> str:
    context = status["context"]
    rate = status["rate_limits"]
    primary = rate.get("primary_5h") or {}
    secondary = rate.get("secondary_weekly") or {}

    lines = [
        "# Codex usage status",
        "",
        f"- Context: {percent(context.get('used_percent'))} used "
        f"({token_count(context.get('input_tokens'))} / {token_count(context.get('model_context_window'))} input tokens)",
        f"- Context remaining: {token_count(context.get('remaining_tokens'))} tokens",
        f"- 5h limit: {percent(primary.get('used_percent'))} used, "
        f"{percent(primary.get('remaining_percent'))} available, resets in {primary.get('resets_in') or 'n/a'}",
        f"- Weekly limit: {percent(secondary.get('used_percent'))} used, "
        f"{percent(secondary.get('remaining_percent'))} available, resets in {secondary.get('resets_in') or 'n/a'}",
        f"- Plan: {rate.get('plan_type') or 'n/a'}",
        f"- Source event: {status.get('event_timestamp') or 'n/a'}",
        "",
        "| Window | Used | Available | Reset |",
        "| --- | ---: | ---: | --- |",
        f"| 5h | {percent(primary.get('used_percent'))} | {percent(primary.get('remaining_percent'))} | {primary.get('resets_at_local') or 'n/a'} |",
        f"| Weekly | {percent(secondary.get('used_percent'))} | {percent(secondary.get('remaining_percent'))} | {secondary.get('resets_at_local') or 'n/a'} |",
    ]
    return "\n".join(lines)


def format_text(status: dict[str, Any]) -> str:
    context = status["context"]
    rate = status["rate_limits"]
    primary = rate.get("primary_5h") or {}
    secondary = rate.get("secondary_weekly") or {}
    return "\n".join(
        [
            "Codex usage status",
            f"Context: {percent(context.get('used_percent'))} "
            f"({token_count(context.get('input_tokens'))}/{token_count(context.get('model_context_window'))} input tokens)",
            f"Context remaining: {token_count(context.get('remaining_tokens'))} tokens",
            f"5h limit: {percent(primary.get('used_percent'))} used, "
            f"{percent(primary.get('remaining_percent'))} available, resets in {primary.get('resets_in') or 'n/a'}",
            f"Weekly limit: {percent(secondary.get('used_percent'))} used, "
            f"{percent(secondary.get('remaining_percent'))} available, resets in {secondary.get('resets_in') or 'n/a'}",
            f"Plan: {rate.get('plan_type') or 'n/a'}",
            f"Source: {status['source']['session_file']}",
        ]
    )


def render_status(status: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(status, indent=2, ensure_ascii=False)
    if output_format == "markdown":
        return format_markdown(status)
    return format_text(status)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=default_codex_home())
    parser.add_argument("--thread-id", default=os.environ.get("CODEX_THREAD_ID"))
    parser.add_argument("--format", choices=["text", "markdown", "json"], default="text")
    parser.add_argument("--watch", type=float, default=0, help="Refresh every N seconds.")
    parser.add_argument("--no-clear", action="store_true", help="Do not clear the terminal in watch mode.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    codex_home = args.codex_home.expanduser()

    while True:
        try:
            status = build_status(codex_home, args.thread_id)
            output = render_status(status, args.format)
        except StatusError as exc:
            output = f"Codex Usage error: {exc}"

        if args.watch and not args.no_clear:
            os.system("cls" if os.name == "nt" else "clear")
        print(output)

        if not args.watch:
            return 0
        time.sleep(max(1.0, args.watch))


if __name__ == "__main__":
    raise SystemExit(main())
