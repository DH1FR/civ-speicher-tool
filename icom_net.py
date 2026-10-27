"""Icom-Netzwerkprotokoll (UDP): Login an Port 50001, CI-V-Tunnel an Port 50002.

Nach dem Protokoll von wfview/kappanhang nachgebaut. Audio wird nicht aktiviert.
"""
import os
import queue
import random
import socket
import struct
import threading
import time

_T = [0x47, 0x5d, 0x4c, 0x42, 0x66, 0x20, 0x23, 0x46, 0x4e, 0x57, 0x45, 0x3d, 0x67, 0x76, 0x60, 0x41,
      0x62, 0x39, 0x59, 0x2d, 0x68, 0x7e, 0x7c, 0x65, 0x7d, 0x49, 0x29, 0x72, 0x73, 0x78, 0x21, 0x6e,
      0x5a, 0x5e, 0x4a, 0x3e, 0x71, 0x2c, 0x2a, 0x54, 0x3c, 0x3a, 0x63, 0x4f, 0x43, 0x75, 0x27, 0x79,
      0x5b, 0x35, 0x70, 0x48, 0x6b, 0x56, 0x6f, 0x34, 0x32, 0x6c, 0x30, 0x61, 0x6d, 0x7b, 0x2f, 0x4b,
      0x64, 0x38, 0x2b, 0x2e, 0x50, 0x40, 0x3f, 0x55, 0x33, 0x37, 0x25, 0x77, 0x24, 0x26, 0x74, 0x6a,
      0x28, 0x53, 0x4d, 0x69, 0x22, 0x5c, 0x44, 0x31, 0x36, 0x58, 0x3b, 0x7a, 0x51, 0x5f, 0x52]
assert sorted(_T) == list(range(0x20, 0x7f)), 'Passwort-Tabelle fehlerhaft'
_SEQ = [0] * 32 + _T + [0] * 1


def encode_cred(s):
    out = bytearray(16)
    for i, ch in enumerate(s.encode('latin-1', 'replace')[:16]):
        p = ch + i
        if p > 126:
            p = 32 + p % 127
        out[i] = _SEQ[p] if p < len(_SEQ) else 0
    return bytes(out)


class NetError(Exception):
    pass


def _hdr(length, typ, seq, sid, rid):
    return struct.pack('<IHHII', length, typ, seq, sid, rid)


