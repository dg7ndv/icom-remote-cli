#!/usr/bin/env python3
"""Icom IC-9700 und IC-705 ueber LAN/WLAN: lesen und einstellen (sendet nie).

Geraet waehlen mit -r 9700 oder -r 705 (Vorgabe 9700, oder Umgebungsvariable ICOM_RADIO).
Zugangsdaten: ic9700.ini bzw. ic705.ini (Host, Benutzer, Passwort). Pro Geraet nur ein Netzwerk-Client.
IC-9700: CI-V-Adresse 0xA2, Main und Sub (--rx main|sub). IC-705: Adresse 0xA4, ein Empfaenger.

Beispiele (statt 'icom_cli.py -r 705' geht auch 'icom_cli.py -r 9700'):
  icom_cli.py -r 705 serve --port 4532 rigctld-Server (Hamlib "NET rigctl", Modell 2) fuer WSJT-X, Log- und Rotorprogramme
  icom_cli.py -r 9700 --rx main vfo exchange   VFO: a b equal (A=B) exchange (A<>B) mem vfo   (--rx waehlt den Empfaenger)
  icom_cli.py -r 9700 swap                     Main und Sub tauschen
  icom_cli.py -r 9700 switch sat 1             Schalter: preamp nb nr notch rit split sat att extpre accsend
                                               (extpre = externer Vorverstaerker, accsend = ACC-SEND-Ausgang; gelten fuer das Band des Empfaengers)
  icom_cli.py -r 9700 agc fast                 AGC fast|mid|slow;  filter 2;  duplex DUP-;  rit 675 (Offset in Hz)
  icom_cli.py -r 9700 scan prog                Scan: stop prog mem select modesel df [--span 4] resume-on resume-off
  icom_cli.py -r 9700 level pbt1 150           weitere Regler: pbt1 pbt2 notch_pos cw_pitch cw_speed (0..255)
  icom_cli.py -r 9700 mem 430 1 20             Speicherkanaele lesen (144, 430 oder 1296 MHz, erster, letzter)
  icom_cli.py -r 9700 meters                   Po SWR ALC COMP Vd Id (Po/SWR/ALC nur beim Senden)
  icom_cli.py -r 9700 config list [GRUPPE]     die 134 Einstellungen der Konfiguration; "config get 1644", "config set 1644 1"
  icom_cli.py -r 705 status                  alles auslesen (Frequenz, Modus, S-Meter, Regler, Schalter, Spannung)
  icom_cli.py -r 705 freq                    Frequenz lesen
  icom_cli.py -r 705 freq 145.500M           Frequenz setzen (k/M/G oder Hz)
  icom_cli.py -r 705 mode                    Modus lesen
  icom_cli.py -r 705 mode FM                 Modus setzen (LSB USB AM CW RTTY FM WFM CW-R RTTY-R)
  icom_cli.py -r 705 smeter                  S-Meter einmal
  icom_cli.py -r 705 smeter -n               S-Meter laufend, Strg+C beendet
  icom_cli.py -r 705 level af                Regler lesen (af rf sql power nr_level nb_level)
  icom_cli.py -r 705 level af 120            Regler setzen (0..255)
  icom_cli.py -r 705 switch preamp 1         Schalter setzen (preamp nb nr notch)
"""
import argparse
import configparser
import os
import sys
import threading
import time
from pathlib import Path

import ic9700_ctl
import ic9700_lan
import ic9700_mem
import ic9700_rigctld
import ic9700_setup
import pegel2

RADIOS = {  # Name -> (CI-V-Adresse, ini-Datei, hat Sub)
    "9700": (0xA2, "ic9700.ini", True),
    "705": (0xA4, "ic705.ini", False),
}

MODES = {0: "LSB", 1: "USB", 2: "AM", 3: "CW", 4: "RTTY", 5: "FM", 6: "WFM", 7: "CW-R", 8: "RTTY-R", 0x17: "DV", 0x22: "DD"}
MODE_CODES = {v: k for k, v in MODES.items()}
LEVELS = dict(ic9700_ctl.LEVELS)  # af rf sql nr_level power nb_level pbt1 pbt2 notch_pos cw_pitch cw_speed
SWITCHES = dict(ic9700_ctl.SWITCHES, att=None, split=None, extpre=None, accsend=None)  # ohne Befehl = eigene Behandlung
SCANS = {"stop": 0x00, "prog": 0x02, "df": 0x03, "mem": 0x22, "select": 0x23, "modesel": 0x24,
         "resume-off": 0xD0, "resume-on": 0xD3}
