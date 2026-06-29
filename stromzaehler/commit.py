# -*- coding: utf-8 -*-
"""Funktion: Zählerstand an Tibber übermitteln – mit Opt-in + 2FA-Gate.

Die sicherheitskritische Reihenfolge lebt nur hier (`perform`); CLI und TUI
liefern lediglich Callbacks für Ein-/Ausgabe. So gibt es genau einen Pfad, der
schreibt – und der tut es erst nach manueller Wert-Bestätigung UND nach
Eingabe eines per E-Mail zugestellten 2FA-Codes.

Schreibender, abrechnungsrelevanter Eingriff – siehe README/Memory.
"""
import random

from . import core
from .markt import MarktError
from .mail import MailError


class CommitAbort(Exception):
    """Vom Benutzer abgebrochen (kein Fehler)."""


class CommitError(Exception):
    """Commit fehlgeschlagen (Mail, Code falsch, Tibber-Fehler …)."""


def current_reading(client, meter_id):
    """Aktuellen inexogy-Zählerstand holen: (kWh float, kWh gerundet int)."""
    r = core.fetch_snapshot(client, meter_id)
    kwh = r["energy"]
    return kwh, int(round(kwh))


def make_code():
    return f"{random.randint(0, 999999):06d}"


def perform(client, meter_id, tibber, email, *,
            ask_value, confirm, notify, prompt_code, enabled=True):
    """Kompletter Commit-Ablauf. Callbacks:

      ask_value(default_int) -> int | None      Wert bestätigen/editieren (None=Abbruch)
      confirm(reading_int, home) -> bool         letzte Sicherheitsabfrage
      notify(msg) -> None                        Status anzeigen
      prompt_code() -> str | None                2FA-Code abfragen (None=Abbruch)

    Rückgabe: gesendeter Int-Wert. Wirft CommitAbort/CommitError.
    """
    if not enabled:
        raise CommitError("Commit ist deaktiviert (tibber_commit=on in der config).")
    if tibber is None:
        raise CommitError("Tibber ist nicht konfiguriert.")
    if not email:
        raise CommitError("Keine 2FA-E-Mail-Adresse konfiguriert.")

    # 1) Home + aktueller Zählerstand
    try:
        home_id, home = tibber.home_id()
    except MarktError as ex:
        raise CommitError(str(ex))
    _, default_int = current_reading(client, meter_id)

    # 2) Wert immer manuell bestätigen/editieren
    value = ask_value(default_int)
    if value is None:
        raise CommitAbort()
    value = int(value)
    if value < 0:
        raise CommitError("Zählerstand muss ≥ 0 sein.")

    # 3) Letzte Sicherheitsabfrage
    if not confirm(value, home):
        raise CommitAbort()

    # 4) 2FA-Code per Mail
    code = make_code()
    from . import mail
    try:
        mail.send_code(email, code, value, home)
    except MailError as ex:
        raise CommitError(f"Code-Mail fehlgeschlagen: {ex}")
    notify(f"Code an {email} gesendet.")

    # 5) Code prüfen
    entered = prompt_code()
    if entered is None:
        raise CommitAbort()
    if entered.strip() != code:
        raise CommitError("Falscher Code – nichts gesendet.")

    # 6) Schreiben
    try:
        tibber.send_meter_reading(value, home_id=home_id)
    except MarktError as ex:
        raise CommitError(f"Tibber: {ex}")
    return value
