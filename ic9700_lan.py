#!/usr/bin/env python3
"""Direkte Verbindung zum IC-9700 ueber Ethernet (Icoms UDP-Protokoll, ohne wfview).

Das Protokoll ist proprietaer; es ist hier nach der Beschreibung der Open-Source-Clients
kappanhang (Go) und wfview nachgebaut, nicht nach Icom-Quellcode:
  Control-Stream UDP 50001: Handshake, Login (Passwort verschluesselt), Token, Verbindungsanfrage
  Serial-Stream  UDP 50002: CI-V-Frames hin und her (wie ein serielles Kabel)

Zugangsdaten stehen in ic9700.ini (Host, Benutzer, Passwort) oder in IC9700_HOST/_USER/_PASS.
Wichtig: Das Geraet laesst nur EINEN Netzwerk-Client zu. wfview muss beendet sein, sonst
schlaegt der Login fehl (und die lokalen UDP-Ports 50002 sind belegt).

Diese Datei ist die Bibliothek (LanRig); die Kommandozeile ist pegel_lan.py.
"""
import configparser
import os
import queue
import random
import socket
import struct
import threading
import time
from pathlib import Path

import pegel2

CONTROL_PORT, SERIAL_PORT, AUDIO_PORT = 50001, 50002, 50003
SAMPLE_RATE, TX_BUF_MS = 48000, 150
DEVNAME = b"IC-705"  # kappanhang meldet sich fuer alle Funkgeraete so; das Geraet prueft den Namen nicht
VERBOSE = False

_TABLE = {
    32: 0x47, 33: 0x5d, 34: 0x4c, 35: 0x42, 36: 0x66, 37: 0x20, 38: 0x23, 39: 0x46,
    40: 0x4e, 41: 0x57, 42: 0x45, 43: 0x3d, 44: 0x67, 45: 0x76, 46: 0x60, 47: 0x41,
    48: 0x62, 49: 0x39, 50: 0x59, 51: 0x2d, 52: 0x68, 53: 0x7e, 54: 0x7c, 55: 0x65,
    56: 0x7d, 57: 0x49, 58: 0x29, 59: 0x72, 60: 0x73, 61: 0x78, 62: 0x21, 63: 0x6e,
    64: 0x5a, 65: 0x5e, 66: 0x4a, 67: 0x3e, 68: 0x71, 69: 0x2c, 70: 0x2a, 71: 0x54,
    72: 0x3c, 73: 0x3a, 74: 0x63, 75: 0x4f, 76: 0x43, 77: 0x75, 78: 0x27, 79: 0x79,
    80: 0x5b, 81: 0x35, 82: 0x70, 83: 0x48, 84: 0x6b, 85: 0x56, 86: 0x6f, 87: 0x34,
    88: 0x32, 89: 0x6c, 90: 0x30, 91: 0x61, 92: 0x6d, 93: 0x7b, 94: 0x2f, 95: 0x4b,
    96: 0x64, 97: 0x38, 98: 0x2b, 99: 0x2e, 100: 0x50, 101: 0x40, 102: 0x3f, 103: 0x55,
    104: 0x33, 105: 0x37, 106: 0x25, 107: 0x77, 108: 0x24, 109: 0x26, 110: 0x74, 111: 0x6a,
    112: 0x28, 113: 0x53, 114: 0x4d, 115: 0x69, 116: 0x22, 117: 0x5c, 118: 0x44, 119: 0x31,
    120: 0x36, 121: 0x58, 122: 0x3b, 123: 0x7a, 124: 0x51, 125: 0x5f, 126: 0x52,
}
assert len(_TABLE) == 95


def passcode(text):
    """Benutzername/Passwort fuer das Login-Paket verschluesseln (max. 16 Zeichen)."""
    data = text.encode()
    out = bytearray(16)
    for i in range(min(len(data), 16)):
        p = data[i] + i
        if p > 126:
            p = 32 + p % 127
        out[i] = _TABLE.get(p, 0)
    return bytes(out)


def dbg(*a):
    if VERBOSE:
        print(*a, flush=True)


