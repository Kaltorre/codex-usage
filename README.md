# Codex Usage

Local Codex plugin for reading the latest context and rate-limit status from Codex rollout logs.

## What It Shows

- Current context occupancy from `last_token_usage.input_tokens / model_context_window`
- Remaining context tokens
- 5-hour rate-limit usage and reset time
- Weekly rate-limit usage and reset time
- Plan type and source session file

## Run Once

```powershell
python .\codex-usage\scripts\context_limit_status.py --format markdown
```

## Watch Continuously

```powershell
.\codex-usage\scripts\watch_context_limit.ps1
```

Use a custom refresh interval:

```powershell
.\codex-usage\scripts\watch_context_limit.ps1 --watch 15
```

## Floating Desktop Widget

Codex plugins do not currently expose a native always-visible panel or pet extension point. For a visible desktop surface, run the included always-on-top widget:

```powershell
.\codex-usage\Codex Usage.bat
```

or:

```powershell
.\codex-usage\scripts\start_context_limit_widget.ps1
```

By default it opens at the last saved widget position. If no saved position exists, it tries to open near the Codex pet/avatar overlay when Codex has saved that position. Other positions:

```powershell
.\codex-usage\scripts\start_context_limit_widget.ps1 --position top-right
.\codex-usage\scripts\start_context_limit_widget.ps1 --position bottom-right
.\codex-usage\scripts\start_context_limit_widget.ps1 --position custom --x 80 --y 80
```

Drag the widget with the mouse from any visible part of the widget. The position is saved after you release the mouse. Press `Esc` or click `x` to close it.

The header also includes scope/config controls:

- `THIS` / `ALL` switches between the current thread/latest session and active-project overview.
- `LEFT` / `USED` switches the metric direction.
- `1.2x` / `1x` / `.8x` cycles the widget scale and saves the choice.
- `CFG` opens project checkboxes for the `ALL` view. Unchecked projects are hidden and saved in `~/.codex/codex-usage-widget.json`.

`ALL` scans local Codex sessions from the last 24 hours by default and keeps the newest session per project directory. The widget grows vertically to fit visible projects, up to `--max-projects` entries (default `8`).

`5h` and `Week` are account-level limits, so they are read from the freshest `token_count` snapshot across local Codex sessions. Project rows still use each project's own latest context snapshot.

## MCP Tool

The plugin exposes one MCP tool:

- `codex_usage_status`

It returns the same status as the CLI in markdown, text, or JSON.

## Notes

Codex currently writes these values to local rollout JSONL as `token_count` events after model/tool activity. This plugin reads those events. It cannot add a native always-visible Codex status bar unless Codex exposes such a plugin UI surface in the future.
