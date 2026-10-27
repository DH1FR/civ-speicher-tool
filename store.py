"""Ablage: je Geraet benannte Speichersaetze als JSON-Dateien plus config.json."""
import json
import os
import re
from memory import Channel

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
CONFIG = os.path.join(BASE, 'config.json')

DEFAULT_CONFIG = {
    'devices': {
        'ic9700': {'host': '192.168.1.65', 'port': 50001, 'user': '', 'password': ''},
        'ic705': {'host': '192.168.1.115', 'port': 50001, 'user': '', 'password': ''},
    },
    'qth': {'text': '', 'lat': None, 'lon': None, 'radius_km': 50},
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG, encoding='utf-8') as f:
            saved = json.load(f)
        for k, v in saved.get('devices', {}).items():
            cfg['devices'].setdefault(k, {}).update(v)
        cfg['qth'].update(saved.get('qth', {}))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    with open(CONFIG, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _safe(name):
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip() or 'Unbenannt'


def _dir(device):
    p = os.path.join(DATA, device)
    os.makedirs(p, exist_ok=True)
    return p


def _path(device, name):
    return os.path.join(_dir(device), _safe(name) + '.json')


def list_sets(device):
    return sorted(f[:-5] for f in os.listdir(_dir(device)) if f.endswith('.json'))


def load_set(device, name):
    """-> (Kanaele, Gruppennamen {int: str})"""
    with open(_path(device, name), encoding='utf-8') as f:
        d = json.load(f)
    names = {int(k): v for k, v in d.get('group_names', {}).items()}
    return [Channel.from_dict(c) for c in d.get('channels', [])], names


def save_set(device, name, channels, group_names=None):
    channels = sorted(channels, key=lambda c: (c.group, c.number))
    names = {str(k): v for k, v in (group_names or {}).items() if v}
    with open(_path(device, name), 'w', encoding='utf-8') as f:
        json.dump({'device': device, 'name': name, 'group_names': names,
                   'channels': [c.to_dict() for c in channels]}, f, indent=1, ensure_ascii=False)


def delete_set(device, name):
    os.remove(_path(device, name))


def rename_set(device, old, new):
    os.rename(_path(device, old), _path(device, new))


def exists(device, name):
    return os.path.exists(_path(device, name))
