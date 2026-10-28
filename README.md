# Icom Speicher-Tool (IC-9700 / IC-705)

Start: `python app.py` (Python 3.11+, keine Zusatzpakete). Test ohne Geraet: Host `sim` eintragen; `python selftest.py`.

1. Einstellungen: IP, Netzwerk-Benutzer/-Passwort je Geraet (am Geraet unter Network > Network User), Ort/PLZ.
2. Speichersaetze je Geraet anlegen, Speicher anlegen/aendern/loeschen.
3. "Vom Geraet lesen" sichert alle Speicher als benannten Satz. "Auf Geraet schreiben" schreibt Auswahl oder alles.
4. "Auf anderes Geraet kopieren" uebertraegt einen Satz (23 cm entfaellt beim IC-705).
5. "Relais suchen": FM- und D-STAR-Relais (2 m / 70 cm / 23 cm) im Umkreis, Quelle a23-wertheim.de.

Daten: data/<geraet>/<satz>.json, config.json (Passwoerter im Klartext).
