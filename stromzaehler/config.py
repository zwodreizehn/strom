# -*- coding: utf-8 -*-
"""Inhalt: Zugangsdaten & Einstellungen laden.

Reihenfolge (zuerst gewinnt): Umgebungsvariablen > Konfigdatei.
Standard-Konfigdatei ~/.config/strom/config (via $STROM_CONFIG_DIR
überschreibbar), Format = einfache KEY=WERT-Zeilen:

    email=du@example.com
    password=geheim
    meter_id=…          # optional, wird sonst automatisch ermittelt
    interval=2          # optional, Sekunden zwischen Live-Abfragen
    tibber_token=…      # optional – Developer-Token (developer.tibber.com),
                        #            bevorzugt für die Marktpreis-Übersicht
    tibber_email=…      # optional – Fallback statt Token (App-Login)
    tibber_password=…   # optional
    tibber_home=…       # optional – appNickname-Teil oder Index, sonst erstes
    tibber_commit=on    # optional – schaltet Zählerstand-Commit frei (Default aus)
    commit_email=…      # optional – Ziel für den 2FA-Code (Default: email)
    chart_height=7      # optional – Zeilenhöhe der Verlauf-/Markt-Charts
                        #            (0 = automatisch ~90 % des Restplatzes)
    brand=…             # optional – Label oben links (Whitelabel)
    export_path=…       # optional – Ziel von `strom export` (Default ~/strom.php)
    mail_from=…         # optional – Absender des 2FA-Codes (Default: commit_email)
    khal_calendar=…     # optional – khal-Kalender für Erinnerungen (Default: khals eigener)
    khal_reminder=30    # optional – Voralarm in Minuten (Default 30)

Die Datei wird beim Schreiben auf Modus 600 gesetzt (nur du lesbar).

Beim allerersten Start ohne Konfiguration startet der interaktive Einrichtungs-
Assistent (siehe wizard.py) und legt diese Datei an.
"""
import os

CONFIG_DIR = os.environ.get("STROM_CONFIG_DIR", os.path.expanduser("~/.config/strom"))
CONFIG_FILE = os.path.join(CONFIG_DIR, "config")


class ConfigError(Exception):
    pass


def _int(raw, default):
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return default


def _read_file():
    data = {}
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                data[k.strip().lower()] = v.strip()
    except FileNotFoundError:
        pass
    return data


def load():
    """Liefert dict(email, password, meter_id, interval) oder ConfigError."""
    f = _read_file()
    email = os.environ.get("STROM_EMAIL") or f.get("email")
    password = os.environ.get("STROM_PASSWORD") or f.get("password")
    meter_id = os.environ.get("STROM_METER") or f.get("meter_id") or None
    raw_iv = os.environ.get("STROM_INTERVAL") or f.get("interval") or "2"
    try:
        interval = max(1.0, float(raw_iv.replace(",", ".")))
    except ValueError:
        interval = 2.0
    raw_ch = os.environ.get("STROM_CHART_HEIGHT") or f.get("chart_height") or "0"
    try:
        chart_height = max(0, int(raw_ch))     # 0 = automatisch (~90 % Restplatz)
    except ValueError:
        chart_height = 0
    if not email or not password:
        raise ConfigError(
            "Keine Zugangsdaten gefunden.\n"
            f"Lege {CONFIG_FILE} an mit:\n"
            "    email=du@example.com\n"
            "    password=…\n"
            "oder setze die Umgebungsvariablen STROM_EMAIL / STROM_PASSWORD.")
    return {
        "email": email, "password": password,
        "meter_id": meter_id, "interval": interval,
        "chart_height": chart_height,
        # Marktpreis-Übersicht (Tibber) – optional
        "tibber_token": os.environ.get("STROM_TIBBER_TOKEN") or f.get("tibber_token"),
        "tibber_email": os.environ.get("STROM_TIBBER_EMAIL") or f.get("tibber_email"),
        "tibber_password": (os.environ.get("STROM_TIBBER_PASSWORD")
                            or f.get("tibber_password")),
        "tibber_home": os.environ.get("STROM_TIBBER_HOME") or f.get("tibber_home"),
        # Zählerstand-Commit (schreibend) – Opt-in, Default aus
        "tibber_commit": (os.environ.get("STROM_TIBBER_COMMIT")
                          or f.get("tibber_commit") or "").lower()
                         in ("1", "on", "true", "yes", "ja"),
        "commit_email": (os.environ.get("STROM_COMMIT_EMAIL")
                         or f.get("commit_email") or email),
        # Whitelabel / Web-Export / Mail – optional
        "brand": os.environ.get("STROM_BRAND") or f.get("brand") or None,
        "export_path": os.path.expanduser(
            os.environ.get("STROM_EXPORT_PATH") or f.get("export_path")
            or "~/strom.php"),
        "mail_from": (os.environ.get("STROM_MAIL_FROM") or f.get("mail_from")
                      or os.environ.get("STROM_COMMIT_EMAIL")
                      or f.get("commit_email") or email),
        # khal-Erinnerung (günstiges Fenster) – optional
        "khal_calendar": (os.environ.get("STROM_KHAL_CALENDAR")
                          or f.get("khal_calendar") or None),
        "khal_reminder": _int(os.environ.get("STROM_KHAL_REMINDER")
                              or f.get("khal_reminder"), 30),
    }


def exists():
    """True, wenn eine Konfiguration mit Zugangsdaten vorliegt (Datei o. Env)."""
    if os.environ.get("STROM_EMAIL") and os.environ.get("STROM_PASSWORD"):
        return True
    f = _read_file()
    return bool(f.get("email") and f.get("password"))


def save_all(data):
    """Komplette Konfiguration schreiben (Einrichtungs-Assistent), Modus 600.
    Leere Werte werden weggelassen."""
    clean = {k: v for k, v in data.items() if v not in (None, "")}
    _write(clean)
    return CONFIG_FILE


def save_meter_id(meter_id):
    """Ermittelte meterId in die Konfigdatei schreiben (Cache)."""
    data = _read_file()
    data["meter_id"] = meter_id
    _write(data)


def _write(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for k, v in data.items():
            f.write(f"{k}={v}\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_FILE)
