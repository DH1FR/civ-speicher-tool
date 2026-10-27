"""Relaislisten (FM + D-STAR) abrufen, nach Standort/Band filtern und in Kanaele umwandeln.

Quelle: a23-wertheim.de (Icom-Repeaterlisten als CSV, D-STAR-Liste von DL2HCK).
Geocoding des Standorts: OpenStreetMap Nominatim.
"""
import csv
import io
import json
import math
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from memory import Channel, MHZ, BAND_2M, BAND_70, BAND_23
from store import BASE

UA = 'IcomTool/0.1 (Amateurfunk Speicherverwaltung)'
CACHE = os.path.join(BASE, 'cache')
URLS = {
    'FM': 'https://a23-wertheim.de/index.php/downloads/d-star/repeater-listen?download='
          '13:deutschland-fm-relaisliste-fuer-icom-geraete-mit-dr-modus-repeater-listen-unterstuetzung',
    'DSTAR': 'https://a23-wertheim.de/index.php/downloads/d-star/repeater-listen?download='
             '10:deutschland-d-star-repeater-fuer-icom-geraete-mit-dr-modus-repeater-listen-unterstuetzung',
}
DEFAULT_OFFSET = {BAND_2M: 600_000, BAND_70: 7_600_000, BAND_23: 28_000_000}


@dataclass
class Repeater:
    kind: str            # 'FM' oder 'DSTAR'
    call: str
    place: str
    freq: int
    duplex: str
    offset: int
    fm_narrow: bool
    tone_mode: str
    tone: float
    rpt1: str
    gateway: str
    lat: float
    lon: float
    dist_km: float = 0.0
    own: bool = False     # aus der eigenen Liste (eigene_relais.json)


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_list(kind, max_age_h=24, force=False):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f'{kind}.csv')
    if force or not os.path.exists(path) or time.time() - os.path.getmtime(path) > max_age_h * 3600:
        try:
            data = _get(URLS[kind])
            with open(path, 'wb') as f:
                f.write(data)
        except OSError:
            if not os.path.exists(path):
                raise
    with open(path, 'rb') as f:
        raw = f.read()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('latin-1')
    return parse_csv(kind, text)


def parse_csv(kind, text):
    out = []
    for row in csv.DictReader(io.StringIO(text), delimiter=';'):
        try:
            freq = round(float(row['Frequency']) * MHZ)
            lat, lon = float(row['Latitude']), float(row['Longitude'])
        except (KeyError, ValueError, TypeError):
            continue
        call = (row.get('Sub Name') or row.get('Repeater Call Sign') or '').strip()
        tone_txt = (row.get('Repeater Tone') or '').replace('Hz', '').strip()
        try:
            tone = float(tone_txt)
        except ValueError:
            tone = 88.5
        out.append(Repeater(
            kind=kind,
            call=call.split(' ')[0] if kind == 'DSTAR' else call,
            place=(row.get('Name') or '').strip(),
            freq=freq,
            duplex=(row.get('Dup') or 'OFF').strip().upper(),
            offset=round(float(row.get('Offset') or 0) * MHZ),
            fm_narrow=(row.get('Mode') or '').strip().upper() == 'FM-N',
            tone_mode=(row.get('TONE') or 'OFF').strip().upper(),
            tone=tone,
            rpt1=(row.get('Repeater Call Sign') or '').strip(),
            gateway=(row.get('Gateway Call Sign') or '').strip(),
            lat=lat, lon=lon))
    return out


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def geocode(text):
    """Ort oder PLZ -> (lat, lon, Anzeigename)."""
    q = urllib.parse.urlencode({'q': text, 'format': 'json', 'limit': 1, 'addressdetails': 0})
    res = json.loads(_get('https://nominatim.openstreetmap.org/search?' + q, 15))
    if not res:
        raise ValueError(f'Ort nicht gefunden: {text}')
    return float(res[0]['lat']), float(res[0]['lon']), res[0]['display_name']


OWN = os.path.join(BASE, 'eigene_relais.json')


def load_own():
    """Eigene Relais (Liste von dicts) - fuer Relais, die in den Online-Listen fehlen oder falsch sind."""
    try:
        with open(OWN, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_own(items):
    with open(OWN, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=1, ensure_ascii=False)


def own_repeaters():
    out = []
    for d in load_own():
        try:
            out.append(Repeater(
                kind=d['kind'], call=d['call'], place=d.get('place', ''), freq=int(d['freq']),
                duplex=d.get('duplex', 'OFF'), offset=int(d.get('offset', 0)), fm_narrow=bool(d.get('fm_narrow', False)),
                tone_mode=d.get('tone_mode', 'OFF'), tone=float(d.get('tone', 88.5)),
                rpt1=d.get('rpt1', ''), gateway=d.get('gateway', ''),
                lat=float(d['lat']), lon=float(d['lon']), own=True))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def find_position(call):
    """Koordinaten eines bekannten Relais per Rufzeichen (z. B. DB0KH) aus den Online-Listen."""
    key = call.strip().upper().split(' ')[0]
    for kind in ('DSTAR', 'FM'):
        try:
            for r in fetch_list(kind):
                if r.call.upper().split(' ')[0] == key:
                    return r.lat, r.lon, r.place
        except OSError:
            continue
    return None


def search(lat, lon, radius_km, model, kinds=('FM', 'DSTAR'), force=False):
    """Relais im Umkreis, die im Band des Geraets liegen (23 cm nur IC-9700), nach Entfernung sortiert.
    Eigene Relais ersetzen gleiche Eintraege (Rufzeichen + Frequenz) der Online-Listen."""
    own = [r for r in own_repeaters() if r.kind in kinds]
    own_keys = {(r.call.upper(), r.freq) for r in own}
    result = []
    for kind in kinds:
        for r in fetch_list(kind, force=force):
            if (r.call.upper(), r.freq) not in own_keys:
                result.append(r)
    result += own
    result = [r for r in result if model.band_of(r.freq) is not None]
    for r in result:
        r.dist_km = haversine(lat, lon, r.lat, r.lon)
    return sorted((r for r in result if r.dist_km <= radius_km), key=lambda r: r.dist_km)


def to_channel(r, number, model, group=None):
    ch = Channel(number=number, group=model.group if group is None else group, freq=r.freq)
    ch.name = f'{r.call} {r.place}'[:16]
    ch.duplex = r.duplex if r.duplex in ('DUP-', 'DUP+') else 'OFF'
    ch.offset = r.offset
    if ch.duplex != 'OFF' and ch.offset == 0:
        band = model.band_of(r.freq)
        ch.offset = DEFAULT_OFFSET.get(band, 0)
    if r.kind == 'DSTAR':
        ch.mode = 'DV'
        ch.ur = 'CQCQCQ'
        ch.r1 = r.rpt1[:8]
        ch.r2 = r.gateway[:8]
    else:
        ch.mode = 'FM'
        ch.filter = 2 if r.fm_narrow else 1
        if r.tone_mode in ('TONE', 'TSQL'):
            ch.tone_mode = r.tone_mode
        ch.tone = ch.tsql = r.tone
    ch.comment = f'{r.kind} {r.dist_km:.0f} km'
    return ch
