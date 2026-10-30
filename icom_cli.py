#!/usr/bin/env python3
"""Icom IC-9700 und IC-705 ueber LAN/WLAN: lesen und einstellen (sendet nie).

Geraet waehlen mit -r 9700 oder -r 705 (Vorgabe 9700, oder Umgebungsvariable ICOM_RADIO).
Zugangsdaten: ic9700.ini bzw. ic705.ini (Host, Benutzer, Passwort). Pro Geraet nur ein Netzwerk-Client.
IC-9700: CI-V-Adresse 0xA2, Main und Sub (--rx main|sub). IC-705: Adresse 0xA4, ein Empfaenger.

Beispiele (statt 'icom_cli.py -r 705' geht auch 'icom_cli.py -r 9700'):
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
import time
from pathlib import Path

import ic9700_lan
import pegel2

RADIOS = {  # Name -> (CI-V-Adresse, ini-Datei, hat Sub)
    "9700": (0xA2, "ic9700.ini", True),
    "705": (0xA4, "ic705.ini", False),
}

MODES = {0: "LSB", 1: "USB", 2: "AM", 3: "CW", 4: "RTTY", 5: "FM", 6: "WFM", 7: "CW-R", 8: "RTTY-R", 0x17: "DV", 0x22: "DD"}
MODE_CODES = {v: k for k, v in MODES.items()}
LEVELS = {"af": (0x14, 0x01), "rf": (0x14, 0x02), "sql": (0x14, 0x03), "nr_level": (0x14, 0x06),
          "power": (0x14, 0x0A), "nb_level": (0x14, 0x12)}
SWITCHES = {"preamp": (0x16, 0x02), "nb": (0x16, 0x22), "nr": (0x16, 0x40), "notch": (0x16, 0x41)}
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


def fmt(v):
    return "-" if v is None else v


def status(rig):
    mode, filt = get_mode(rig)
    raw, db = smeter(rig)
    print(f"Frequenz  {get_freq(rig) / 1e6:.6f} MHz")
    print(f"Modus     {fmt(mode)}  Filter {fmt(filt)}")
    print(f"S-Meter   {db:+6.1f} dB rel. S9 (roh {raw})")
    for n in LEVELS:
        print(f"{n:<9} {fmt(level(rig, n))}")
    for n, cmd in SWITCHES.items():
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-r", "--radio", choices=RADIOS, default=os.environ.get("ICOM_RADIO", "9700"), help="Geraet (Vorgabe 9700)")
    ap.add_argument("--rx", choices=("main", "sub"), help="nur IC-9700: Empfaenger waehlen (Vorgabe: der gerade gewaehlte)")
    ap.add_argument("--host", help="IP des Geraets (sonst ini-Datei)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("pegel", help="S-Meter: beim IC-9700 Main und Sub, beim IC-705 der eine Empfaenger")
    p = sub.add_parser("freq"); p.add_argument("wert", nargs="?")
    p = sub.add_parser("mode"); p.add_argument("wert", nargs="?")
    p = sub.add_parser("smeter"); p.add_argument("-n", action="store_true")
    p = sub.add_parser("level"); p.add_argument("name", choices=LEVELS); p.add_argument("wert", nargs="?", type=int)
    p = sub.add_parser("switch"); p.add_argument("name", choices=SWITCHES); p.add_argument("wert", type=int, choices=(0, 1))
    a = ap.parse_args()

    civ, ini, has_sub = RADIOS[a.radio]
    if a.rx and not has_sub:
        sys.exit(f"IC-{a.radio} hat keinen Sub-Empfaenger")
    pegel2.CIV_RIG = civ
    c = configparser.ConfigParser()
    c.read(Path(__file__).with_name(ini))
    if "radio" not in c:
        sys.exit(f"{ini} fehlt oder hat keinen Abschnitt [radio]")
    r = c["radio"]
    with ic9700_lan.LanRig(a.host or r["host"], r["user"], r["password"]) as rig:
        if a.rx:
            rig.select(a.rx)
        if a.cmd == "pegel":
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
        elif a.cmd == "level":
            if a.wert is not None:
                if not set_cmd(rig, LEVELS[a.name], *bytes.fromhex(f"{max(0, min(255, a.wert)):04d}")):
                    sys.exit("Geraet hat abgelehnt")
            print(fmt(level(rig, a.name)))
        elif a.cmd == "switch":
            if not set_cmd(rig, SWITCHES[a.name], a.wert):
                sys.exit("Geraet hat abgelehnt")
            d = data(rig, *SWITCHES[a.name])
            print("an" if d and d[0] else "aus")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
