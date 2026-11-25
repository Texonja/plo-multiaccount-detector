from datetime import datetime
import tkinter as tk
from tkinter import ttk

from .report_view import STATS, decimal, integer, number
from .ui_theme import AMBER, BLUE, HEADER, INSET, LINE, MUTED, PANEL, TEXT, font, label, rule


def short_date(value):
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return value or "—"


class PairDetails(tk.Frame):
    def __init__(self, parent, unit):
        super().__init__(parent, bg=PANEL)
        self.u = unit
        self.row = None
        self.page = "Playing profile"
        bar = tk.Frame(self, bg=HEADER, height=unit(41))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        label(bar, "Pair details", bg=HEADER, size=12, bold=True).pack(side="left", padx=unit(15))
        self.rank = label(bar, bg=HEADER, fg=MUTED, size=9)
        self.rank.pack(side="right", padx=unit(15))
        self.players = {}
        for key, letter, color in (("a", "A", BLUE), ("b", "B", AMBER)):
            line = tk.Frame(self, bg=PANEL)
            line.pack(fill="x", padx=unit(16), pady=(unit(12 if key == "a" else 7), 0))
            label(line, letter, bg=color, fg=HEADER, size=9, bold=True, width=2).pack(side="left")
            name = label(line, bold=True, size=11, anchor="w")
            hands = label(line, fg=MUTED, size=9)
            hands.pack(side="right")
            name.pack(side="left", padx=unit(8), fill="x", expand=True)
            self.players[key] = name, hands
        tabs = tk.Frame(self, bg=PANEL)
        tabs.pack(fill="x", pady=(unit(15), 0), padx=unit(15))
        self.tabs = {}
        for page in ("Playing profile", "Scoring"):
            tab = tk.Frame(tabs, bg=PANEL)
            tab.pack(side="left")
            btn = tk.Button(tab, text=page, font=font(9, True), bg=PANEL, fg=MUTED,
                            activeforeground=TEXT, activebackground=PANEL, relief="flat",
                            borderwidth=0, cursor="hand2", padx=unit(9), pady=unit(4),
                            command=lambda p=page: self.switch(p))
            btn.pack()
            marker = tk.Frame(tab, height=unit(2), bg=PANEL)
            marker.pack(fill="x")
            self.tabs[page] = btn, marker
        rule(self).pack(fill="x")
        body = tk.Frame(self, bg=PANEL)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=PANEL, borderwidth=0, highlightthickness=0, width=1)
        self.scroll = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _: self.paint())
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.switch(self.page)

    def wheel(self, evt):
        if self.scroll.winfo_ismapped():
            self.canvas.yview_scroll(-int(evt.delta / 120), "units")

    def switch(self, page):
        self.page = page
        for key, (btn, marker) in self.tabs.items():
            btn.configure(fg=AMBER if key == page else MUTED)
            marker.configure(bg=AMBER if key == page else PANEL)
        self.canvas.yview_moveto(0)
        self.paint()

    def show(self, index, row):
        self.row = row
        self.rank.configure(text=f"Pair #{integer(index+1)}" if row is not None else "")
        for side, (name, hands) in self.players.items():
            name.configure(text=row[f"player_{side}"] if row else "—")
            hands.configure(text=integer(row.get(f"player_{side}_sample_hands")) + " hands" if row else "")
        self.paint()

    def text(self, x, y, value, *, color=TEXT, size=9, bold=False, anchor="w"):
        self.canvas.create_text(self.u(x), self.u(y), text=value, anchor=anchor,
                                fill=color, font=font(size, bold))

    def line(self, x1, y1, x2, y2, color=LINE):
        self.canvas.create_line(self.u(x1), self.u(y1), self.u(x2), self.u(y2), fill=color)

    def rect(self, x1, y1, x2, y2, color):
        self.canvas.create_rectangle(self.u(x1), self.u(y1), self.u(x2), self.u(y2),
                                     fill=color, outline="")

    def paint(self):
        self.canvas.delete("all")
        # Canvas coordinates use logical 96-dpi pixels like the rest of the layout.
        width = self.canvas.winfo_width() / self.u(100) * 100
        if width < 100:
            return
        if not self.row:
            self.text(width/2, 36, "Select a pair in the table.", color=MUTED, anchor="center")
            height = 70
        elif self.page == "Playing profile":
            height = self.draw_profile(width)
        else:
            height = self.draw_scores(width)
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), self.u(height)))
        if self.u(height) > self.canvas.winfo_height():
            self.scroll.pack(side="right", fill="y")
        else:
            self.scroll.pack_forget()
            self.canvas.yview_moveto(0)

    def draw_profile(self, width):
        left, right = 16, width-16
        start, end = left+47, right-100
        xa, xb = right-53, right
        self.text(left, 20, "Stat", color=MUTED)
        self.text(xa, 20, "A %", color=BLUE, bold=True, anchor="e")
        self.text(xb, 20, "B %", color=AMBER, bold=True, anchor="e")
        for tick in (0, 50, 100):
            x = start + (end-start)*tick/100
            self.text(x, 20, str(tick), color=MUTED, size=8, anchor="center")
            self.line(x, 33, x, 211, "#434a4e")
        for i, (key, name) in enumerate(STATS):
            y = 50 + 36*i
            self.text(left, y, name, bold=True)
            for side, color, offset, value_x in (("a", BLUE, -7, xa), ("b", AMBER, 1, xb)):
                raw = self.row.get(f"player_{side}_{key}")
                n = number(raw)
                self.rect(start, y+offset, end, y+offset+5, "#3c4246")
                if n is not None and n > 0:
                    self.rect(start, y+offset, start+(end-start)*min(n,100)/100, y+offset+5, color)
                self.text(value_x, y, decimal(raw), color=color, anchor="e")
        self.line(left, 224, right, 224)
        self.text(left, 247, "Sample detail", size=11, bold=True)
        x1, x2 = right-106, right
        self.text(x1, 248, "Player A", size=9, color=BLUE, anchor="e")
        self.text(x2, 248, "Player B", size=9, color=AMBER, anchor="e")
        fields = (("threebet_opp", "3Bet opportunities"), ("saw_flop", "Saw flop"),
                  ("showdowns", "Showdowns"), ("first_seen", "First seen"), ("last_seen", "Last seen"))
        for i, (key, name) in enumerate(fields):
            y = 277 + i*26
            if i % 2 == 0:
                self.rect(left-4, y-12, right+4, y+13, "#2e3439")
            self.text(left, y, name, color=MUTED)
            for side, x in (("a", x1), ("b", x2)):
                raw = self.row.get(f"player_{side}_{key}")
                self.text(x, y, short_date(raw) if key.endswith("seen") else integer(raw), anchor="e")
        return 400

    def draw_scores(self, width):
        left, right = 16, width-16
        if "score" in self.row:
            self.text(left, 22, "Stat", color=MUTED)
            self.text(right, 22, "log10 LR", color=MUTED, anchor="e")
            self.line(left, 38, right, 38)
            for i, (key, name) in enumerate(STATS):
                if key == "pfr":
                    key, name = "pfr_given_vpip", "PFR | VPIP"
                y = 57 + i * 33
                self.text(left, y, name, bold=True)
                self.text(right, y, decimal(self.row.get(f"{key}_log10_lr")), anchor="e")
                self.line(left, y + 16, right, y + 16)
            self.rect(left - 5, 225, right + 5, 267, INSET)
            self.text(left + 3, 246, "Total score", bold=True)
            self.text(right - 4, 246, decimal(self.row["score"]), color=AMBER, size=14, bold=True, anchor="e")
            return 282
        match, diff = left+(right-left)*.5, left+(right-left)*.77
        for x, title in ((left, "Stat"), (match, "Match"), (diff, "Rel. diff."), (right, "Points")):
            self.text(x, 22, title, color=MUTED, anchor="w" if x == left else "e")
        self.line(left, 38, right, 38)
        for i, (key, name) in enumerate(STATS):
            y = 57 + i*33
            self.text(left, y, name, bold=True)
            for x, suffix in ((match, "match_pct"), (diff, "diff_pct")):
                value = decimal(self.row.get(f"{key}_{suffix}"))
                self.text(x, y, value + ("%" if value != "—" else ""), anchor="e")
            self.text(right, y, integer(self.row.get(f"{key}_points")), color=AMBER, anchor="e")
            self.line(left, y+16, right, y+16, "#373d42")
        self.text(left, 224, "Sample points")
        self.text(right, 224, integer(self.row.get("sample_points")), color=AMBER, anchor="e")
        self.rect(left-5, 247, right+5, 289, INSET)
        self.text(left+3, 267, "Total points", bold=True)
        self.text(right-4, 267, integer(self.row.get("risk_points")), color=AMBER,
                  size=14, bold=True, anchor="e")
        return 306
