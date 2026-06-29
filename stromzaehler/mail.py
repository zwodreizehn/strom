# -*- coding: utf-8 -*-
"""Funktion: E-Mail-Versand über den himalaya-CLI-Mailer (für 2FA-Codes).

Kein Python-Mailpaket – es wird der vorhandene `himalaya`-Client genutzt
(`himalaya template send`, RFC822-Kopf + Body via stdin). Gleiches Muster wie
im kasse-Projekt. Absender/Konto per Umgebungsvariable überschreibbar.
"""
import os
import re
import shutil
import subprocess

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

FROM_NAME = os.environ.get("STROM_MAIL_NAME", "strom").strip() or "strom"
FROM_ADDR = os.environ.get("STROM_MAIL_FROM") or None      # via set_from()/config
ACCOUNT = os.environ.get("STROM_MAIL_ACCOUNT") or None     # None = himalaya-Default


def set_from(addr):
    """Absenderadresse des 2FA-Codes setzen (aus der Konfiguration, Whitelabel).
    Eine bereits per $STROM_MAIL_FROM gesetzte Adresse hat Vorrang."""
    global FROM_ADDR
    if not FROM_ADDR and addr:
        FROM_ADDR = str(addr).strip()


class MailError(Exception):
    pass


def _send(empfaenger, betreff, text):
    if not shutil.which("himalaya"):
        raise MailError("himalaya nicht gefunden (CLI-Mailer nicht installiert).")
    if not FROM_ADDR:
        raise MailError("Kein Absender konfiguriert (mail_from= bzw. "
                        "$STROM_MAIL_FROM setzen).")
    kopf = [f"From: {FROM_NAME} <{FROM_ADDR}>",
            f"To: {empfaenger}",
            f"Subject: {betreff}"]
    msg = "\n".join(kopf) + "\n\n" + text.rstrip() + "\n"
    cmd = ["himalaya", "template", "send"]
    if ACCOUNT:
        cmd += ["-a", ACCOUNT]
    try:
        r = subprocess.run(cmd, input=msg.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=90)
    except FileNotFoundError:
        raise MailError("himalaya nicht gefunden.")
    except subprocess.TimeoutExpired:
        raise MailError("Zeitüberschreitung beim Senden.")
    if r.returncode != 0:
        raise MailError(_fehlertext(r.stderr, r.stdout))


def _fehlertext(stderr, stdout):
    roh = (stderr or stdout).decode("utf-8", "replace")
    for z in roh.splitlines():
        z = re.sub(r"^\s*\d+:\s*", "", _ANSI.sub("", z).strip())
        if z and not z.startswith("Note:") and z.rstrip(":") != "Error":
            return z
    return "Senden fehlgeschlagen."


def send_code(empfaenger, code, reading_int, home):
    """2FA-Bestätigungscode für einen Zählerstand-Commit verschicken."""
    betreff = f"strom · Bestätigungscode {code}"
    text = (
        "Bestätigungscode für die Übermittlung eines Zählerstands an Tibber:\n\n"
        f"    {code}\n\n"
        f"Zählerstand: {reading_int} kWh\n"
        f"Tibber-Home: {home}\n\n"
        "Gib diesen Code im strom-Dashboard ein, um den Commit abzuschließen.\n"
        "Wenn du das nicht ausgelöst hast, ignoriere diese Mail – es wird nichts "
        "gesendet.\n"
    )
    _send(empfaenger, betreff, text)