PITCH = lambda v: f"{300 + round(v * 600 / 255)} Hz"  # noqa: E731
HUMAN = {"cw_pitch": PITCH, "cw_speed": lambda v: f"{6 + round(v * 42 / 255)} WPM",
         "pbt1": lambda v: f"{v - 128:+d}", "pbt2": lambda v: f"{v - 128:+d}", "notch_pos": lambda v: f"{v - 128:+d}"}
AGC = {1: "FAST", 2: "MID", 3: "SLOW"}


def data(rig, *cmd):
    """Nutzdaten hinter dem Befehl, None bei NG oder ohne Antwort."""
    try:
        f = rig.civ(*cmd)
    except TimeoutError:
        return None
    return None if f[4] == 0xFA else bytes(f[4 + len(cmd):-1])


def get_freq(rig):
    return rig.freq()


def get_mode(rig):
    d = data(rig, 0x04)
    return (MODES.get(d[0], hex(d[0])), d[1]) if d else (None, None)


def smeter(rig):
    raw = rig.smeter_raw()
    return raw, pegel2.raw_to_db(raw)


def level(rig, name):
    d = data(rig, *LEVELS[name])
    return int(d.hex()) if d and len(d) >= 2 else None


def set_cmd(rig, cmd, *args):
    f = rig.civ(*cmd, *args)
    return f[4] == 0xFB


class LiveProvider(ic9700_rigctld.Provider):
    """rigctld-Anbindung direkt an das Geraet. Es wird nur der gewaehlte Empfaenger bedient (Hamlib-VFOA = "main").
    Senden ist bewusst nicht moeglich (ptt_allowed bleibt False): T 1 wird mit einem Fehler abgelehnt."""
    ptt_allowed = False

    def __init__(self, rig):
        self.rig, self.lock = rig, threading.Lock()
        self.cache, self.t_fast, self.t_slow, self.ctl = {}, 0.0, 0.0, {}

    def snapshot(self):
        with self.lock:
            now = time.time()
            if now - self.t_fast > 0.4:  # Frequenz, Modus und S-Meter oft, Regler selten (spart WLAN-Verkehr)
                try:
                    d = data(self.rig, 0x04)
                    dm = data(self.rig, 0x1A, 0x06)
                    self.cache = {"freq": get_freq(self.rig), "raw": smeter(self.rig)[0],
                                  "mode": d[0] if d else 1, "data": bool(dm and dm[0])}
                except TimeoutError:
                    pass
                self.t_fast = now
            if now - self.t_slow > 5:
                self.ctl = {k: v for k in ("af", "rf", "sql", "power") if (v := level(self.rig, k)) is not None}
                self.t_slow = now
            return {"sel": "main", "main": dict(self.cache, ctl=dict(self.ctl))}

    def command(self, *cmd):
        with self.lock:
            kind = cmd[0]
            if kind == "freq":
                self.rig.set_freq(cmd[2])
                self.cache["freq"] = cmd[2]
            elif kind == "mode":
                set_cmd(self.rig, (0x06,), cmd[2], 1)
                set_cmd(self.rig, (0x1A, 0x06), 1 if cmd[3] else 0, 1)
                self.cache["mode"], self.cache["data"] = cmd[2], bool(cmd[3])
            elif kind == "ctl":
                set_cmd(self.rig, LEVELS[cmd[2]], *bytes.fromhex(f"{cmd[3]:04d}"))
                self.ctl[cmd[2]] = cmd[3]
            self.t_fast = 0.0


