# -*- coding: utf-8 -*-
"""Funktion: günstigstes Verbrauchsfenster als khal-Erinnerung exportieren.

Baut auf MARKT auf (markt.Overview.cheapest_window): das billigste
zusammenhängende Preisfenster ab jetzt wird als Kalendertermin mit Voralarm
angelegt. Als iCalendar-Ereignis (fester Standard, unabhängig vom khal-Datums-
format) mit tagesstabiler UID – ein erneuter Export am selben Tag aktualisiert
denselben Termin, statt einen zweiten anzulegen.

Bevorzugt wird die Datei direkt in das vdir-Verzeichnis des Zielkalenders
geschrieben (khal-Konfiguration wird dafür ausgelesen); khal indiziert die
geänderte Datei beim nächsten Aufruf selbst. So bleibt genau eine Datei pro Tag
liegen. Lässt sich das Verzeichnis nicht ermitteln, wird ersatzweise
»khal import« benutzt. Nur stdlib.
"""
import datetime as dt
import os
import shutil
import subprocess
import tempfile


class KhalError(Exception):
    pass


def available():
    """Ist die khal-CLI installiert?"""
    return shutil.which("khal") is not None


def calendars():
    """Namen der khal-Kalender (leere Liste bei Fehler)."""
    try:
        out = subprocess.run(["khal", "printcalendars"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    return [c.strip() for c in out.stdout.splitlines() if c.strip()]


# ── khal-Konfiguration (Kalenderpfade) ──────────────────────────────────────
def _khal_config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    p = os.path.join(base, "khal", "config")
    return p if os.path.exists(p) else None


def _parse_khal_config():
    """(paths, default) aus der khal-Konfig lesen.

    paths: dict Kalendername -> vdir-Verzeichnis (nur explizite ›type = calendar‹
    bzw. pfadgleiche Einträge). default: Name des Standardkalenders (oder None).
    """
    path = _khal_config_path()
    if not path:
        return {}, None
    paths, entries, default = {}, {}, None
    section = subsec = None
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[[") and line.endswith("]]"):
                    subsec = line[2:-2].strip().strip('"\'')
                    entries.setdefault(subsec, {})
                    continue
                if line.startswith("[") and line.endswith("]"):
                    section, subsec = line[1:-1].strip(), None
                    continue
                if "=" not in line:
                    continue
                k, v = (x.strip() for x in line.split("=", 1))
                v = v.strip('"\'')
                if section == "calendars" and subsec:
                    entries[subsec][k] = v
                elif section == "default" and k == "default_calendar":
                    default = v
    except OSError:
        return {}, None
    for name, kv in entries.items():
        p = kv.get("path")
        if not p or kv.get("type") not in (None, "calendar"):
            continue
        p = os.path.expanduser(os.path.expandvars(p))
        if os.path.isdir(p):
            paths[name] = p
    return paths, default


def _target_dir(calendar=None):
    """vdir-Verzeichnis des Zielkalenders bestimmen (oder None)."""
    paths, default = _parse_khal_config()
    if not paths:
        return None
    if calendar and calendar in paths:
        return paths[calendar]
    if default and default in paths:
        return paths[default]
    if len(paths) == 1:
        return next(iter(paths.values()))
    return paths.get(default) if default else None


# ── iCalendar ───────────────────────────────────────────────────────────────
def _ct(x):
    return f"{x:.1f}".replace(".", ",")


def _esc(text):
    """iCalendar-TEXT escapen (RFC 5545 §3.3.11)."""
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))


def _local_naive(d):
    """Aware- oder Naive-Zeit → naive lokale Zeit (schwebender ICS-Zeitstempel)."""
    if d.tzinfo is not None:
        d = d.astimezone().replace(tzinfo=None)
    return d


def _uid(start):
    return f"strom-cheap-{_local_naive(start):%Y%m%d}@strom"


def build_ics(start, end, avg_ct, reminder_min=30, brand="STROM", uid=None,
              note=None):
    """VEVENT für das günstige Fenster als iCalendar-Text (mit Voralarm) bauen."""
    start = _local_naive(start)
    end = _local_naive(end)
    uid = uid or _uid(start)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = f"⚡ Guenstiger Strom · {_ct(avg_ct)} ct/kWh"
    desc = (f"Guenstigstes Verbrauchsfenster laut Tibber: "
            f"{start:%H:%M}–{end:%H:%M} Uhr, "
            f"ø {_ct(avg_ct)} ct/kWh.")
    if note:
        desc += f"\n{note}"
    desc += f"\nErzeugt von {brand}."
    alarm = (f"Guenstiger Strom in {int(reminder_min)} min "
             f"({start:%H:%M} Uhr, {_ct(avg_ct)} ct/kWh)")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//strom//khal-export//DE",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{start:%Y%m%dT%H%M%S}",
        f"DTEND:{end:%Y%m%dT%H%M%S}",
        f"SUMMARY:{_esc(summary)}",
        f"DESCRIPTION:{_esc(desc)}",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_esc(alarm)}",
        f"TRIGGER:-PT{int(reminder_min)}M",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


# ── Export ──────────────────────────────────────────────────────────────────
def _write_vdir(target_dir, uid, ics):
    """Ereignis atomar als <uid>.ics ins vdir schreiben (in-place-Überschreiben)."""
    dest = os.path.join(target_dir, uid + ".ics")
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(ics)
    os.replace(tmp, dest)
    # khal indiziert geänderte Dateien beim nächsten Aufruf selbst; einmal
    # anstoßen, damit der Termin sofort sichtbar ist (Fehler ignorieren).
    try:
        subprocess.run(["khal", "list", "today", "1d"],
                       capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


def _import_cli(ics, calendar):
    """Ersatzweg: über »khal import --batch« einspielen."""
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".ics", delete=False,
                                         encoding="utf-8") as f:
            f.write(ics)
            tmp = f.name
        cmd = ["khal", "import", "--batch"]
        if calendar:
            cmd += ["-a", calendar]
        cmd.append(tmp)
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        raise KhalError(f"khal-Aufruf fehlgeschlagen: {e}")
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    if res.returncode != 0:
        msg = (res.stderr or res.stdout or "unbekannter Fehler").strip()
        raise KhalError(f"khal import: {msg}")


def export_window(start, end, avg_ct, reminder_min=30, calendar=None,
                  brand="STROM", note=None):
    """Erinnerung für das Fenster in khal anlegen (idempotent je Tag).

    Rückgabe: kurzer Bestätigungstext (Zeitraum · Preis). KhalError bei Problemen.
    """
    if not available():
        raise KhalError("khal ist nicht installiert (khal-CLI nicht gefunden).")
    ics = build_ics(start, end, avg_ct, reminder_min, brand, note=note)
    target = _target_dir(calendar)
    if target:
        try:
            _write_vdir(target, _uid(start), ics)
        except OSError as e:
            raise KhalError(f"Konnte Termin nicht schreiben: {e}")
    else:
        _import_cli(ics, calendar)      # Verzeichnis unbekannt → khal import
    s = _local_naive(start)
    e = _local_naive(end)
    return f"{s:%H:%M}–{e:%H:%M} Uhr · ø {_ct(avg_ct)} ct/kWh"
