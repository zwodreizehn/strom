# -*- coding: utf-8 -*-
"""Funktion: Börsen-/Marktpreis-Übersicht über Tibber.

Tibber bietet keine offizielle E-Mail/Passwort-API – aber der App-Login
(`app.tibber.com/login.credentials`) liefert einen JWT, der vom
GraphQL-Endpoint `api.tibber.com/v1-beta/gql` (Schema `viewer`) akzeptiert
wird. Genau diesen Weg nutzt diese Klasse: einloggen → Token cachen (Datei,
Modus 600) → bei Ablauf automatisch neu einloggen.

Geliefert werden die stündlichen Tibber-Gesamtpreise (Energie + Steuer/Abgaben)
in **ct/kWh** für heute (und morgen, sobald ~13 Uhr veröffentlicht). Nur stdlib.

(Die separate Tibber *Data API* unter data-api.tibber.com liefert Geräte-
Telemetrie/Live-Power per OAuth2 – für Preise nicht nötig, daher hier nicht
genutzt.)
"""
import base64
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request

LOGIN_URL = "https://app.tibber.com/login.credentials"
GQL_URL = "https://api.tibber.com/v1-beta/gql"

PRICE_QUERY = (
    "{ viewer { homes { id appNickname currentSubscription { priceInfo {"
    " current { total energy tax startsAt level currency }"
    " today { total startsAt level }"
    " tomorrow { total startsAt level } } } } } }"
)

# Tibber-Preisstufen → kurze deutsche Anzeige
LEVELS = {
    "VERY_CHEAP":     "sehr günstig",
    "CHEAP":          "günstig",
    "NORMAL":         "normal",
    "EXPENSIVE":      "teuer",
    "VERY_EXPENSIVE": "sehr teuer",
}


class MarktError(Exception):
    pass


# ── Datenmodell ─────────────────────────────────────────────────────────────
class PricePoint:
    """Ein Stundenpreis. total/energy/tax in ct/kWh."""
    __slots__ = ("start", "total", "energy", "tax", "level", "currency")

    def __init__(self, d, currency=None):
        self.start = dt.datetime.fromisoformat(d["startsAt"])
        self.total = round((d.get("total") or 0.0) * 100, 2)      # €/kWh → ct/kWh
        self.energy = round((d.get("energy") or 0.0) * 100, 2)
        self.tax = round((d.get("tax") or 0.0) * 100, 2)
        self.level = d.get("level") or "NORMAL"
        self.currency = d.get("currency") or currency or "EUR"

    def level_label(self):
        return LEVELS.get(self.level, self.level.lower())


class Overview:
    """Preis-Übersicht eines Tibber-Homes inkl. abgeleiteter Kennzahlen."""

    def __init__(self, home, current, today, tomorrow):
        self.home = home
        self.current = current          # PricePoint | None
        self.today = today              # list[PricePoint]
        self.tomorrow = tomorrow        # list[PricePoint] (leer bis ~13 Uhr)
        self.fetched = dt.datetime.now()

    def stats(self):
        """(min, ø, max) der heutigen Gesamtpreise in ct/kWh."""
        if not self.today:
            return (0.0, 0.0, 0.0)
        t = [p.total for p in self.today]
        return (min(t), sum(t) / len(t), max(t))

    def cheapest(self):
        return min(self.today, key=lambda p: p.total) if self.today else None

    def most_expensive(self):
        return max(self.today, key=lambda p: p.total) if self.today else None

    def now_index(self):
        """Index der aktuellen Stunde in today (oder None)."""
        now = dt.datetime.now().astimezone()
        for i, p in enumerate(self.today):
            if p.start <= now < p.start + dt.timedelta(hours=1):
                return i
        return None

    def cheapest_window(self, hours=1):
        """Günstigstes zusammenhängendes Fenster ab jetzt (für khal-Erinnerung).
        Rückgabe (start, end, ø-ct/kWh) – bezieht morgen mit ein, falls da."""
        series = self.today + self.tomorrow
        now = dt.datetime.now().astimezone()
        future = [p for p in series if p.start + dt.timedelta(hours=1) > now]
        if len(future) < hours:
            future = series
        if len(future) < hours:
            return None
        best = None
        for i in range(0, len(future) - hours + 1):
            win = future[i:i + hours]
            avg = sum(p.total for p in win) / hours
            if best is None or avg < best[2]:
                best = (win[0].start, win[-1].start + dt.timedelta(hours=1), avg)
        return best


