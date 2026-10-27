"""Speicherkanal-Modell und CI-V-Kodierung (Befehl 1A 00) fuer IC-9700 und IC-705.

Das Byte-Layout stammt aus den wfview-Rig-Definitionen (MemFormat). Es wurde
hier nicht gegen echte Geraete getestet: Kanaele, die vom Geraet gelesen wurden,
behalten ihre Rohdaten (raw) und werden beim Schreiben nur an den bekannten
Feldern geaendert.
"""
import re
from dataclasses import dataclass, field, asdict

MODES = {'LSB': 0, 'USB': 1, 'AM': 2, 'CW': 3, 'RTTY': 4, 'FM': 5, 'WFM': 6,
         'CW-R': 7, 'RTTY-R': 8, 'DV': 17, 'DD': 22}
MODE_NAMES = {v: k for k, v in MODES.items()}
DUPLEX = ['OFF', 'DUP-', 'DUP+', 'RPS']      # RPS nur IC-9700 im DD-Modus
TONEMODES = ['OFF', 'TONE', 'TSQL', 'DTCS']

MHZ = 1_000_000


@dataclass(frozen=True)
class Model:
    key: str
    title: str
    civ: int
    fmt: str
    group: int
    first: int
    last: int
    bands: tuple          # erlaubte Baender (Hz von, Hz bis)
    modes: tuple
    group_range: tuple = (0, 0)     # (erste, letzte) Speichergruppe
    band_groups: tuple = ()         # ((Band, Gruppe), ...) falls Gruppen fest an Baender gebunden sind
    group_labels: tuple = ()        # ((Gruppe, Standardname), ...)

    def group_for(self, hz):
        """Gruppe, in die eine Frequenz gehoert (nur IC-9700: Gruppe = Band), sonst None."""
        for band, g in self.band_groups:
            if band[0] <= hz <= band[1]:
                return g
        return None

    def groups(self):
        return list(range(self.group_range[0], self.group_range[1] + 1))

    def default_label(self, g):
        return dict(self.group_labels).get(g, '')

    @property
    def parser(self):
        return [(int(p), int(w), s) for p, w, s in re.findall(r'%(\d+)\.(\d+)([A-Za-z])', self.fmt)]

    @property
    def length(self):
        return max(p - 1 + w for p, w, _ in self.parser)

    def band_of(self, hz):
        for lo, hi in self.bands:
            if lo <= hz <= hi:
                return (lo, hi)
        return None


BAND_2M = (144 * MHZ, 146 * MHZ)
BAND_70 = (430 * MHZ, 440 * MHZ)
BAND_23 = (1240 * MHZ, 1300 * MHZ)

IC9700 = Model(
    'ic9700', 'IC-9700', 0xA2,
    '%1.1a %2.2b %4.1c %5.5f %10.1g %11.1h %12.1i %13.1j %14.1m %15.3n %18.3o %21.1p '
    '%22.2q %24.1r %25.3s %28.8t %36.8u %44.8v %52.16z',
    group=1, first=1, last=99,
    bands=(BAND_2M, BAND_70, BAND_23),
    modes=('LSB', 'USB', 'AM', 'CW', 'FM', 'CW-R', 'DV', 'DD'),
    group_range=(1, 3),
    band_groups=((BAND_2M, 1), (BAND_70, 2), (BAND_23, 3)),
    group_labels=((1, '2 m'), (2, '70 cm'), (3, '23 cm')))

IC705 = Model(
    'ic705', 'IC-705', 0xA4,
    '%1.2a %3.2b %5.1d %6.5f %11.1g %12.1h %13.1i %14.1j %15.1m %16.3n %19.3o %22.1p '
    '%23.2q %25.1r %26.3s %29.8t %37.8u %45.8v %53.5F %58.1G %59.1H %60.1I %61.1J %62.1M '
    '%63.3N %66.3O %69.1P %70.2Q %72.1R %73.3S %76.8T %84.8U %92.8V %100.16z',
    group=1, first=0, last=99,
    bands=((30_000, 60 * MHZ), (144 * MHZ, 148 * MHZ), (430 * MHZ, 450 * MHZ)),    # KW/6 m, 2 m, 70 cm
    modes=('LSB', 'USB', 'AM', 'CW', 'RTTY', 'FM', 'WFM', 'CW-R', 'RTTY-R', 'DV'),
    group_range=(0, 99))

