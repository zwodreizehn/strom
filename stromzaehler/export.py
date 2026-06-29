# -*- coding: utf-8 -*-
"""Funktion: nicht-interaktiver HTML/PHP-Export der Dashboard-Werte.

Erzeugt eine in sich geschlossene, handy-taugliche Seite (IBM-3270-Optik wie
die TUI) mit aktueller Leistung, Tagesverbrauch, Zählerständen, Tibber-Markt-
preisen und – fürs schnelle Entscheiden am Handy – einer **Empfehlung** (Ampel),
ob/wann sich der Maschinenbetrieb lohnt.

Die Werte werden zum Erzeugungszeitpunkt fest in die Seite geschrieben; der
PHP-Kopf setzt nur No-Cache-Header, damit der Browser stets die frisch
geschriebene Datei lädt. Gedacht für einen 10-Minuten-Cronjob
(`timed_export.sh`), der die Zieldatei jeweils atomar überschreibt.

Keine Interaktion, keine Schreibzugriffe auf Tibber – reine Anzeige.
"""
import datetime as dt
import html
import os

from . import core, brand

DEFAULT_OUT = os.path.expanduser(
    os.environ.get("STROM_EXPORT_PATH") or "~/strom.php")
META_REFRESH = 300        # Sekunden – Handy lädt selbsttätig nach
INTERVAL_MIN = 10         # Erwarteter Cron-Takt (nur für die Anzeige)


# ── Formatierung ─────────────────────────────────────────────────────────────
def _w(p):
    if abs(p) >= 1000:
        return f"{p / 1000:.2f} kW".replace(".", ",")
    return f"{p:.0f} W"


def _kwh(e):
    return f"{e:.2f} kWh".replace(".", ",") if e is not None else "—"


def _ct(c):
    return f"{c:.1f}".replace(".", ",")


# ── Empfehlung (Ampel) ───────────────────────────────────────────────────────
# level → (CSS-Klasse, Ampel, Kurztext)
_AMPEL = {
    "VERY_CHEAP":     ("gut",  "🟢", "sehr günstig"),
    "CHEAP":          ("gut",  "🟢", "günstig"),
    "NORMAL":         ("mittel", "🟡", "normal"),
    "EXPENSIVE":      ("teuer", "🔴", "teuer"),
    "VERY_EXPENSIVE": ("teuer", "🔴", "sehr teuer"),
}


def _cheapest_upcoming(ov):
    """Günstigste Stunde ab jetzt (heute+morgen) als PricePoint, oder None."""
    now = dt.datetime.now().astimezone()
    future = [p for p in (ov.today + ov.tomorrow)
              if p.start + dt.timedelta(hours=1) > now]
    if not future:
        future = ov.today
    return min(future, key=lambda p: p.total) if future else None


def _recommendation(ov):
    """(css_klasse, ampel_emoji, headline, detail) für die Empfehlungs-Box."""
    if ov is None or not ov.current:
        return ("grau", "⚪", "Keine Preisdaten",
                "Tibber-Marktpreise sind gerade nicht verfügbar – "
                "Entscheidung nach Gefühl bzw. später erneut prüfen.")
    c = ov.current
    css, ampel, lbl = _AMPEL.get(c.level, ("mittel", "🟡", "normal"))
    best = _cheapest_upcoming(ov)
    now_h = dt.datetime.now().astimezone().hour
    best_is_now = best is not None and best.start.hour == now_h \
        and best.start.date() == dt.date.today()

    if css == "gut":
        head = "JETZT läuft’s günstig – Maschinen jetzt einschalten"
        detail = (f"Aktuell {_ct(c.total)} ct/kWh ({lbl}). "
                  "Guter Zeitpunkt für stromintensive Arbeiten.")
    elif css == "mittel":
        head = "Mittlerer Preis – Betrieb möglich"
        if best is not None and not best_is_now:
            detail = (f"Aktuell {_ct(c.total)} ct/kWh ({lbl}). "
                      f"Etwas günstiger ab {best.start:%H}:00 Uhr "
                      f"({_ct(best.total)} ct/kWh).")
        else:
            detail = f"Aktuell {_ct(c.total)} ct/kWh ({lbl})."
    else:
        head = "Teuer – wenn möglich warten"
        if best is not None and not best_is_now:
            detail = (f"Aktuell {_ct(c.total)} ct/kWh ({lbl}). "
                      f"Deutlich günstiger ab {best.start:%H}:00 Uhr "
                      f"({_ct(best.total)} ct/kWh) – Betrieb bis dahin aufschieben.")
        else:
            detail = (f"Aktuell {_ct(c.total)} ct/kWh ({lbl}). "
                      "Heute keine wesentlich günstigere Stunde mehr.")
    return (css, ampel, head, detail)


