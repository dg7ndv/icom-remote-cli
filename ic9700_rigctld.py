#!/usr/bin/env python3
"""Hamlib-kompatibler rigctld-Server (NET rigctl, Modell 2) fuer WSJT-X, Log- und Rotorprogramme.

Die GUI stellt Frequenz, Modus und S-Meter aus ihrem Zustand bereit und reicht Befehle an den Worker weiter;
der Server selbst spricht nie mit dem Geraet. Zuordnung: VFOA = Main, VFOB = Sub.

Unterstuetzt: f F m M v V t T l L s S (Split nur als "nicht verfuegbar") \\dump_state \\chk_vfo \\get_powerstat
\\get_info q. Sender (T 1) ist nur erlaubt, wenn ptt_allowed gesetzt ist; er faellt nach max_tx_s Sekunden
oder beim Trennen des Clients automatisch wieder ab.

Test ohne Geraet:  ic9700_rigctld.py --demo      dann   rigctl -m 2 -r localhost:4532 f
"""
import socket
import socketserver
import threading
import time

# Hamlib-Modusname <-> CI-V-Modus (Daten-Modi PKT* = Modus plus DATA-Schalter)
HAMLIB_TO_CIV = {"LSB": (0x00, False), "USB": (0x01, False), "AM": (0x02, False), "CW": (0x03, False),
                 "RTTY": (0x04, False), "FM": (0x05, False), "CWR": (0x07, False), "RTTYR": (0x08, False),
                 "LSB-D": (0x00, True), "USB-D": (0x01, True), "FM-D": (0x05, True), "AM-D": (0x02, True),
                 "PKTLSB": (0x00, True), "PKTUSB": (0x01, True), "PKTFM": (0x05, True), "PKTAM": (0x02, True)}
CIV_TO_HAMLIB = {0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CW", 0x04: "RTTY", 0x05: "FM",
                 0x07: "CWR", 0x08: "RTTYR", 0x17: "FM", 0x22: "FM"}
PKT = {"LSB": "PKTLSB", "USB": "PKTUSB", "FM": "PKTFM", "AM": "PKTAM"}
BANDWIDTH = {"FM": 15000, "AM": 6000, "CW": 500, "CWR": 500, "RTTY": 500, "RTTYR": 500}
VFO_SLOT = {"VFOA": "main", "MAIN": "main", "CURRVFO": None, "VFOB": "sub", "SUB": "sub"}
SLOT_VFO = {"main": "VFOA", "sub": "VFOB"}
LEVEL_RAW = {"AF": "af", "RF": "rf", "SQL": "sql", "RFPOWER": "power"}

ENIMPL, ENAVAIL, EINVAL, EPROTO = -4, -11, -1, -8
RIG_NAME = "IC-9700 (LAN)"  # fuer \\get_info; andere Geraete setzen RIG_NAME und RX_RANGES vor dem Start
RX_RANGES = [(144e6, 148e6), (430e6, 450e6), (1240e6, 1300e6)]


def raw_to_db(raw):
    """S-Meter-Rohwert (0-255) in dB relativ S9, wie in pegel2/GUI."""
    return -54 + raw * 54 / 120 if raw <= 120 else (raw - 120) * 60 / 121


def dump_state():
    """Antwort auf \\dump_state (Format wie Hamlib 4.6; nur die Bereiche, die der IC-9700 abdeckt)."""
    modes = "0x1ff"
    rx = RX_RANGES
    lines = ["1", "1", "0"]
    lines += [f"{lo:.6f} {hi:.6f} {modes} -1 -1 0x17e00007 0xf" for lo, hi in rx] + ["0 0 0 0 0 0 0"]
    lines += [f"{lo:.6f} {hi:.6f} {modes} 2000 100000 0x17e00007 0xf" for lo, hi in rx] + ["0 0 0 0 0 0 0"]
    lines += [f"{modes} 1", f"{modes} 0", "0 0"]
    lines += ["0xc 2400", "0xc 1800", "0xc 3000", "0xc 0", "0x2 500", "0x2 2400", "0x2 50", "0x2 0",
              "0x10 300", "0x10 2400", "0x10 50", "0x10 0", "0x1 8000", "0x1 2400", "0x1 10000",
              "0x20 15000", "0x20 8000", "0x40 230000", "0 0"]
    lines += ["9990", "9990", "10000", "0", "10 ", "10 20 30 ",
              "0xffffffffffffffff", "0xffffffffffffffff", "0xfffffffff7ffffff", "0xfffeff7083ffffff",
              "0xffffffffffffffff", "0xffffffffffffffbf",
              "vfo_ops=0x0", "ptt_type=0x1", "targetable_vfo=0x0", "has_set_vfo=1", "has_get_vfo=1",
              "has_set_freq=1", "has_get_freq=1", "has_set_conf=0", "has_get_conf=0", "has_power2mW=0",
              "has_mW2power=0", "has_get_ant=0", "has_set_ant=0", "timeout=0", "rig_model=1",
              "rigctld_version=ic9700_rigctld", "done"]
    return "\n".join(lines) + "\n"


