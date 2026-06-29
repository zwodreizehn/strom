# -*- coding: utf-8 -*-
"""Retro-Terminal-Stil (IBM-3270, Phosphor-Grün).

Zwei Welten:
  * curses  – Farbpaare P_* via setup_colors(); versucht echte Phosphor-Töne
              per init_color, fällt sonst auf die 8 Standardfarben zurück.
  * Klartext – ANSI-(Truecolor-)Konstanten für render.py (netmon-Optik);
               automatisch leer, wenn nicht in ein TTY geschrieben wird.
"""
import curses
import sys

# Farbpaar-IDs (curses)
P_GREEN, P_BRIGHT, P_DIM, P_CYAN, P_YELLOW, P_RED, P_OIA, P_BLUE = range(1, 9)

def setup_colors():
    """Nur die 8 Standard-ANSI-Farben des Terminals (System-Grün). Helligkeit
    kommt über A_BOLD (im UI-Code gesetzt) – keine eigene Palette via
    init_color, damit nichts verbogen wird."""
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except Exception:
        bg = curses.COLOR_BLACK

    g = curses.COLOR_GREEN
    curses.init_pair(P_GREEN,  g, bg)
    curses.init_pair(P_BRIGHT, g, bg)              # hell = grün + A_BOLD
    curses.init_pair(P_DIM,    g, bg)              # dezent = grün (ggf. A_DIM)
    curses.init_pair(P_CYAN,   curses.COLOR_CYAN, bg)
    curses.init_pair(P_YELLOW, curses.COLOR_YELLOW, bg)
    curses.init_pair(P_RED,    curses.COLOR_RED, bg)
    curses.init_pair(P_BLUE,   curses.COLOR_BLUE, bg)
    # OIA-Leiste: schwarzer Text auf grünem Grund (IBM-3270-Statusfeld)
    curses.init_pair(P_OIA,    curses.COLOR_BLACK, g)


# ── Klartext-ANSI (render.py) ──────────────────────────────────────────────
_TTY = sys.stdout.isatty()


def _c(code):
    return code if _TTY else ""


# Standard-ANSI-Farben (System-Palette des Terminals), kein Truecolor.
G   = _c("\033[32m")            # System-Grün
GH  = _c("\033[1;32m")          # hell = grün + fett
GD  = _c("\033[2;32m")          # dezent = grün gedimmt
CY  = _c("\033[36m")
YW  = _c("\033[33m")
RD  = _c("\033[31m")
W   = _c("\033[37m")
BGG = _c("\033[42m\033[30m")    # OIA: grüner Hintergrund, schwarzer Text
B   = _c("\033[1m")
N   = _c("\033[0m")