class Stream:
    """Ein UDP-Stream (Control oder Serial) mit Handshake, Ping, Idle und Retransmit."""

    def __init__(self, host, remote_port, local_port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", local_port))
        self.sock.connect((host, remote_port))
        self.sock.settimeout(0.5)
        ip, port = self.sock.getsockname()
        ip32 = struct.unpack(">I", socket.inet_aton(ip))[0]
        self.local_sid = ((ip32 << 16) & 0xFFFFFFFF) | (port & 0xFFFF)
        self.remote_sid = 0
        self.send_seq = 1
        self.pkt7_seq = 1
        self.pkt7_inner = 0x8304
        self.txbuf = {}
        self.lock = threading.Lock()
        self.queue = queue.Queue()
        self.running = False
        self.last_nonidle = 0.0
        self.use_idle = True
        self.threads = []

    # ---- Pakete bauen -------------------------------------------------------
    def sids(self):
        return struct.pack(">II", self.local_sid, self.remote_sid)

    def ctrl(self, typ, word=0):
        return bytes([0x10, 0, 0, 0, typ, 0, word & 0xFF, word >> 8]) + self.sids()

    def put_sids(self, p):
        p[8:16] = self.sids()

    # ---- Senden -------------------------------------------------------------
    def raw(self, data):
        dbg("TX", bytes(data).hex(" "))
        try:
            self.sock.send(bytes(data))
        except OSError:
            pass

    def send_tracked(self, packet, idle=False):
        """Paket mit laufender Sequenznummer (Bytes 6-7) senden und fuer Retransmit merken."""
        p = bytearray(packet)
        with self.lock:
            seq = self.send_seq
            self.send_seq = (self.send_seq + 1) & 0xFFFF
            p[6], p[7] = seq & 0xFF, seq >> 8
            self.txbuf[seq] = bytes(p)
            if len(self.txbuf) > 400:
                self.txbuf.pop(next(iter(self.txbuf)))
            if not idle:
                self.last_nonidle = time.time()
        self.raw(p)

    # ---- Handshake ----------------------------------------------------------
    def _recv_match(self, pred, timeout):
        end = time.time() + timeout
        while time.time() < end:
            try:
                r = self.sock.recv(2048)
            except socket.timeout:
                continue
            dbg("RX", r.hex(" "))
            if pred(r):
                return r
        return None

    def handshake(self):
        for _ in range(5):
            self.raw(self.ctrl(3))
            self.raw(self.ctrl(3))
            r = self._recv_match(lambda r: len(r) == 16 and r[4] == 4, 1.0)
            if r:
                self.remote_sid = struct.unpack(">I", r[8:12])[0]
                break
        else:
            raise TimeoutError("keine Antwort vom IC-9700 (IP, Network Control und wfview beendet pruefen)")
        for _ in range(5):
            self.raw(self.ctrl(6, 1))
            self.raw(self.ctrl(6, 1))
            if self._recv_match(lambda r: len(r) == 16 and r[4] == 6 and r[6] == 1, 1.0):
                break
        else:
            raise TimeoutError("Handshake-Bestaetigung vom IC-9700 fehlt")
        self.running = True
        for target in (self._rx, self._idle, self._ping) if self.use_idle else (self._rx, self._ping):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self.threads.append(t)

    # ---- Hintergrund-Threads ------------------------------------------------
    def _rx(self):
        while self.running:
            try:
                r = self.sock.recv(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            dbg("RX", r.hex(" "))
            self._handle(r)

    def _handle(self, r):
        n = len(r)
        if n == 21 and r[1:6] == b"\x00\x00\x00\x07\x00":
            if r[16] == 0:  # Ping vom Geraet beantworten
                p = bytearray(21)
                p[0], p[4] = 0x15, 0x07
                p[6:8] = r[6:8]
                self.put_sids(p)
                p[16] = 0x01
                p[17:21] = r[17:21]
                self.raw(p)
            return
        if n >= 16 and r[0] in (0x10, 0x18) and r[1:6] == b"\x00\x00\x00\x01\x00":
            if r[0] == 0x10:
                seqs = [struct.unpack("<H", r[6:8])[0]]
            else:
                seqs = []
                for i in range(16, n - 3, 4):
                    a, b = struct.unpack("<HH", r[i:i + 4])
                    seqs.extend(range(a, b + 1))
            for s in seqs:
                p = self.txbuf.get(s)
                if p is None:
                    p = bytes([0x10, 0, 0, 0, 0, 0, s & 0xFF, s >> 8]) + self.sids()
                self.raw(p)
                self.raw(p)
            return
        if n == 16 and r[:6] == b"\x10\x00\x00\x00\x00\x00":  # Idle vom Geraet
            return
        self.queue.put(r)

    def _idle(self):
        while self.running:
            time.sleep(0.1 if time.time() - self.last_nonidle < 1.0 else 1.0)
            if self.running:
                self.send_tracked(self.ctrl(0), idle=True)

    def _ping(self):
        n = 0
        while self.running:
            p = bytearray(21)
            p[0], p[4] = 0x15, 0x07
            self.put_sids(p)
            with self.lock:
                p[6], p[7] = self.pkt7_seq & 0xFF, self.pkt7_seq >> 8
                self.pkt7_seq = (self.pkt7_seq + 1) & 0xFFFF
                inner = self.pkt7_inner
                self.pkt7_inner = (self.pkt7_inner + 1) & 0xFFFF
            p[17], p[18], p[19], p[20] = random.randrange(256), inner & 0xFF, inner >> 8, 0x06
            self.raw(p)
            for _ in range(30):  # 3 s, aber schnell beendbar
                if not self.running:
                    return
                time.sleep(0.1)

    def close(self):
        if self.running and self.remote_sid:
            self.raw(self.ctrl(5))
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass


class Control(Stream):
    tx_audio = False  # Mikrofon-Audiostrom zum Geraet beim Login freischalten

    def __init__(self, host):
        super().__init__(host, CONTROL_PORT, CONTROL_PORT)
        self.inner = 0
        self.auth_id = b"\0" * 6

    def _inner(self, p):
        p[22], p[23], p[24] = 0, self.inner & 0xFF, self.inner >> 8
        self.inner += 1

    def send_login(self, user, password):
        p = bytearray(128)
        p[0] = 0x80
        self.put_sids(p)
        p[16:22] = b"\x00\x00\x00\x70\x01\x00"
        self._inner(p)
        p[26:28] = os.urandom(2)
        p[64:80] = passcode(user)
        p[80:96] = passcode(password)
        p[96:104] = b"icom-pc\x00"
        self.send_tracked(p)

    def send_auth(self, magic):
        p = bytearray(64)
        p[0] = 0x40
        self.put_sids(p)
        p[16:22] = bytes([0, 0, 0, 0x30, 0x01, magic])
        self._inner(p)
        p[26:32] = self.auth_id
        self.send_tracked(p)

    def send_conninfo(self, user, a8id, tx_audio=False):
        p = bytearray(144)
        p[0] = 0x90
        self.put_sids(p)
        p[16:22] = b"\x00\x00\x00\x80\x01\x03"
        self._inner(p)
        p[26:32] = self.auth_id
        p[32:48] = a8id
        p[64:64 + len(DEVNAME)] = DEVNAME
        p[96:112] = passcode(user)
        p[112:120] = bytes([1, 1 if tx_audio else 0, 4, 4, 0, 0, SAMPLE_RATE >> 8, SAMPLE_RATE & 0xFF])
        p[120:124] = bytes([0, 0, SAMPLE_RATE >> 8, SAMPLE_RATE & 0xFF])
        p[124:128] = bytes([0, 0, SERIAL_PORT >> 8, SERIAL_PORT & 0xFF])
        p[128:134] = bytes([0, 0, AUDIO_PORT >> 8, AUDIO_PORT & 0xFF, 0, 0])
        p[134:136] = bytes([TX_BUF_MS >> 8, TX_BUF_MS & 0xFF])
        p[136:144] = bytes([1, 0, 0, 0, 0, 0, 0, 0])
        self.send_tracked(p)

    def login(self, user, password, timeout=10):
        self.handshake()
        self.send_login(user, password)
        end = time.time() + timeout
        got_login = False
        auth_ok, a8id, requested = False, None, False
        while time.time() < end:
            try:
                r = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            n = len(r)
            if n == 96 and r[:8] == b"\x60\x00\x00\x00\x00\x00\x01\x00":
                if r[48:52] == b"\xff\xff\xff\xfe":
                    raise PermissionError("Benutzername oder Passwort falsch (oder anderer Client angemeldet)")
                self.auth_id = bytes(r[26:32])
                got_login = True
                self.send_auth(0x02)
                self.send_auth(0x05)
            elif n == 168 and r[:6] == b"\xa8\x00\x00\x00\x00\x00":
                a8id = bytes(r[66:82])
            elif n == 64 and r[:6] == b"\x40\x00\x00\x00\x00\x00":
                if r[21] == 0x05:
                    auth_ok = True
            elif n == 80 and r[:6] == b"\x50\x00\x00\x00\x00\x00":
                if r[48:51] == b"\xff\xff\xff":
                    raise PermissionError("Anmeldung vom IC-9700 abgelehnt")
                if r[48:51] == b"\x00\x00\x00" and r[64] == 1:
                    raise ConnectionError("IC-9700 hat die Verbindung getrennt")
            elif n == 144 and r[:6] == b"\x90\x00\x00\x00\x00\x00" and r[96] == 1:
                t = threading.Thread(target=self._reauth, daemon=True)
                t.start()
                self.threads.append(t)
                return r[64:].split(b"\0")[0].decode(errors="replace")
            if got_login and auth_ok and a8id and not requested:
                self.send_conninfo(user, a8id, self.tx_audio)
                requested = True
        raise TimeoutError("Login-Ablauf beim IC-9700 nicht abgeschlossen")

    def _reauth(self):
        """Das Geraet trennt nach etwa einer Minute, wenn der Token nicht erneuert wird."""
        while self.running:
            for _ in range(450):  # 45 s, in kleinen Schritten, damit das Beenden schnell geht
                if not self.running:
                    return
                time.sleep(0.1)
            self.send_auth(0x05)
            while not self.queue.empty():  # Antworten (64 Byte) verwerfen
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break

    def logout(self):
        if self.running:
            self.send_auth(0x01)
            time.sleep(0.3)
        self.close()


class Serial(Stream):
    def __init__(self, host):
        super().__init__(host, SERIAL_PORT, SERIAL_PORT)
        self.ser_seq = 1

    def open(self):
        self.handshake()
        self._open_close(True)

    def _open_close(self, opening):
        p = bytearray(22)
        p[0] = 0x16
        self.put_sids(p)
        p[16:19] = b"\xc0\x01\x00"
        p[19], p[20] = self.ser_seq >> 8, self.ser_seq & 0xFF
        self.ser_seq += 1
        p[21] = 0x05 if opening else 0x00
        self.send_tracked(p)

    def send_civ(self, payload):
        p = bytearray(21 + len(payload))
        p[0] = 0x15 + len(payload)
        self.put_sids(p)
        p[16], p[17], p[18] = 0xC1, len(payload), 0x00
        p[19], p[20] = self.ser_seq >> 8, self.ser_seq & 0xFF
        self.ser_seq = (self.ser_seq + 1) & 0xFFFF
        p[21:] = payload
        self.send_tracked(p)

    def recv_civ(self, timeout):
        """Naechste CI-V-Nutzdaten (bytes) oder None."""
        end = time.time() + timeout
        while time.time() < end:
            try:
                r = self.queue.get(timeout=max(0.01, end - time.time()))
            except queue.Empty:
                return None
            # Laenge steht in Byte 0-3 (little endian), Nutzlaenge in Byte 17-18 (Scope-Pakete sind 518 Byte lang)
            if (len(r) >= 22 and r[16] == 0xC1 and int.from_bytes(r[0:4], "little") == len(r)
                    and (r[17] | r[18] << 8) == len(r) - 21):
                return bytes(r[21:])
        return None

    def shutdown(self):
        if self.running:
            self._open_close(False)
            time.sleep(0.3)
        self.close()


class Audio(Stream):
    """Audio-Datenstrom (UDP 50003): 16-Bit-PCM, mono, 48 kHz; ein 20-ms-Block kommt in zwei Paketen."""

    HEAD1, HEAD2 = b"\x6c\x05\x00\x00\x00\x00", b"\x44\x02\x00\x00\x00\x00"

    def __init__(self, host):
        super().__init__(host, AUDIO_PORT, AUDIO_PORT)
        self.use_idle = False  # dieser Strom nutzt keine Idle-Pakete
        self.pcm = queue.Queue()  # (Sequenznummer, Nutzdaten)
        self.tx_count = 0

    def open(self):
        self.handshake()

    def send_pcm(self, block):
        """Einen 20-ms-Block (1920 Byte, 16-Bit mono 48 kHz) zum Geraet senden: zwei Pakete (1364 + 556 Byte).

        Format wie beim Empfang: Laenge (LE), Folgenummer, Kennungen, 0x8000, eigene Zaehlung (BE), Nutzlaenge (BE)."""
        if len(block) != 1920:
            raise ValueError("ein Block muss 1920 Byte lang sein")
        for part in (block[:1364], block[1364:]):
            p = bytearray(24 + len(part))
            p[0:4] = len(p).to_bytes(4, "little")
            self.put_sids(p)
            p[16], p[17] = 0x80, 0x00
            p[18], p[19] = self.tx_count >> 8, self.tx_count & 0xFF
            self.tx_count = (self.tx_count + 1) & 0xFFFF
            p[22], p[23] = len(part) >> 8, len(part) & 0xFF
            p[24:] = part
            self.send_tracked(p)

    def _handle(self, r):
        if len(r) >= 24 and r[:6] in (self.HEAD1, self.HEAD2) and len(r) in (1388, 580):
            self.pcm.put((r[6] | r[7] << 8, bytes(r[24:])))
            return
        super()._handle(r)

    def shutdown(self):
        self.close()


def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(Path(__file__).with_name("ic9700.ini"))
    sec = cfg["radio"] if cfg.has_section("radio") else {}
    return (os.environ.get("IC9700_HOST") or sec.get("host", "192.168.20.200"),
            os.environ.get("IC9700_USER") or sec.get("user", ""),
            os.environ.get("IC9700_PASS") or sec.get("password", ""))


class LanRig(pegel2.Rig):
    """Wie pegel2.Rig (freq, smeter_raw, select, set_freq, ...), aber per Ethernet statt PTY."""

    def __init__(self, host=None, user=None, password=None, audio=False, tx_audio=False):
        h, u, p = load_config()
        host, user, password = host or h, user or u, password or p
        if not user or not password:
            raise SystemExit("Benutzer/Passwort fehlen: ic9700.ini (siehe Datei) oder IC9700_USER/IC9700_PASS setzen")
        self.ctl = self.ser = None
        self.frames = queue.Queue()  # normale CI-V-Antworten
        self.scope = {}              # Empfaenger (0 = Main, 1 = Sub) -> (Zeit, letzter Scope-Frame)
        self.scope_on = False
        self.audio = None
        self._pump_run = False
        self.ctl = Control(host)
        self.ctl.tx_audio = tx_audio
        try:
            self.device = self.ctl.login(user, password)
            self.ser = Serial(host)
            self.ser.open()
            if audio:
                self.audio = Audio(host)
                self.audio.open()
            self._pump_run = True
            threading.Thread(target=self._pump, daemon=True).start()
        except BaseException:
            self.close()
            raise

    def _pump(self):
        """Zerlegt den CI-V-Datenstrom in Frames: Scope-Daten (27 00) getrennt von den Antworten."""
        buf = b""
        while self._pump_run:
            ser = self.ser
            if ser is None:
                break
            data = ser.recv_civ(0.2)
            if not data:
                continue
            buf += data
            while True:
                start = buf.find(b"\xfe\xfe")
                stop = buf.find(b"\xfd", start + 2) if start >= 0 else -1
                if start < 0 or stop < 0:
                    break
                f, buf = buf[start:stop + 1], buf[stop + 1:]
                if len(f) > 7 and f[4] == 0x27 and f[5] == 0x00:
                    self.scope[f[6]] = (time.time(), f)
                else:
                    self.frames.put(f)

    def civ(self, *cmd):
        frame = bytes([0xFE, 0xFE, pegel2.CIV_RIG, pegel2.CIV_CTRL, *cmd, 0xFD])
        while not self.frames.empty():  # alte Frames verwerfen
            try:
                self.frames.get_nowait()
            except queue.Empty:
                break
        self.ser.send_civ(frame)
        end = time.time() + 1.5
        while time.time() < end:
            try:
                f = self.frames.get(timeout=0.2)
            except queue.Empty:
                continue
            if f[2] == pegel2.CIV_CTRL and f[3] == pegel2.CIV_RIG and f[4] in (cmd[0], 0xFB, 0xFA):
                return f
        raise TimeoutError(f"keine CI-V-Antwort auf {frame.hex(' ')}")

    def scope_enable(self, on=True):
        """Scope-Datenausgabe ein/aus (27 11). Immer wieder ausschalten, sonst sendet das Geraet weiter."""
        self.civ(0x27, 0x11, 0x01 if on else 0x00)
        self.scope_on = on

    def close(self):
        self._pump_run = False
        if self.scope_on and self.ser is not None:
            try:
                self.scope_enable(False)
            except Exception:
                pass
        for s, fn in ((self.audio, "shutdown"), (self.ser, "shutdown"), (self.ctl, "logout")):
            if s is not None:
                try:
                    getattr(s, fn)()
                except Exception:
                    s.close()
        self.ser = self.ctl = self.audio = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
