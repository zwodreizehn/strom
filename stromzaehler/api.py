# -*- coding: utf-8 -*-
"""Inhalt: Client für die inexogy- (vormals Discovergy-) REST-API.

Authentifizierung per HTTP Basic Auth (E-Mail/Passwort) – das volle
OAuth-1.0-Verfahren der offiziellen Doku ist dafür nicht nötig. Nur stdlib
(urllib). Basis: https://api.inexogy.com/public/v1

Rate-Limit der API: 100 Anfragen/s, 1 gleichzeitige Verbindung pro IP.
"""
import base64
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.inexogy.com/public/v1"


class ApiError(Exception):
    pass


def _auth_header(email, password):
    raw = f"{email}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _get(path, auth, params=None, timeout=15):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"Authorization": auth, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ApiError("Zugangsdaten abgelehnt (HTTP 401).")
        if e.code == 429:
            raise ApiError("Rate-Limit erreicht (HTTP 429).")
        raise ApiError(f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise ApiError(f"Netzwerkfehler: {e.reason}")
    except socket.timeout:
        raise ApiError("Zeitüberschreitung (Server antwortet nicht).")
    except json.JSONDecodeError:
        raise ApiError("Ungültige Antwort (kein JSON).")


class Client:
    """Dünner Wrapper um die wichtigsten Endpunkte."""

    def __init__(self, email, password):
        self.auth = _auth_header(email, password)

    def meters(self):
        """Alle Zähler des Kontos (Liste von dicts)."""
        return _get("/meters", self.auth)

    def last_reading(self, meter_id):
        """Letzte Momentaufnahme (Live, ~2 s) eines Zählers."""
        return _get("/last_reading", self.auth, {"meterId": meter_id})

    def readings(self, meter_id, frm, to=None, resolution="raw", fields=None):
        """Zeitreihe. frm/to = Millisekunden-Epoch; resolution z. B.
        raw, one_minute, fifteen_minutes, one_hour, one_day."""
        p = {"meterId": meter_id, "from": int(frm), "resolution": resolution}
        if to is not None:
            p["to"] = int(to)
        if fields:
            p["fields"] = ",".join(fields)
        return _get("/readings", self.auth, p)

    def field_names(self, meter_id):
        """Verfügbare Messfelder des Zählers."""
        return _get("/field_names", self.auth, {"meterId": meter_id})
