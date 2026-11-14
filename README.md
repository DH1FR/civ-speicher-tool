# CIV-Speicher-Tool (IC-9700 / IC-705)

[English version](README.en.md)
Start: `python app.py` (Python 3.11+, keine Zusatzpakete). Test ohne Geraet: Host `sim` eintragen; `python selftest.py`.

1. Einstellungen: IP, Netzwerk-Benutzer/-Passwort je Geraet (am Geraet unter Network > Network User), Ort/PLZ.
2. Speichersaetze je Geraet anlegen, Speicher anlegen/aendern/loeschen.
3. "Vom Geraet lesen" sichert alle Speicher als benannten Satz. "Auf Geraet schreiben" schreibt Auswahl oder alles.
4. "Auf anderes Geraet kopieren" uebertraegt einen Satz (23 cm entfaellt beim IC-705).
5. "Relais suchen": FM- und D-STAR-Relais (2 m / 70 cm / 23 cm) im Umkreis, Quelle a23-wertheim.de.

Daten: data/<geraet>/<satz>.json, config.json (Passwoerter im Klartext, nicht ins Repository einchecken).

## Hinweise

- **Haftung:** Das Programm schreibt und loescht Speicher in echten Funkgeraeten. Nutzung auf eigene Gefahr; vorher mit "Vom Geraet lesen" sichern.
- **Kein Icom-Produkt:** Inoffizielles Hobbyprojekt, nicht mit Icom Inc. verbunden. Icom, IC-9700 und IC-705 sind Marken von Icom Inc.
- **Protokoll:** Das CI-V-Kommando-Format folgt der oeffentlichen Icom-CI-V-Referenz. Das Netzwerkprotokoll (UDP, Login) und das Byte-Layout der Speicher wurden anhand der quelloffenen Projekte [wfview](https://wfview.org/) und kappanhang als Beschreibung nachvollzogen und hier eigenstaendig neu implementiert; Code aus diesen Projekten wurde nicht uebernommen.
- **Datenquellen:** Relaislisten von [a23-wertheim.de](https://a23-wertheim.de) (D-STAR-Liste von DL2HCK), Ortssuche ueber [Nominatim / OpenStreetMap](https://nominatim.openstreetmap.org) (Daten (c) OpenStreetMap-Mitwirkende, ODbL). Eigene Relais: `eigene_relais.json`.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
