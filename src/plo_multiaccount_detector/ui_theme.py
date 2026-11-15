"""Shared colors, typography and report-grid styling."""
import tkinter as tk
from tkinter import ttk

SURFACE = "#30353a"
PANEL = "#282d32"
INSET = "#23282c"
HEADER = "#202428"
EDGE = "#171b1e"
LINE = "#42484e"
TEXT = "#e9e9e5"
MUTED = "#b0b7ba"
AMBER = "#efb569"
BLUE = "#7db7da"
SILVER = "#d8dadb"
INK = "#262d32"


def font(size=10, bold=False):
    return ("Segoe UI", size, "bold" if bold else "normal")


def label(parent, text="", *, bg=PANEL, fg=TEXT, size=10, bold=False, **kw):
    return tk.Label(parent, text=text, bg=bg, fg=fg, font=font(size, bold),
                    borderwidth=0, highlightthickness=0, padx=0, pady=0, **kw)


def rule(parent, color=LINE):
    return tk.Frame(parent, bg=color, height=1, borderwidth=0)


def style_grid(root, unit):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                    foreground=TEXT, font=font(), rowheight=unit(28),
                    borderwidth=0, relief="flat", lightcolor=EDGE, darkcolor=EDGE)
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.map("Treeview", background=[("selected", "#194f7c")],
              foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", background="#454b50", foreground="#f1f1ed",
                    font=font(9), padding=(unit(6), unit(6)), borderwidth=1,
                    relief="raised", lightcolor="#575d61", darkcolor="#34393d",
                    bordercolor="#33383c")
    style.map("Treeview.Heading", background=[("active", "#555c61")])
    style.configure("Vertical.TScrollbar", troughcolor="#252a2e", background="#555d62",
                    borderwidth=0, arrowsize=unit(12), arrowcolor="#e1e4e5",
                    bordercolor=PANEL, lightcolor="#60676c", darkcolor=LINE)
    style.configure("Horizontal.TScrollbar", troughcolor="#252a2e", background="#555d62",
                    borderwidth=0, arrowsize=unit(12), arrowcolor="#e1e4e5")
