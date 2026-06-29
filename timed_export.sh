#!/usr/bin/env bash
# timed_export.sh – nicht-interaktiver Export der Strom-Werte als HTML/PHP.
#
# Schreibt die Handy-Seite (Leistung, Tagesverbrauch, Marktpreise + Empfehlung)
# an den in der Konfiguration (export_path) bzw. per $STROM_EXPORT_PATH
# festgelegten Pfad und überschreibt sie jeweils atomar. Ohne Interaktion,
# damit als Cronjob lauffähig (z. B. alle 10 Minuten):
#
#   */10 * * * * /pfad/zu/strom/timed_export.sh >> /pfad/zu/strom/export.log 2>&1
#
# Schreibt KEINE Daten an einen Anbieter (reine Anzeige).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Liegt das Ziel auf einem Mount (z. B. sshfs-Webspace) und ist dieser nicht
# eingehängt, lieber sauber aussteigen statt ins leere Verzeichnis zu schreiben.
if [ -n "${STROM_EXPORT_PATH:-}" ]; then
  MNT="$(dirname "$STROM_EXPORT_PATH")"
  if [ ! -d "$MNT" ]; then
    echo "$(date '+%F %T') Zielverzeichnis $MNT fehlt (nicht gemountet?) – übersprungen." >&2
    exit 0
  fi
fi

# Pfad: $STROM_EXPORT_PATH hat Vorrang, sonst entscheidet die Konfiguration.
python3 "$HERE/strom" export ${STROM_EXPORT_PATH:+"$STROM_EXPORT_PATH"}
echo "$(date '+%F %T') OK"
