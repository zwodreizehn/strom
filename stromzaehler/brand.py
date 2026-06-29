# -*- coding: utf-8 -*-
"""Whitelabel-Branding: das Label der OIA-Statusleiste (oben links).

Wird beim Start einmal aus der Konfiguration gesetzt (`brand=` bzw.
$STROM_BRAND). Default ist die generische Retro-Beschriftung; eigene Marken
einfach per Konfiguration überschreiben. So bleibt das Werkzeug whitelabel-fähig,
ohne dass Modul-Signaturen das Label durchreichen müssen.
"""

#: Label oben links in der Status-/OIA-Leiste (TUI, Klartext, Web-Export).
OIA = "IBM 3270 ▐ STROM"


def set_label(label):
    """Branding setzen (leer/None lässt den Default stehen)."""
    global OIA
    if label and str(label).strip():
        OIA = str(label).strip()
