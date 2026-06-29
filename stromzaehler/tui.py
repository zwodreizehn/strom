# -*- coding: utf-8 -*-
"""Live-Dashboard (curses): htop-artige UX, IBM-3270-Optik.

Ein Hintergrund-Thread pollt den Zähler (last_reading) im eingestellten
Intervall; die Oberfläche zeichnet flüssig neu (≈4 fps) und blockiert nie auf
dem Netz. Nicht-scrollendes Vollbild mit OIA-Leisten oben/unten (wie netmon):
oben Statusfeld mit Uhr, unten Funktionstasten. Reine stdlib (curses).
"""
import curses
import datetime as dt
import threading

from . import core, khal, theme, bigfont, brand
from .theme import (P_GREEN, P_BRIGHT, P_DIM, P_CYAN, P_YELLOW, P_RED,
                    P_OIA, P_BLUE)

SPARK = "▁▂▃▄▅▆▇█"
SPIN = "|/-\\"


def run(client, meter_id, meter, interval, tibber=None,
        commit_enabled=False, commit_email=None, chart_height=0):
    curses.wrapper(_main, client, meter_id, meter, interval, tibber,
                   commit_enabled, commit_email, chart_height)


def _main(stdscr, client, meter_id, meter, interval, tibber,
          commit_enabled, commit_email, chart_height):
    try:
        curses.set_escdelay(25)
    except Exception:
        pass
    curses.curs_set(0)
    theme.setup_colors()
    App(stdscr, client, meter_id, meter, interval, tibber,
        commit_enabled, commit_email, chart_height).loop()


# Tibber-Preisstufe → Farbpaar
def price_pair(level):
    return {"VERY_CHEAP": P_BRIGHT, "CHEAP": P_BRIGHT, "NORMAL": P_GREEN,
            "EXPENSIVE": P_YELLOW, "VERY_EXPENSIVE": P_RED}.get(level, P_GREEN)


def fmt_ct(c):
    return f"{c:.1f} ct".replace(".", ",")


# ── Formatierung ───────────────────────────────────────────────────────────
def fmt_w(p):
    """Leistung hübsch: <1 kW in W, sonst in kW (deutsches Komma)."""
    if abs(p) >= 1000:
        return f"{p / 1000:.2f} kW".replace(".", ",")
    return f"{p:.0f} W"


def fmt_kwh(e):
    return f"{e:.2f} kWh".replace(".", ",") if e is not None else "—"


def sparkline(values, width):
    """Watt-Reihe als Block-Sparkline der letzten <width> Werte."""
    vals = list(values)[-width:]
    if not vals:
        return ""
    hi = max(vals) or 1.0
    return "".join(SPARK[min(len(SPARK) - 1, int(v / hi * (len(SPARK) - 1)))]
                   for v in vals)


# ── Hintergrund-Poller ─────────────────────────────────────────────────────
class Poller(threading.Thread):
    # Marktpreise ändern sich stündlich, Leistung im 15-Min-Raster –
    # beide seltener abfragen als den Zähler-Snapshot.
    MARKET_REFRESH = 600          # Sekunden zwischen Markt-Abfragen
    POWER_REFRESH = 60            # Sekunden zwischen 15-Min-Leistungsabfragen

    def __init__(self, client, meter_id, session, interval, tibber=None):
        super().__init__(daemon=True)
        self.client = client
        self.meter_id = meter_id
        self.session = session
        self.interval = interval
        self.tibber = tibber
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self._last_market = 0.0
        self._last_power = 0.0

    def run(self):
        while not self.stop.is_set():
            self._tick()
            self._power_tick()
            self._market_tick()
            self.stop.wait(self.interval)

    def _power_tick(self, force=False):
        import time as _t
        if not (force or not self.session.power_series
                or _t.time() - self._last_power >= self.POWER_REFRESH):
            return
        self._last_power = _t.time()
        try:
            series = core.fetch_power_series(self.client, self.meter_id)
            with self.lock:
                self.session.set_power_series(series)
        except Exception:
            pass

    def _tick(self):
        try:
            r = core.fetch_snapshot(self.client, self.meter_id)
            today = dt.date.today()
            with self.lock:
                if self.session.day != today:
                    try:
                        be, bo = core.fetch_day_baseline(
                            self.client, self.meter_id, today)
                        self.session.set_baseline(be, bo, today)
                    except Exception:
                        pass
                self.session.update(r)
        except Exception as ex:
            with self.lock:
                self.session.set_error(str(ex))

    def _market_tick(self, force=False):
        if not self.tibber:
            return
        import time as _t
        hour_changed = self.session.market_hour != dt.datetime.now().hour
        due = (force or self.session.market is None
               or hour_changed
               or _t.time() - self._last_market >= self.MARKET_REFRESH)
        if not due:
            return
        self._last_market = _t.time()
        try:
            ov = self.tibber.overview()
            with self.lock:
                self.session.set_market(ov)
        except Exception as ex:
            with self.lock:
                self.session.set_market_error(str(ex))

    def refresh_now(self):
        self._tick()
        self._power_tick(force=True)
        self._market_tick(force=True)


