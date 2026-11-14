# CIV-Speicher-Tool (IC-9700 / IC-705)

[Deutsche Version](README.md)

A Windows desktop tool (Python/Tkinter) to manage the memory channels of the Icom IC-9700 and IC-705 over the network (CI-V over LAN).

Start: `python app.py` (Python 3.11+, no extra packages). Test without a radio: enter host `sim`; `python selftest.py`.

1. Settings: IP address, network user/password per radio (on the radio under Network > Network User), place/ZIP code.
2. Create memory sets per radio; create, edit and delete memory channels.
3. "Read from radio" saves all memories as a named set. "Write to radio" writes the selection or everything.
4. "Copy to other radio" transfers a set (23 cm is dropped for the IC-705). Selected channels can also be copied and pasted (Ctrl+C / Ctrl+V), including into another radio's set.
5. "Find repeaters": FM and D-STAR repeaters (2 m / 70 cm / 23 cm) around your location, source a23-wertheim.de.

Data: `data/<radio>/<set>.json`, `config.json` (passwords in plain text, never commit it to the repository).

## Notes

- **Liability:** The program writes and deletes memories in real radios. Use at your own risk; back up first with "Read from radio".
- **Not an Icom product:** Unofficial hobby project, not affiliated with Icom Inc. Icom, IC-9700 and IC-705 are trademarks of Icom Inc.
- **Protocol:** The CI-V command format follows Icom's public CI-V reference. The network protocol (UDP, login) and the memory byte layout were understood from the open-source projects [wfview](https://wfview.org/) and kappanhang as a description and re-implemented independently here; no code from these projects was copied.
- **Data sources:** Repeater lists from [a23-wertheim.de](https://a23-wertheim.de) (D-STAR list by DL2HCK), place search via [Nominatim / OpenStreetMap](https://nominatim.openstreetmap.org) (data (c) OpenStreetMap contributors, ODbL). Custom repeaters: `eigene_relais.json`.

## License

MIT, see [LICENSE](LICENSE).
