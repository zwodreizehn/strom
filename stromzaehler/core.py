# -*- coding: utf-8 -*-
"""Funktion: Einheiten-Umrechnung, abgeleitete Kennzahlen, Session-Historie.

Roh-Einheiten der API (empirisch bestätigt, Stand 2026-06; geprüft gegen das
Energie-Delta der Stundenwerte – 204900 mW == 0,2049 kWh/h):

    power, power1..power3 : Milliwatt (mW)   →  Watt = roh / 1000
    energy, energyOut     : 10^-10 kWh       →  kWh  = roh / 1e10

Geschäftslogik (Was bedeuten die Zahlen) lebt hier; reine HTTP-Zugriffe in
api.py, Darstellung in tui.py / render.py.
"""
import datetime as dt
from collections import deque

MW_PER_W = 1000.0
RAW_PER_KWH = 1e10


def w(mw):
    """Milliwatt → Watt."""
    return (mw or 0) / MW_PER_W


def kwh(raw):
    """10^-10 kWh → kWh."""
    return (raw or 0) / RAW_PER_KWH


def parse_reading(d):
    """API-last_reading → flaches dict in SI-Einheiten (W bzw. kWh)."""
    v = d.get("values", {}) or {}
    return {
        "time": d.get("time", 0),                 # ms-Epoch
        "power": w(v.get("power")),               # Gesamtleistung (W)
        "l1": w(v.get("power1")),                 # je Phase (W)
        "l2": w(v.get("power2")),
        "l3": w(v.get("power3")),
        "energy": kwh(v.get("energy")),           # Zählerstand Bezug (kWh)
        "energy_out": kwh(v.get("energyOut")),    # Zählerstand Einspeisung (kWh)
    }


def fetch_snapshot(client, meter_id):
    """Eine Live-Momentaufnahme holen und umrechnen."""
    return parse_reading(client.last_reading(meter_id))


def fetch_power_series(client, meter_id, hours=6):
    """15-Minuten-Leistungsreihe (W) der letzten <hours> Stunden.

    SLP-Lastprofilzähler liefern keine 2-Sekunden-Momentanleistung
    (last_reading.power ≈ 0). Aus den 15-Min-Intervallen ergibt sich aber die
    mittlere Leistung (= Energie-Delta je Viertelstunde). Rückgabe: Liste
    [{'time': ms, 'power': W}], chronologisch."""
    now = int(dt.datetime.now().timestamp() * 1000)
    frm = now - int(hours * 3600 * 1000)
    rows = client.readings(meter_id, frm, resolution="fifteen_minutes",
                           fields=["power"])
    return [{"time": r.get("time", 0), "power": w(r.get("values", {}).get("power"))}
            for r in rows]


def fetch_day_baseline(client, meter_id, day=None):
    """Zählerstände (Bezug, Einspeisung) zu Tagesbeginn → für 'Verbrauch heute'.
    Liefert (energy_kwh, energy_out_kwh); fehlende Werte als None."""
    day = day or dt.date.today()
    midnight = dt.datetime(day.year, day.month, day.day)
    frm = int(midnight.timestamp() * 1000)
    rows = client.readings(meter_id, frm, resolution="one_hour",
                           fields=["energy", "energyOut"])
    if not rows:
        return None, None
    first = rows[0].get("values", {})
    return kwh(first.get("energy")), kwh(first.get("energyOut"))


class Session:
    """Live-Zustand des Dashboards: letzte Messung, Watt-Historie (Sparkline,
    Min/Ø/Max) und Tagesbasis (Zählerstand um Mitternacht)."""

    def __init__(self, maxlen=600):
        self.history = deque(maxlen=maxlen)   # Watt-Werte (Gesamtleistung)
        self.last = None                      # zuletzt umgerechnete Messung
        self.error = None                     # letzter Fehlertext (oder None)
        self.updated = None                   # datetime der letzten Antwort
        self.day = None                       # Datum der gesetzten Tagesbasis
        self.base_energy = None               # kWh-Zählerstand Tagesbeginn
        self.base_energy_out = None
        self.count = 0                        # Anzahl erfolgreicher Messungen
        # 15-Minuten-Leistungsreihe (SLP-Zähler ohne Momentanleistung)
        self.power_series = []                # [{'time','power'}], chronologisch
        self.recent_power = None              # W der letzten 15-Min-Stufe
        self.recent_power_time = None         # ms-Epoch dazu
        self.power_updated = None
        # Marktpreis-Übersicht (Tibber) – optional, separat aktualisiert
        self.market = None                    # markt.Overview | None
        self.market_error = None
        self.market_updated = None
        self.market_hour = None               # Stunde der letzten Markt-Abfrage

    def update(self, reading):
        self.last = reading
        self.error = None
        self.updated = dt.datetime.now()
        self.history.append(reading["power"])
        self.count += 1

    def set_error(self, msg):
        self.error = msg
        self.updated = dt.datetime.now()

    def set_baseline(self, energy, energy_out, day):
        self.day = day
        self.base_energy = energy
        self.base_energy_out = energy_out

    def set_power_series(self, series):
        self.power_series = series or []
        self.power_updated = dt.datetime.now()
        if self.power_series:
            last = self.power_series[-1]
            self.recent_power = last["power"]
            self.recent_power_time = last["time"]

    def power_stats(self):
        """(min, ø, max) der 15-Min-Leistungsreihe in W."""
        if not self.power_series:
            return (0.0, 0.0, 0.0)
        p = [x["power"] for x in self.power_series]
        return (min(p), sum(p) / len(p), max(p))

    def set_market(self, overview):
        self.market = overview
        self.market_error = None
        self.market_updated = dt.datetime.now()
        self.market_hour = dt.datetime.now().hour

    def set_market_error(self, msg):
        self.market_error = msg
        self.market_updated = dt.datetime.now()
        self.market_hour = dt.datetime.now().hour

    def stats(self):
        """(min, ø, max) der Watt-Historie."""
        if not self.history:
            return (0.0, 0.0, 0.0)
        h = list(self.history)
        return (min(h), sum(h) / len(h), max(h))

    def today_kwh(self):
        """Bezug heute (kWh) oder None, wenn Basis/Messung fehlt."""
        if self.last is None or self.base_energy is None:
            return None
        return max(0.0, self.last["energy"] - self.base_energy)

    def today_out_kwh(self):
        """Einspeisung heute (kWh) oder None."""
        if self.last is None or self.base_energy_out is None:
            return None
        return max(0.0, self.last["energy_out"] - self.base_energy_out)


def resolve_meter(client, meter_id=None):
    """meterId sicherstellen. Gibt (meter_id, meter_dict|None) zurück.
    Ohne Vorgabe wird der erste Zähler des Kontos gewählt."""
    if meter_id:
        meter = None
        try:
            for m in client.meters():
                if m.get("meterId") == meter_id:
                    meter = m
                    break
        except Exception:
            pass
        return meter_id, meter
    meters = client.meters()
    if not meters:
        from .api import ApiError
        raise ApiError("Keine Zähler im Konto gefunden.")
    return meters[0]["meterId"], meters[0]
