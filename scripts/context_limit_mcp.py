#!/usr/bin/env python3
"""Minimal MCP server for Codex Usage."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from context_limit_status import build_status, default_codex_home, render_status


SERVER_NAME = "codex-usage"
SERVER_VERSION = "0.1.0"


def write_message(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def result(message_id: Any, payload: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": payload}


def error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def tool_schema() -> dict[str, Any]:
    return {
        "name": "codex_usage_status",
        "description": "Show latest Codex context occupancy and 5-hour/weekly rate-limit status from local token_count events.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "Optional Codex thread id. Defaults to CODEX_THREAD_ID or latest rollout session.",
                },
                "codex_home": {
                    "type": "string",
                    "description": "Optional Codex home directory. Defaults to CODEX_HOME or ~/.codex.",
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "text", "json"],
                    "default": "markdown",
                },
            },
            "additionalProperties": False,
        },
    }


def call_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    codex_home = Path(arguments.get("codex_home") or default_codex_home()).expanduser()
    thread_id = arguments.get("thread_id")
    output_format = arguments.get("format") or "markdown"
    status = build_status(codex_home, thread_id)
    text = render_status(status, output_format)
    return {"content": [{"type": "text", "text": text}]}


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")

    if method == "initialize":
        return result(
            message_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return result(message_id, {"tools": [tool_schema()]})
    if method == "tools/call":
        params = message.get("params") or {}
        if params.get("name") != "codex_usage_status":
            return error(message_id, -32602, f"Unknown tool: {params.get('name')}")
        try:
            return result(message_id, call_tool(params.get("arguments") or {}))
        except Exception as exc:  # MCP should return tool errors instead of crashing.
            return result(
                message_id,
                {
                    "isError": True,
                    "content": [{"type": "text", "text": f"{exc}\n\n{traceback.format_exc()}"}],
                },
            )

    if message_id is None:
        return None
    return error(message_id, -32601, f"Method not found: {method}")


def main() -> int:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            message = json.loads(raw_line)
            response = handle_request(message)
        except Exception as exc:
            response = error(None, -32700, str(exc))
        if response is not None:
            write_message(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
