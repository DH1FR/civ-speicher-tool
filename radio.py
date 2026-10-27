"""Geraeteebene: Speicher lesen/schreiben/loeschen ueber CI-V (oder Simulator)."""
from icom_net import IcomLink, NetError
from memory import MODELS, decode, encode, request_payload, delete_payload

CMD = b'\x1a\x00'


class Radio:
    def __init__(self, model):
        self.model = model

    def read_channel(self, number, group=None):
        raise NotImplementedError

    def write_channel(self, ch):
        raise NotImplementedError

    def clear_channel(self, number, group=None):
        raise NotImplementedError

    def close(self):
        pass

    def read_all(self, progress=None, groups=None):
        """Liest alle Speicher der angegebenen Gruppen (Standard: alle Gruppen des Modells)."""
        m = self.model
        groups = list(groups) if groups is not None else m.groups()
        out = []
        per = m.last - m.first + 1
        total = per * len(groups)
        done = 0
        for g in groups:
            for n in range(m.first, m.last + 1):
                for attempt in range(2):
                    try:
                        ch = self.read_channel(n, g)
                        break
                    except NetError as e:
                        if 'NG' in str(e):      # Gruppe/Kanal existiert nicht
                            ch = None
                            break
                        if attempt:
                            raise
                if ch:
                    out.append(ch)
                done += 1
                if progress and not progress(done, total, g, n):
                    return out
        return out


class IcomRadio(Radio):
    def __init__(self, model, host, user, password, port=50001):
        super().__init__(model)
        self.link = IcomLink(host, user, password, port)
        self.link.connect()
        if self.link.civ_addr != model.civ:
            # Geraet meldet eigene CI-V-Adresse; sie wird verwendet, aber ein Modellfehler faellt auf
            self.warning = f'CI-V-Adresse 0x{self.link.civ_addr:02X} (erwartet 0x{model.civ:02X}) - richtiges Geraet gewaehlt?'
        else:
            self.warning = ''

    def read_channel(self, number, group=None):
        g = self.model.group if group is None else group
        data = self.link.transact(CMD + request_payload(self.model, g, number), CMD)
        return decode(self.model, data)

    def write_channel(self, ch):
        self.link.transact(CMD + encode(self.model, ch), None)

    def clear_channel(self, number, group=None):
        g = self.model.group if group is None else group
        try:
            self.link.transact(CMD + delete_payload(self.model, g, number), None)
        except NetError as e:
            if 'keine Antwort' not in str(e):
                raise
        # Ergebnis pruefen: manche Geraete quittieren das Loeschen nicht immer
        if self.read_channel(number, g) is not None:
            raise NetError(f'Speicher Gruppe {g} / Kanal {number} konnte nicht geloescht werden')

    def close(self):
        self.link.close()


class SimRadio(Radio):
    """Simuliertes Geraet zum Ausprobieren ohne Hardware (Host 'sim')."""

    def __init__(self, model):
        super().__init__(model)
        self.mem = {}        # (Gruppe, Nummer) -> Payload
        self.warning = 'Simulation - kein echtes Geraet'

    def read_channel(self, number, group=None):
        raw = self.mem.get((self.model.group if group is None else group, number))
        return decode(self.model, raw) if raw else None

    def write_channel(self, ch):
        self.mem[(ch.group, ch.number)] = encode(self.model, ch)

    def clear_channel(self, number, group=None):
        self.mem.pop((self.model.group if group is None else group, number), None)


def open_radio(model_key, cfg):
    model = MODELS[model_key]
    if cfg['host'].strip().lower() == 'sim':
        return SimRadio(model)
    return IcomRadio(model, cfg['host'].strip(), cfg['user'], cfg['password'], int(cfg.get('port', 50001)))
