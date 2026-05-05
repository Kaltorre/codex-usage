---
name: codex-usage
description: Show current Codex context occupancy, remaining context tokens, and 5-hour/weekly rate-limit availability from local Codex token_count events. Use when the user asks about context usage, token window, 5h limit, weekly limit, rate limits, remaining usage, or ongoing Codex usage status.
---

# Codex Usage

Use this skill when the user asks for Codex context, token, or limit status.

## Workflow

1. Prefer the MCP tool `codex_usage_status` when it is available.
2. If the MCP tool is not available, run the local CLI:

```powershell
python .\codex-usage\scripts\context_limit_status.py --format markdown
```

3. Report the current context percent, context tokens remaining, 5-hour limit usage/availability, weekly limit usage/availability, and reset times.

## Continuous Monitoring

For a terminal watcher, run:

```powershell
.\codex-usage\scripts\watch_context_limit.ps1
```

The watcher refreshes every 5 seconds by default. Pass script arguments through to the Python CLI when needed, for example:

```powershell
.\codex-usage\scripts\watch_context_limit.ps1 --watch 15
```

For an always-on-top desktop widget, run:

```powershell
.\codex-usage\Codex Usage.bat
```

or:

```powershell
.\codex-usage\scripts\start_context_limit_widget.ps1
```

The widget opens at the last saved position by default. If no saved position exists, it tries to open near the Codex pet/avatar overlay. It can be dragged from any visible part of the widget and saves its position on mouse release.

Header controls:

- `LEFT` / `USED`: switch between remaining and used values.
- `THIS` / `ALL`: switch between the current thread/latest session and active-project overview.
- `1.2x` / `1x` / `.8x`: cycle the widget scale and save the choice.
- `CFG`: open project checkboxes for the `ALL` view. Hidden projects are saved in `~/.codex/codex-usage-widget.json`.

Use `--position top-left`, `--position top-right`, `--position bottom-left`, `--position bottom-right`, or `--position custom --x 80 --y 80` when needed. Use `--active-hours 48` to change how far back `ALL` scans, and `--max-projects 12` to show more project rows.

Account-level `5h` and weekly limits should be read from the freshest `token_count` snapshot across all local Codex sessions. Project context rows should continue to use the selected/current project's own latest context snapshot.

## Data Source

The plugin reads the latest local Codex rollout JSONL file under `~/.codex/sessions` and extracts the newest `token_count` event. Context occupancy is computed as `last_token_usage.input_tokens / model_context_window`. The 5-hour and weekly values come from `rate_limits.primary` and `rate_limits.secondary`.

## Limitation

This plugin does not create a native always-visible Codex status bar. Current Codex plugin manifests expose skills and MCP tools, but not an always-on UI surface or pet extension point. The desktop widget, CLI watcher, and MCP tool are the live surfaces this plugin can provide from local data.