MODELS = {m.key: m for m in (IC9700, IC705)}


@dataclass
class Channel:
    number: int = 1
    group: int = 0
    name: str = ''
    freq: int = 0                 # Hz
    mode: str = 'FM'
    filter: int = 1
    datamode: int = 0
    duplex: str = 'OFF'
    offset: int = 0               # Hz
    tone_mode: str = 'OFF'
    tone: float = 88.5
    tsql: float = 88.5
    dtcs_pol: int = 0
    dtcs: int = 23
    dvsql: int = 0
    dsql: int = 0
    ur: str = ''
    r1: str = ''
    r2: str = ''
    comment: str = ''
    raw: str = ''                 # Rohdaten vom Geraet (hex), nur bei gelesenen Kanaelen

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        names = Channel.__dataclass_fields__
        return Channel(**{k: v for k, v in d.items() if k in names})


# --- BCD-Helfer -------------------------------------------------------------

def bcd_be(n, nbytes):
    digits = f'{int(n):0{nbytes * 2}d}'[-nbytes * 2:]
    return bytes(int(digits[i:i + 2], 16) for i in range(0, len(digits), 2))


def from_bcd_be(b):
    return int(''.join(f'{x:02x}' for x in b))


def bcd_le(n, nbytes):
    return bcd_be(n, nbytes)[::-1]


def from_bcd_le(b):
    return from_bcd_be(bytes(b)[::-1])


def _text(b):
    return bytes(b).decode('ascii', 'replace').rstrip(' \x00')


def _pad(s, n):
    return s.encode('ascii', 'replace')[:n].ljust(n, b' ')


# --- Dekodieren / Kodieren -------------------------------------------------

def request_payload(model, group, number):
    out = b''
    for pos, w, spec in model.parser:
        if spec == 'a':
            out += bcd_be(group, w)
    return out + bcd_be(number, 2)


def delete_payload(model, group, number):
    return request_payload(model, group, number) + b'\xff'


def decode(model, payload):
    """Payload (ohne 1A 00) -> Channel oder None bei leerem Speicher."""
    payload = bytes(payload)
    ch = Channel(group=model.group)
    seen_freq = False
    for pos, w, spec in model.parser:
        if pos - 1 + w > len(payload):
            return None
        d = payload[pos - 1:pos - 1 + w]
        try:
            if spec == 'a':
                ch.group = from_bcd_be(d)
            elif spec == 'b':
                ch.number = from_bcd_be(d)
            elif spec == 'c' and d[0] == 0xFF:
                return None
            elif spec == 'd' and d[0] == 0xFF:
                return None
            elif spec == 'f':
                ch.freq = from_bcd_le(d)
                seen_freq = True
            elif spec == 'g':
                ch.mode = MODE_NAMES.get(from_bcd_be(d), 'FM')
            elif spec == 'h':
                ch.filter = from_bcd_be(d)
            elif spec == 'i':
                ch.datamode = from_bcd_be(d)
            elif spec == 'j':
                ch.duplex = DUPLEX[min((d[0] >> 4) & 0xF, 3)]
                ch.tone_mode = TONEMODES[min(d[0] & 0xF, 3)]
            elif spec == 'm':
                ch.dsql = (d[0] >> 4) & 0xF
            elif spec == 'n':
                ch.tone = from_bcd_be(d[1:3]) / 10
            elif spec == 'o':
                ch.tsql = from_bcd_be(d[1:3]) / 10
            elif spec == 'p':
                ch.dtcs_pol = ((d[0] >> 3) & 2) | (d[0] & 1)
            elif spec == 'q':
                ch.dtcs = from_bcd_be(d)
            elif spec == 'r':
                ch.dvsql = from_bcd_be(d)
            elif spec == 's':
                ch.offset = from_bcd_le(d) * 100
            elif spec == 't':
                ch.ur = _text(d)
            elif spec == 'u':
                ch.r1 = _text(d)
            elif spec == 'v':
                ch.r2 = _text(d)
            elif spec == 'z':
                ch.name = _text(d)
        except (ValueError, IndexError):
            continue
    if not seen_freq or ch.freq == 0:
        return None
    ch.raw = payload.hex()
    return ch


