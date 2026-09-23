#!/usr/bin/env python3
"""
Tech Intelligence - desktop widget.

A small always-on-top window that shows the latest saved briefing (read
straight from the SQLite database main.py already writes to) and the latest
gold/silver rates (read from prices.py's separate database). Polls for
updates every 60 seconds; does not do any collecting/AI/fetching work
itself - both data sources stay fully standalone, this just displays them.

Usage:
    python widget.py          # console window
    pythonw widget.py         # no console window (use this for Startup)
"""
import json
import logging
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import font as tkfont
from tkinter import ttk
from urllib.parse import urlparse

import prices
from app import config, database

REFRESH_MS = 60_000
WINDOW_WIDTH = 380
WINDOW_HEIGHT = 560

BG = "#1e1f24"
CARD_BG = "#282a33"
FG = "#e8e8ec"
MUTED = "#9a9ba5"
ACCENT = "#5b8def"


def importance_color(score: int) -> str:
    if score >= 8:
        return "#e5534b"
    if score >= 5:
        return "#e2a33d"
    return "#5fb96f"


class TechWidget(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tech Intelligence")
        self.configure(bg=BG)
        self.attributes("-topmost", True)
        self.minsize(300, 300)
        self._last_briefing_id = None
        self._place_top_right()
        self._build_chrome()
        self._build_price_strip()
        self._build_scroll_area()
        self.refresh(initial=True)
        self.refresh_prices()
        self.after(REFRESH_MS, self._poll)

    def _place_top_right(self) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        x = sw - WINDOW_WIDTH - 24
        y = 40
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")

    def _build_chrome(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=12, pady=(10, 4))

        tk.Label(
            header, text="\U0001F9E0 TECH INTELLIGENCE", bg=BG, fg=FG,
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left")

        tk.Button(
            header, text="↻", command=lambda: self.refresh(force=True),
            bg=BG, fg=MUTED, bd=0, activebackground=BG, activeforeground=FG,
            font=("Segoe UI", 10), cursor="hand2",
        ).pack(side="right")

        self.subtitle_var = tk.StringVar(value="Loading...")
        tk.Label(
            self, textvariable=self.subtitle_var, bg=BG, fg=MUTED,
            font=("Segoe UI", 9), anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 8))

    def _build_price_strip(self) -> None:
        strip = tk.Frame(self, bg=CARD_BG)
        strip.pack(fill="x", padx=12, pady=(0, 10))
        for col in range(3):
            strip.columnconfigure(col, weight=1)

        self._price_vars = {}
        short_names = {"Gold Hallmark": "Hallmark", "Gold Tajabi": "Tajabi", "Silver": "Silver"}
        icons = {"Gold Hallmark": "\U0001F947", "Gold Tajabi": "\U0001F947", "Silver": "\U0001F948"}
        for col, metal in enumerate(("Gold Hallmark", "Gold Tajabi", "Silver")):
            cell = tk.Frame(strip, bg=CARD_BG)
            cell.grid(row=0, column=col, sticky="nsew", padx=8, pady=8)

            tk.Label(
                cell, text=f"{icons[metal]} {short_names[metal]}", bg=CARD_BG, fg=MUTED,
                font=("Segoe UI", 8),
            ).pack(anchor="w")

            var = tk.StringVar(value="--")
            self._price_vars[metal] = var
            tk.Label(
                cell, textvariable=var, bg=CARD_BG, fg=FG, font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w")

        self.price_date_var = tk.StringVar(value="")
        tk.Label(
            self, textvariable=self.price_date_var, bg=BG, fg=MUTED,
            font=("Segoe UI", 8), anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 8))

    def refresh_prices(self) -> None:
        try:
            rows = prices.get_latest_prices()
        except Exception:
            logging.getLogger(__name__).exception("Failed to read gold/silver prices")
            return

        if not rows:
            self.price_date_var.set("Gold/silver rates: not fetched yet")
            return

        for row in rows:
            var = self._price_vars.get(row["metal"])
            if var is not None:
                var.set(f"Rs {row['price_npr']:,} /tola")

        source_date = rows[0]["source_date"] or ""
        self.price_date_var.set(f"FENEGOSIDA rate as of {source_date}")

    def _build_scroll_area(self) -> None:
        container = tk.Frame(self, bg=BG)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.body = tk.Frame(canvas, bg=BG)

        self.body.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.body, anchor="nw", width=WINDOW_WIDTH - 16)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(12, 0))
        scrollbar.pack(side="right", fill="y")

        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_wheel)

    def _poll(self) -> None:
        self.refresh()
        self.refresh_prices()
        self.after(REFRESH_MS, self._poll)

    def refresh(self, initial: bool = False, force: bool = False) -> None:
        row = database.get_latest_briefing()
        now_str = datetime.now().strftime("%H:%M")

        if row is None:
            self.subtitle_var.set(f"No briefing yet - last checked {now_str}")
            return

        if not force and not initial and row["id"] == self._last_briefing_id:
            self.subtitle_var.set(f"Up to date - last checked {now_str}")
            return

        self._last_briefing_id = row["id"]
        try:
            data = json.loads(row["raw_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            data = {}

        created = row["created_at"] or ""
        self.subtitle_var.set(f"Generated {created[:16].replace('T', ' ')} - checked {now_str}")
        self._render(data)

    def _render(self, data: dict) -> None:
        for child in self.body.winfo_children():
            child.destroy()

        stories = sorted(
            data.get("stories", []), key=lambda s: s.get("importance", 0), reverse=True
        )
        if not stories:
            tk.Label(
                self.body, text="No stories in the latest briefing.",
                bg=BG, fg=MUTED, font=("Segoe UI", 10), wraplength=WINDOW_WIDTH - 32,
            ).pack(anchor="w", pady=20)
            return

        for i, story in enumerate(stories, start=1):
            self._add_story_card(i, story)

        trends = data.get("trends") or []
        if trends:
            self._add_section("\U0001F4C8 TRENDS", trends)

        watch_next = data.get("watch_next") or []
        if watch_next:
            self._add_section("\U0001F440 WATCH NEXT", watch_next)

    def _add_story_card(self, i: int, story: dict) -> None:
        card = tk.Frame(self.body, bg=CARD_BG)
        card.pack(fill="x", pady=(0, 8), ipady=8, ipadx=10)

        top = tk.Frame(card, bg=CARD_BG)
        top.pack(fill="x", padx=2)

        title = f"{i}. {story.get('title', 'Untitled')}"
        tk.Label(
            top, text=title, bg=CARD_BG, fg=FG, font=("Segoe UI", 10, "bold"),
            wraplength=WINDOW_WIDTH - 90, justify="left", anchor="w",
        ).pack(side="left", fill="x", expand=True)

        importance = int(story.get("importance", 0) or 0)
        tk.Label(
            top, text=f"{importance}/10", bg=CARD_BG, fg=importance_color(importance),
            font=("Segoe UI", 9, "bold"),
        ).pack(side="right")

        what_happened = story.get("what_happened", "")
        if what_happened:
            tk.Label(
                card, text=what_happened, bg=CARD_BG, fg=FG, font=("Segoe UI", 9),
                wraplength=WINDOW_WIDTH - 40, justify="left", anchor="w",
            ).pack(fill="x", padx=2, pady=(6, 0))

        why = story.get("why_it_matters", "")
        if why:
            tk.Label(
                card, text=f"Why it matters: {why}", bg=CARD_BG, fg=MUTED,
                font=("Segoe UI", 9, "italic"), wraplength=WINDOW_WIDTH - 40,
                justify="left", anchor="w",
            ).pack(fill="x", padx=2, pady=(6, 0))

        urls = story.get("source_urls") or []
        if urls and urls[0].startswith(("http://", "https://")):
            domain = urlparse(urls[0]).netloc.removeprefix("www.") or urls[0]
            link = tk.Label(
                card, text=f"Source: {domain}", bg=CARD_BG, fg=ACCENT,
                font=("Segoe UI", 8, "underline"), cursor="hand2", anchor="w",
            )
            link.pack(fill="x", padx=2, pady=(6, 0))
            link.bind("<Button-1>", lambda e, u=urls[0]: webbrowser.open(u))

    def _add_section(self, heading: str, items: list) -> None:
        tk.Label(
            self.body, text=heading, bg=BG, fg=FG, font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(6, 2))
        for item in items:
            tk.Label(
                self.body, text=f"• {item}", bg=BG, fg=MUTED, font=("Segoe UI", 9),
                wraplength=WINDOW_WIDTH - 32, justify="left", anchor="w",
            ).pack(fill="x", pady=1)


def main() -> None:
    database.init_db()
    app = TechWidget()
    app.mainloop()


if __name__ == "__main__":
    main()
