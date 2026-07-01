# -*- coding: utf-8 -*-
"""Einstieg: Befehlszeile und Start des Live-Dashboards."""
import sys

from . import config, api, core, render, markt, brand, wizard, khal
from .theme import GH, YW, RD, N, B
from . import __version__

HELP = f"""\
{GH}{B}strom{N} – Live-Stromzähler-Dashboard (inexogy / vormals Discovergy)

  strom                interaktives Live-Dashboard (TUI)
  strom now            einmalige Momentaufnahme (Klartext)
  strom watch [SEK]    Momentaufnahme alle SEK Sekunden (Default 5)
  strom markt          Tibber-Marktpreise heute (Klartext)
  strom khal [STD] [--note T] [-y]  günstiges Fenster als khal-Erinnerung
  strom export [PFAD]  HTML/PHP-Seite schreiben (Default aus export_path)
  strom commit         aktuellen Zählerstand an Tibber senden (Opt-in + 2FA)
  strom meters         alle Zähler des Kontos auflisten
  strom setup          Einrichtungs-Assistent (Konfiguration neu anlegen)
  strom test           Verbindung/Login prüfen
  strom version | help

Beim allerersten Start (ohne Konfiguration) startet automatisch der
Einrichtungs-Assistent. Zugangsdaten liegen danach in
~/.config/strom/config  (email=, password=)  oder kommen aus den
Umgebungsvariablen STROM_EMAIL / STROM_PASSWORD.
Marktpreise optional über tibber_token= bzw. tibber_email= / tibber_password=.
"""


def _setup():
    """Config laden, Client bauen, meterId sicherstellen.
    Rückgabe: (client, meter_id, meter, cfg, tibber)."""
    cfg = config.load()
    client = api.Client(cfg["email"], cfg["password"])
    meter_id = cfg["meter_id"]
    if meter_id:
        meter_id, meter = core.resolve_meter(client, meter_id)
    else:
        meter_id, meter = core.resolve_meter(client, None)
        config.save_meter_id(meter_id)
    tibber = None
    if cfg.get("tibber_token") or (cfg.get("tibber_email")
                                   and cfg.get("tibber_password")):
        tibber = markt.Tibber(email=cfg.get("tibber_email"),
                              password=cfg.get("tibber_password"),
                              token=cfg.get("tibber_token"),
                              home=cfg.get("tibber_home"))
    return client, meter_id, meter, cfg, tibber


def _commit_cli(client, meter_id, tibber, cfg):
    """Interaktiver Zählerstand-Commit (Opt-in + 2FA) auf der Kommandozeile."""
    from . import commit

    def ask_value(default_int):
        s = input(f"Zählerstand in kWh [{default_int}] (Enter=übernehmen, "
                  f"q=Abbruch): ").strip()
        if s.lower() in ("q", "quit", "abbruch", "abbrechen"):
            return None
        if not s:
            return default_int
        if not s.isdigit():
            print(f"{RD}Ungültige Zahl.{N}")
            return None
        return int(s)

    def confirm(val, home):
        a = input(f"{val} kWh an Tibber-Home »{home}« senden? "
                  f"Ein Code wird an {cfg['commit_email']} gemailt. (j/N) ")
        return a.strip().lower() in ("j", "ja", "y", "yes")

    def prompt_code():
        s = input("Code aus der E-Mail (leer=Abbruch): ").strip()
        return s or None

    try:
        val = commit.perform(
            client, meter_id, tibber, cfg["commit_email"],
            ask_value=ask_value, confirm=confirm, notify=lambda m: print(m),
            prompt_code=prompt_code, enabled=cfg["tibber_commit"])
        print(f"{GH}{B}✓ Zählerstand {val} kWh an Tibber gesendet.{N}")
    except commit.CommitAbort:
        print("Abgebrochen – nichts gesendet.")
    except commit.CommitError as e:
        print(f"{RD}{e}{N}")


