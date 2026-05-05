#!/usr/bin/env python3
"""Small always-on-top desktop widget for Codex usage status."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tkinter as tk
from pathlib import Path
from typing import Any

from context_limit_status import StatusError, build_status, default_codex_home, list_project_statuses, percent


BG = "#111827"
PANEL = "#172033"
TEXT = "#E5E7EB"
MUTED = "#9CA3AF"
GREEN = "#14B8A6"
YELLOW = "#F59E0B"
RED = "#EF4444"
BAR_BG = "#263244"
CORNER_MARGIN = 24
MIN_WIDGET_HEIGHT = 182
ROW_HEIGHT = 23
HEIGHT_CHROME = 110
SCALE_LEVELS = (1.0, 0.8, 1.2)


def short_tokens(value: int | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(value)


def compact_text(value: str | None, max_len: int) -> str:
    if not value:
        return "n/a"
    if len(value) <= max_len:
        return value
    return value[: max(1, max_len - 1)] + "…"


def color_for(value: float | None) -> str:
    if value is None:
        return MUTED
    if value >= 85:
        return RED
    if value >= 65:
        return YELLOW
    return GREEN


def color_for_remaining(value: float | None) -> str:
    if value is None:
        return MUTED
    if value <= 15:
        return RED
    if value <= 35:
        return YELLOW
    return GREEN


def load_pet_position(codex_home: Path, width: int, height: int) -> tuple[int, int] | None:
    state_path = codex_home / ".codex-global-state.json"
    if not state_path.exists():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    bounds = state.get("electron-avatar-overlay-bounds")
    if not isinstance(bounds, dict):
        persisted = state.get("electron-persisted-atom-state") or {}
        bounds = persisted.get("electron-avatar-overlay-bounds")
    if not isinstance(bounds, dict):
        return None

    try:
        x = int(bounds.get("x", 20))
        y = int(bounds.get("y", 20))
        overlay_width = int(bounds.get("width", 0))
        overlay_height = int(bounds.get("height", 0))
    except (TypeError, ValueError):
        return None

    if overlay_width:
        x = x + overlay_width - width
    if overlay_height:
        y = y + overlay_height + 8
    return x, y


def saved_position_path(codex_home: Path) -> Path:
    return codex_home / "codex-usage-widget.json"


def legacy_saved_position_path(codex_home: Path) -> Path:
    return codex_home / "context-limit-monitor-widget.json"


def load_widget_settings(codex_home: Path) -> dict[str, Any]:
    path = saved_position_path(codex_home)
    if not path.exists():
        path = legacy_saved_position_path(codex_home)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_widget_settings(codex_home: Path, updates: dict[str, Any]) -> None:
    payload = load_widget_settings(codex_home)
    payload.update(updates)
    try:
        saved_position_path(codex_home).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def load_saved_position(codex_home: Path) -> tuple[int, int] | None:
    payload = load_widget_settings(codex_home)
    try:
        return int(payload["x"]), int(payload["y"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_position(codex_home: Path, x: int, y: int) -> None:
    save_widget_settings(codex_home, {"x": x, "y": y})


def load_display_mode(codex_home: Path) -> str:
    mode = load_widget_settings(codex_home).get("display_mode")
    return mode if mode in {"remaining", "used"} else "remaining"


def save_display_mode(codex_home: Path, mode: str) -> None:
    save_widget_settings(codex_home, {"display_mode": mode})


def load_scope_mode(codex_home: Path) -> str:
    mode = load_widget_settings(codex_home).get("scope_mode")
    return mode if mode in {"this", "all"} else "this"


def save_scope_mode(codex_home: Path, mode: str) -> None:
    save_widget_settings(codex_home, {"scope_mode": mode})


def disabled_cwds(codex_home: Path) -> set[str]:
    raw = load_widget_settings(codex_home).get("disabled_cwds", [])
    if not isinstance(raw, list):
        return set()
    return {item for item in raw if isinstance(item, str)}


def save_disabled_cwds(codex_home: Path, values: set[str]) -> None:
    save_widget_settings(codex_home, {"disabled_cwds": sorted(values)})


def normalize_scale(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 1.0
    return min(SCALE_LEVELS, key=lambda candidate: abs(candidate - numeric))


def format_scale(value: float) -> str:
    if value == 1.2:
        return "1.2x"
    if value == 1.0:
        return "1x"
    return ".8x"


def load_widget_scale(codex_home: Path) -> float:
    return normalize_scale(load_widget_settings(codex_home).get("scale", 1.0))


def save_widget_scale(codex_home: Path, value: float) -> None:
    save_widget_settings(codex_home, {"scale": normalize_scale(value)})


def next_scale(value: float) -> float:
    scale = normalize_scale(value)
    index = SCALE_LEVELS.index(scale)
    return SCALE_LEVELS[(index + 1) % len(SCALE_LEVELS)]


class UsageWidget:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.codex_home = args.codex_home.expanduser()
        self.root = tk.Tk()
        self.root.title("Codex usage")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", args.alpha)
        if not args.decorated:
            self.root.overrideredirect(True)

        self.scale = normalize_scale(args.scale) if args.scale is not None else load_widget_scale(self.codex_home)
        self.width = self.scaled(args.width, min_value=260)
        self.height = self.scaled(args.height, min_value=90)
        self.display_mode = load_display_mode(self.codex_home)
        self.scope_mode = load_scope_mode(self.codex_home)
        args.max_projects = max(3, args.max_projects)
        self.refresh_after_id: str | None = None
        self.base_row_keys = ["context", "primary", "secondary"]
        self.global_row_keys = ["primary", "secondary"]
        self.project_row_keys = ["context"] + [f"project_{index}" for index in range(args.max_projects - 1)]
        self.all_row_keys = self.global_row_keys + self.project_row_keys
        self.drag_start: tuple[int, int] | None = None
        self.status_vars = {
            "context": tk.StringVar(value="Context: loading"),
            "context_reset": tk.StringVar(value=""),
            "context_pct": tk.StringVar(value="n/a"),
            "primary": tk.StringVar(value="5h: loading"),
            "primary_reset": tk.StringVar(value=""),
            "primary_pct": tk.StringVar(value="n/a"),
            "secondary": tk.StringVar(value="Week: loading"),
            "secondary_reset": tk.StringVar(value=""),
            "secondary_pct": tk.StringVar(value="n/a"),
            "source": tk.StringVar(value="Waiting for token_count"),
            "mode": tk.StringVar(value="LEFT" if self.display_mode == "remaining" else "USED"),
            "scope": tk.StringVar(value="THIS" if self.scope_mode == "this" else "ALL"),
            "scale": tk.StringVar(value=format_scale(self.scale)),
        }
        for key in self.all_row_keys:
            self.status_vars.setdefault(key, tk.StringVar(value=""))
            self.status_vars.setdefault(f"{key}_reset", tk.StringVar(value=""))
            self.status_vars.setdefault(f"{key}_pct", tk.StringVar(value=""))

        self._build()
        self._position()
        self._bind()
        self.refresh()

    def scaled(self, value: int | float, min_value: int = 1) -> int:
        return max(min_value, int(round(float(value) * self.scale)))

    def ui_font(self, size: int, weight: str | None = None, family: str = "Segoe UI") -> tuple[str, int] | tuple[str, int, str]:
        scaled_size = max(5, int(round(size * self.scale)))
        if weight:
            return family, scaled_size, weight
        return family, scaled_size

    def _build(self) -> None:
        self.frame = tk.Frame(self.root, bg=PANEL, bd=0, highlightthickness=1, highlightbackground="#334155")
        self.frame.pack(fill="both", expand=True)

        header = tk.Frame(self.frame, bg=PANEL)
        header.pack(fill="x", padx=self.scaled(8), pady=(self.scaled(6), self.scaled(3)))
        tk.Label(header, text="Codex Usage", fg=TEXT, bg=PANEL, font=self.ui_font(9, "bold")).pack(side="left")

        close = tk.Label(header, text="x", fg=MUTED, bg=PANEL, font=self.ui_font(9, "bold"), cursor="hand2")
        close.pack(side="right", padx=(self.scaled(5), 0))
        close.bind("<Button-1>", lambda _event: self.root.destroy())

        scale_button = tk.Label(
            header,
            textvariable=self.status_vars["scale"],
            fg=MUTED,
            bg="#223044",
            font=self.ui_font(7, "bold"),
            width=4,
            padx=self.scaled(2),
            pady=0,
            cursor="hand2",
        )
        scale_button.pack(side="right", padx=(0, self.scaled(4)))
        scale_button.bind("<Button-1>", self.cycle_scale)

        mode_button = tk.Label(
            header,
            textvariable=self.status_vars["mode"],
            fg=TEXT,
            bg="#0F766E",
            font=self.ui_font(7, "bold"),
            width=4,
            padx=self.scaled(3),
            pady=0,
            cursor="hand2",
        )
        mode_button.pack(side="right", padx=(0, self.scaled(5)))
        mode_button.bind("<Button-1>", self.toggle_display_mode)

        scope_button = tk.Label(
            header,
            textvariable=self.status_vars["scope"],
            fg=TEXT,
            bg="#374151",
            font=self.ui_font(7, "bold"),
            width=4,
            padx=self.scaled(3),
            pady=0,
            cursor="hand2",
        )
        scope_button.pack(side="right", padx=(0, self.scaled(4)))
        scope_button.bind("<Button-1>", self.toggle_scope_mode)

        config_button = tk.Label(
            header,
            text="CFG",
            fg=MUTED,
            bg="#223044",
            font=self.ui_font(7, "bold"),
            width=3,
            padx=self.scaled(3),
            pady=0,
            cursor="hand2",
        )
        config_button.pack(side="right", padx=(0, self.scaled(4)))
        config_button.bind("<Button-1>", self.open_config)

        self.rows: dict[str, tk.Canvas] = {}
        self.row_frames: dict[str, tk.Frame] = {}
        self._row_header()
        self._row("context", self.status_vars["context"], self.status_vars["context_reset"], self.status_vars["context_pct"])
        self._row("primary", self.status_vars["primary"], self.status_vars["primary_reset"], self.status_vars["primary_pct"])
        self._row("secondary", self.status_vars["secondary"], self.status_vars["secondary_reset"], self.status_vars["secondary_pct"])
        self.projects_separator = tk.Frame(self.frame, bg=PANEL)
        separator_line = tk.Frame(self.projects_separator, bg="#334155", height=1)
        separator_line.pack(fill="x", pady=(8, 3))
        tk.Label(
            self.projects_separator,
            text="projects",
            fg=MUTED,
            bg=PANEL,
            font=self.ui_font(7),
            anchor="w",
        ).pack(fill="x")
        for key in self.all_row_keys[3:]:
            self._row(key, self.status_vars[key], self.status_vars[f"{key}_reset"], self.status_vars[f"{key}_pct"], visible=False)
        self.projects_separator.pack_forget()

        self.source_label = tk.Label(
            self.frame,
            textvariable=self.status_vars["source"],
            fg="#64748B",
            bg=PANEL,
            font=self.ui_font(7),
            anchor="w",
        )
        self.source_label.pack(fill="x", padx=self.scaled(8), pady=(self.scaled(8), self.scaled(14)))

    def _row_header(self) -> None:
        row = tk.Frame(self.frame, bg=PANEL)
        row.pack(fill="x", padx=self.scaled(8), pady=(self.scaled(4), 0))
        row.grid_columnconfigure(2, weight=1)

        tk.Label(row, text="", fg=MUTED, bg=PANEL, font=self.ui_font(7), width=8).grid(row=0, column=0)
        tk.Label(row, text="info", fg=MUTED, bg=PANEL, font=self.ui_font(7), anchor="e", width=12).grid(
            row=0, column=1, sticky="e", padx=(0, self.scaled(6))
        )
        tk.Label(row, text="", fg=MUTED, bg=PANEL, font=self.ui_font(7)).grid(row=0, column=2, sticky="ew")
        tk.Label(row, text="%", fg=MUTED, bg=PANEL, font=self.ui_font(7), anchor="e", width=7).grid(
            row=0, column=3, sticky="e"
        )

    def _row(
        self,
        key: str,
        label_var: tk.StringVar,
        reset_var: tk.StringVar,
        pct_var: tk.StringVar,
        visible: bool = True,
    ) -> None:
        row = tk.Frame(self.frame, bg=PANEL)
        if visible:
            row.pack(fill="x", padx=self.scaled(8), pady=(self.scaled(5), 0))
        row.grid_columnconfigure(2, weight=1)

        label = tk.Label(row, textvariable=label_var, fg=TEXT, bg=PANEL, font=self.ui_font(8), anchor="w", width=8)
        label.grid(row=0, column=0, sticky="w")

        reset = tk.Label(
            row,
            textvariable=reset_var,
            fg=MUTED,
            bg=PANEL,
            font=self.ui_font(8, family="Consolas"),
            anchor="e",
            width=12,
        )
        reset.grid(row=0, column=1, sticky="e", padx=(0, self.scaled(6)))

        canvas = tk.Canvas(row, width=1, height=self.scaled(6, min_value=3), bg=PANEL, bd=0, highlightthickness=0)
        canvas.grid(row=0, column=2, sticky="ew", padx=(0, self.scaled(6)))

        pct = tk.Label(
            row,
            textvariable=pct_var,
            fg=TEXT,
            bg=PANEL,
            font=self.ui_font(8, family="Consolas"),
            anchor="e",
            width=7,
        )
        pct.grid(row=0, column=3, sticky="e")

        self.rows[key] = canvas
        self.row_frames[key] = row

    def show_row(self, key: str) -> None:
        frame = self.row_frames[key]
        if frame.winfo_manager():
            return
        before = getattr(self, "source_label", None)
        if before is not None:
            frame.pack(fill="x", padx=self.scaled(8), pady=(self.scaled(5), 0), before=before)
        else:
            frame.pack(fill="x", padx=self.scaled(8), pady=(self.scaled(5), 0))

    def hide_row(self, key: str) -> None:
        frame = self.row_frames[key]
        if frame.winfo_manager():
            frame.pack_forget()

    def show_projects_separator(self) -> None:
        if self.projects_separator.winfo_manager():
            return
        before_key = self.project_row_keys[0]
        before = self.row_frames.get(before_key)
        if before is not None and before.winfo_manager():
            self.projects_separator.pack(fill="x", padx=self.scaled(8), before=before)
        else:
            self.projects_separator.pack(fill="x", padx=self.scaled(8), before=self.source_label)

    def hide_projects_separator(self) -> None:
        if self.projects_separator.winfo_manager():
            self.projects_separator.pack_forget()

    def resize_for_rows(self, row_count: int) -> None:
        separator_extra = self.scaled(22) if self.projects_separator.winfo_manager() else 0
        height = max(
            self.scaled(MIN_WIDGET_HEIGHT, min_value=90),
            self.scaled(HEIGHT_CHROME, min_value=55) + separator_extra + (row_count * self.scaled(ROW_HEIGHT, min_value=12)),
        )
        width = self.width
        self.root.geometry(f"{width}x{height}+{self.root.winfo_x()}+{self.root.winfo_y()}")

    def _position(self) -> None:
        self.root.update_idletasks()
        x = self.args.x
        y = self.args.y
        if self.args.position == "saved":
            saved_position = load_saved_position(self.codex_home)
            if saved_position:
                x, y = saved_position
            else:
                pet_position = load_pet_position(self.codex_home, self.width, self.height)
                if pet_position:
                    x, y = pet_position
        elif self.args.position == "pet":
            pet_position = load_pet_position(self.codex_home, self.width, self.height)
            if pet_position:
                x, y = pet_position
        elif self.args.position in {"top-left", "top-right", "bottom-left", "bottom-right"}:
            x, y = self.coordinates_for_position(self.args.position)

        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def coordinates_for_position(self, position: str) -> tuple[int, int]:
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        if position == "top-left":
            return CORNER_MARGIN, CORNER_MARGIN
        if position == "top-right":
            return screen_width - self.width - CORNER_MARGIN, CORNER_MARGIN
        if position == "bottom-left":
            return CORNER_MARGIN, screen_height - self.height - (CORNER_MARGIN * 2)
        if position == "bottom-right":
            return screen_width - self.width - CORNER_MARGIN, screen_height - self.height - (CORNER_MARGIN * 2)
        return self.root.winfo_x(), self.root.winfo_y()

    def move_to_position(self, position: str) -> str:
        x, y = self.coordinates_for_position(position)
        self.root.geometry(f"+{x}+{y}")
        save_position(self.codex_home, x, y)
        return "break"

    def toggle_display_mode(self, _event: tk.Event | None = None) -> str:
        self.display_mode = "used" if self.display_mode == "remaining" else "remaining"
        self.status_vars["mode"].set("LEFT" if self.display_mode == "remaining" else "USED")
        save_display_mode(self.codex_home, self.display_mode)
        self.refresh()
        return "break"

    def toggle_scope_mode(self, _event: tk.Event | None = None) -> str:
        self.scope_mode = "all" if self.scope_mode == "this" else "this"
        self.status_vars["scope"].set("THIS" if self.scope_mode == "this" else "ALL")
        save_scope_mode(self.codex_home, self.scope_mode)
        self.refresh()
        return "break"

    def cycle_scale(self, _event: tk.Event | None = None) -> str:
        self.scale = next_scale(self.scale)
        save_widget_scale(self.codex_home, self.scale)
        self.status_vars["scale"].set(format_scale(self.scale))
        save_position(self.codex_home, self.root.winfo_x(), self.root.winfo_y())
        self.width = self.scaled(self.args.width, min_value=260)
        self.height = self.scaled(self.args.height, min_value=90)
        if self.refresh_after_id is not None:
            try:
                self.root.after_cancel(self.refresh_after_id)
            except tk.TclError:
                pass
            self.refresh_after_id = None
        self.frame.destroy()
        self._build()
        self._bind_drag(self.frame)
        self.root.geometry(f"{self.width}x{self.height}+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self.refresh()
        return "break"

    def open_config(self, _event: tk.Event | None = None) -> str:
        try:
            statuses = list_project_statuses(self.codex_home, hours=self.args.active_hours, limit=50)
        except StatusError:
            statuses = []

        window = tk.Toplevel(self.root)
        window.title("Context projects")
        window.configure(bg=PANEL)
        window.attributes("-topmost", True)
        window.geometry("520x360")

        tk.Label(
            window,
            text=f"Projects active in last {int(self.args.active_hours)}h",
            fg=TEXT,
            bg=PANEL,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 6))

        body = tk.Frame(window, bg=PANEL)
        body.pack(fill="both", expand=True, padx=12)

        disabled = disabled_cwds(self.codex_home)
        variables: dict[str, tk.BooleanVar] = {}

        if not statuses:
            tk.Label(body, text="No active Codex project sessions found.", fg=MUTED, bg=PANEL).pack(anchor="w")

        for status in statuses:
            source = status.get("source") or {}
            cwd = source.get("cwd") or source.get("session_file") or ""
            if not cwd:
                continue
            project = source.get("project_name") or Path(cwd).name or "project?"
            thread = compact_text(source.get("thread_name"), 42)
            var = tk.BooleanVar(value=cwd not in disabled)
            variables[cwd] = var
            checkbox = tk.Checkbutton(
                body,
                variable=var,
                text=f"{project}  ·  {thread}",
                fg=TEXT,
                bg=PANEL,
                activeforeground=TEXT,
                activebackground=PANEL,
                selectcolor=BG,
                anchor="w",
                font=("Segoe UI", 8),
            )
            checkbox.pack(fill="x", anchor="w")

        actions = tk.Frame(window, bg=PANEL)
        actions.pack(fill="x", padx=12, pady=10)

        def apply() -> None:
            next_disabled = {cwd for cwd, var in variables.items() if not var.get()}
            save_disabled_cwds(self.codex_home, next_disabled)
            window.destroy()
            self.refresh()

        tk.Button(actions, text="Apply", command=apply).pack(side="right")
        tk.Button(actions, text="Cancel", command=window.destroy).pack(side="right", padx=(0, 8))
        return "break"

    def _bind(self) -> None:
        self.root.bind("<Escape>", lambda _event: self.root.destroy())
        self._bind_drag(self.root)
        self._bind_drag(self.frame)

    def _bind_drag(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._start_drag, add="+")
        widget.bind("<B1-Motion>", self._drag, add="+")
        widget.bind("<ButtonRelease-1>", self._end_drag, add="+")
        for child in widget.winfo_children():
            self._bind_drag(child)

    def _start_drag(self, event: tk.Event) -> None:
        self.drag_start = (event.x, event.y)

    def _drag(self, event: tk.Event) -> None:
        if self.drag_start is None:
            return
        x = self.root.winfo_x() + event.x - self.drag_start[0]
        y = self.root.winfo_y() + event.y - self.drag_start[1]
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, _event: tk.Event) -> None:
        self.drag_start = None
        save_position(self.codex_home, self.root.winfo_x(), self.root.winfo_y())

    def set_bar(self, key: str, value: float | None, remaining_mode: bool = False) -> None:
        canvas = self.rows[key]
        canvas.delete("all")
        width = max(1, canvas.winfo_width() or self.width - 110)
        bar_height = self.scaled(6, min_value=3)
        canvas.configure(height=bar_height)
        canvas.create_rectangle(0, 0, width, bar_height, fill=BAR_BG, width=0)
        if value is None:
            return
        fill_width = int(width * max(0, min(100, value)) / 100)
        fill = color_for_remaining(value) if remaining_mode else color_for(value)
        canvas.create_rectangle(0, 0, fill_width, bar_height, fill=fill, width=0)

    def clear_row(self, key: str) -> None:
        self.status_vars[key].set("")
        self.status_vars[f"{key}_reset"].set("")
        self.status_vars[f"{key}_pct"].set("")
        self.set_bar(key, None)

    def refresh_all_scope(self) -> None:
        statuses = list_project_statuses(self.codex_home, hours=self.args.active_hours, limit=50)
        disabled = disabled_cwds(self.codex_home)
        visible = [status for status in statuses if ((status.get("source") or {}).get("cwd") or "") not in disabled]
        project_row_keys = self.project_row_keys

        for key in self.all_row_keys:
            self.clear_row(key)
            self.hide_row(key)
        self.hide_projects_separator()

        global_status = visible[0] if visible else (statuses[0] if statuses else None)
        shown_globals = 0
        if global_status:
            limits = global_status.get("rate_limits") or {}
            primary = limits.get("primary_5h") or {}
            secondary = limits.get("secondary_weekly") or {}
            if self.display_mode == "remaining":
                primary_value = primary.get("remaining_percent")
                secondary_value = secondary.get("remaining_percent")
                remaining_mode = True
            else:
                primary_value = primary.get("used_percent")
                secondary_value = secondary.get("used_percent")
                remaining_mode = False

            self.show_row("primary")
            self.status_vars["primary"].set("5h")
            self.status_vars["primary_reset"].set(primary.get("resets_in") or "n/a")
            self.status_vars["primary_pct"].set(percent(primary_value))
            self.set_bar("primary", primary_value, remaining_mode=remaining_mode)

            self.show_row("secondary")
            self.status_vars["secondary"].set("Week")
            self.status_vars["secondary_reset"].set(secondary.get("resets_in") or "n/a")
            self.status_vars["secondary_pct"].set(percent(secondary_value))
            self.set_bar("secondary", secondary_value, remaining_mode=remaining_mode)
            shown_globals = 2

        for key, status in zip(project_row_keys, visible):
            self.show_row(key)
            source = status.get("source") or {}
            context = status.get("context") or {}
            project = compact_text(source.get("project_name") or "project?", 8)
            window = context.get("model_context_window")
            used_tokens = context.get("input_tokens")
            remaining_tokens = context.get("remaining_tokens")
            used_percent = context.get("used_percent")
            remaining_percent = None
            if isinstance(remaining_tokens, int) and isinstance(window, int) and window > 0:
                remaining_percent = remaining_tokens / window * 100

            if self.display_mode == "remaining":
                info = f"{short_tokens(remaining_tokens)}/{short_tokens(window)}"
                pct = remaining_percent
                self.set_bar(key, remaining_percent, remaining_mode=True)
            else:
                info = f"{short_tokens(used_tokens)}/{short_tokens(window)}"
                pct = used_percent
                self.set_bar(key, used_percent)

            self.status_vars[key].set(project)
            self.status_vars[f"{key}_reset"].set(info)
            self.status_vars[f"{key}_pct"].set(percent(pct))
        if visible:
            self.show_projects_separator()

        if not statuses:
            self.show_row("context")
            self.status_vars["context"].set("No data")
            self.status_vars["source"].set(f"ALL · no token_count sessions in last {int(self.args.active_hours)}h")
            self.resize_for_rows(1)
            return

        if not visible:
            self.show_row("context")
            self.status_vars["context"].set("Hidden")
            self.status_vars["source"].set(f"ALL projects · all {len(statuses)} hidden by CFG")
            self.resize_for_rows(max(1, shown_globals + 1))
            return

        shown = min(len(visible), len(project_row_keys))
        suffix = "" if len(visible) <= len(project_row_keys) else f" · projects {shown}/{len(visible)}"
        filtered = "" if len(visible) == len(statuses) else f" · {len(statuses) - len(visible)} hidden"
        self.status_vars["source"].set(f"ALL projects · {int(self.args.active_hours)}h{suffix}{filtered} · CFG filters")
        self.resize_for_rows(max(1, shown_globals + shown))

    def refresh(self) -> None:
        if self.scope_mode == "all":
            try:
                self.refresh_all_scope()
            except StatusError as exc:
                for key in self.all_row_keys:
                    self.clear_row(key)
                    self.hide_row(key)
                self.hide_projects_separator()
                self.show_row("context")
                self.status_vars["context"].set("ALL n/a")
                self.status_vars["context_reset"].set("")
                self.status_vars["context_pct"].set("n/a")
                self.status_vars["source"].set(str(exc))
                self.resize_for_rows(1)
            self.schedule_refresh()
            return

        try:
            for key in self.base_row_keys:
                self.show_row(key)
            for key in self.all_row_keys[3:]:
                self.clear_row(key)
                self.hide_row(key)
            self.hide_projects_separator()
            self.resize_for_rows(3)
            status = build_status(self.codex_home, self.args.thread_id)
            source = status.get("source") or {}
            context = status["context"]
            limits = status["rate_limits"]
            primary = limits.get("primary_5h") or {}
            secondary = limits.get("secondary_weekly") or {}

            context_used = context.get("used_percent")
            primary_used = primary.get("used_percent")
            secondary_used = secondary.get("used_percent")
            context_remaining = context.get("remaining_tokens")
            context_window = context.get("model_context_window")
            context_used_tokens = context.get("input_tokens")
            context_remaining_percent = None
            if isinstance(context_remaining, int) and isinstance(context_window, int) and context_window > 0:
                context_remaining_percent = context_remaining / context_window * 100
            primary_remaining = primary.get("remaining_percent")
            secondary_remaining = secondary.get("remaining_percent")

            if self.display_mode == "remaining":
                self.status_vars["context"].set("CTX")
                self.status_vars["context_reset"].set(f"{short_tokens(context_remaining)}/{short_tokens(context_window)}")
                self.status_vars["context_pct"].set(percent(context_remaining_percent))
                self.status_vars["primary"].set("5h")
                self.status_vars["primary_reset"].set(primary.get("resets_in") or "n/a")
                self.status_vars["primary_pct"].set(percent(primary_remaining))
                self.status_vars["secondary"].set("Week")
                self.status_vars["secondary_reset"].set(secondary.get("resets_in") or "n/a")
                self.status_vars["secondary_pct"].set(percent(secondary_remaining))
                self.set_bar("context", context_remaining_percent, remaining_mode=True)
                self.set_bar("primary", primary_remaining, remaining_mode=True)
                self.set_bar("secondary", secondary_remaining, remaining_mode=True)
            else:
                self.status_vars["context"].set("CTX")
                self.status_vars["context_reset"].set(f"{short_tokens(context_used_tokens)}/{short_tokens(context_window)}")
                self.status_vars["context_pct"].set(percent(context_used))
                self.status_vars["primary"].set("5h")
                self.status_vars["primary_reset"].set(primary.get("resets_in") or "n/a")
                self.status_vars["primary_pct"].set(percent(primary_used))
                self.status_vars["secondary"].set("Week")
                self.status_vars["secondary_reset"].set(secondary.get("resets_in") or "n/a")
                self.status_vars["secondary_pct"].set(percent(secondary_used))
                self.set_bar("context", context_used)
                self.set_bar("primary", primary_used)
                self.set_bar("secondary", secondary_used)

            project = source.get("project_name") or "project?"
            selector = "thread" if source.get("selection") == "current thread" else "latest"
            thread_name = compact_text(source.get("thread_name"), 20)
            event_time = (status.get("event_timestamp") or "n/a").replace("T", " ").replace("Z", "")
            self.status_vars["source"].set(f"{selector} · {compact_text(project, 12)} · {thread_name} · {event_time[-8:]}")
        except StatusError as exc:
            self.status_vars["context"].set("CTX n/a")
            self.status_vars["context_reset"].set("")
            self.status_vars["context_pct"].set("n/a")
            self.status_vars["primary"].set("5h n/a")
            self.status_vars["primary_reset"].set("")
            self.status_vars["primary_pct"].set("n/a")
            self.status_vars["secondary"].set("Week n/a")
            self.status_vars["secondary_reset"].set("")
            self.status_vars["secondary_pct"].set("n/a")
            self.status_vars["source"].set(str(exc))
            for key in self.rows:
                self.set_bar(key, None)

        self.schedule_refresh()

    def schedule_refresh(self) -> None:
        self.refresh_after_id = self.root.after(max(1000, int(self.args.refresh * 1000)), self.refresh)

    def run(self) -> None:
        self.root.mainloop()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=default_codex_home())
    parser.add_argument("--thread-id", default=os.environ.get("CODEX_THREAD_ID"))
    parser.add_argument("--refresh", type=float, default=5)
    parser.add_argument("--active-hours", type=float, default=24)
    parser.add_argument("--max-projects", type=int, default=8)
    parser.add_argument(
        "--position",
        choices=["saved", "pet", "top-left", "top-right", "bottom-left", "bottom-right", "custom"],
        default="saved",
    )
    parser.add_argument("--x", type=int, default=24)
    parser.add_argument("--y", type=int, default=24)
    parser.add_argument("--width", type=int, default=300)
    parser.add_argument("--height", type=int, default=182)
    parser.add_argument("--scale", type=float, default=None)
    parser.add_argument("--alpha", type=float, default=0.94)
    parser.add_argument("--decorated", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    UsageWidget(args).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