def serve(rig, radio, port, bind):
    ic9700_rigctld.RIG_NAME = f"IC-{radio} (LAN)"
    if radio == "705":
        ic9700_rigctld.RX_RANGES = [(0.03e6, 60e6), (144e6, 148e6), (430e6, 450e6)]
    srv = ic9700_rigctld.RigctlServer(LiveProvider(rig), port, bind, log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
    srv.start()
    print(f"Test: rigctl -m 2 -r {bind}:{port} f   (Strg+C beendet; Senden ist in diesem Programm gesperrt)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()


def fmt(v):
    return "-" if v is None else v


def status(rig):
    mode, filt = get_mode(rig)
    raw, db = smeter(rig)
    print(f"Frequenz  {get_freq(rig) / 1e6:.6f} MHz")
    print(f"Modus     {fmt(mode)}  Filter {fmt(filt)}")
    print(f"S-Meter   {db:+6.1f} dB rel. S9 (roh {raw})")
    for n in LEVELS:
        v = level(rig, n)
        print(f"{n:<9} {fmt(v)}" + (f"  ({HUMAN[n](v)})" if v is not None and n in HUMAN else ""))
    for n, cmd in SWITCHES.items():
        if cmd is None:
            continue
        d = data(rig, *cmd)
        print(f"{n:<9} {'-' if not d else ('an' if d[0] else 'aus')}")
    d = data(rig, 0x16, 0x12)
    print(f"{'agc':<9} {AGC.get(d[0], d[0]) if d else '-'}")
    d = data(rig, 0x15, 0x15)
    if d and len(d) >= 2:
        raw = int(d.hex())
        print(f"{'Vd':<9} {10 + (raw - 13) * 6 / 228:.1f} V (roh {raw})" if raw >= 13 else f"{'Vd':<9} roh {raw}")
    d = data(rig, 0x1C, 0x00)
    print(f"{'Senden':<9} {'-' if not d else ('JA' if d[0] else 'nein')}")
    c = ic9700_ctl.read_all(rig)
    for k in ("att", "split", "extpre", "accsend"):
        if k in c:
            print(f"{k:<9} {'an' if c[k] else 'aus'}")
    for k in ("duplex", "filter", "rit_offset"):
        if k in c:
            print(f"{k:<9} {c[k]}")


class connect:
    """Anmelden und pruefen, ob das Geraet antwortet; nach einem harten Abbruch haelt es die alte Sitzung noch einige
    Sekunden fest. Dann bis zu 4 Versuche mit Pause, danach eine verstaendliche Meldung statt eines Tracebacks."""

    def __init__(self, host, user, password, tries=4, pause=5):
        for n in range(1, tries + 1):
            rig = None
            try:
                rig = ic9700_lan.LanRig(host, user, password)
                rig.civ(0x19, 0x00)  # Geraete-ID lesen als Lebenszeichen
                self.rig = rig
                return
            except TimeoutError as e:
                if rig is not None:
                    rig.close()
                if n < tries:
                    print(f"keine Antwort ({e}); neuer Versuch {n + 1}/{tries} in {pause} s ...", file=sys.stderr, flush=True)
                    time.sleep(pause)
        sys.exit("Keine Verbindung zum Geraet. Laeuft noch die GUI, wfview oder ein anderes Programm (nur ein Client erlaubt)? "
                 "Nach einem Abbruch (Strg+C) hilft es, 10-20 s zu warten.")

    def __enter__(self):
        return self.rig

    def __exit__(self, *exc):
        self.rig.close()


def only_9700(a):
    if a.radio != "9700":
        sys.exit("Dieser Befehl gibt es nur fuer den IC-9700")


def vfo_cmd(rig, aktion):
    """VFO A/B, A=B, A<>B (ueber Lesen und kreuzweises Schreiben) und VFO-/Speicherbetrieb des gewaehlten Empfaengers."""
    if aktion in ("a", "b"):
        ok = set_cmd(rig, (0x07, 0x00 if aktion == "a" else 0x01))
        print(f"VFO {aktion.upper()}" if ok else "abgelehnt (im Satellitenmodus gibt es kein VFO B)")
    elif aktion == "equal":
        print("A=B" if set_cmd(rig, (0x07, 0xA0)) else "abgelehnt")
    elif aktion == "mem":
        print("Speicherbetrieb" if set_cmd(rig, (0x08,)) else "abgelehnt")
    elif aktion == "vfo":
        print("VFO-Betrieb" if set_cmd(rig, (0x07, 0x00)) else "abgelehnt")
    else:  # exchange
        got = []
        for v in (0x00, 0x01):
            if not set_cmd(rig, (0x07, v)):
                set_cmd(rig, (0x07, 0x00))
                sys.exit("abgelehnt (im Satellitenmodus gibt es kein VFO B)")
            m = data(rig, 0x04)
            dm = data(rig, 0x1A, 0x06)
            got.append((get_freq(rig), m[0], m[1], dm[0] if dm else 0))
        for v, (hz, mode, fil, dat) in zip((0x01, 0x00), got):  # B bekommt A, A bekommt B
            set_cmd(rig, (0x07, v))
            rig.set_freq(hz)
            set_cmd(rig, (0x06,), mode, fil)
            set_cmd(rig, (0x1A, 0x06), dat, fil)
        print(f"A<>B: A {got[1][0] / 1e6:.6f} MHz, B {got[0][0] / 1e6:.6f} MHz")


def interp(x, pts):
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def meters(rig):
    rows = (("Po", 0x11, lambda r: f"{r * 100 // 255} %"), ("SWR", 0x12, lambda r: ">3" if r > 120 else f"{interp(r, [(0, 1.0), (48, 1.5), (80, 2.0), (120, 3.0)]):.1f}"),
            ("ALC", 0x13, lambda r: f"{min(100, r * 100 // 120)} %"), ("COMP", 0x14, lambda r: f"{interp(r, [(0, 0.0), (130, 15.0), (210, 25.5), (255, 30.0)]):.0f} dB"),
            ("Vd", 0x15, lambda r: f"{interp(r, [(0, 0.0), (13, 10.0), (241, 16.0)]):.1f} V"),
            ("Id", 0x16, lambda r: f"{interp(r, [(0, 0.0), (121, 10.0), (241, 20.0)]):.1f} A"))
    for name, sc, fmt_ in rows:
        d = data(rig, 0x15, sc)
        print(f"{name:<5}", f"{fmt_(int(d.hex()))}  (roh {int(d.hex())})" if d and len(d) >= 2 else "-")


def config_cmd(rig, a):
    S = ic9700_setup
    if a.aktion == "list":
        for g in S.GROUPS:
            if a.arg and a.arg.lower() not in g.lower():
                continue
            print(f"\n== {g} ==")
            for e in (e for e in S.ENTRIES if e[0] == g):
                v = ""
                if a.werte:
                    try:
                        v = "  = " + show_value(e, S.read_value(rig, e[1]))
                    except TimeoutError:
                        v = "  = ?"
                print(f"{e[1]}  {e[2]}{v}")
        return
    if not a.arg or a.arg not in S.BY_KEY:
        sys.exit(f"Schluessel unbekannt: {a.arg} (siehe 'config list')")
    e = S.BY_KEY[a.arg]
    if a.aktion == "get":
        print(show_value(e, S.read_value(rig, a.arg)))
        return
    if a.wert is None:
        sys.exit("config set SCHLUESSEL WERT")
    val = a.wert
    if e[3] == "e" and not val.isdigit():  # Bezeichnung statt Zahl
        names = [n.lower() for n in e[4]]
        if val.lower() not in names:
            sys.exit(f"Wert unbekannt, moeglich: {', '.join(e[4])}")
        val = names.index(val.lower())
    elif e[3] == "b" and val.lower() in ("an", "ein", "on"):
        val = 1
    elif e[3] == "b" and val.lower() in ("aus", "off"):
        val = 0
    print("ok" if S.write_value(rig, a.arg, int(val)) else "vom Geraet abgelehnt")
    print("jetzt:", show_value(e, S.read_value(rig, a.arg)))


def show_value(e, v):
    if v is None:
        return "-"
    if e[3] == "b":
        return "an" if v else "aus"
    if e[3] == "e" and 0 <= v < len(e[4]):
        return f"{v} ({e[4][v]})"
    return str(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-r", "--radio", choices=RADIOS, default=os.environ.get("ICOM_RADIO", "9700"), help="Geraet (Vorgabe 9700)")
    ap.add_argument("--rx", choices=("main", "sub"), help="nur IC-9700: Empfaenger waehlen (Vorgabe: der gerade gewaehlte)")
    ap.add_argument("--host", help="IP des Geraets (sonst ini-Datei)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("pegel", help="S-Meter: beim IC-9700 Main und Sub, beim IC-705 der eine Empfaenger")
    p = sub.add_parser("serve", help="rigctld-Server (Hamlib NET rigctl)")
    p.add_argument("--port", type=int, default=4532, help="TCP-Port (Vorgabe 4532)")
    p.add_argument("--bind", default="127.0.0.1", help="Adresse (Vorgabe nur lokal; 0.0.0.0 = im ganzen Netz)")
    p = sub.add_parser("freq"); p.add_argument("wert", nargs="?")
    p = sub.add_parser("mode"); p.add_argument("wert", nargs="?")
    p = sub.add_parser("smeter"); p.add_argument("-n", action="store_true")
    p = sub.add_parser("level"); p.add_argument("name", choices=LEVELS); p.add_argument("wert", nargs="?", type=int)
    p = sub.add_parser("switch"); p.add_argument("name", choices=SWITCHES); p.add_argument("wert", type=int, choices=(0, 1))
    p = sub.add_parser("vfo", help="VFO A/B, A=B, A<>B, VFO/Speicher")
    p.add_argument("aktion", choices=("a", "b", "equal", "exchange", "mem", "vfo"))
    sub.add_parser("swap", help="Main und Sub tauschen (IC-9700)")
    p = sub.add_parser("agc"); p.add_argument("wert", nargs="?", choices=("fast", "mid", "slow"))
    p = sub.add_parser("filter"); p.add_argument("wert", nargs="?", type=int, choices=(1, 2, 3))
    p = sub.add_parser("duplex"); p.add_argument("wert", nargs="?", choices=("off", "dup-", "dup+"))
    p = sub.add_parser("rit"); p.add_argument("wert", nargs="?", type=int, help="Offset in Hz (-9999..9999)")
    p = sub.add_parser("scan"); p.add_argument("aktion", choices=SCANS)
    p.add_argument("--span", type=int, choices=range(1, 8), default=4, help="dF-Scan: 1=+-5k 2=+-10k 3=+-20k 4=+-50k 5=+-100k 6=+-500k 7=+-1M")
    p = sub.add_parser("mem", help="Speicherkanaele lesen (IC-9700)")
    p.add_argument("band", choices=("144", "430", "1296")); p.add_argument("erster", type=int); p.add_argument("letzter", type=int, nargs="?")
    sub.add_parser("meters", help="Po SWR ALC COMP Vd Id")
    p = sub.add_parser("config", help="Einstellungen der Konfigurationsseite (IC-9700, CI-V 1A 05)")
    p.add_argument("aktion", choices=("list", "get", "set")); p.add_argument("arg", nargs="?"); p.add_argument("wert", nargs="?")
    p.add_argument("--werte", action="store_true", help="list: aktuelle Werte mitlesen (dauert)")
    a = ap.parse_args()

    civ, ini, has_sub = RADIOS[a.radio]
    ic9700_ctl.HAS_BAND_SETTINGS = a.radio == "9700"
    if a.cmd == "switch" and a.name in ic9700_ctl.BAND_SETTINGS and a.radio != "9700":
        sys.exit(f"{a.name} gibt es nur beim IC-9700")
    if a.rx and not has_sub:
        sys.exit(f"IC-{a.radio} hat keinen Sub-Empfaenger")
    pegel2.CIV_RIG = civ
    c = configparser.ConfigParser()
    c.read(Path(__file__).with_name(ini))
    if "radio" not in c:
        sys.exit(f"{ini} fehlt oder hat keinen Abschnitt [radio]")
    r = c["radio"]
    with connect(a.host or r["host"], r["user"], r["password"]) as rig:
        if a.rx:
            rig.select(a.rx)
        if a.cmd == "serve":
            serve(rig, a.radio, a.port, a.bind)
        elif a.cmd == "pegel":
            if has_sub:
                print(pegel2.line(pegel2.read_both(rig)), flush=True)
            else:
                raw, db = smeter(rig)
                print(f"{get_freq(rig) / 1e6:12.6f} MHz  {db:+6.1f} dB (raw {raw:3d})", flush=True)
        elif a.cmd == "status":
            status(rig)
        elif a.cmd == "freq":
            if a.wert:
                hz = pegel2.parse_hz(a.wert)
                rig.set_freq(hz)
                time.sleep(0.2)
            print(f"{get_freq(rig) / 1e6:.6f} MHz")
        elif a.cmd == "mode":
            if a.wert:
                m = a.wert.upper()
                if m not in MODE_CODES:
                    sys.exit(f"Modus unbekannt: {m} (moeglich: {' '.join(MODES.values())})")
                set_cmd(rig, (0x06,), MODE_CODES[m], 1)
                time.sleep(0.2)
            print(*get_mode(rig))
        elif a.cmd == "smeter":
            fehler = 0
            while True:
                try:
                    raw, db = smeter(rig)
                except TimeoutError:  # WLAN-Aussetzer: ein paar Mal weiter versuchen
                    fehler += 1
                    print(f"keine Antwort vom Geraet ({fehler}/5)", file=sys.stderr, flush=True)
                    if not a.n or fehler >= 5:
                        sys.exit("Verbindung verloren")
                    continue
                fehler = 0
                print(f"{db:+6.1f} dB rel. S9 (roh {raw:3d})", flush=True)
                if not a.n:
                    break
                time.sleep(0.3)
        elif a.cmd == "vfo":
            vfo_cmd(rig, a.aktion)
        elif a.cmd == "swap":
            only_9700(a)
            print("getauscht" if set_cmd(rig, (0x07, 0xB0)) else "abgelehnt")
        elif a.cmd == "agc":
            if a.wert:
                ic9700_ctl.set_control(rig, "agc", {"fast": 1, "mid": 2, "slow": 3}[a.wert])
            d = data(rig, 0x16, 0x12)
            print(AGC.get(d[0], "-") if d else "-")
        elif a.cmd == "filter":
            if a.wert:
                ic9700_ctl.set_control(rig, "filter", a.wert)
            print(get_mode(rig)[1])
        elif a.cmd == "duplex":
            if a.wert:
                ic9700_ctl.set_control(rig, "duplex", a.wert.upper())
            print(ic9700_ctl.read_all(rig).get("duplex", "-"))
        elif a.cmd == "rit":
            if a.wert is not None:
                ic9700_ctl.set_control(rig, "rit_offset", a.wert)
                ic9700_ctl.set_control(rig, "rit", 1)
            c = ic9700_ctl.read_all(rig)
            print(f"{'an' if c.get('rit') else 'aus'} {c.get('rit_offset', '-')} Hz")
        elif a.cmd == "scan":
            if a.aktion == "df":
                set_cmd(rig, (0x0E, 0xA0 + a.span))
            print("ok" if set_cmd(rig, (0x0E, SCANS[a.aktion])) else "vom Geraet abgelehnt")
        elif a.cmd == "mem":
            only_9700(a)
            for ch in ic9700_mem.read_range(rig, {"144": 1, "430": 2, "1296": 3}[a.band], a.erster, a.letzter or a.erster):
                print(ic9700_mem.format_row(ch))
        elif a.cmd == "meters":
            meters(rig)
        elif a.cmd == "config":
            only_9700(a)
            config_cmd(rig, a)
        elif a.cmd == "level":
            if a.wert is not None:
                if not set_cmd(rig, LEVELS[a.name], *bytes.fromhex(f"{max(0, min(255, a.wert)):04d}")):
                    sys.exit("Geraet hat abgelehnt")
            v = level(rig, a.name)
            print(fmt(v) if v is None or a.name not in HUMAN else f"{v}  ({HUMAN[a.name](v)})")
        elif a.cmd == "switch":
            if not ic9700_ctl.set_control(rig, a.name, a.wert):
                sys.exit("Geraet hat abgelehnt")
            print("an" if ic9700_ctl.read_all(rig).get(a.name) else "aus")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except TimeoutError as e:  # Aussetzer mitten im Befehl (WLAN): kurze Meldung statt Traceback
        sys.exit(f"Das Geraet hat nicht geantwortet ({e}). Bitte noch einmal versuchen.")