def _khal_cli(tibber, cfg, argv):
    """Günstigstes Verbrauchsfenster als khal-Erinnerung anlegen.

    Argumente: [STUNDEN] [--note TEXT] [-y|--yes]. Ohne -y wird vor dem
    Eintragen zurückgefragt; -y überspringt die Rückfrage (für Cron/Skripte).
    """
    if not khal.available():
        print(f"{RD}khal ist nicht installiert (khal-CLI nicht gefunden).{N}")
        return
    if tibber is None:
        print(f"{RD}Tibber ist nicht konfiguriert – der khal-Export baut auf "
              f"den Marktpreisen auf.{N}")
        return
    hours, note, assume_yes = 1, None, False
    rest, i = argv[1:], 0
    while i < len(rest):
        a = rest[i]
        if a in ("-y", "--yes", "--ja", "--y"):
            assume_yes = True
        elif a == "--note":
            i += 1
            note = rest[i] if i < len(rest) else None
        elif a.startswith("--note="):
            note = a[len("--note="):] or None
        elif a.isdigit():
            hours = max(1, int(a))
        else:
            print(f"{YW}Unbekanntes Argument: {a}{N}")
        i += 1

    ov = tibber.overview()
    win = ov.cheapest_window(hours)
    if not win:
        print(f"{RD}Keine Preisdaten für ein {hours}-Stunden-Fenster.{N}")
        return
    start, end, avg = win
    reminder = cfg.get("khal_reminder", 30)
    cal = cfg.get("khal_calendar") or "khals Standardkalender"
    av = f"{avg:.1f}".replace(".", ",")

    print(f"{GH}{B}Folgender Termin wird in khal eingetragen:{N}")
    print(f"  ⚡ Günstiger Strom · {av} ct/kWh")
    print(f"  {start:%a %d.%m.}  {start:%H:%M}–{end:%H:%M} Uhr")
    print(f"  Kalender: {cal}")
    print(f"  Voralarm: {reminder} min vorher")
    if note:
        print(f"  Notiz:    {note}")

    if not assume_yes:
        if not sys.stdin.isatty():
            print(f"{RD}Keine Rückfrage möglich (keine Eingabe). "
                  f"Für Cron/Skripte -y verwenden.{N}")
            return
        try:
            ans = input("Eintragen? (J/n) ").strip().lower()
        except EOFError:
            ans = "n"
        if ans in ("n", "nein", "no"):
            print("Abgebrochen – nichts eingetragen.")
            return

    summary = khal.export_window(
        start, end, avg, reminder_min=reminder,
        calendar=cfg.get("khal_calendar"), brand=cfg.get("brand") or "STROM",
        note=note)
    print(f"{GH}{B}✓ khal-Erinnerung angelegt:{N} {summary} "
          f"(Voralarm {reminder} min)")


def main(argv):
    cmd = argv[0] if argv else None

    if cmd in ("help", "-h", "--help"):
        print(HELP)
        return
    if cmd in ("version", "-v", "--version"):
        print(f"strom {__version__}")
        return

    # Erststart bzw. ausdrücklicher Wunsch: Einrichtungs-Assistent.
    if cmd == "setup":
        try:
            wizard.run()
        except KeyboardInterrupt:
            print("\nAbgebrochen – nichts gespeichert.")
        return
    try:
        if not config.exists():
            if not wizard.maybe_run():
                raise config.ConfigError(
                    "Keine Konfiguration. Starte »strom setup« auf einem "
                    "Terminal oder setze STROM_EMAIL / STROM_PASSWORD.")
    except config.ConfigError as e:
        print(f"{RD}{e}{N}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAbgebrochen – nichts gespeichert.")
        return

    # Der erste API-Zugriff kann je nach Netz einige Sekunden blockieren –
    # kurz Rückmeldung geben (nur auf einem TTY), damit der Start nicht stumm
    # wirkt. Fehler und Strg-C dabei sauber abfangen statt Traceback.
    _hint = sys.stderr.isatty()
    if _hint:
        print("» Verbinde mit inexogy …", file=sys.stderr, flush=True)
    try:
        client, meter_id, meter, cfg, tibber = _setup()
    except config.ConfigError as e:
        print(f"{RD}{e}{N}")
        sys.exit(1)
    except api.ApiError as e:
        print(f"{RD}Verbindung zur inexogy-API fehlgeschlagen: {e}{N}")
        print(f"{YW}Das ist meist ein API- oder Netzproblem, nicht deine "
              f"Konfiguration – bitte später erneut versuchen.{N}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        sys.exit(130)
    brand.set_label(cfg.get("brand"))
    from . import mail
    mail.set_from(cfg.get("mail_from"))

    try:
        if cmd is None:
            if sys.stdin.isatty() and sys.stdout.isatty():
                from . import tui
                tui.run(client, meter_id, meter, cfg["interval"], tibber,
                        cfg["tibber_commit"], cfg["commit_email"],
                        cfg["chart_height"], cfg.get("khal_calendar"),
                        cfg.get("khal_reminder", 30))
            else:
                render.snapshot(client, meter_id, meter)
        elif cmd == "now":
            render.snapshot(client, meter_id, meter)
        elif cmd == "watch":
            sek = 5.0
            if len(argv) > 1:
                try:
                    sek = max(1.0, float(argv[1].replace(",", ".")))
                except ValueError:
                    pass
            render.watch(client, meter_id, meter, sek)
        elif cmd == "markt":
            render.market(tibber)
        elif cmd == "khal":
            _khal_cli(tibber, cfg, argv)
        elif cmd == "export":
            from . import export
            out = argv[1] if len(argv) > 1 else cfg.get("export_path")
            path = export.generate(client, meter_id, tibber, out)
            print(f"{GH}{B}✓ Seite geschrieben:{N} {path}")
        elif cmd == "commit":
            _commit_cli(client, meter_id, tibber, cfg)
        elif cmd == "meters":
            render.list_meters(client)
        elif cmd == "test":
            render.test(client, meter_id)
        else:
            print(HELP)
    except api.ApiError as e:
        print(f"{RD}{e}{N}")
        sys.exit(1)
    except markt.MarktError as e:
        print(f"{RD}Tibber: {e}{N}")
        sys.exit(1)
    except khal.KhalError as e:
        print(f"{RD}khal: {e}{N}")
        sys.exit(1)
    except KeyboardInterrupt:
        pass