def encode(model, ch):
    """Channel -> Payload fuer 1A 00 (inkl. Gruppe und Kanalnummer)."""
    new = not (ch.raw and len(ch.raw) == model.length * 2)
    buf = bytearray(model.length) if new else bytearray.fromhex(ch.raw)
    for pos, w, spec in model.parser:
        if spec.isupper() and not new:
            continue                       # VFO-B-Daten des Geraets unveraendert lassen
        s = spec.lower()
        i = pos - 1
        if s == 'a':
            val = bcd_be(ch.group, w)
        elif s == 'b':
            val = bcd_be(ch.number, w)
        elif s in 'cd':
            continue                       # Scan/Split nicht anfassen
        elif s == 'f':
            val = bcd_le(ch.freq, w)
        elif s == 'g':
            val = bcd_be(MODES.get(ch.mode, 5), 1)
        elif s == 'h':
            val = bcd_be(ch.filter, 1)
        elif s == 'i':
            val = bcd_be(ch.datamode, 1)
        elif s == 'j':
            val = bytes([(DUPLEX.index(ch.duplex) << 4) | TONEMODES.index(ch.tone_mode)])
        elif s == 'm':
            val = bytes([((ch.dsql & 0xF) << 4) | (buf[i] & 0x0F)])
        elif s == 'n':
            val = b'\x00' + bcd_be(round(ch.tone * 10), 2)
        elif s == 'o':
            val = b'\x00' + bcd_be(round(ch.tsql * 10), 2)
        elif s == 'p':
            val = bytes([((ch.dtcs_pol << 3) & 0x10) | (ch.dtcs_pol & 1)])
        elif s == 'q':
            val = bcd_be(ch.dtcs, 2)
        elif s == 'r':
            val = bcd_be(ch.dvsql, 1)
        elif s == 's':
            val = bcd_le(ch.offset // 100, w)
        elif s == 't':
            val = _pad(ch.ur, w)
        elif s == 'u':
            val = _pad(ch.r1, w)
        elif s == 'v':
            val = _pad(ch.r2, w)
        elif s == 'z':
            val = _pad(ch.name, w)
        else:
            continue
        buf[i:i + len(val)] = val
    return bytes(buf)


def convert_set(channels, src, dst, existing=()):
    """Speicher von einem Geraet auf das andere uebertragen.
    IC-9700: Gruppe richtet sich nach dem Band (1 = 2 m, 2 = 70 cm, 3 = 23 cm).
    IC-705 : die Gruppennummer bleibt erhalten (9700-Gruppe 1 -> 705-Gruppe 1).
    Gibt (Kanaele, Hinweise) zurueck. Kollidierende Nummern werden auf freie Plaetze verschoben."""
    out, notes = [], []
    used = {(c.group, c.number) for c in existing}    # beim Zusammenfuehren schon belegte Plaetze
    for ch in sorted(channels, key=lambda c: (c.group, c.number)):
        if dst.band_of(ch.freq) is None:
            notes.append(f'G{ch.group}/{ch.number} {ch.name}: {ch.freq / MHZ:.4f} MHz nicht im Bereich des {dst.title}')
            continue
        if ch.mode not in dst.modes:
            notes.append(f'G{ch.group}/{ch.number} {ch.name}: Betriebsart {ch.mode} am {dst.title} nicht verfuegbar')
            continue
        new = Channel.from_dict(ch.to_dict())
        new.raw = ''
        if dst.band_groups:
            new.group = dst.group_for(ch.freq)
        else:
            new.group = max(dst.group_range[0], min(dst.group_range[1], ch.group))
        new.number = max(dst.first, min(dst.last, new.number))
        if (new.group, new.number) in used:
            free = next((n for n in range(dst.first, dst.last + 1) if (new.group, n) not in used), None)
            if free is None:
                notes.append(f'G{ch.group}/{ch.number} {ch.name}: Gruppe {new.group} voll')
                continue
            notes.append(f'G{ch.group}/{ch.number} {ch.name}: Nummer belegt, neu als G{new.group}/{free}')
            new.number = free
        used.add((new.group, new.number))
        out.append(new)
    return out, notes
