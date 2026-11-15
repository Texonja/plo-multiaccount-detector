"""Local Windows workspace for existing detector reports and HM2 backups."""
from __future__ import annotations

import csv
from datetime import datetime
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from . import __version__
from .candidate_table import CandidateTable
from .pair_details import PairDetails
from .report_view import CSV_NAME, Report, integer
from .ui_theme import AMBER, EDGE, HEADER, INK, LINE, MUTED, PANEL, SILVER, TEXT, font, label, rule, style_grid

ASSETS = Path(__file__).with_name("assets")
ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "sample_output" / CSV_NAME


def export_rows(report, order, target):
    if target.resolve() == report.path.resolve():
        raise ValueError("Choose a different filename for the export.")
    with report.path.open(encoding="utf-8-sig", newline="") as source:
        fields = next(csv.reader(source))
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False,
                                         encoding="utf-8-sig", newline="") as stream:
            temp = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(report.rows[i] for i in order)
        temp.replace(target)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


class DetectorWindow:
    def __init__(self, root):
        self.root = root
        self.report = None
        self.source = None
        self.process = None
        self.tmp = None
        self.events = queue.Queue()
        self.buttons = {}
        self.scale = root.winfo_fpixels("1i") / 96
        u = self.unit
        root.title(f"PLO Multiaccount Detector {__version__}")
        root.configure(bg=EDGE)
        root.minsize(min(root.winfo_screenwidth(), u(875)), min(root.winfo_screenheight()-60, u(495)))
        width = min(u(1330), root.winfo_screenwidth()-u(30))
        height = min(u(797), root.winfo_screenheight()-u(95))
        root.geometry(f"{width}x{height}+{max(0,(root.winfo_screenwidth()-width)//2)}+"
                      f"{max(0,(root.winfo_screenheight()-height)//3)}")
        style_grid(root, u)
        self.images = {key: tk.PhotoImage(file=ASSETS / (key + ".png"))
                       for key in ("cards", "database", "run", "folder", "export")}
        if os.name == "nt":
            root.iconbitmap(str(ASSETS / "detector.ico"))
        self.header()
        self.ribbon()
        self.statusbar()
        panes = tk.PanedWindow(root, orient="horizontal", bg=EDGE, borderwidth=0,
                               sashwidth=u(5), sashrelief="flat", showhandle=False,
                               opaqueresize=True)
        panes.pack(fill="both", expand=True)
        self.details = PairDetails(panes, u)
        self.table = CandidateTable(panes, u, self.selected)
        left_width = round(width*.64)
        panes.add(self.table, minsize=u(435), width=left_width, stretch="always")
        panes.add(self.details, minsize=u(328), width=width-left_width-u(5), stretch="always")
        root.bind("<Control-f>", self.focus_search)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.table.set_rows([])
        if SAMPLE.is_file():
            self.load(SAMPLE)
        else:
            self.message.set("Open a backup or CSV report.")

    def unit(self, n):
        return round(n*self.scale)

    def header(self):
        u = self.unit
        bar = tk.Frame(self.root, bg=HEADER)
        bar.pack(fill="x")
        tk.Label(bar, image=self.images["cards"], bg=HEADER, bd=0).pack(
            side="left", padx=(u(12), u(8)), pady=u(4))
        label(bar, "PLO", bg=HEADER, size=17, bold=True).pack(side="left")
        tk.Frame(bar, bg="#626768", width=1, height=u(21)).pack(side="left", padx=u(12))
        label(bar, "Multiaccount Detector", bg=HEADER, fg="#d9dcdb", size=13).pack(side="left")
        self.filename = label(bar, bg=HEADER, fg="#c4cbcd", size=9)
        self.filename.pack(side="right", padx=u(17))
        rule(self.root, "#111416").pack(fill="x")

    def ribbon(self):
        u = self.unit
        outer = tk.Frame(self.root, bg=SILVER)
        outer.pack(fill="x")
        rule(outer, "#ffffff").pack(fill="x")
        ribbon = tk.Frame(outer, bg=SILVER)
        ribbon.pack(fill="x", padx=u(9), pady=(u(4), u(3)))
        actions = (
            ("Database", (("database", "Open backup", self.open_backup), ("run", "Analyze", self.analyze))),
            ("Reports", (("folder", "Open report", self.open_report), ("export", "Export CSV", self.export))),
        )
        for caption, group in actions:
            column = tk.Frame(ribbon, bg=SILVER)
            column.pack(side="left", padx=u(3))
            row = tk.Frame(column, bg=SILVER)
            row.pack()
            for key, title, action in group:
                active = key == "run"
                border = tk.Frame(row, bg="#b18643" if active else SILVER)
                border.pack(side="left", padx=u(1))
                bg = "#f0d5a6" if active else SILVER
                btn = tk.Button(border, text=title, image=self.images[key], compound="top",
                                command=action, bg=bg, fg=INK, font=font(9, active),
                                activebackground="#f9e5bf", activeforeground=INK, disabledforeground="#767d80",
                                borderwidth=0, relief="flat", cursor="hand2",
                                padx=u(8), pady=0, highlightthickness=0)
                btn.pack(padx=1, pady=1)
                btn.bind("<Enter>", lambda e, b=btn: b.configure(bg="#e9e9e4") if b["state"]=="normal" else None)
                btn.bind("<Leave>", lambda e, b=btn, color=bg: b.configure(bg=color))
                self.buttons[key] = btn
            label(column, caption, bg=SILVER, fg="#50595d", size=8).pack(pady=(2, 0))
            tk.Frame(ribbon, bg="#adb2b3", width=1).pack(side="left", fill="y", padx=(u(3), 0))
            tk.Frame(ribbon, bg="#eef0f0", width=1).pack(side="left", fill="y")
        self.totals = {}
        for key, caption in (("pairs", "Pairs"), ("players", "Players"), ("hands", "Hands")):
            group = tk.Frame(ribbon, bg=SILVER)
            group.pack(side="right", padx=u(14))
            total = label(group, "—", bg=SILVER, fg=INK, size=16, bold=True)
            total.pack(anchor="e")
            label(group, caption, bg=SILVER, fg="#50595d", size=9).pack(anchor="e")
            self.totals[key] = total
        rule(outer, "#a0a7aa").pack(fill="x")
        rule(self.root, EDGE).pack(fill="x")

    def statusbar(self):
        u = self.unit
        status = tk.Frame(self.root, bg=HEADER)
        status.pack(side="bottom", fill="x")
        rule(status).pack(fill="x")
        self.lamp = label(status, "●", bg=HEADER, fg="#91bc83", size=8)
        self.lamp.pack(side="left", padx=(u(12), u(6)))
        self.message = tk.StringVar(value="Ready")
        label(status, textvariable=self.message, bg=HEADER, fg=TEXT, size=9).pack(side="left", pady=u(4))
        self.table_sizes = label(status, bg=HEADER, fg=MUTED, size=9)
        self.table_sizes.pack(side="right", padx=u(12))
        self.visible_count = label(status, bg=HEADER, fg=MUTED, size=9)
        self.visible_count.pack(side="right", padx=u(12))

    def focus_search(self, _event):
        self.table.entry.focus_set()
        self.table.entry.selection_range(0, "end")
        return "break"

    def selected(self, index, row, count):
        self.details.show(index, row)
        self.visible_count.configure(text=f"Showing {integer(count)} / {integer(len(self.table.rows))}")

    def load(self, path):
        try:
            self.display(Report.read(path))
        except (OSError, ValueError, csv.Error) as exc:
            messagebox.showerror("Open report", str(exc), parent=self.root)

    def display(self, report):
        self.report = report
        self.source = report.source(ROOT)
        self.table.set_rows(report.rows)
        info = report.summary
        name = Path(str(info.get("input_path") or report.path.name)).name
        self.filename.configure(text=("Sample   /   " if report.path == SAMPLE else "") + name)
        self.totals["hands"].configure(text=integer(info.get("hands_parsed")))
        self.totals["players"].configure(text=integer(info.get("unique_players_with_stats_sample")))
        self.totals["pairs"].configure(text=integer(len(report.rows)))
        config = info.get("config") or {}
        sizes = config.get("table_sizes_for_stats") if isinstance(config, dict) else None
        self.table_sizes.configure(text="  /  ".join(f"{s}-max" for s in sizes) if isinstance(sizes,list) else "")
        self.message.set("Ready")

    def open_report(self):
        path = filedialog.askopenfilename(parent=self.root, title="Open report",
                                          filetypes=[("CSV report", "*.csv")], initialdir=ROOT)
        if path:
            self.load(Path(path))

    def open_backup(self):
        path = filedialog.askopenfilename(parent=self.root, title="Choose a backup to analyze",
                                          filetypes=[("HM2 backup", "*.pghembk *.sql"), ("All files", "*.*")],
                                          initialdir=ROOT)
        if path:
            self.start_analysis(Path(path))

    def analyze(self):
        if self.source and self.source.is_file():
            self.start_analysis(self.source)
        else:
            self.open_backup()

    def export(self):
        if self.report is None:
            return
        name = filedialog.asksaveasfilename(parent=self.root, title="Export visible pairs",
                    initialfile="candidate_pairs.csv", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if name:
            try:
                export_rows(self.report, self.table.order, Path(name))
                self.message.set(f"Exported {integer(len(self.table.order))} pairs")
            except (OSError, ValueError, csv.Error) as exc:
                messagebox.showerror("CSV export", str(exc), parent=self.root)

    def start_analysis(self, source):
        if self.process is not None:
            return
        reports = ROOT / "reports"
        try:
            reports.mkdir(exist_ok=True)
            self.tmp = tempfile.TemporaryDirectory(dir=reports, prefix=".analysis-")
            temp_report = Path(self.tmp.name) / "report"
            cmd = [sys.executable, "-m", "plo_multiaccount_detector", "--input", str(source),
                   "--out", str(temp_report), "--config", str(ROOT/"config.json"), "--progress-every", "10000"]
            env = dict(os.environ, PYTHONPATH=str(ROOT/"src"), PYTHONIOENCODING="utf-8",
                       PYTHONDONTWRITEBYTECODE="1")
            self.process = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            if self.tmp:
                self.tmp.cleanup()
                self.tmp = None
            messagebox.showerror("Analysis", str(exc), parent=self.root)
            return
        self.busy(True)
        self.message.set(f"Analyzing · {source.name}")
        threading.Thread(target=self.read_progress, args=(self.process,), daemon=True).start()
        self.root.after(120, self.poll)

    def read_progress(self, process):
        last = ""
        with process.stdout as stream:
            for line in stream:
                last = line.strip()
                match = re.search(r"parsed=([\d,]+)", last)
                if match:
                    self.events.put(("progress", int(match[1].replace(",", ""))))
        self.events.put(("done", (process.wait(), last)))

    def poll(self):
        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                self.root.after(150, self.poll)
                return
            if kind == "progress":
                self.message.set(f"Processed {integer(data)} hands")
            else:
                self.finish_analysis(*data)
                return

    def finish_analysis(self, code, last):
        self.process = None
        try:
            if code:
                raise ValueError(last or f"Analysis stopped (exit code {code}).")
            stage = Path(self.tmp.name) / "report"
            report = Report.read(stage / CSV_NAME)
            dest = ROOT / "reports" / datetime.now().strftime("multiaccount_report_%Y-%m-%d_%H-%M-%S_%f")
            stage.rename(dest)
            report.path = dest / CSV_NAME
            self.display(report)
            self.message.set("Analysis complete")
        except (OSError, ValueError, csv.Error) as exc:
            self.message.set("Analysis failed")
            messagebox.showerror("Analysis", str(exc), parent=self.root)
        finally:
            self.tmp.cleanup()
            self.tmp = None
            self.busy(False)

    def busy(self, active):
        self.lamp.configure(fg=AMBER if active else "#91bc83")
        for key, button in self.buttons.items():
            enabled = not active and (key != "export" or self.report is not None)
            button.configure(state="normal" if enabled else "disabled")

    def close(self):
        if self.process is not None:
            self.process.terminate()
            self.process.wait()
        if self.tmp is not None:
            self.tmp.cleanup()
        self.root.destroy()


def main():
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    root = tk.Tk()
    app = DetectorWindow(root)
    app.busy(False)
    root.mainloop()
