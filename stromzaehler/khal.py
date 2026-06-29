# -*- coding: utf-8 -*-
"""Funktion (Stub): Erinnerungs-Export nach khal (CLI-Kalender).

Geplant: günstige Verbrauchsfenster (aus markt.py → cheapest_window) als
Kalender-Erinnerung exportieren, z. B. via `khal new` oder eine .ics-Datei.
Bewusst noch nicht verdrahtet; siehe README → 'Noch offen'.
"""
import shutil


def available():
    """Ist die khal-CLI installiert?"""
    return shutil.which("khal") is not None


def export_reminder(start, end, summary, description=""):
    """Erinnerung in khal anlegen. Noch nicht implementiert.

    Vorgesehen (Beispiel):
        khal new <start> <end> <summary> :: <description>
    """
    raise NotImplementedError("khal-Export ist noch nicht implementiert.")
