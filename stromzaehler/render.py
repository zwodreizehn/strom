# -*- coding: utf-8 -*-
"""Klartext-Ausgabe (Momentaufnahmen) – für `strom now`, `strom watch`,
`strom meters`, `strom test` sowie für Pipes/Dateien. IBM-3270-Optik wie
netmon; Farben verschwinden automatisch ohne TTY (siehe theme.py)."""
import datetime as dt
import sys
import time

from . import core, brand
from .theme import G, GH, GD, CY, YW, RD, W, BGG, B, N

WIDTH = 60


def _w(p):
    if abs(p) >= 1000:
        return f"{p / 1000:.2f} kW".replace(".", ",")
    return f"{p:.0f} W"


def _kwh(e):
    return f"{e:.2f} kWh".replace(".", ",") if e is not None else "—"


def _bar(frac, width=24):
    frac = max(0.0, min(1.0, frac))
    fill = int(round(frac * width))
    return f"{G}{'█' * fill}{GD}{'░' * (width - fill)}{N}"


def _row(label, value, vc=G):
    dots = max(2, 24 - len(label))
    return f"  {W}{label.upper()}{GD}{'.' * dots}{N}  {vc}{value}{N}"


def _oia(meter, meter_id):
    ser = (meter or {}).get("printedFullSerialNumber") or meter_id[:14]
    left = f" {brand.OIA} "
    right = f" {ser}  {dt.datetime.now():%H:%M:%S} "
    mid = max(0, WIDTH - len(left) - len(right))
    print(f"{BGG}{B}{left}{' ' * mid}{right}{N}")


def _block(reading, today, today_out, scale, recent=None):
    live = reading["power"] != 0
    p = reading["power"] if live else (recent or 0.0)
    print()
    titel = "MOMENTANE LEISTUNG" if live else "LEISTUNG · Ø LETZTE 15 MIN"
    print(f"{W}{B}▌ {titel}{N}")
    print(f"  {GH}{B}{_w(abs(p)):>10}{N}  {_bar(abs(p) / scale)}"
          + (f"  {CY}↩ Einspeisung{N}" if p < 0 else ""))
    if any((reading["l1"], reading["l2"], reading["l3"])):
        for name, key in (("L1", "l1"), ("L2", "l2"), ("L3", "l3")):
            v = reading[key]
            print(f"  {CY}{name}{N} {_w(v):>9}  {_bar(abs(v) / scale, 18)}")
    else:
        print(f"  {GD}Phasen L1–L3: n. v. (SLP-Lastprofilzähler){N}")
    print()
    print(f"{W}{B}▌ HEUTE{N}")
    print(_row("Bezug heute", _kwh(today), GH))
    print(_row("Einspeisung heute", _kwh(today_out)))
    print(_row("Zählerstand Bezug", _kwh(reading["energy"])))
    print(_row("Zählerstand Einsp.", _kwh(reading["energy_out"])))


def snapshot(client, meter_id, meter=None):
    """Eine Momentaufnahme ausgeben."""
    r = core.fetch_snapshot(client, meter_id)
    try:
        be, bo = core.fetch_day_baseline(client, meter_id)
    except Exception:
        be = bo = None
    today = (r["energy"] - be) if be is not None else None
    today_out = (r["energy_out"] - bo) if bo is not None else None
    recent = None
    try:
        series = core.fetch_power_series(client, meter_id, hours=1)
        if series:
            recent = series[-1]["power"]
    except Exception:
        pass
    eff = r["power"] if r["power"] else (recent or 0.0)
    scale = max(500.0, abs(eff) * 1.15)
    _oia(meter, meter_id)
    _block(r, today, today_out, scale, recent)
    print()


def watch(client, meter_id, meter, sek):
    """Momentaufnahme alle <sek> Sekunden (Bildschirm wird gelöscht)."""
    try:
        while True:
            if sys.stdout.isatty():
                sys.stdout.write("\033[2J\033[H")
            snapshot(client, meter_id, meter)
            print(f"{GD}  ↻ alle {sek:g}s · Strg-C beendet{N}")
            time.sleep(sek)
    except KeyboardInterrupt:
        print()


def list_meters(client):
    """Alle Zähler des Kontos auflisten."""
    meters = client.meters()
    if not meters:
        print(f"{YW}Keine Zähler im Konto.{N}")
        return
    for m in meters:
        loc = m.get("location", {}) or {}
        ort = f"{loc.get('zip', '')} {loc.get('city', '')}".strip()
        print(f"{GH}{B}{m.get('printedFullSerialNumber', '?')}{N}  "
              f"{GD}{m.get('measurementType', '')}{N}")
        print(f"  meterId : {m.get('meterId')}")
        print(f"  Hersteller: {m.get('manufacturerId')}   Ort: {ort}")


def test(client, meter_id):
    """Verbindung/Login prüfen und einen Wert holen."""
    r = core.fetch_snapshot(client, meter_id)
    ts = dt.datetime.fromtimestamp(r["time"] / 1000)
    print(f"{G}✓ Login ok, meterId {meter_id}{N}")
    print(f"  letzte Messung {ts:%Y-%m-%d %H:%M:%S}  ·  "
          f"Leistung {_w(r['power'])}  ·  Zählerstand {_kwh(r['energy'])}")


# ── Marktpreise (Tibber) ────────────────────────────────────────────────────
_PRICE_COLORS = {"VERY_CHEAP": GH, "CHEAP": GH, "NORMAL": G,
                 "EXPENSIVE": YW, "VERY_EXPENSIVE": RD}


def _ct(c):
    return f"{c:.1f} ct".replace(".", ",")


def market(tibber):
    """Tibber-Preisübersicht für heute als Klartext-Tabelle."""
    if tibber is None:
        print(f"{YW}Tibber nicht konfiguriert "
              f"(tibber_email= / tibber_password= in der config).{N}")
        return
    ov = tibber.overview()
    _oia({"printedFullSerialNumber": f"TIBBER {ov.home}"}, "")
    mn, avg, mx = ov.stats()
    cheap, exp = ov.cheapest(), ov.most_expensive()
    print()
    if ov.current:
        c = ov.current
        col = _PRICE_COLORS.get(c.level, G)
        print(f"  {W}{B}JETZT{N}  {col}{B}{_ct(c.total)}/kWh{N}  "
              f"{col}{c.level_label()}{N}   "
              f"{GD}Energie {_ct(c.energy)} · Steuer/Abgaben {_ct(c.tax)}{N}")
    print(f"  {GD}ø heute {_ct(avg)}   "
          f"min {_ct(mn)}" + (f" um {cheap.start:%H}h" if cheap else "")
          + f"   max {_ct(mx)}" + (f" um {exp.start:%H}h" if exp else "") + N)
    print()
    rows = ov.today + ov.tomorrow
    lo = min(p.total for p in rows)
    hi = max(p.total for p in rows)
    span = (hi - lo) or 1.0
    ni = ov.now_index()
    for i, p in enumerate(rows):
        col = _PRICE_COLORS.get(p.level, G)
        mark = f"{CY}{B}▶{N}" if i == ni else " "
        tag = "" if p.start.date() == ov.today[0].start.date() else "+1"
        fill = int(round((p.total - lo) / span * 20))
        bar = f"{col}{'█' * fill}{GD}{'░' * (20 - fill)}{N}"
        print(f" {mark} {CY}{tag:>2}{p.start:%H}:00{N}  {col}{_ct(p.total):>8}{N}  "
              f"{bar}  {col}{p.level_label()}{N}")
    print()