# ── Daten holen ──────────────────────────────────────────────────────────────
def _gather(client, meter_id, tibber):
    """Snapshot + Tagesbasis + 15-Min-Leistung + Tibber-Übersicht einsammeln.
    Netzfehler werden je Quelle abgefangen; fehlende Teile bleiben None."""
    r = core.fetch_snapshot(client, meter_id)
    try:
        be, bo = core.fetch_day_baseline(client, meter_id)
    except Exception:
        be = bo = None
    today = (r["energy"] - be) if be is not None else None
    today_out = (r["energy_out"] - bo) if bo is not None else None
    recent, series = None, []
    try:
        series = core.fetch_power_series(client, meter_id, hours=3)
        if series:
            recent = series[-1]["power"]
    except Exception:
        pass
    ov = None
    if tibber is not None:
        try:
            ov = tibber.overview()
        except Exception:
            ov = None
    return r, today, today_out, recent, series, ov


# ── HTML/PHP bauen ───────────────────────────────────────────────────────────
def _price_bars(ov):
    """Tagespreis-Balken (heute) als HTML; aktuelle Stunde markiert."""
    if ov is None or not ov.today:
        return '<p class="hint">Keine Tibber-Preisdaten.</p>'
    rows = ov.today
    lo = min(p.total for p in rows)
    hi = max(p.total for p in rows)
    span = (hi - lo) or 1.0
    ni = ov.now_index()
    cells = []
    for i, p in enumerate(rows):
        h = 12 + int(round((p.total - lo) / span * 88))   # 12..100 %
        cls = _AMPEL.get(p.level, ("mittel", "", ""))[0]
        now = " now" if i == ni else ""
        label = f"{p.start:%H}"
        cells.append(
            f'<div class="bar{now}">'
            f'<span class="bw{now}"></span>'
            f'<i class="bf {cls}" style="height:{h}%"></i>'
            f'<span class="bl">{label}</span></div>')
    return '<div class="bars">' + "".join(cells) + "</div>"


