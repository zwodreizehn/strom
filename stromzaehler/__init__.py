# -*- coding: utf-8 -*-
"""strom – Live-Dashboard für Smartmeter (inexogy) mit Marktpreisen (Tibber).

Whitelabel-Ausgabe: beim Erststart fragt ein Assistent (wizard.py) die nötigen
Keys/Variablen ab und legt die Konfiguration an; Branding ist konfigurierbar.

Aufbau (Funktion / Inhalt / Oberfläche getrennt):
  config.py – Inhalt:   Zugangsdaten & Einstellungen laden
  wizard.py – Funktion: interaktiver Erststart-Assistent (Config anlegen)
  brand.py  – Funktion: Whitelabel-Label der Statusleiste
  api.py    – Inhalt:   REST-Client der inexogy-API (Basic Auth, nur stdlib)
  core.py   – Funktion: Einheiten-Umrechnung, Kennzahlen, Session-Historie
  markt.py  – Funktion: Tibber-Marktpreise + sendMeterReading (GraphQL)
  commit.py – Funktion: Zählerstand-Commit mit Opt-in + 2FA
  export.py – Funktion: HTML/PHP-Seite mit Empfehlung (Web-Export, cron)
  mail.py   – Funktion: 2FA-Code-Versand über himalaya
  khal.py   – Funktion: günstigstes Fenster als khal-Erinnerung exportieren
  theme.py / render.py / tui.py – Retro-Terminal-UI (Klartext bzw. curses)
  cli.py    – Einstieg / Befehlszeile
"""
__version__ = "2.1.0"
