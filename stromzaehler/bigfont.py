# -*- coding: utf-8 -*-
"""Vierzeilige Block-Ziffern (80er-LED-Optik) für große Zahlen im Dashboard.

`render(text)` liefert 4 Zeilen gleicher Länge; unbekannte Zeichen werden als
Leerraum dargestellt. Nur Ziffern, Trenner (.,), Leer- und ein paar Sonder-
zeichen sind definiert."""

# Jede Glyphe: 4 Zeilen. '#' = Block, ' ' = leer. Ziffern 3 breit.
_G = {
    "0": ("###", "# #", "# #", "###"),
    "1": ("  #", "  #", "  #", "  #"),
    "2": ("###", "  #", "## ", "###"),
    "3": ("###", " ##", "  #", "###"),
    "4": ("# #", "###", "  #", "  #"),
    "5": ("###", "## ", "  #", "###"),
    "6": ("###", "#  ", "###", "###"),
    "7": ("###", "  #", " # ", " # "),
    "8": ("###", "# #", "###", "###"),
    "9": ("###", "# #", "###", "  #"),
    ".": (" ", " ", " ", "#"),
    ",": (" ", " ", " ", "#"),
    ":": (" ", "#", " ", "#"),
    " ": ("  ", "  ", "  ", "  "),
    "k": ("   ", "# #", "## ", "# #"),
    "W": ("   ", "# #", "# #", "###"),
    "h": ("   ", "#  ", "## ", "# #"),
}


def render(text, gap=1):
    """Text → Liste von 4 Zeilen (Block-Ziffern), Glyphen durch <gap> Leer
    getrennt."""
    rows = ["", "", "", ""]
    sep = " " * gap
    s = str(text)
    for ci, ch in enumerate(s):
        g = _G.get(ch, _G[" "])
        for r in range(4):
            rows[r] += g[r] + ("" if ci == len(s) - 1 else sep)
    return [r.replace("#", "█") for r in rows]
