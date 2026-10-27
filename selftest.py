"""Offline-Selbsttest (ohne Geraet): python selftest.py"""
import repeaters
from memory import IC9700, IC705, Channel, decode, encode, convert_set, MHZ
from radio import SimRadio
import icom_net  # prueft die Passwort-Tabelle per assert

# Kodierung/Dekodierung, Rundlauf
for m in (IC9700, IC705):
    ch = Channel(number=5, group=m.group, name='DB0ABB Adelebsen', freq=145_750_000, duplex='DUP-',
                 offset=600_000, tone_mode='TONE', tone=88.5, mode='FM')
    p = encode(m, ch)
    assert len(p) == m.length, (m.key, len(p), m.length)
    back = decode(m, p)
    for f in ('number', 'name', 'freq', 'duplex', 'offset', 'tone_mode', 'tone', 'mode'):
        assert getattr(back, f) == getattr(ch, f), (m.key, f, getattr(back, f))
    # gelesener Kanal behaelt Rohdaten, Aenderung wirkt
    back.name = 'NEU'
    assert decode(m, encode(m, back)).name == 'NEU'
    dv = Channel(number=6, group=m.group, name='DB0ABL', freq=439_900_000, mode='DV', duplex='DUP-',
                 offset=7_600_000, ur='CQCQCQ', r1='DB0ABL B', r2='DB0ABL G')
    b2 = decode(m, encode(m, dv))
    assert (b2.ur, b2.r1, b2.r2, b2.mode) == ('CQCQCQ', 'DB0ABL B', 'DB0ABL G', 'DV')
print('Codec OK')

# Simulator
r = SimRadio(IC9700)
r.write_channel(Channel(number=1, group=1, name='X', freq=145_500_000))
r.write_channel(Channel(number=1, group=2, name='Y', freq=439_000_000))
assert [(c.group, c.number) for c in r.read_all()] == [(1, 1), (2, 1)]
print('Simulator OK')

# Kopieren 9700 -> 705 und zurueck (Gruppen)
chs = [Channel(number=1, group=1, name='A', freq=145_500_000), Channel(number=1, group=2, name='B', freq=439_000_000),
       Channel(number=1, group=3, name='C', freq=1_298_000_000)]
out, notes = convert_set(chs, IC9700, IC705)
assert [(c.group, c.number) for c in out] == [(1, 1), (2, 1)] and len(notes) == 1, (out, notes)
back, _ = convert_set(out, IC705, IC9700)
assert [(c.group, c.number) for c in back] == [(1, 1), (2, 1)]
print('Kopieren OK')

# Relais (benoetigt Internet): Hamburg
try:
    lat, lon, name = repeaters.geocode('20095 Hamburg')
    n9700 = repeaters.search(lat, lon, 60, IC9700)
    n705 = repeaters.search(lat, lon, 60, IC705)
    print(f'Relais bei {name[:40]}: IC-9700 {len(n9700)}, IC-705 {len(n705)}')
    assert all(IC705.band_of(x.freq) for x in n705)
    print(repeaters.to_channel(n9700[0], 1, IC9700))
except OSError as e:
    print('Relaistest uebersprungen:', e)