class Stream:
    """Eine UDP-Verbindung (Control oder CI-V) mit Handshake, Ping und Retransmit."""

    def __init__(self, host, port, name):
        self.addr = (host, port)
        self.name = name
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('', 0))
        self.local_port = self.sock.getsockname()[1]
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect((host, port))
            ip = struct.unpack('>I', socket.inet_aton(probe.getsockname()[0]))[0]
            probe.close()
        except OSError:
            ip = random.getrandbits(32)
        self.myid = ((ip & 0xFFFF) << 16) | self.local_port
        self.rid = 0
        self.seq = 1            # Das Geraet zaehlt "Are you ready" (Seq 1) nicht als Datenpaket
        self.ping_seq = 0
        self.sent = {}
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.running = False

    # -- Aufbau
    def _raw(self, data):
        self.sock.sendto(data, self.addr)

    def _ctl(self, typ, seq):
        self._raw(_hdr(0x10, typ, seq, self.myid, self.rid))

    def handshake(self, timeout=6.0):
        self.sock.settimeout(0.5)
        end = time.time() + timeout
        got = False
        while time.time() < end and not got:
            self._ctl(3, 0)
            try:
                while True:
                    d, _ = self.sock.recvfrom(2048)
                    if len(d) >= 16 and struct.unpack_from('<H', d, 4)[0] == 4:
                        self.rid = struct.unpack_from('<I', d, 8)[0]
                        got = True
                        break
            except socket.timeout:
                pass
        if not got:
            raise NetError(f'{self.name}: keine Antwort von {self.addr[0]}:{self.addr[1]} (Netzwerk-Fernsteuerung am Geraet aktiv?)')
        ready = False
        while time.time() < end and not ready:
            self._ctl(6, 1)
            try:
                while True:
                    d, _ = self.sock.recvfrom(2048)
                    if len(d) >= 16 and struct.unpack_from('<H', d, 4)[0] == 6:
                        ready = True
                        break
            except socket.timeout:
                pass
        if not ready:
            raise NetError(f'{self.name}: Handshake unvollstaendig')
        self.sock.settimeout(0.3)
        self.running = True
        threading.Thread(target=self._rx, daemon=True).start()
        threading.Thread(target=self._ping, daemon=True).start()

    # -- Senden
    def send(self, body, typ=0):
        """body = alles nach dem 16-Byte-Header; Laengen-/Seq-Felder werden gesetzt."""
        with self.lock:
            seq = self.seq
            self.seq = (self.seq + 1) & 0xFFFF
            pkt = _hdr(16 + len(body), typ, seq, self.myid, self.rid) + body
            self.sent[seq] = pkt
            self.sent.pop((seq - 200) & 0xFFFF, None)
            self._raw(pkt)

    def _ping(self):
        while self.running:
            body = b'\x00' + struct.pack('<I', int(time.time() * 1000) & 0xFFFFFFFF)
            self._raw(_hdr(0x15, 7, self.ping_seq, self.myid, self.rid) + body)
            self.ping_seq = (self.ping_seq + 1) & 0xFFFF
            time.sleep(0.1)

    # -- Empfangen
    def _rx(self):
        while self.running:
            try:
                d, _ = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(d) < 16:
                continue
            ln, typ, seq = struct.unpack_from('<IHH', d, 0)
            if typ == 7 and len(d) >= 0x15:
                if d[0x10] == 0:
                    self._raw(_hdr(0x15, 7, seq, self.myid, self.rid) + b'\x01' + d[0x11:0x15])
            elif typ == 1:
                seqs = [seq] if len(d) == 16 else [struct.unpack_from('<H', d, o)[0] for o in range(16, len(d) - 1, 2)]
                for s in seqs:
                    if s in self.sent:
                        self._raw(self.sent[s])
                    else:
                        self._raw(_hdr(0x10, 0, s, self.myid, self.rid))   # Leerpaket als Ersatz
            elif typ == 5:
                self.running = False
                self.q.put(None)
            elif typ == 0 and len(d) > 16:
                self.q.put(d)

    def wait(self, pred, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                d = self.q.get(timeout=max(0.05, end - time.time()))
            except queue.Empty:
                break
            if d is None:
                raise NetError(f'{self.name}: Verbindung vom Geraet getrennt')
            if pred(d):
                return d
        raise NetError(f'{self.name}: Zeitueberschreitung')

    def close(self):
        if self.running:
            try:
                self._ctl(5, self.seq)
            except OSError:
                pass
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass


class IcomLink:
    """Verbindung zu einem Icom-Geraet; stellt CI-V-Transaktionen bereit."""

    def __init__(self, host, user, password, port=50001, civ_port=50002, controller=0xE0):
        self.host, self.user, self.password = host, user, password
        self.port, self.civ_port, self.ctrl_addr = port, civ_port, controller
        self.civ_addr = None
        self.ctrl = self.civ = None
        self.token = 0
        self.tokreq = random.getrandbits(16)
        self.inner = 0x30
        self.civ_seq = 0
        self._timer_stop = threading.Event()
        self.civ_lock = threading.Lock()

    def _inner(self):
        self.inner = (self.inner + 1) & 0xFFFF
        return self.inner

    def _token_pkt(self, kind, size=0x40, reply=0x01):
        b = bytearray(size - 16)
        struct.pack_into('>I', b, 0, size - 0x10)
        b[4], b[5] = reply, kind
        struct.pack_into('>H', b, 6, self._inner())
        struct.pack_into('<H', b, 0x0A, self.tokreq)
        struct.pack_into('<I', b, 0x0C, self.token)
        return b

    def connect(self):
        try:
            self._connect()
        except Exception:
            self.close()
            raise

    def _connect(self):
        c = self.ctrl = Stream(self.host, self.port, 'Steuerung')
        c.handshake()
        # Login
        b = self._token_pkt(0x00, 0x80)
        b[4], b[5] = 0x01, 0x00
        b[0x40 - 16:0x50 - 16] = encode_cred(self.user)
        b[0x50 - 16:0x60 - 16] = encode_cred(self.password)
        b[0x60 - 16:0x70 - 16] = b'IcomTool'.ljust(16, b'\x00')
        c.send(bytes(b))
        resp = c.wait(lambda d: len(d) == 0x60)
        if resp[0x30:0x34] == b'\xff\xff\xff\xfe':
            raise NetError('Anmeldung abgelehnt (Benutzer/Passwort pruefen)')
        self.token = struct.unpack_from('<I', resp, 0x1C)[0]
        # Token bestaetigen
        c.send(bytes(self._token_pkt(0x02)))
        caps = c.wait(lambda d: len(d) >= 0x42 + 0x66, 8.0)
        radio = caps[0x42:0x42 + 0x66]
        guid = radio[0:16]
        name = radio[0x10:0x30]
        self.civ_addr = radio[0x52]
        # CI-V-Stream anfordern
        self.civ = Stream(self.host, self.civ_port, 'CI-V')
        b = self._token_pkt(0x03, 0x90)
        b[0x20 - 16:0x30 - 16] = guid
        b[0x40 - 16:0x60 - 16] = name
        b[0x60 - 16:0x70 - 16] = encode_cred(self.user)
        b[0x70 - 16] = 0                       # kein RX-Audio
        b[0x71 - 16] = 0                       # kein TX-Audio
        struct.pack_into('>I', b, 0x7C - 16, self.civ.local_port)
        struct.pack_into('>I', b, 0x80 - 16, self.civ.local_port + 1)
        struct.pack_into('>I', b, 0x84 - 16, 150)
        b[0x88 - 16] = 1
        c.send(bytes(b))
        try:
            c.wait(lambda d: len(d) == 0x90, 4.0)
        except NetError:
            pass
        self.civ.handshake()
        self.civ.send(b'\xc0\x01\x00' + struct.pack('>H', self._civ_next()) + b'\x04')
        threading.Thread(target=self._renew, daemon=True).start()

    def _civ_next(self):
        v = self.civ_seq
        self.civ_seq = (self.civ_seq + 1) & 0xFFFF
        return v

    def _renew(self):
        while not self._timer_stop.wait(60):
            try:
                self.ctrl.send(bytes(self._token_pkt(0x05)))
            except OSError:
                return

    def close(self):
        self._timer_stop.set()
        for s in (self.civ, self.ctrl):
            if s is None:
                continue
            try:
                if s is self.civ and s.running:
                    s.send(b'\xc0\x01\x00' + struct.pack('>H', self._civ_next()) + b'\x00')
                if s is self.ctrl and self.token:
                    s.send(bytes(self._token_pkt(0x01)))
                    time.sleep(0.1)
            except OSError:
                pass
            s.close()
        self.ctrl = self.civ = None

    # -- CI-V
    def transact(self, body, match, timeout=2.5):
        """body: Befehlsbytes (ohne FE FE.. FD). match: erwartetes Antwortpraefix.
        Gibt Antwort nach dem Praefix zurueck; b'' bei ACK (FB). Wirft NetError bei NG/Timeout."""
        frame = bytes([0xFE, 0xFE, self.civ_addr, self.ctrl_addr]) + body + b'\xfd'
        with self.civ_lock:
            while not self.civ.q.empty():
                self.civ.q.get_nowait()
            pkt = b'\xc1' + struct.pack('<H', len(frame)) + struct.pack('>H', self._civ_next()) + frame
            self.civ.send(pkt)
            end = time.time() + timeout
            while time.time() < end:
                try:
                    d = self.civ.wait(lambda x: len(x) > 0x15 and x[0x10] == 0xC1, max(0.1, end - time.time()))
                except NetError as e:
                    if 'Zeit' in str(e):
                        break
                    raise
                for f in d[0x15:].split(b'\xfd'):
                    if len(f) >= 5 and f[0] == 0xFE and f[1] == 0xFE and f[2] == self.ctrl_addr and f[3] == self.civ_addr:
                        p = f[4:]
                        if p == b'\xfb':
                            return b''
                        if p == b'\xfa':
                            raise NetError('Geraet antwortet mit NG')
                        if match and p.startswith(match):
                            return p[len(match):]
        raise NetError('CI-V: keine Antwort')
