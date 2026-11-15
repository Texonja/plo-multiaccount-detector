import tkinter as tk
from tkinter import ttk

from .report_view import decimal, integer, number
from .ui_theme import AMBER, INSET, LINE, MUTED, PANEL, SURFACE, TEXT, font, label

COLUMNS = (
    ("rank", "#", 43), ("player_a", "Player A", 138), ("player_b", "Player B", 138),
    ("risk_points", "Points", 66), ("mutual_hands", "Shared hands", 101),
    ("min_sample_hands", "Min. hands", 88), ("vpip_match_pct", "VPIP match", 90),
    ("pfr_match_pct", "PFR match", 90),
)


class CandidateTable(tk.Frame):
    def __init__(self, parent, unit, on_select):
        super().__init__(parent, bg=SURFACE)
        self.on_select = on_select
        self.rows = []
        self.order = []
        self.sort_by = "risk_points"
        self.descending = True
        self.query = tk.StringVar()
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x")
        tk.Frame(bar, width=unit(3), bg=AMBER).pack(side="left", fill="y")
        label(bar, "Candidate pairs", size=12, bold=True).pack(side="left", padx=unit(13))
        search = tk.Frame(bar, bg=INSET, highlightbackground=LINE, highlightthickness=1)
        search.pack(side="right", padx=unit(12), pady=unit(8))
        lens = tk.Canvas(search, width=unit(24), height=unit(23), bg=INSET, highlightthickness=0)
        lens.pack(side="left")
        lens.create_oval(unit(7), unit(5), unit(15), unit(13), outline=MUTED, width=unit(1.5))
        lens.create_line(unit(14), unit(12), unit(19), unit(17), fill=MUTED, width=unit(1.5))
        self.entry = tk.Entry(search, textvariable=self.query, width=17, bg=INSET, fg=TEXT,
                              insertbackground=TEXT, borderwidth=0, highlightthickness=0,
                              font=font(9), selectbackground="#245983")
        self.entry.pack(side="left", padx=(0, unit(4)))
        self.hint = label(self.entry, "Find player", bg=INSET, fg=MUTED, size=9, cursor="xterm")
        self.hint.place(x=0, rely=.5, anchor="w")
        self.hint.bind("<Button-1>", lambda _: self.entry.focus_set())
        lens.bind("<Button-1>", lambda _: self.entry.focus_set())
        self.entry.bind("<FocusIn>", lambda _: self.hint.place_forget())
        self.entry.bind("<FocusOut>", lambda _: self.update_hint())
        self.entry.bind("<Escape>", self.clear_search)
        self.clear = tk.Button(search, text="×", font=font(10), bg=INSET, fg=MUTED,
                               activebackground=LINE, activeforeground=TEXT, relief="flat",
                               bd=0, padx=unit(4), pady=0, command=self.clear_search,
                               takefocus=False, cursor="hand2")
        self.clear.pack(side="left")

        body = tk.Frame(self, bg=SURFACE)
        body.pack(fill="both", expand=True)
        self.grid_view = ttk.Treeview(body, columns=[c[0] for c in COLUMNS], show="headings",
                                      selectmode="browse")
        self.grid_view.grid(row=0, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        for key, _, width in COLUMNS:
            name = key in ("player_a", "player_b")
            self.grid_view.column(key, width=unit(width), minwidth=unit(72 if name else width-9),
                                  anchor="w" if name else "center", stretch=name)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.grid_view.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.hscroll = ttk.Scrollbar(body, orient="horizontal", command=self.grid_view.xview)
        self.grid_view.configure(yscrollcommand=scroll.set, xscrollcommand=self.scroll_x)
        self.grid_view.tag_configure("odd", background=SURFACE)
        self.grid_view.tag_configure("even", background="#373c41")
        self.cell_colors = self.grid_view.tk.call("package", "vcompare",
                                   self.grid_view.tk.call("package", "provide", "Tk"), "9.0") >= 0
        self.grid_view.tag_configure("points", foreground="#f1be78")
        self.grid_view.tag_configure("match", foreground="#a6cd9d")
        self.grid_view.bind("<<TreeviewSelect>>", lambda _: self.selection_changed())
        self.empty = label(body, "No matching pairs.", bg=SURFACE, fg=MUTED)
        self.query.trace_add("write", lambda *_: self.populate())
        self.headings()

    def scroll_x(self, first, last):
        self.hscroll.set(first, last)
        if float(first) > 0 or float(last) < 1:
            self.hscroll.grid(row=1, column=0, sticky="ew")
        else:
            self.hscroll.grid_remove()

    def update_hint(self):
        if not self.query.get() and self.focus_get() != self.entry:
            self.hint.place(x=0, rely=.5, anchor="w")

    def clear_search(self, event=None):
        self.query.set("")
        self.grid_view.focus_set()
        self.update_hint()
        return "break"

    def headings(self):
        for key, title, _ in COLUMNS:
            if key == self.sort_by:
                title += " ▾" if self.descending else " ▴"
            self.grid_view.heading(key, text=title, command=lambda k=key: self.sort(k),
                                   anchor="w" if key in ("player_a", "player_b") else "center")

    def sort(self, key):
        self.descending = not self.descending if key == self.sort_by else key not in ("rank", "player_a", "player_b")
        self.sort_by = key
        self.headings()
        self.populate()

    def set_rows(self, rows):
        self.rows = rows
        self.sort_by, self.descending = "risk_points", True
        self.headings()
        self.grid_view.selection_remove(self.grid_view.selection())
        self.query.set("")
        self.update_hint()

    def populate(self):
        needle = self.query.get().strip().casefold()
        current = self.grid_view.selection()
        self.order = [i for i, row in enumerate(self.rows) if not needle or
                      any(needle in row[k].casefold() for k in ("player_a", "player_b"))]
        def value(i):
            if self.sort_by == "rank":
                return i
            raw = self.rows[i].get(self.sort_by)
            if self.sort_by in ("player_a", "player_b"):
                return raw.casefold()
            n = number(raw)
            return n if n is not None else float("-inf")
        self.order.sort(key=value, reverse=self.descending)
        tree = self.grid_view
        tree.delete(*tree.get_children())
        for index, i in enumerate(self.order):
            row = self.rows[i]
            values = [integer(i+1), row["player_a"], row["player_b"],
                      *(integer(row.get(key)) for key, _, _ in COLUMNS[3:6]),
                      decimal(row.get("vpip_match_pct")), decimal(row.get("pfr_match_pct"))]
            tree.insert("", "end", iid=str(i), values=values, tags=("even" if index % 2 else "odd",))
            if self.cell_colors:
                tree.tk.call(tree, "tag", "cell", "add", "points", (str(i), "risk_points"))
                for stat in ("vpip", "pfr"):
                    if (number(row.get(f"{stat}_points")) or 0) > 0:
                        tree.tk.call(tree, "tag", "cell", "add", "match", (str(i), f"{stat}_match_pct"))
        if self.order:
            self.empty.place_forget()
            item = current[0] if current and tree.exists(current[0]) else str(self.order[0])
            tree.selection_set(item)
            tree.focus(item)
            tree.see(item)
        else:
            self.empty.place(relx=.5, rely=.4, anchor="center")
        self.selection_changed()

    def selection_changed(self):
        selection = self.grid_view.selection()
        rank = int(selection[0]) if selection else None
        self.on_select(rank, self.rows[rank] if rank is not None else None, len(self.order))