# ── App / Zeichnen ─────────────────────────────────────────────────────────
class App:
    def __init__(self, scr, client, meter_id, meter, interval, tibber=None,
                 commit_enabled=False, commit_email=None, chart_height=0):
        self.scr = scr
        self.client = client
        self.meter_id = meter_id
        self.meter = meter or {}
        self.interval = interval
        self.tibber = tibber
        self.commit_enabled = commit_enabled
        self.commit_email = commit_email
        self.chart_height = chart_height
        self.session = core.Session()
        self.poller = Poller(client, meter_id, self.session, interval, tibber)
        self.scale = 1000.0      # Watt-Vollausschlag der Balken (auto)

    # — Low-Level —
    def _put(self, y, x, s, pair=P_GREEN, bold=False):
        h, w = self.scr.getmaxyx()
        if y < 0 or y >= h or x >= w - 1:
            return
        attr = curses.color_pair(pair)
        if bold:
            attr |= curses.A_BOLD
        if pair == P_DIM:
            attr |= curses.A_DIM
        try:
            self.scr.addnstr(y, x, s, w - x - 1, attr)
        except curses.error:
            pass

    def _bar(self, y, x, width, frac, pair=P_BRIGHT):
        frac = max(0.0, min(1.0, frac))
        fill = int(round(frac * width))
        self._put(y, x, "█" * fill, pair, bold=True)
        self._put(y, x + fill, "░" * (width - fill), P_DIM)

    def _power_bar(self, y, x, width, value, rmin, rmax, scale, frame, trend,
                   vpair=P_BRIGHT):
        """Changierender Leistungsbalken: fester Sockel bis Recent-Min, ein
        schimmerndes Fluktuationsband bis Recent-Max (Highlight wandert in
        Tendenz-Richtung), Marke für den aktuellen Wert und eine dezente
        Projektions-Marke (Max bzw. Min × Tendenz-Faktor)."""
        if width <= 0:
            return
        scale = scale or 1.0

        def pos(v):
            return max(0, min(width, int(round(abs(v) / scale * width))))

        lo, hi = sorted((pos(rmin), pos(rmax)))
        a = pos(value)
        band = hi - lo
        step = (frame // 4) % band if band > 0 else 0     # langsamer
        hpos = (lo + step) if trend >= 0 else (hi - step)     # Richtung = Tendenz
        # Glow-Schweif hinter der Kopfzelle (Index = Abstand zum Kopf)
        glow = [("█", vpair, True), ("▓", vpair, True),
                ("▓", P_GREEN, False), ("▒", P_GREEN, False)]
        for i in range(width):
            if i < lo:
                self._put(y, x + i, "█", vpair, bold=True)        # Sockel
            elif i <= hi:
                d = (hpos - i) if trend >= 0 else (i - hpos)      # nachziehen
                if 0 <= d < len(glow):
                    ch, pair, bold = glow[d]
                    self._put(y, x + i, ch, pair, bold=bold)      # Schimmer+Glow
                else:
                    self._put(y, x + i, "▒", P_GREEN)             # Band
            else:
                self._put(y, x + i, "░", P_DIM)                   # frei
        if 0 <= a < width:
            self._put(y, x + a, "│", P_CYAN, bold=True)           # aktueller Wert
        # Projektions-Marke aus der Tendenz (dezent)
        s = max(-1.0, min(1.0, trend / max(rmax, 1.0)))
        if abs(s) > 0.05:
            if s > 0:
                pp, mark = pos(rmax * (1.0 + 0.15 * s)), "›"
            else:
                pp, mark = pos(rmin * (1.0 + 0.15 * s)), "‹"
            if 0 <= pp < width:
                self._put(y, x + pp, mark, P_DIM)

    def _vbars(self, y, x, height, values, vmin, vmax, pair_fn=None,
               base_pair=P_GREEN, mark_idx=None, mark_char="X"):
        """Mehrzeiliges vertikales Balkenchart (oben ausgerichtet, Höhe = rows).
        Achtel-Blöcke für Sub-Zeilen-Auflösung. Optional eine Spalte unten mit
        mark_char markieren (z. B. 'Jetzt')."""
        BLOCKS = " ▁▂▃▄▅▆▇█"
        if height <= 0 or not values:
            return
        span = (vmax - vmin) or 1.0
        for c, v in enumerate(values):
            frac = (v - vmin) / span
            frac = 0.0 if frac < 0 else (1.0 if frac > 1 else frac)
            level = frac * height
            pair = pair_fn(c) if pair_fn else base_pair
            for k in range(height):                 # k=0 unten … height-1 oben
                fill = level - k
                if fill <= 0:
                    break
                idx = 8 if fill >= 1 else int(round(fill * 8))
                if idx <= 0:
                    break
                self._put(y + (height - 1 - k), x + c, BLOCKS[idx], pair,
                          bold=(idx == 8))
        if mark_idx is not None and 0 <= mark_idx < len(values):
            self._put(y + height, x + mark_idx, mark_char, P_CYAN, bold=True)

    def _kv(self, y, label, value, vpair=P_GREEN, vbold=False):
        """Schlüssel … Wert  mit Punkt-Füllung (netmon-Stil)."""
        h, w = self.scr.getmaxyx()
        dots = max(2, 26 - len(label))
        self._put(y, 2, label.upper(), P_GREEN)
        self._put(y, 2 + len(label) + 1, "." * dots, P_DIM)
        self._put(y, 2 + len(label) + 1 + dots + 1, value, vpair, bold=vbold)

    def _hdr(self, y, text):
        h, w = self.scr.getmaxyx()
        self._put(y, 1, "▌ " + text.upper(), P_BRIGHT, bold=True)
        self._put(y, 4 + len(text), " " + "·" * max(0, w - 6 - len(text)), P_DIM)

    # — OIA-Leisten —
    def _oia_top(self, spin, stale):
        h, w = self.scr.getmaxyx()
        ser = (self.meter.get("printedFullSerialNumber")
               or self.meter.get("serialNumber") or self.meter_id[:12])
        left = f" {brand.OIA} · LIVE "
        flag = " ⚠ OFFLINE " if stale else ""
        right = f"{flag} {ser}  {dt.datetime.now():%a %d %b %H:%M:%S} {spin} "
        mid = max(0, (w - 1) - len(left) - len(right))
        bar = (left + " " * mid + right)[:w - 1]
        self._put(0, 0, bar + " " * max(0, (w - 1) - len(bar)),
                  P_RED if stale else P_OIA, bold=True)

    def _oia_bot(self, updated, count):
        h, w = self.scr.getmaxyx()
        self._put(h - 2, 0, "·" * (w - 1), P_DIM)
        # Funktionstasten links
        keys = [("R", "Aktualisieren"), ("M", "Markt"), ("C", "Commit"),
                ("K", "khal"), ("Q", "Beenden")]
        x = 1
        for key, lab in keys:
            self._put(h - 1, x, key, P_BRIGHT, bold=True)
            self._put(h - 1, x + 1, "=" + lab, P_GREEN)
            x += 2 + len(lab) + 2
        # Status rechts
        upd = updated.strftime("%H:%M:%S") if updated else "—"
        right = f"#{count}  ↻{self.interval:g}s  letzte {upd} "
        self._put(h - 1, max(x, (w - 1) - len(right)), right, P_DIM)

    # — Hauptschleife —
    def loop(self):
        self.poller.start()
        self.scr.timeout(250)        # ≈4 Neuzeichnungen/s
        si = 0
        while True:
            self.draw(SPIN[si % 4], si)
            si += 1
            try:
                ch = self.scr.get_wch()
            except curses.error:
                continue             # Timeout → nur neu zeichnen
            except KeyboardInterrupt:
                break
            k = ch.lower() if isinstance(ch, str) else ch
            if k in ("q", "\x1b"):
                break
            elif k == "r":
                self.poller.refresh_now()
            elif k == "m":
                self.market_popup()
            elif k == "k":
                have = "ja" if khal.available() else "nein (khal nicht gefunden)"
                self.info_popup("KHAL / Erinnerungs-Export", [
                    f"khal installiert: {have}",
                    "",
                    "Geplant: günstigstes Verbrauchsfenster des Tages als",
                    "khal-Erinnerung exportieren (baut auf MARKT auf).",
                    "Code-Haken liegt bereit in stromzaehler/khal.py.",
                ])
            elif k == "c":
                self.commit_flow()
            elif ch == curses.KEY_RESIZE:
                continue
        self.poller.stop.set()

    def draw(self, spin, frame=0):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        with self.poller.lock:
            s = self.session
            last = dict(s.last) if s.last else None
            err = s.error
            updated = s.updated
            today = s.today_kwh()
            today_out = s.today_out_kwh()
            count = s.count
            market = s.market
            market_err = s.market_error
            pseries = [x["power"] for x in s.power_series]
            recent_power = s.recent_power
            recent_time = s.recent_power_time
            mn, avg, mx = s.power_stats()

        stale = bool(err) or last is None
        self._oia_top(spin, stale and last is not None)

        if last is None:
            msg = "verbinde mit inexogy …" if not err else f"Fehler: {err}"
            self._put(h // 2, max(2, (w - len(msg)) // 2),
                      msg, P_RED if err else P_CYAN, bold=True)
            self._oia_bot(updated, count)
            self.scr.refresh()
            return

        # Leistungsquelle: echte Momentanleistung (falls der Zähler sie liefert),
        # sonst die mittlere Leistung der letzten 15-Minuten-Stufe (SLP-Zähler).
        live = last["power"] != 0
        p = last["power"] if live else (recent_power or 0.0)
        # Balken-Skala automatisch (mind. 500 W, 15 % Headroom, auf 100 W)
        target = max(500.0, abs(p) * 1.15, mx * 1.15)
        self.scale = (int(target / 100) + 1) * 100.0

        y = 2
        # ── LEISTUNG ─────────────────────────────────────────────────────
        if live:
            self._hdr(y, "Momentane Leistung")
            sub = "live"
        else:
            self._hdr(y, "Leistung · Ø letzte 15 Min")
            sub = (f"Stand {dt.datetime.fromtimestamp(recent_time / 1000):%H:%M}"
                   if recent_time else "—")
        y += 1
        # Recent-Band (letzte ~1 h) und Tendenz für den changierenden Balken
        recent = pseries[-4:] if pseries else []
        rmin = min(recent) if recent else abs(p)
        rmax = max(recent) if recent else abs(p)
        trend = (pseries[-1] - pseries[-min(4, len(pseries))]
                 if len(pseries) >= 2 else 0.0)
        arrow = "↑" if trend > 20 else ("↓" if trend < -20 else "→")
        ppair = P_BRIGHT if p >= 0 else P_BLUE   # negativ = Einspeisung
        self._put(y + 1, 2, f"{fmt_w(abs(p)):>10}", ppair, bold=True)
        bw = max(10, w - 26)
        self._power_bar(y + 1, 14, bw, abs(p), rmin, rmax, self.scale,
                        frame, trend, ppair)
        self._put(y + 1, 14 + bw + 1, f"/ {fmt_w(self.scale)}", P_DIM)
        head = "↩ Einspeisung" if p < 0 else f"{sub}  {arrow}"
        self._put(y, 24, head, P_BLUE if p < 0 else P_DIM)
        y += 3
        phases = [last["l1"], last["l2"], last["l3"]]
        if any(phases):
            for name, val in zip(("L1", "L2", "L3"), phases):
                self._put(y, 2, name, P_CYAN, bold=True)
                self._put(y, 5, f"{fmt_w(val):>9}", P_GREEN)
                self._bar(y, 16, max(8, bw - 2), abs(val) / self.scale, P_GREEN)
                y += 1
        else:
            self._put(y, 2, "Phasen L1–L3: n. v. (SLP-Lastprofilzähler, "
                            "nur 15-Min-Werte)", P_DIM)
            y += 1
        y += 1

        # ── HEUTE ────────────────────────────────────────────────────────
        hy = y
        self._hdr(y, "Heute")
        y += 1
        self._kv(y, "Bezug heute", fmt_kwh(today), P_BRIGHT, vbold=True)
        y += 1
        self._kv(y, "Einspeisung heute", fmt_kwh(today_out), P_BLUE)
        y += 1
        self._kv(y, "Zählerstand Bezug", fmt_kwh(last["energy"]))
        y += 1
        self._kv(y, "Zählerstand Einsp.", fmt_kwh(last["energy_out"]))
        y += 2
        # Gesamt-Zählerstand (Bezug) als 80er-LED-Ziffern rechts daneben
        val = f"{last['energy']:.2f}".replace(".", ",")
        big = bigfont.render(val)
        bigw = len(big[0])
        bx = w - bigw - 3
        if bx >= 44:                       # nur wenn genug Platz neben den Labels
            self._put(hy, w - 19, "BEZUG GESAMT ·kWh", P_DIM)
            for i, line in enumerate(big):
                self._put(hy + 1 + i, bx, line, P_BRIGHT, bold=True)

        # Gemeinsame Chart-Höhe für VERLAUF + MARKT (Config oder ~90 % Restplatz)
        two = bool(self.tibber)
        avail = (h - 2) - y                      # Zeilen bis zur unteren OIA-Leiste
        overhead = 7 if two else 3               # Köpfe/Infozeilen/X-Achse/Abstände
        slots = 2 if two else 1
        space = max(2, avail - overhead)
        if self.chart_height > 0:
            H = max(1, min(self.chart_height, space // slots))
        else:
            H = max(1, int(0.9 * (space // slots)))

        # ── VERLAUF (15-Min-Leistung, letzte Stunden) ────────────────────
        self._hdr(y, "Verlauf · 15-Min-Leistung")
        y += 1
        self._put(y, 2, f"min {fmt_w(mn):>9}", P_DIM)
        self._put(y, 20, f"ø {fmt_w(avg):>9}", P_GREEN)
        self._put(y, 38, f"max {fmt_w(mx):>9}", P_YELLOW, bold=True)
        y += 1
        cols = pseries[-(w - 4):]
        self._vbars(y, 2, H, cols, 0.0, max(max(cols) if cols else 1.0, 1.0),
                    base_pair=P_GREEN)
        y += H + 1

        # ── MARKT (Tibber) ───────────────────────────────────────────────
        if two and y < h - 2:
            self._market_panel(y, w, h, market, market_err, H)

        if err:
            self._put(h - 3, 1, f"⚠ {err}", P_RED)
        self._oia_bot(updated, count)
        self.scr.refresh()

    # — MARKT-Panel (kompakt, im Dashboard) —
    def _market_panel(self, y, w, h, market, market_err, H=1):
        if not self.tibber:
            self._hdr(y, "Markt · Tibber")
            self._put(y + 1, 2, "— nicht konfiguriert (tibber_email/password) —",
                      P_DIM)
            return
        self._hdr(y, f"Markt · Tibber ({market.home if market else '…'})")
        y += 1
        if market is None:
            msg = market_err or "lade Preise …"
            self._put(y, 2, ("⚠ " + msg) if market_err else msg,
                      P_RED if market_err else P_DIM)
            return
        cur = market.current
        mn, avg, mx = market.stats()
        ch = market.cheapest()
        if cur:
            self._put(y, 2, "Jetzt", P_GREEN)
            self._put(y, 8, fmt_ct(cur.total) + "/kWh", price_pair(cur.level),
                      bold=True)
            self._put(y, 22, cur.level_label(), price_pair(cur.level))
        self._put(y, 38, f"ø {fmt_ct(avg)}", P_GREEN)
        if ch:
            self._put(y, 50, f"min {fmt_ct(mn)} {ch.start:%H}h", P_BRIGHT)
        y += 1
        # 24h-Preisverlauf als farbiges Balkenchart, „Jetzt"-Spalte mit X
        today = market.today
        if today and y < h - 2:
            cols = [pp.total for pp in today]
            lo, hi = min(cols), max(cols)
            base = lo - (hi - lo) * 0.12          # auch die günstigste Stunde sichtbar
            self._vbars(y, 2, H, cols, base, hi,
                        pair_fn=lambda c: price_pair(today[c].level),
                        mark_idx=market.now_index(), mark_char="X")

    # — MARKT-Popup (Stundentabelle) —
    def market_popup(self):
        while True:
            self.scr.erase()
            h, w = self.scr.getmaxyx()
            self._oia_top("·", False)
            with self.poller.lock:
                market = self.session.market
                merr = self.session.market_error
            if not self.tibber:
                self._hdr(2, "Markt · Tibber")
                self._put(4, 4, "Nicht konfiguriert. Trage in ~/.config/strom/config",
                          P_GREEN)
                self._put(5, 4, "tibber_email= und tibber_password= ein.", P_GREEN)
            elif market is None:
                self._hdr(2, "Markt · Tibber")
                self._put(4, 4, ("⚠ " + merr) if merr else "lade Preise …",
                          P_RED if merr else P_CYAN)
            else:
                self._market_table(market, w, h)
            self._put(h - 1, 1, "[beliebige Taste] zurück", P_YELLOW, bold=True)
            self.scr.refresh()
            try:
                ch = self.scr.get_wch()
            except curses.error:
                continue
            if ch == curses.KEY_RESIZE:
                continue
            return

    def _market_table(self, market, w, h):
        self._hdr(2, f"Markt · Tibber ({market.home})")
        mn, avg, mx = market.stats()
        ch = market.cheapest()
        ex = market.most_expensive()
        self._put(3, 2, f"ø {fmt_ct(avg)}/kWh", P_GREEN)
        if ch:
            self._put(3, 16, f"min {fmt_ct(mn)} um {ch.start:%H}h", P_BRIGHT)
        if ex:
            self._put(3, 40, f"max {fmt_ct(mx)} um {ex.start:%H}h", P_RED)
        rows = market.today + market.tomorrow
        if not rows:
            return
        lo = min(p.total for p in rows)
        hi = max(p.total for p in rows)
        span = (hi - lo) or 1.0
        ni = market.now_index()
        barw = max(8, min(28, w - 40))
        top = 5
        cap = (h - 2) - top
        # Bei wenig Platz die schon vergangenen Stunden überspringen
        start = 0
        if len(rows) > cap and ni:
            start = max(0, min(ni - 2, len(rows) - cap))
        y = top
        for i, p in enumerate(rows[start:start + cap], start):
            pair = price_pair(p.level)
            sel = (i == ni)
            mark = "▶" if sel else " "
            self._put(y, 1, mark, P_CYAN, bold=True)
            tag = "" if p.start.date() == market.today[0].start.date() else "+1 "
            self._put(y, 3, f"{tag}{p.start:%H}:00", P_CYAN if sel else P_GREEN,
                      bold=sel)
            self._put(y, 12, f"{fmt_ct(p.total):>8}", pair, bold=sel)
            fill = int(round((p.total - lo) / span * barw))
            self._put(y, 22, "█" * fill, pair)
            self._put(y, 22 + fill, "░" * (barw - fill), P_DIM)
            self._put(y, 22 + barw + 2, p.level_label(), pair)
            y += 1

    # — Einzeilen-Eingabe (für Commit) —
    def _prompt(self, y, label, default=""):
        """Einzeilige Eingabe; Enter=ok (Text), ESC=Abbruch (None)."""
        curses.curs_set(1)
        buf = list(default)
        try:
            while True:
                h, w = self.scr.getmaxyx()
                self.scr.move(y, 0)
                self.scr.clrtoeol()
                prompt = f"{label}: " + "".join(buf)
                self._put(y, 4, prompt, P_CYAN, bold=True)
                self.scr.move(y, min(4 + len(prompt), w - 1))
                self.scr.refresh()
                try:
                    ch = self.scr.get_wch()
                except curses.error:
                    continue
                if isinstance(ch, str):
                    if ch in ("\n", "\r"):
                        return "".join(buf).strip()
                    if ch == "\x1b":
                        return None
                    if ch in ("\x7f", "\b", "\x08"):
                        if buf:
                            buf.pop()
                    elif ch == "\x15":             # Ctrl-U
                        buf.clear()
                    elif ch.isprintable():
                        buf.append(ch)
                elif ch == curses.KEY_BACKSPACE:
                    if buf:
                        buf.pop()
                elif ch == curses.KEY_ENTER:
                    return "".join(buf).strip()
        finally:
            curses.curs_set(0)

    # — Zählerstand → Tibber (Opt-in + 2FA) —
    def commit_flow(self):
        from . import commit
        if not self.tibber:
            self.info_popup("Zählerstand → Tibber",
                            ["Tibber ist nicht konfiguriert."])
            return
        if not self.commit_enabled:
            self.info_popup("Zählerstand → Tibber", [
                "Commit ist deaktiviert (Opt-in).",
                "",
                "Zum Freischalten in ~/.config/strom/config:",
                "    tibber_commit=on",
            ])
            return
        lines = []   # (text, pair)

        def redraw():
            self.scr.erase()
            self._oia_top("·", False)
            self._hdr(2, "Zählerstand → Tibber")
            y = 4
            for txt, pair in lines:
                self._put(y, 4, txt, pair)
                y += 1
            self.scr.refresh()
            return y

        def ask_value(default_int):
            v = self._prompt(redraw() + 1,
                             "Zählerstand kWh (Enter=übernehmen, ESC=Abbruch)",
                             str(default_int))
            if v is None:
                return None
            v = v.strip()
            if not v:
                v = str(default_int)
            if not v.isdigit():
                lines.append(("Ungültige Zahl.", P_RED))
                return None
            lines.append((f"Wert: {int(v)} kWh", P_BRIGHT))
            return int(v)

        def confirm(val, home):
            redraw()
            a = self._prompt(redraw() + 1,
                             f"{val} kWh an »{home}« senden? Code wird gemailt (j/n)",
                             "n")
            return (a or "").strip().lower() in ("j", "ja", "y", "yes")

        def notify(msg):
            lines.append((msg, P_GREEN))
            redraw()

        def prompt_code():
            redraw()
            return self._prompt(redraw() + 1, "Code aus der E-Mail (ESC=Abbruch)", "")

        try:
            val = commit.perform(
                self.client, self.meter_id, self.tibber, self.commit_email,
                ask_value=ask_value, confirm=confirm, notify=notify,
                prompt_code=prompt_code, enabled=self.commit_enabled)
            lines.append((f"✓ {val} kWh an Tibber gesendet.", P_BRIGHT))
        except commit.CommitAbort:
            lines.append(("Abgebrochen – nichts gesendet.", P_YELLOW))
        except commit.CommitError as ex:
            lines.append((f"✗ {ex}", P_RED))
        redraw()
        h, _ = self.scr.getmaxyx()
        self._put(h - 1, 1, "[beliebige Taste] zurück", P_YELLOW, bold=True)
        self.scr.refresh()
        try:
            self.scr.get_wch()
        except curses.error:
            pass

    # — Popup —
    def info_popup(self, title, lines):
        while True:
            self.scr.erase()
            h, w = self.scr.getmaxyx()
            self._oia_top("·", False)
            self._hdr(2, title)
            y = 4
            for ln in lines:
                self._put(y, 4, ln, P_GREEN)
                y += 1
            self._put(h - 1, 1, "[beliebige Taste] zurück", P_YELLOW, bold=True)
            self.scr.refresh()
            try:
                ch = self.scr.get_wch()
            except curses.error:
                continue
            if ch == curses.KEY_RESIZE:
                continue
            return