def _build_html(r, today, today_out, recent, series, ov):
    now = dt.datetime.now()
    live = r["power"] != 0
    p = r["power"] if live else (recent or 0.0)
    leist_titel = "Momentane Leistung" if live else "Leistung · Ø letzte 15 Min"

    css_klasse, ampel, head, detail = _recommendation(ov)

    if ov and ov.current:
        c = ov.current
        mn, avg, mx = ov.stats()
        preis_block = (
            f'<div class="big">{_ct(c.total)}<small> ct/kWh</small></div>'
            f'<div class="sub">Ø heute {_ct(avg)} · min {_ct(mn)} · '
            f'max {_ct(mx)} ct</div>')
    else:
        preis_block = '<div class="sub">keine Preisdaten</div>'

    home = html.escape(ov.home) if ov else ""
    stand = now.strftime("%d.%m.%Y %H:%M")

    return f"""<?php
header("Cache-Control: no-cache, no-store, must-revalidate");
header("Pragma: no-cache");
header("Expires: 0");
?><!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="refresh" content="{META_REFRESH}">
<title>Strom · {home}</title>
<style>
  :root {{ --bg:#050805; --green:#27d34a; --dim:#1c8a32; --faint:#0d3b18;
           --amber:#e6b400; --red:#ff4d4d; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--green);
          font-family:"DejaVu Sans Mono",ui-monospace,Menlo,Consolas,monospace;
          -webkit-text-size-adjust:100%; padding:14px; max-width:560px;
          margin:0 auto; }}
  .oia {{ background:var(--green); color:#000; font-weight:bold; padding:4px 8px;
          display:flex; justify-content:space-between; letter-spacing:1px;
          font-size:13px; }}
  h2 {{ font-size:13px; letter-spacing:1px; color:#dfffe6; margin:18px 0 6px;
        border-bottom:1px solid var(--faint); padding-bottom:3px;
        text-transform:uppercase; }}
  .card {{ border:1px solid var(--faint); padding:12px 14px; margin-top:10px;
           border-radius:4px; }}
  .big {{ font-size:40px; font-weight:bold; color:#eafff0; line-height:1.1; }}
  .big small {{ font-size:16px; color:var(--dim); font-weight:normal; }}
  .sub {{ color:var(--dim); font-size:13px; margin-top:2px; }}
  .reco {{ border-width:2px; border-style:solid; padding:14px;
           border-radius:6px; margin-top:6px; }}
  .reco .h {{ font-size:18px; font-weight:bold; margin:4px 0 6px; }}
  .reco .d {{ font-size:14px; line-height:1.4; }}
  .reco.gut    {{ border-color:var(--green); background:#06210d; color:#aaffbe; }}
  .reco.mittel {{ border-color:var(--amber); background:#231d00; color:#ffe98a; }}
  .reco.teuer  {{ border-color:var(--red);   background:#240808; color:#ffb3b3; }}
  .reco.grau   {{ border-color:var(--dim);   background:#0a140c; color:#9fdfb0; }}
  .ampel {{ font-size:26px; vertical-align:middle; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  td {{ padding:3px 0; }}
  td.v {{ text-align:right; color:#eafff0; font-weight:bold; }}
  .bars {{ display:flex; align-items:flex-end; gap:2px; height:120px;
           margin-top:6px; }}
  .bar {{ flex:1; display:flex; flex-direction:column; align-items:center;
          justify-content:flex-end; height:100%; position:relative; }}
  .bf {{ width:100%; display:block; background:var(--dim); border-radius:1px; }}
  .bf.gut {{ background:var(--green); }}
  .bf.mittel {{ background:var(--amber); }}
  .bf.teuer {{ background:var(--red); }}
  .bar.now .bf {{ outline:1px solid #fff; }}
  .bw {{ position:absolute; top:-2px; font-size:11px; color:#fff; }}
  .bar.now .bw::before {{ content:"X"; }}
  .bl {{ font-size:9px; color:var(--dim); margin-top:2px; }}
  .foot {{ color:var(--dim); font-size:12px; margin-top:18px;
           text-align:center; }}
  .hint {{ color:var(--dim); font-size:13px; }}
</style>
</head>
<body>
<div class="oia"><span>{html.escape(brand.OIA)}</span><span>{stand}</span></div>

<div class="reco {css_klasse}">
  <div><span class="ampel">{ampel}</span></div>
  <div class="h">{html.escape(head)}</div>
  <div class="d">{html.escape(detail)}</div>
</div>

<h2>Marktpreis</h2>
<div class="card">{preis_block}</div>
{_price_bars(ov)}

<h2>{html.escape(leist_titel)}</h2>
<div class="card">
  <div class="big">{_w(abs(p))}{' <small>↩ Einspeisung</small>' if p < 0 else ''}</div>
  <table>
    <tr><td>Bezug heute</td><td class="v">{_kwh(today)}</td></tr>
    <tr><td>Einspeisung heute</td><td class="v">{_kwh(today_out)}</td></tr>
    <tr><td>Zählerstand Bezug</td><td class="v">{_kwh(r['energy'])}</td></tr>
    <tr><td>Zählerstand Einsp.</td><td class="v">{_kwh(r['energy_out'])}</td></tr>
  </table>
</div>

<div class="foot">
  Stand {stand} Uhr · aktualisiert alle {INTERVAL_MIN} Min ·
  Seite lädt selbst alle {META_REFRESH // 60} Min neu{(' · Tibber ' + home) if home else ''}
</div>
</body>
</html>
"""


# ── Schreiben ────────────────────────────────────────────────────────────────
def _write_atomic(path, text):
    """Datei atomar (über .tmp + replace) überschreiben."""
    d = os.path.dirname(path) or "."
    tmp = os.path.join(d, ".strom.php.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def generate(client, meter_id, tibber, out_path=None):
    """Seite erzeugen und an out_path (Default aus export_path/~/strom.php)
    schreiben. Rückgabe: geschriebener Pfad."""
    out_path = out_path or DEFAULT_OUT
    r, today, today_out, recent, series, ov = _gather(client, meter_id, tibber)
    text = _build_html(r, today, today_out, recent, series, ov)
    _write_atomic(out_path, text)
    return out_path