# ── HTTP-Helfer ─────────────────────────────────────────────────────────────
def _jwt_exp(token):
    """Ablaufzeit (Epoch) aus dem JWT lesen; 0 bei Fehler."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)              # base64url-Padding
        data = json.loads(base64.urlsafe_b64decode(payload))
        return int(data.get("exp", 0))
    except Exception:
        return 0


def _post_json(url, body, headers=None, timeout=15):
    data = json.dumps(body).encode("utf-8")
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise MarktError("Tibber-Login abgelehnt (Zugangsdaten prüfen).")
        raise MarktError(f"Tibber HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise MarktError(f"Netzwerkfehler: {e.reason}")
    except (ValueError, json.JSONDecodeError):
        raise MarktError("Ungültige Antwort von Tibber.")


# ── Tibber-Client ───────────────────────────────────────────────────────────
class Tibber:
    """Schlanker Tibber-Client: Login-Token cachen, Preise abfragen."""

    def __init__(self, email=None, password=None, token=None, home=None,
                 token_path=None):
        self.email = email
        self.password = password
        self.static_token = token     # Developer-Token (developer.tibber.com)
        self.home_sel = home          # appNickname-Teilstring oder Index ("0")
        self.token_path = token_path or os.path.expanduser(
            "~/.config/strom/tibber_token.json")
        self._token = None
        self._exp = 0

    def configured(self):
        return bool(self.static_token or (self.email and self.password))

    # — Token-Verwaltung —
    def _load_cached(self):
        if self._token and time.time() < self._exp - 60:
            return self._token
        try:
            with open(self.token_path, encoding="utf-8") as f:
                c = json.load(f)
            if time.time() < int(c.get("exp", 0)) - 60:
                self._token, self._exp = c["token"], int(c["exp"])
                return self._token
        except (FileNotFoundError, ValueError, KeyError):
            pass
        return None

    def _login(self):
        resp = _post_json(LOGIN_URL,
                          {"email": self.email, "password": self.password})
        token = resp.get("token")
        if not token:
            raise MarktError("Tibber-Login lieferte keinen Token.")
        self._token = token
        self._exp = _jwt_exp(token) or int(time.time() + 3000)
        try:
            os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
            tmp = self.token_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"token": token, "exp": self._exp}, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.token_path)
        except OSError:
            pass
        return token

    def _token_value(self):
        if self.static_token:
            return self.static_token
        return self._load_cached() or self._login()

    def _gql(self, query):
        token = self._token_value()
        body = {"query": query}
        resp = _post_json(GQL_URL, body, {"Authorization": "Bearer " + token})
        # Token serverseitig abgelehnt → frisch einloggen (nur im App-Login-Modus)
        if resp.get("errors") and any(
                e.get("extensions", {}).get("code") == "UNAUTHENTICATED"
                for e in resp["errors"]):
            if self.static_token and not (self.email and self.password):
                raise MarktError("Tibber-Token abgelehnt (ungültig/abgelaufen?).")
            token = self._login()
            resp = _post_json(GQL_URL, body,
                              {"Authorization": "Bearer " + token})
        if resp.get("errors"):
            msg = resp["errors"][0].get("message", "unbekannter Fehler")
            raise MarktError(f"Tibber-Abfrage: {msg}")
        return resp.get("data", {})

    # — Preise —
    def overview(self):
        """Preis-Übersicht für das gewählte Home (sonst das erste)."""
        homes = (self._gql(PRICE_QUERY).get("viewer", {}) or {}).get("homes", [])
        homes = [h for h in homes if h.get("currentSubscription")]
        if not homes:
            raise MarktError("Kein Tibber-Home mit aktivem Vertrag gefunden.")
        home = self._pick_home(homes)
        pi = home["currentSubscription"]["priceInfo"]
        cur = PricePoint(pi["current"]) if pi.get("current") else None
        currency = cur.currency if cur else "EUR"
        today = [PricePoint(p, currency) for p in (pi.get("today") or [])]
        tomorrow = [PricePoint(p, currency) for p in (pi.get("tomorrow") or [])]
        return Overview(home.get("appNickname") or "Tibber",
                        cur, today, tomorrow)

    def _pick_home(self, homes):
        sel = self.home_sel
        if sel:
            if sel.isdigit() and int(sel) < len(homes):
                return homes[int(sel)]
            for h in homes:
                if sel.lower() in (h.get("appNickname") or "").lower():
                    return h
        return homes[0]

    def homes(self):
        """Liste der Home-Namen (für Konfiguration/Auswahl)."""
        data = self._gql("{ viewer { homes { appNickname } } }")
        return [h.get("appNickname") or "?"
                for h in (data.get("viewer", {}) or {}).get("homes", [])]

    def home_id(self):
        """homeId (UUID) des gewählten Homes – für sendMeterReading."""
        homes = (self._gql("{ viewer { homes { id appNickname"
                           " currentSubscription { status } } } }")
                 .get("viewer", {}) or {}).get("homes", [])
        if not homes:
            raise MarktError("Kein Tibber-Home gefunden.")
        h = self._pick_home(homes)
        return h["id"], (h.get("appNickname") or "Tibber")

    def send_meter_reading(self, reading_int, home_id=None, time=None):
        """Zählerstand (ganze kWh) an Tibber senden.

        ACHTUNG: schreibender, abrechnungsrelevanter Eingriff. Aufrufer ist für
        Opt-in und 2FA-Bestätigung verantwortlich (siehe cli/tui). Nutzt die
        – aus der Introspection ausgeblendete, aber gültige – Mutation
        sendMeterReading(input: MeterReadingInput).
        """
        if home_id is None:
            home_id, _ = self.home_id()
        reading_int = int(reading_int)
        fields = [f"homeId: {json.dumps(home_id)}", f"reading: {reading_int}"]
        if time:
            fields.append(f"time: {json.dumps(time)}")
        mutation = ("mutation { sendMeterReading(input: { "
                    + ", ".join(fields) + " }) { __typename } }")
        return self._gql(mutation)