class Provider:
    """Schnittstelle zur GUI. Die GUI-Seite ueberschreibt die Methoden."""
    ptt_allowed = False
    max_tx_s = 120

    def snapshot(self):
        """{"sel": "main", "main": {"freq": Hz, "mode": civ, "data": bool, "raw": 0-255, "ctl": {...}}, "sub": ...}"""
        raise NotImplementedError

    def command(self, *cmd):
        """Befehl an den Worker (freq/mode/sel/ctl/ptt ...)."""
        raise NotImplementedError


class Session:
    """Eine Client-Verbindung."""

    def __init__(self, prov, log):
        self.prov, self.log = prov, log
        self.vfo = None   # None = der im Geraet gewaehlte Empfaenger
        self.ptt_on_at = None

    def slot(self, snap):
        return self.vfo or snap.get("sel", "main")

    def reply_rprt(self, code):
        return f"RPRT {code}\n"

    def handle(self, line):
        """Eine Befehlszeile verarbeiten. Gibt (Antworttext, beenden) zurueck."""
        line = line.strip()
        if not line:
            return "", False
        if line[0] in "+;|,":  # erweitertes Protokoll wird nicht gebraucht, Zeichen ignorieren
            line = line[1:].strip()
        if line.startswith("\\"):
            name, _, rest = line[1:].partition(" ")
            alias = {"dump_state": "dump_state", "chk_vfo": "chk_vfo", "get_powerstat": "powerstat",
                     "get_info": "info", "get_freq": "f", "set_freq": "F", "get_mode": "m", "set_mode": "M",
                     "get_vfo": "v", "set_vfo": "V", "get_ptt": "t", "set_ptt": "T", "get_level": "l",
                     "set_level": "L", "quit": "q", "get_split_vfo": "s", "get_split_mode": "splitmode", "get_split_freq": "splitfreq", "set_split_vfo": "S",
                     "get_rit": "j", "get_xit": "z", "get_ant": "y", "get_lock_mode": "lock"}.get(name)
            if alias is None:
                return self.reply_rprt(ENIMPL), False
            cmd, args = alias, rest.split()
        else:
            parts = line.split()
            cmd, args = parts[0], parts[1:]
        try:
            return self.run(cmd, args), cmd in ("q", "Q")
        except (ValueError, IndexError):
            return self.reply_rprt(EINVAL), False

    def run(self, cmd, args):
        p = self.prov
        if cmd == "dump_state":
            return dump_state()
        if cmd == "chk_vfo":
            return "0\n"
        if cmd == "powerstat":
            return "1\n"
        if cmd == "info":
            return RIG_NAME + "\n"
        if cmd in ("q", "Q"):
            return ""
        if cmd == "lock":
            return "0\nRPRT 0\n"
        snap = p.snapshot()
        slot = self.slot(snap)
        if cmd == "f":
            return f"{snap[slot]['freq']}\n" if slot in snap else self.reply_rprt(ENAVAIL)
        if cmd == "F":
            hz = int(round(float(args[0])))
            p.command("freq", slot, hz)
            if slot in snap:
                snap[slot]["freq"] = hz
            return self.reply_rprt(0)
        if cmd == "m":
            if slot not in snap or "mode" not in snap[slot]:
                return self.reply_rprt(ENAVAIL)
            name = CIV_TO_HAMLIB.get(snap[slot]["mode"], "USB")
            if snap[slot].get("data") and name in PKT:
                name = PKT[name]
            bw = BANDWIDTH.get(name.replace("PKT", ""), 2400)
            return f"{name}\n{bw}\n"
        if cmd == "M":
            mode = args[0].upper()
            if mode not in HAMLIB_TO_CIV:
                return self.reply_rprt(EINVAL)
            code, data = HAMLIB_TO_CIV[mode]
            p.command("mode", slot, code, data)
            return self.reply_rprt(0)
        if cmd == "v":
            return SLOT_VFO[slot] + "\n"
        if cmd == "V":
            want = VFO_SLOT.get(args[0].upper(), "?")
            if want == "?":
                return self.reply_rprt(EINVAL)
            self.vfo = want  # nur fuer diese Verbindung; das Geraet wird nicht umgeschaltet
            return self.reply_rprt(0)
        if cmd == "s":
            return "0\nNone\n"
        if cmd == "splitmode":
            return "\n0\n"
        if cmd == "splitfreq":
            return f"{snap[slot]['freq']}\n"
        if cmd in ("S", "i", "I", "r", "R", "x", "X"):
            return self.reply_rprt(ENAVAIL)
        if cmd == "y":
            return "0\n"
        if cmd in ("j", "z"):
            return "0\n"
        if cmd == "t":
            return ("1" if self.ptt_on_at else "0") + "\n"
        if cmd == "T":
            return self.set_ptt(args[0] not in ("0",))
        if cmd == "l":
            name = args[0].upper()
            if name == "STRENGTH":
                if slot not in snap or "raw" not in snap[slot]:
                    return self.reply_rprt(ENAVAIL)
                return f"{int(round(raw_to_db(snap[slot]['raw'])))}\n"
            if name in LEVEL_RAW:
                ctl = snap.get(slot, {}).get("ctl", {})
                key = LEVEL_RAW[name]
                return f"{ctl[key] / 255:.4f}\n" if key in ctl else self.reply_rprt(ENAVAIL)
            return self.reply_rprt(ENIMPL)
        if cmd == "L":
            name = args[0].upper()
            if name in LEVEL_RAW:
                val = max(0.0, min(1.0, float(args[1])))
                p.command("ctl", slot, LEVEL_RAW[name], int(round(val * 255)))
                return self.reply_rprt(0)
            return self.reply_rprt(ENIMPL)
        return self.reply_rprt(ENIMPL)

    def set_ptt(self, on):
        p = self.prov
        if not on:
            if self.ptt_on_at:
                p.command("ptt", False)
            self.ptt_on_at = None
            return self.reply_rprt(0)
        if not p.ptt_allowed:
            self.log("PTT abgelehnt (in der Oberflaeche nicht freigegeben)")
            return self.reply_rprt(ENAVAIL)
        self.ptt_on_at = time.time()
        self.log("PTT EIN (rigctld)")
        p.command("ptt", True)
        return self.reply_rprt(0)

    def close(self):
        if self.ptt_on_at:
            self.prov.command("ptt", False)
            self.ptt_on_at = None
            self.log("Verbindung zu - PTT AUS")


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        srv = self.server
        sess = Session(srv.prov, srv.log)
        self.connection.settimeout(1.0)
        srv.log(f"Client {self.client_address[0]}:{self.client_address[1]} verbunden")
        buf = b""
        try:
            while not srv.stopping:
                # Sende-Zeitlimit pruefen
                if sess.ptt_on_at and time.time() - sess.ptt_on_at > srv.prov.max_tx_s:
                    srv.prov.command("ptt", False)
                    sess.ptt_on_at = None
                    srv.log(f"PTT nach {srv.prov.max_tx_s} s automatisch AUS")
                try:
                    chunk = self.connection.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    text, quit_ = sess.handle(raw.decode("ascii", "replace"))
                    if text:
                        self.connection.sendall(text.encode())
                    if quit_:
                        return
        except OSError:
            pass
        finally:
            sess.close()
            srv.log(f"Client {self.client_address[0]} getrennt")


class RigctlServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, prov, port=4532, host="127.0.0.1", log=print):
        super().__init__((host, port), _Handler)
        self.prov, self.log, self.stopping = prov, log, False
        self.thread = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.3}, daemon=True)

    def start(self):
        self.thread.start()
        self.log(f"rigctld-Server lauscht auf {self.server_address[0]}:{self.server_address[1]}")

    def stop(self):
        self.stopping = True
        self.shutdown()
        self.server_close()


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", required=True, help="ohne Geraet mit festen Testwerten starten")
    ap.add_argument("--port", type=int, default=4532)
    a = ap.parse_args()

    class Demo(Provider):
        def __init__(self):
            self.s = {"sel": "main", "main": {"freq": 144_455_000, "mode": 0x05, "raw": 60, "ctl": {"power": 0}},
                      "sub": {"freq": 432_443_505, "mode": 0x01, "data": False, "raw": 100, "ctl": {"power": 0}}}

        def snapshot(self):
            return {k: dict(v) if isinstance(v, dict) else v for k, v in self.s.items()}

        def command(self, *cmd):
            print("Befehl:", cmd)
            if cmd[0] == "freq":
                self.s[cmd[1]]["freq"] = cmd[2]
            if cmd[0] == "mode":
                self.s[cmd[1]]["mode"], self.s[cmd[1]]["data"] = cmd[2], cmd[3]

    srv = RigctlServer(Demo(), a.port)
    srv.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()


if __name__ == "__main__":
    main()
