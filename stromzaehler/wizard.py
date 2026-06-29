# -*- coding: utf-8 -*-
"""Funktion: interaktiver Einrichtungs-Assistent (Erststart).

Läuft, wenn noch keine Konfiguration mit Zugangsdaten existiert und ein TTY
vorhanden ist. Fragt die nötigen Keys/Variablen ab und schreibt daraus die
Konfigurationsdatei (Modus 600). So lässt sich das Werkzeug als Whitelabel-
Lösung ohne vorbereitete Datei in Betrieb nehmen.
"""
import getpass
import sys

from . import config
from .theme import GH, GD, YW, RD, N, B


def _ask(prompt, default=None, secret=False, required=False):
    """Eine Eingabe abfragen. Leere Eingabe → default. Schleift bei required."""
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        try:
            if secret:
                val = getpass.getpass(f"  {prompt}{suffix}: ").strip()
            else:
                val = input(f"  {prompt}{suffix}: ").strip()
        except EOFError:
            val = ""
        if not val and default is not None:
            return default
        if not val and required:
            print(f"  {RD}Pflichtfeld – bitte ausfüllen.{N}")
            continue
        return val or None


def _yesno(prompt, default=False):
    d = "J/n" if default else "j/N"
    val = (_ask(f"{prompt} ({d})", default="") or "").strip().lower()
    if not val:
        return default
    return val in ("j", "ja", "y", "yes")


def run():
    """Assistent ausführen und Konfiguration schreiben. Rückgabe: Pfad."""
    print(f"\n{GH}{B}strom – Einrichtung{N}")
    print(f"{GD}  Keine Konfiguration gefunden. Ein paar Angaben, dann läuft's.")
    print(f"  Felder mit Default per Enter übernehmen. Strg-C bricht ab.{N}\n")

    data = {}

    print(f"{B}1) Stromzähler (inexogy / vormals Discovergy){N}")
    data["email"] = _ask("inexogy E-Mail/Login", required=True)
    data["password"] = _ask("inexogy Passwort", secret=True, required=True)
    data["meter_id"] = _ask("Zähler-ID (leer = automatisch ermitteln)")
    data["interval"] = _ask("Abfrage-Intervall in Sekunden", default="2")

    print(f"\n{B}2) Darstellung{N}")
    data["brand"] = _ask("Label oben links (leer = Default 'IBM 3270 ▐ STROM')")
    data["chart_height"] = _ask("Chart-Höhe in Zeilen (0 = automatisch)",
                                default="0")

    print(f"\n{B}3) Marktpreise (Tibber) – optional{N}")
    if _yesno("Tibber-Marktpreise einbinden?", default=False):
        print(f"{GD}  Empfohlen: Developer-Token von developer.tibber.com.")
        print(f"  Alternativ App-Login per E-Mail/Passwort.{N}")
        data["tibber_token"] = _ask("Tibber Developer-Token (leer = App-Login)")
        if not data["tibber_token"]:
            data["tibber_email"] = _ask("Tibber E-Mail")
            data["tibber_password"] = _ask("Tibber Passwort", secret=True)
        data["tibber_home"] = _ask("Tibber-Home (appNickname-Teil/Index, leer = 1.)")

        print(f"\n{B}4) Zählerstand an Tibber senden – optional, schreibend{N}")
        print(f"{GD}  Abgesichert per Opt-in + 2FA-Code per E-Mail.{N}")
        if _yesno("Commit-Funktion freischalten?", default=False):
            data["tibber_commit"] = "on"
            data["commit_email"] = _ask("Ziel für den 2FA-Code",
                                        default=data["email"])
            data["mail_from"] = _ask("Absender des 2FA-Codes (himalaya)",
                                     default=data["commit_email"])

    print(f"\n{B}5) Web-Export – optional{N}")
    if _yesno("HTML/PHP-Seite per 'strom export' schreiben?", default=False):
        data["export_path"] = _ask("Zielpfad der Seite", default="~/strom.php")

    path = config.save_all(data)
    print(f"\n{GH}{B}✓ Konfiguration gespeichert:{N} {path}")
    print(f"{GD}  Ändern jederzeit von Hand möglich; Werte siehe README.{N}\n")
    return path


def maybe_run():
    """Assistent nur starten, wenn nötig (keine Config) und sinnvoll (TTY).
    Rückgabe: True, wenn eingerichtet wurde; False sonst."""
    if config.exists():
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    run()
    return True
