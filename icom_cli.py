#!/usr/bin/env python3
"""Icom IC-9700 und IC-705 ueber LAN/WLAN: lesen und einstellen (sendet nie).

Geraet waehlen mit -r 9700 oder -r 705 (Vorgabe 9700, oder Umgebungsvariable ICOM_RADIO).
Zugangsdaten: ic9700.ini bzw. ic705.ini (Host, Benutzer, Passwort). Pro Geraet nur ein Netzwerk-Client.
IC-9700: CI-V-Adresse 0xA2, Main und Sub (--rx main|sub). IC-705: Adresse 0xA4, ein Empfaenger.

Beispiele (statt 'icom_cli.py -r 705' geht auch 'icom_cli.py -r 9700'):
  icom_cli.py -r 705 -2mmin status             erst 144.300 MHz und Sendeleistung auf Minimum stellen, dann Status zeigen
  icom_cli.py -r 705 serve --port 4532 rigctld-Server (Hamlib "NET rigctl", Modell 2) fuer WSJT-X, Log- und Rotorprogramme
  icom_cli.py -r 9700 --rx main vfo exchange   VFO: a b equal (A=B) exchange (A<>B) mem vfo   (--rx waehlt den Empfaenger)
  icom_cli.py -r 9700 swap                     Main und Sub tauschen
  icom_cli.py -r 705 atu [on|off]              Antennentuner (1C 01) lesen/ein/aus; ein Abstimmlauf wuerde senden und fehlt deshalb
  icom_cli.py -r 9700 switch sat 1             Schalter: preamp nb nr notch rit split sat att extpre accsend
                                               (extpre = externer Vorverstaerker, accsend = ACC-SEND-Ausgang; gelten fuer das Band des Empfaengers)
  icom_cli.py -r 9700 agc fast                 AGC fast|mid|slow;  filter 2;  duplex DUP-;  rit 675 (Offset in Hz)
  icom_cli.py -r 9700 scan prog                Scan: stop prog mem select modesel df [--span 4] resume-on resume-off
  icom_cli.py -r 9700 level pbt1 150           weitere Regler: pbt1 pbt2 notch_pos cw_pitch cw_speed (0..255)
  icom_cli.py -r 9700 mem list 430 1 20        Speicherkanaele anzeigen (IC-9700: Band 144/430/1296; IC-705: Gruppe 0-99)
  icom_cli.py -r 9700 mem recall 430 3         Kanal ins VFO laden (stellt Frequenz und Modus ein)
  icom_cli.py -r 9700 mem write 430 5 --aktuell --name TEST   Kanal schreiben (weitere Felder: --offset 7.6M --ur CQCQCQ --r1 "DB0VOX B" --r2 "DB0VOX G") (ohne --ja nur Vorschau; alter Inhalt wird protokolliert)
  icom_cli.py -r 9700 scope edges [144]        feste Scope-Bereiche je Band lesen; "scope edge 144 4 144.0M 144.5M [--ja]" setzen
  icom_cli.py -r 9700 dstar_liste --ab 20      D-STAR-Liste (dstar_liste.json) ab Kanal 20 programmieren (ohne --ja nur Plan)
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
import csv
import json
import math
import os
import signal
import sys
import threading
import time
from pathlib import Path

import ic9700_ctl
import ic9700_lan
import ic9700_mem
import ic9700_rigctld
import ic9700_scope
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
RADIO = "9700"  # wird in main() gesetzt (fuer die Leistungsanzeige in status)
AGC = {1: "FAST", 2: "MID", 3: "SLOW"}


def vd_volts(rig, radio="9700"):
    """Versorgungsspannung aus dem Vd-Meter (15 15). IC-9700: 13=10 V, 241=16 V. IC-705: 75=5 V, 241=16 V (laut CI-V-Referenz)."""
    d = data(rig, 0x15, 0x15)
    if not d or len(d) < 2:
        return None
    raw = int(d.hex())
    if radio == "705":
        return interp(raw, [(0, 0.0), (75, 5.0), (241, 16.0), (255, 16.0)])
    return 10 + (raw - 13) * 6 / 228 if raw >= 13 else raw * 10 / 13  # unter 10 V grob linear (nur eine Naeherung)


def supply_type(rig, radio):
    """IC-705: Art der Stromversorgung laut Geraet (1A 0B): "extern" oder "Akku"; sonst None."""
    if radio != "705":
        return None
    d = data(rig, 0x1A, 0x0B)
    return None if not d else ("Akku" if d[0] else "extern")


def power_text(raw, hz, radio, volts=None, supply=None):
    """Sendeleistung 0..255 in Watt: linear bis zum Maximum, nach unten auf die kleinste Leistung des Geraets begrenzt.
    IC-9700 (Datenblatt): 144 MHz 0,5-100 W, 430 MHz 0,5-75 W, 1200 MHz 0,1-10 W.
    IC-705 (Datenblatt): 0,5-10 W bei 13,8 V, 0,5-5 W bei 7,4 V (Akku BP-272); dazwischen grob linear geschaetzt."""
    note = ""
    if radio == "9700":
        pmin, pmax = (0.5, 100.0) if hz < 200e6 else (0.5, 75.0) if hz < 1e9 else (0.1, 10.0)
    else:
        pmin, pmax = 0.5, 10.0
        if volts is not None and volts < 6.0:  # nur USB-Versorgung (ca. 5 V): der IC-705 sendet dann nicht
            return f"0 W - Senden nicht moeglich (nur {volts:.1f} V, USB-Versorgung?)"
        if supply:  # das Geraet sagt selbst, ob Akku oder externe Versorgung: Akku 5 W, extern 10 W
            pmax = 5.0 if supply == "Akku" else 10.0
            note = f"  {supply}" + (f", {volts:.1f} V" if volts is not None else "")
        elif volts is not None:
            pmax = 10.0 if volts >= 11.7 else 5.0 if volts <= 8.5 else 5.0 + (volts - 8.5) / (11.7 - 8.5) * 5.0
            note = f"  bei {volts:.1f} V"
    w = max(pmin, raw / 255 * pmax)
    return f"ca. {w:.1f} W" + (" (Minimum)" if raw / 255 * pmax <= pmin else "") + f"  [Bereich {pmin:g}-{pmax:g} W{note}]"


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


COLORS = {"gruen": "32", "gelb": "33", "rot": "31"}


def color(text, name):
    """ANSI-Farbe nur, wenn die Ausgabe ein Terminal ist (nicht in Pipes und Dateien)."""
    return f"\033[1;{COLORS[name]}m{text}\033[0m" if sys.stdout.isatty() and not os.environ.get("NO_COLOR") else text


def supply_line(rig, radio):
    """Eine Zeile zur Stromversorgung, bunt: gruen = in Ordnung, gelb = Vorsicht, rot = Senden nicht moeglich oder Akku fast leer.
    IC-705: Art laut Geraet (1A 0B: 00 = extern, 01 = Akku) plus Spannung; IC-9700 hat keine solche Abfrage, nur die Spannung."""
    volts = vd_volts(rig, radio)
    sup = supply_type(rig, radio)
    vtxt = "?" if volts is None else f"{volts:.1f} V"
    if volts is not None and volts < 6.0:
        return color(f"Versorgung: {vtxt} - nur USB? Senden nicht moeglich", "rot")
    if sup == "Akku":
        ok = volts is None or volts >= 7.0
        return color(f"Versorgung: Akku {vtxt}" + ("" if ok else " - Akku fast leer"), "gelb" if ok else "rot") + "  (max. 5 W)"
    if sup == "extern":
        ok = volts is None or 11.7 <= volts <= 15.9
        return color(f"Versorgung: extern {vtxt}" + ("" if ok else " - ausserhalb 13,8 V +-15 %"), "gruen" if ok else "gelb")
    ok = volts is not None and 11.7 <= volts <= 15.9
    return color(f"Versorgung: {vtxt}", "gruen" if ok else "gelb")


def status(rig):
    print(supply_line(rig, RADIO))
    mode, filt = get_mode(rig)
    raw, db = smeter(rig)
    print(f"Frequenz  {get_freq(rig) / 1e6:.6f} MHz")
    print(f"Modus     {fmt(mode)}  Filter {fmt(filt)}")
    print(f"S-Meter   {db:+6.1f} dB rel. S9 (roh {raw})")
    for n in LEVELS:
        v = level(rig, n)
        extra = f"  ({HUMAN[n](v)})" if v is not None and n in HUMAN else ""
        if n == "power" and v is not None:
            extra = "  " + power_text(v, get_freq(rig), RADIO, vd_volts(rig, RADIO), supply_type(rig, RADIO))
        print(f"{n:<9} {fmt(v)}{extra}")
    for n, cmd in SWITCHES.items():
        if cmd is None:
            continue
        d = data(rig, *cmd)
        print(f"{n:<9} {'-' if not d else ('an' if d[0] else 'aus')}")
    d = data(rig, 0x16, 0x12)
    print(f"{'agc':<9} {AGC.get(d[0], d[0]) if d else '-'}")
    v = vd_volts(rig, RADIO)
    print(f"{'Vd':<9} {'-' if v is None else f'{v:.1f} V'}")
    sup = supply_type(rig, RADIO)
    if sup:
        print(f"{'Versorgung':<10} {sup} (laut Geraet)")
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

    def __init__(self, host, user, password, tries=4, pause=5, civ_addr=None):
        for n in range(1, tries + 1):
            rig = None
            try:
                rig = ic9700_lan.LanRig(host, user, password, civ_addr=civ_addr)
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


# Vorlage fuer einen leeren IC-705-Speicherplatz (64-Byte-Sicht wie beim IC-9700; wird beim Schreiben auf 111 Byte erweitert): Standardwerte fuer Ton (88,5 Hz),
# DTCS (023) und Digital-Squelch; Frequenz, Modus, Ablage, Rufzeichen und Name werden darueber geschrieben.
TEMPLATE_705 = bytes.fromhex("0000505239041702001000000885000885000023000060074351435143512020444230564f582042444230564f582047444230564f5820202020202020202020")


def mem_group(a):
    """IC-9700: Band 144/430/1296 -> Gruppe 1/2/3; IC-705: Speichergruppe 0-99."""
    if a.radio == "9700":
        if a.gruppe not in ("144", "430", "1296"):
            sys.exit("IC-9700: Band 144, 430 oder 1296 angeben")
        return {"144": 1, "430": 2, "1296": 3}[a.gruppe]
    if not a.gruppe.isdigit() or not 0 <= int(a.gruppe) <= 99:
        sys.exit("IC-705: Speichergruppe 0 bis 99 angeben")
    return int(a.gruppe)


def mem_expand_705(raw):
    """64-Byte-Sicht -> 111 Byte fuers IC-705: Empfangsdaten (48), gleiche Daten noch einmal als Sende-Kopie (47, ohne das erste Byte), Name (16)."""
    return raw[:48] + raw[1:48] + raw[48:64]


def mem_raw(rig, radio, group, ch):
    """64 Byte Kanaldaten oder None (leerer Platz). Die Feldlage ist bei beiden Geraeten gleich (Byte 5 ... 68 der CI-V-Tabelle);
    das IC-705 speichert sie als 111 Byte (siehe mem_expand_705)."""
    if radio == "9700":
        return ic9700_mem.read_raw(rig, group, ch)
    f = rig.civ(0x1A, 0x00, *bytes.fromhex(f"{group:04d}"), *bytes.fromhex(f"{ch:04d}"))
    d = bytes(f[10:-1])
    if f[4] == 0xFA or len(d) != 111:
        return None
    return d[:48] + d[95:111]  # IC-705: 48 Byte Empfang + 47 Byte Sende-Kopie + 16 Byte Name -> gleiche Sicht wie beim IC-9700


def mem_row(raw, ch):
    if raw is None:
        return {"ch": ch, "empty": True}
    return {"ch": ch, "scan": raw[0], "freq": ic9700_mem.freq_from_bcd(raw[1:6]), "mode": ic9700_mem.MODES.get(raw[6], f"?{raw[6]:02x}"),
            "filter": f"FIL{raw[7]}", "data": bool(raw[8]), "duplex": ic9700_mem.DUPLEX.get(raw[9] >> 4, "?"),
            "tone": ic9700_mem.TONE.get(raw[9] & 0x0F, "?"), "name": bytes(raw[-16:]).decode("ascii", "replace").strip()}


def mem_cmd(rig, a, has_sub):
    group = mem_group(a)
    if a.aktion == "list":
        for ch in range(a.kanal, (a.letzter or a.kanal) + 1):
            try:
                raw = mem_raw(rig, a.radio, group, ch)
            except TimeoutError:
                raw = None
            print(ic9700_mem.format_row(mem_row(raw, ch)))
        return
    raw = mem_raw(rig, a.radio, group, a.kanal)
    if a.aktion == "recall":
        c = mem_row(raw, a.kanal)
        if c.get("empty"):
            sys.exit("Der Speicherplatz ist leer")
        slot0 = None
        if has_sub:  # IC-9700: der Empfaenger, der schon auf dem Band steht, nimmt die Frequenz (Main und Sub nie auf demselben Band)
            both = pegel2.read_both(rig)
            band = ic9700_ctl.band_index(c["freq"])
            slot = a.rx or next((k for k in ("main", "sub") if ic9700_ctl.band_index(both[k][0]) == band), None)
            if slot is None:
                slot = "main" if rig.freq() == both["main"][0] else "sub"
            slot0 = "main" if rig.freq() == both["main"][0] else "sub"
            rig.select(slot)
        rig.set_freq(c["freq"])
        fil = int(c["filter"][3:])
        set_cmd(rig, (0x06,), ic9700_mem.MODE_CODES[c["mode"]], fil)
        set_cmd(rig, (0x1A, 0x06), 1 if c["data"] else 0, fil)
        if slot0 and slot0 != slot:
            rig.select(slot0)
        print(f"geladen{f' in {slot}' if has_sub else ''}: {c['freq'] / 1e6:.6f} MHz {c['mode']} {c['filter']}  {c['name']}")
        return
    # write
    fields = {}
    if a.aktuell:
        d = data(rig, 0x04)
        fields.update(freq=get_freq(rig), mode=MODES.get(d[0]), filter=d[1])
    if a.freq:
        fields["freq"] = pegel2.parse_hz(a.freq)
    if a.offset:
        fields["offset"] = pegel2.parse_hz(a.offset)
    for k in ("ur", "r1", "r2"):
        if getattr(a, k) is not None:
            fields[k] = getattr(a, k)
    for k in ("mode", "name", "filter", "duplex"):
        if getattr(a, k) is not None:
            fields[k] = getattr(a, k).upper() if k in ("mode", "duplex") else getattr(a, k)
    if not fields:
        sys.exit("Nichts zu schreiben: --freq, --mode, --name, --filter, --duplex oder --aktuell angeben")
    base = raw or (ic9700_mem.read_raw(rig, group, 100) if a.radio == "9700" else TEMPLATE_705)
    if base is None:
        sys.exit("Der Platz ist leer und es gibt keine Vorlage (Scan-Rand-Kanal 100 nicht lesbar)")
    if raw is None and a.radio == "705" and not {"freq", "mode"} <= set(fields) and not a.aktuell:
        sys.exit("Leerer IC-705-Platz: bitte mindestens --freq und --mode angeben (oder --aktuell)")
    new = ic9700_mem.apply_fields(base, fields)
    print("vorher:  ", ic9700_mem.format_row(mem_row(raw, a.kanal)), "\n          " + ic9700_mem.extra_text(raw) if raw else "(leer)")
    print("nachher: ", ic9700_mem.format_row(mem_row(new, a.kanal)), "\n          " + ic9700_mem.extra_text(new))
    if not a.ja:
        print("Nur Vorschau. Zum Schreiben denselben Befehl mit --ja wiederholen.")
        return
    print(mem_store(rig, a.radio, group, a.kanal, raw, new, fields))


def mem_store(rig, radio, group, ch, raw, new, fields):
    """Kanal wirklich schreiben und zuruecklesen (alter Inhalt wird protokolliert). Gibt eine Meldung zurueck."""
    if radio == "9700":
        return ic9700_mem.write_channel(rig, group, ch, fields)["msg"]
    ok = rig.civ(0x1A, 0x00, *bytes.fromhex(f"{group:04d}"), *bytes.fromhex(f"{ch:04d}"), *mem_expand_705(new))[4] == 0xFB
    time.sleep(0.3)
    back = mem_raw(rig, radio, group, ch)
    with ic9700_mem.LOG.open("a") as fh:
        fh.write(json.dumps({"zeit": time.strftime("%Y-%m-%d %H:%M:%S"), "geraet": "705", "gruppe": group, "kanal": ch,
                             "alt": raw.hex() if raw else None, "neu": new.hex(), "ok": bool(ok and back == new)}) + "\n")
    return ("gespeichert und zurueckgelesen" if ok and back == new else "Geraet hat abgelehnt" if not ok
            else "geschrieben, Rueckleswert weicht ab (bitte pruefen)")


def dstar_liste(rig, a):
    """D-STAR-Relaisliste (dstar_liste.json) ab Startkanal in den Speicher schreiben. Ohne --ja nur Plan. Belegte Plaetze mit
    anderem Inhalt werden nur mit --ueberschreiben ersetzt; ein identischer Kanal wird uebersprungen."""
    cfg = json.loads(Path(a.datei or Path(__file__).with_name("dstar_liste.json")).read_text(encoding="utf-8"))
    start = a.ab if a.ab is not None else cfg.get("start_kanal", 20)
    ur = cfg.get("ur", "CQCQCQ")
    counters = {}
    plan = []
    for e in cfg["relais"]:
        if a.radio not in e.get("geraete", ["9700", "705"]):
            plan.append((e, None, None, f"nur fuer IC-{'/'.join(e['geraete'])}"))
            continue
        if not e.get("bestaetigt") and not a.auch_unbestaetigte:
            plan.append((e, None, None, "unbestaetigt (mit --auch-unbestaetigte)"))
            continue
        band = ic9700_ctl.band_index(e["freq"])
        if a.radio == "705":
            if band not in (0, 1) or e["modus"] == "DD":
                plan.append((e, None, None, "IC-705 hat dafuer kein Band bzw. keinen Modus"))
                continue
            group = int(a.gruppe)
        else:
            if band is None:
                plan.append((e, None, None, "ausserhalb der Baender"))
                continue
            group = band + 1
        if e.get("kanal"):  # feste Nummer: zaehlt nicht in der laufenden Vergabe mit
            ch = int(e["kanal"])
        else:
            ch = start + counters.get(group, 0)
            counters[group] = counters.get(group, 0) + 1
        if ch > 99:
            plan.append((e, None, None, "kein Platz bis Kanal 99"))
            continue
        plan.append((e, group, ch, ""))
    for e, group, ch, why in plan:
        if group is None:
            print(f"-  {e['name']:<12} uebersprungen: {why}")
            continue
        fields = {"freq": e["freq"], "mode": e["modus"], "duplex": e["duplex"], "offset": e.get("ablage", 0), "name": e["name"][:16],
                  "ur": ur, "r1": e["r1"], "r2": e["r2"], "filter": e.get("filter", 2)}
        raw = mem_raw(rig, a.radio, group, ch)
        base = raw or (ic9700_mem.read_raw(rig, group, 100) if a.radio == "9700" else TEMPLATE_705)
        new = ic9700_mem.apply_fields(base, fields)
        gtxt = {"9700": {1: "144", 2: "430", 3: "1296"}.get(group), "705": f"Gruppe {group}"}[a.radio]
        if raw is not None and new == raw:
            print(f"=  {gtxt:>10} Kanal {ch:02d}  {e['name']:<12} schon vorhanden, unveraendert")
            continue
        if raw is not None and not a.ueberschreiben:
            c = mem_row(raw, ch)
            print(f"!  {gtxt:>10} Kanal {ch:02d}  {e['name']:<12} Platz belegt mit '{c['name']}' {c['freq'] / 1e6:.4f} MHz - nicht ueberschrieben (--ueberschreiben)")
            continue
        if not a.ja:
            print(f"+  {gtxt:>10} Kanal {ch:02d}  {e['name']:<12} {e['freq'] / 1e6:.4f} MHz {e['modus']} {e['duplex']}  (Plan)")
            continue
        print(f"+  {gtxt:>10} Kanal {ch:02d}  {e['name']:<12} {e['freq'] / 1e6:.4f} MHz {e['modus']}: {mem_store(rig, a.radio, group, ch, raw, new, fields)}")
    if not a.ja:
        print("Nur Plan. Zum Schreiben denselben Befehl mit --ja wiederholen.")


def dv_rx_info(rig):
    """Zuletzt empfangene D-STAR-Rufzeichen (CI-V 20 00 02): dict oder None, wenn seit dem Einschalten noch keine empfangen wurden."""
    f = rig.civ(0x20, 0x00, 0x02)
    d = bytes(f[7:-1])
    if f[4] == 0xFA or len(d) < 38 or d[0] == 0xFF:
        return None
    t = lambda a, b: d[a:b].decode("ascii", "replace").strip()  # noqa: E731
    return {"flags": d[:2].hex(), "ack": d[1] & 7, "mit_relais": bool(d[0] & 8), "mycall": t(2, 10), "ur": t(14, 22),
            "rxrpt1": t(22, 30), "rxrpt2": t(30, 38)}


ACK = {0: "keine", 1: "Relais gesperrt", 2: "keine Antwort (Receive no reply)", 3: "Quittung (Send acknowledge)", 4: "Wiederholung angefordert",
       6: "Auto-Quittung (Send auto acknowledge)", 7: "Relais-Steuerung"}


def relais_test(rig, a):
    """Testsendung ueber ein D-STAR-Relais: Relais einstellen, Kanal abhoeren, minimale Leistung, kurz senden (nur mit --ja), danach pruefen,
    ob das Relais dein Rufzeichen mit eigenem Kopf zurueckschickt (CI-V 20 00 02) und wie das Statusbyte (20 02 02) aussieht."""
    cfg = json.loads(Path(a.datei or Path(__file__).with_name("dstar_liste.json")).read_text(encoding="utf-8"))
    e = next((x for x in cfg["relais"] if x["name"].upper() == a.relais.upper()), None)
    if e is None or e.get("modus") != "DV":
        sys.exit(f"Relais '{a.relais}' nicht in der Liste oder kein DV-Eintrag")
    secs = max(0.5, min(3.0, a.sekunden))
    call = a.call.upper()
    f8 = lambda t: t.upper().ljust(8)[:8].encode("ascii")  # noqa: E731
    print(f"Plan: {e['name']} {e['freq'] / 1e6:.4f} MHz DV, {e['duplex']} {e['ablage'] / 1e6:g} MHz, MY {call}, UR CQCQCQ, RPT1 {e['r1']}, RPT2 {e['r2']}")
    watt = min(10.0, a.watt) if a.watt else None
    if a.hoeren is not None:
        print(f"      NUR ABHOEREN " + ("unbegrenzt" if not a.hoeren else f"{a.hoeren:g} s") + ", es wird nicht gesendet")
    else:
        print(f"      Leistung {'Minimum' if watt is None else f'ca. {watt:g} W'}, Senden {secs:g} s auf Main, vorher 3 s abhoeren"
              + ("" if a.ja else "   (nur Plan, ohne --ja wird nichts gesendet)"))
    if not a.ja and a.hoeren is None:
        return
    rig.select("main")
    time.sleep(0.1)
    rig.set_freq(e["freq"])
    set_cmd(rig, (0x06,), 0x17, 2)
    ic9700_ctl.set_control(rig, "duplex", e["duplex"])
    u = f"{int(round(e['ablage'] / 100)):06d}"
    rig.civ(0x0D, int(u[4]) << 4 | int(u[5]), int(u[2]) << 4 | int(u[3]), int(u[0]) << 4 | int(u[1]))
    ok1 = rig.civ(0x1F, 0x01, *f8("CQCQCQ"), *f8(e["r1"]), *f8(e["r2"]))[4] == 0xFB
    ok0 = rig.civ(0x1F, 0x00, *f8(call), *b"    ")[4] == 0xFB
    raw_pw = 0 if watt is None else max(0, min(255, round(watt / 75.0 * 255)))  # 70 cm: Maximum 75 W, linear (Naeherung)
    set_cmd(rig, LEVELS["power"], *bytes.fromhex(f"{raw_pw:04d}"))
    time.sleep(0.4)
    print(f"Eingestellt: {get_freq(rig) / 1e6:.4f} MHz, Rufzeichen {'gesetzt' if ok0 and ok1 else 'ABGELEHNT'}, Leistung {power_text(level(rig, 'power'), get_freq(rig), '9700')}")
    if not (ok0 and ok1):
        sys.exit("Rufzeichen wurden nicht angenommen - Abbruch ohne Senden")
    if a.hoeren is not None:  # passives Mithoeren (0 = unbegrenzt bis Strg+C oder kill): Koepfe, Squelch-Oeffnungen und S-Meter ins Log
        logf = Path(a.log or Path(__file__).with_name(f"hoerlog_{e['name'].replace(' ', '_')}.log"))
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

        def log(text):
            line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {text}"
            with logf.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            print(line, flush=True)

        log(f"START {e['name']} {e['freq'] / 1e6:.4f} MHz, MY {call}, " + ("unbegrenzt" if not a.hoeren else f"{a.hoeren:g} s") + f", Log {logf.name}")
        last, peak, heard, opened, fails = None, 0, 0, 0, 0
        t_end = time.time() + a.hoeren if a.hoeren else None
        t_print, sq_before, peak_all = time.time(), False, 0
        try:
            while t_end is None or time.time() < t_end:
                try:
                    raw = smeter(rig)[0]
                    sq = data(rig, 0x15, 0x01)
                    sq_now = bool(sq and sq[0])
                    info = dv_rx_info(rig)
                    fails = 0
                except TimeoutError:
                    fails += 1
                    log(f"keine Antwort vom Geraet ({fails}/10)")
                    if fails >= 10:
                        log("ABBRUCH: Verbindung verloren")
                        break
                    time.sleep(2)
                    continue
                peak, peak_all = max(peak, raw), max(peak_all, raw)
                if sq_now and not sq_before:
                    opened += 1
                    log(f"Squelch offen, S-Meter roh {raw}")
                sq_before = sq_now
                if info and info != last:
                    heard += 1
                    last = info
                    log(f"KOPF  MY '{info['mycall']}'  UR '{info['ur']}'  RPT1 '{info['rxrpt1']}'  RPT2 '{info['rxrpt2']}'  Flags {info['flags']}  "
                        f"{'ueber Relais' if info['mit_relais'] else 'direkt'}  Quittung: {ACK.get(info['ack'], info['ack'])}")
                if time.time() - t_print >= 300:  # alle 5 Minuten ein Lebenszeichen
                    log(f"lebt: S-Meter Spitze der letzten 5 min roh {peak}, bisher {heard} Koepfe, {opened}x Squelch offen")
                    t_print, peak = time.time(), 0
                time.sleep(0.3)
        except KeyboardInterrupt:
            pass
        log(f"ENDE: {heard} Koepfe, {opened}x Squelch offen, S-Meter Spitze roh {peak_all}")
        return
    # 1) Abhoeren
    seen, busy = [], False
    end = time.time() + 3
    while time.time() < end:
        raw = smeter(rig)[0]
        sq = data(rig, 0x15, 0x01)
        st = data(rig, 0x20, 0x02, 0x02)
        seen.append(raw)
        if raw > 20 or (sq and sq[0]) or (st and st[0] & 0x50):
            busy = True
            break
        time.sleep(0.3)
    print(f"Abhoeren: S-Meter max roh {max(seen)}, " + ("KANAL BELEGT - es wird nicht gesendet" if busy else "Kanal frei"))
    if busy:
        return
    before = dv_rx_info(rig)
    # 2) Senden (PTT immer wieder aus)
    meters = {}
    try:
        print(f"SENDE {secs:g} s ...", flush=True)
        set_cmd(rig, (0x1C, 0x00), 1)
        t0 = time.time()
        while time.time() - t0 < secs:
            time.sleep(0.4)
            for name, sc in (("Po", 0x11), ("SWR", 0x12), ("ALC", 0x13)):
                d = data(rig, 0x15, sc)
                if d and len(d) >= 2:
                    meters[name] = max(meters.get(name, 0), int(d.hex()))
    finally:
        for _ in range(3):
            try:
                set_cmd(rig, (0x1C, 0x00), 0)
                if (data(rig, 0x1C, 0x00) or b"\x00")[0] == 0:
                    break
            except TimeoutError:
                pass
    print("Empfang wieder an. Sendemesswerte: " + ", ".join(f"{k} roh {v}" for k, v in meters.items()))
    # 3) Antwort des Relais
    got, sq_open, peak = None, False, 0
    end = time.time() + 6
    while time.time() < end:
        info = dv_rx_info(rig)
        peak = max(peak, smeter(rig)[0])
        sq = data(rig, 0x15, 0x01)
        sq_open = sq_open or bool(sq and sq[0])
        if info and info != before:
            got = info
            break
        time.sleep(0.3)
    st = data(rig, 0x20, 0x02, 0x02)
    print(f"Nach dem Senden: S-Meter Spitze roh {peak}, Squelch {'war offen' if sq_open else 'blieb zu'}, DV-Status {st.hex() if st else '-'}")
    if got is None:
        print("ERGEBNIS: keine digitale Antwort vom Relais empfangen (nicht erreichbar, zu schwach oder Relais antwortet nicht).")
        return
    print(f"Empfangener Kopf: MY '{got['mycall']}'  UR '{got['ur']}'  RPT1 '{got['rxrpt1']}'  RPT2 '{got['rxrpt2']}'  Flags {got['flags']}  Quittung: {ACK.get(got['ack'], got['ack'])}"
          f"  {'ueber Relais' if got['mit_relais'] else 'direkt'}")
    mine = got["mycall"].upper().startswith(call)
    print("ERGEBNIS: " + ("RELAIS ERREICHT - dein eigenes Rufzeichen kam ueber " + got["rxrpt1"] + " zurueck." if mine
                          else "Es kam ein Signal von " + got["mycall"] + ", nicht dein eigenes - Relais ist aktiv, aber dein Aufruf ist nicht bestaetigt."))


HOME_FILE = Path(__file__).with_name("relais_einstellungen.json")
PMAX_9700 = {"2 m": 100.0, "70 cm": 75.0, "23 cm": 10.0}  # maximale Sendeleistung je Band (IC-9700)
CSV_KOPF = ["Datum", "Zeit", "Geraet", "Relais", "Ort", "km", "Ausgabe_MHz", "Eingabe_MHz", "Ablage_MHz", "Stufe", "Sendezeit_s", "Leistung_W",
            "Po_roh", "SWR_roh", "ALC_roh", "Antwort", "Squelch_offen", "Feldstaerke_roh", "Feldstaerke_dB_S9", "S_Stufe", "Rauschen_roh", "Antenne", "Bemerkung"]


def dist_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def s_stufe(raw):
    """S-Meter-Rohwert als S-Stufe (S9 = 120, darueber in dB)."""
    if raw <= 120:
        return f"S{min(9, round(raw / 120 * 9))}"
    return f"S9+{pegel2.raw_to_db(raw):.0f}dB"


def messen(rig, secs):
    """Spitze des S-Meters und ob der Squelch aufging, ueber secs Sekunden."""
    peak, sq_open, end = 0, False, time.time() + secs
    while time.time() < end:
        peak = max(peak, smeter(rig)[0])
        sq = data(rig, 0x15, 0x01)
        sq_open = sq_open or bool(sq and sq[0])
        time.sleep(0.15)
    return peak, sq_open


def relaistest(rig, a):
    """Testlauf an allen FM-Relais im Umkreis: Relais am IC-9700 einstellen, Kanal abhoeren, kurz mit Traeger tasten (nur mit --ja) und die Antwort des
    Relais als Feldstaerke messen; Ergebnis als Tabellenzeile (CSV) anhaengen. Relais ohne Reaktion werden am Ende aufgelistet; dann wird gefragt, ob sie
    mit dem Subton (CTCSS aus der Liste) nochmal versucht werden sollen. Mit --hoeren wird nichts gesendet (nur Feldstaerke des Relais messen)."""
    home = json.loads(HOME_FILE.read_text())
    rel = json.loads(Path(a.datei or Path(__file__).with_name("daten") / "fm_deutschland.json").read_text(encoding="utf-8"))["relais"]
    plan = sorted(((dist_km(home["lat"], home["lon"], r["lat"], r["lon"]), r) for r in rel if r.get("lat") is not None), key=lambda t: t[0])
    plan = [(d, r) for d, r in plan if d <= a.km and not (a.band and r["band"] != a.band)]
    secs = max(0.3, min(2.0, a.sekunden))
    watt = "max" if a.watt in (None, "max") else float(a.watt)
    sende = not a.hoeren
    print(f"QTH {home.get('qth', '')} ({home['lat']:.4f}, {home['lon']:.4f}), Umkreis {a.km:g} km: {len(plan)} FM-Relais")
    for d, r in plan:
        print(f"  {d:5.1f} km  {r['call']:8} {r['freq_mhz']:>9.4f} MHz  Eingabe {r['eingabe_mhz']}  Ton {r.get('ctcss') or '-':<5} {r['ort'][:28]}")
    if sende:
        print(f"Ablauf: je Relais nur ein kurzer Traeger von {secs:g} s, Leistung " + ("MAXIMUM" if watt == "max" else f"{watt:g} W")
              + " (je Band begrenzt), danach 4 s Antwort messen. Relais ohne Reaktion werden am Ende genannt, dann wird wegen des Subtons gefragt.")
    else:
        print("Ablauf: nur Mithoeren (6 s je Relais), es wird NICHT gesendet.")
    if not plan:
        return
    if not a.ja:
        print("Nur Plan. Zum Ausfuehren denselben Befehl mit --ja wiederholen" + (" (dann wird GESENDET)." if sende else "."))
        return
    csvp = Path(a.csv or Path(__file__).with_name("messungen") / "relaistest.csv")
    csvp.parent.mkdir(exist_ok=True)
    neu = not csvp.exists()
    rig.select("main")
    time.sleep(0.1)
    hz0, md, dm = get_freq(rig), data(rig, 0x04), data(rig, 0x1A, 0x06)
    dup0 = (data(rig, 0x0F) or b"\x10")[0]
    off0 = data(rig, 0x0C)
    pw0 = level(rig, "power")
    ergebnisse = []

    def messzeile(w, d, r, stufe, ton=None):
        """Ein Relais einmal messen (und je nach Modus tasten); schreibt die Tabellenzeile und gibt (Antwort, Zeile) zurueck."""
        einstellen(rig, r, watt, ton)
        raw0, _ = messen(rig, 1.0)
        bel, vals, peak, sq = None, {}, 0, False
        if sende:
            peak0, sq0 = messen(rig, 3.0)
            if peak0 > 20 or sq0:
                bel = "Kanal belegt, nicht gesendet"
            else:
                vals = tasten(rig, secs)
                peak, sq = messen(rig, 4.0)
        else:
            peak, sq = messen(rig, 6.0)
        jetzt = time.localtime()
        antwort = "" if bel else ("ja" if (sq or peak > raw0 + 5) else "nein")
        wp = (PMAX_9700[r["band"]] if watt == "max" else min(watt, PMAX_9700[r["band"]])) if sende else ""
        row = [time.strftime("%Y-%m-%d", jetzt), time.strftime("%H:%M:%S", jetzt), "IC-9700", r["call"], r["ort"], f"{d:.1f}", f"{r['freq_mhz']:.4f}",
               r.get("eingabe_mhz") or "", r.get("ablage_mhz") or "", stufe if sende else "nur Hoeren", f"{secs:g}" if sende else "",
               f"{wp:g}" if wp != "" else "", vals.get("Po", ""), vals.get("SWR", ""), vals.get("ALC", ""), antwort, "ja" if sq else "nein",
               "" if bel else peak, "" if bel else f"{pegel2.raw_to_db(peak):.1f}", "" if bel else s_stufe(peak), raw0, a.antenne or "", bel or ""]
        w.writerow(row)
        ergebnisse.append(row)
        print(f"  {r['call']:8} {r['freq_mhz']:>9.4f}  {stufe:<18}" + (bel or f"Antwort {antwort}, Feldstaerke {s_stufe(peak)} (roh {peak}, {pegel2.raw_to_db(peak):+.1f} dB zu S9), "
                                                                          f"Rauschen roh {raw0}" + (f", Po roh {vals.get('Po')}, SWR roh {vals.get('SWR')}" if sende else "")), flush=True)
        return antwort, row

    try:
        if sende:  # SWR-Vorpruefung mit kleiner Leistung, bevor mit hoher Leistung getastet wird
            r0 = plan[0][1]
            print(f"SWR-Vorpruefung an {r0['call']} mit wenig Leistung ...")
            einstellen(rig, r0, 5.0)
            vor = tasten(rig, 0.6)
            ok = vor.get("SWR", 99) <= 80  # roh 80 = SWR 2,0
            print(f"  Po roh {vor.get('Po')}, SWR roh {vor.get('SWR')} -> " + ("in Ordnung" if ok else "SWR ZU HOCH, Abbruch ohne Messung"))
            if not ok:
                return
        keine = []
        with csvp.open("a", encoding="utf-8-sig" if neu else "utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            if neu:
                w.writerow(CSV_KOPF)
            for d, r in plan:
                antwort, _row = messzeile(w, d, r, "Traeger")
                fh.flush()
                if antwort == "nein":
                    keine.append((d, r))
                time.sleep(3 if sende else 0.5)
        if sende and keine:
            print("\nKeine Reaktion mit reinem Traeger:")
            for d, r in keine:
                print(f"  {r['call']:8} {r['freq_mhz']:>9.4f} MHz  {d:.1f} km  " + (f"Subton laut Liste {r['ctcss']:g} Hz" if r.get("ctcss") else "kein Subton in der Liste"))
            mit_ton = [(d, r) for d, r in keine if r.get("ctcss")]
            wahl = a.subton
            if wahl == "fragen":
                wahl = "ja" if mit_ton and sys.stdin.isatty() and input(f"\nDiese {len(mit_ton)} Relais mit Subton probieren? [j/N] ").strip().lower() in ("j", "ja", "y") else "nein"
            if wahl == "ja" and mit_ton:
                with csvp.open("a", encoding="utf-8", newline="") as fh:
                    w = csv.writer(fh, delimiter=";")
                    for d, r in mit_ton:
                        messzeile(w, d, r, f"Traeger+Subton {r['ctcss']:g}", r["ctcss"])
                        fh.flush()
                        time.sleep(3)
            else:
                print("Subton-Durchgang nicht ausgefuehrt" + ("." if mit_ton else " (keine Relais mit Subton in der Liste)."))
    finally:
        try:
            set_cmd(rig, (0x1C, 0x00), 0)
        except Exception:
            pass
        wiederherstellen(rig, hz0, md, dm, dup0, off0, pw0)
    print(f"{len(ergebnisse)} Zeilen in {csvp}")


def einstellen(rig, r, watt, ton=None):
    """Relais auf Main einstellen: Frequenz, FM, DATA aus, Duplex mit Ablage, Sendeton (ton in Hz, sonst aus), Leistung (W oder 'max')."""
    rig.select("main")
    time.sleep(0.1)
    rig.set_freq(int(round(r["freq_mhz"] * 1e6)))
    fil = (data(rig, 0x04) or b"\x00\x01")[1]
    set_cmd(rig, (0x06,), 0x05, fil)
    set_cmd(rig, (0x1A, 0x06), 0, fil)
    ab = r.get("ablage_mhz") or 0
    ic9700_ctl.set_control(rig, "duplex", "OFF" if not ab else ("DUP-" if r.get("ablage") != "+" else "DUP+"))
    if ab:
        u = f"{int(round(ab * 1e7)):06d}"
        rig.civ(0x0D, int(u[4]) << 4 | int(u[5]), int(u[2]) << 4 | int(u[3]), int(u[0]) << 4 | int(u[1]))
    if ton:  # Sendeton (CTCSS): Frequenz 1B 00 und Schalter 16 42
        d4 = f"{int(round(ton * 10)):04d}"
        rig.civ(0x1B, 0x00, 0x00, int(d4[0:2], 16), int(d4[2:4], 16))
        rig.civ(0x16, 0x42, 1)
    else:
        rig.civ(0x16, 0x42, 0)  # kein Sendeton: nur Traeger
    pmax = PMAX_9700[r["band"]]
    raw = 255 if watt == "max" else max(0, min(255, round(float(watt) / pmax * 255)))
    set_cmd(rig, LEVELS["power"], *bytes.fromhex(f"{raw:04d}"))
    time.sleep(0.3)


def tasten(rig, secs):
    """Traeger secs Sekunden senden (PTT ueber CI-V, immer wieder aus); liefert die groessten Po-, SWR- und ALC-Rohwerte."""
    vals = {}
    try:
        set_cmd(rig, (0x1C, 0x00), 1)
        t0 = time.time()
        while time.time() - t0 < secs:
            time.sleep(0.2)
            for name, sc in (("Po", 0x11), ("SWR", 0x12), ("ALC", 0x13)):
                d = data(rig, 0x15, sc)
                if d and len(d) >= 2:
                    vals[name] = max(vals.get(name, 0), int(d.hex()))
    finally:
        for _ in range(3):
            try:
                set_cmd(rig, (0x1C, 0x00), 0)
                if (data(rig, 0x1C, 0x00) or b"\x00")[0] == 0:
                    break
            except TimeoutError:
                pass
    return vals


def wiederherstellen(rig, hz0, md, dm, dup0, off0, pw0):
    try:
        rig.select("main")
        time.sleep(0.1)
        rig.set_freq(hz0)
        if md:
            set_cmd(rig, (0x06,), md[0], md[1])
        if dm:
            set_cmd(rig, (0x1A, 0x06), dm[0], md[1] if md else 1)
        set_cmd(rig, (0x0F,), dup0)
        if off0 and len(off0) >= 3:
            rig.civ(0x0D, *off0[:3])
        if pw0 is not None:
            set_cmd(rig, LEVELS["power"], *bytes.fromhex(f"{pw0:04d}"))
        print(f"Zustand wiederhergestellt: {hz0 / 1e6:.4f} MHz, Leistung {pw0}")
    except Exception as e:
        print("Zustand konnte nicht ganz wiederhergestellt werden:", e)


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
    elif RADIO == "705":  # IC-705: 07 B0 tauscht VFO A und B direkt
        print("A<>B" if set_cmd(rig, (0x07, 0xB0)) else "abgelehnt (nicht im Speicher- oder Rufkanalbetrieb)")
    else:  # exchange (IC-9700: ueber Lesen und kreuzweises Schreiben)
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


def meters(rig, radio="9700"):
    rows = (("Po", 0x11, lambda r: f"{r * 100 // 255} %"), ("SWR", 0x12, lambda r: ">3" if r > 120 else f"{interp(r, [(0, 1.0), (48, 1.5), (80, 2.0), (120, 3.0)]):.1f}"),
            ("ALC", 0x13, lambda r: f"{min(100, r * 100 // 120)} %"), ("COMP", 0x14, lambda r: f"{interp(r, [(0, 0.0), (130, 15.0), (210, 25.5), (255, 30.0)]):.0f} dB"),
            ("Vd", 0x15, (lambda r: f"{interp(r, [(0, 0.0), (75, 5.0), (241, 16.0)]):.1f} V") if radio == "705"
             else (lambda r: f"{interp(r, [(0, 0.0), (13, 10.0), (241, 16.0)]):.1f} V")),
            ("Id", 0x16, (lambda r: f"{interp(r, [(0, 0.0), (121, 2.0), (241, 4.0)]):.2f} A") if radio == "705"
             else (lambda r: f"{interp(r, [(0, 0.0), (121, 10.0), (241, 20.0)]):.1f} A")))
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
    ap.add_argument("-2mmin", "--2mmin", dest="m2min", action="store_true",
                    help="vorher 144.300 MHz und minimale Sendeleistung einstellen (sendet nicht), dann den Befehl ausfuehren")
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
    p = sub.add_parser("atu", help="IC-705: Antennentuner-Status lesen, ein- und ausschalten (kein Abstimmlauf, das wuerde senden)")
    p.add_argument("wert", nargs="?", choices=("on", "off"))
    p = sub.add_parser("agc"); p.add_argument("wert", nargs="?", choices=("fast", "mid", "slow"))
    p = sub.add_parser("filter"); p.add_argument("wert", nargs="?", type=int, choices=(1, 2, 3))
    p = sub.add_parser("duplex"); p.add_argument("wert", nargs="?", choices=("off", "dup-", "dup+"))
    p = sub.add_parser("rit"); p.add_argument("wert", nargs="?", type=int, help="Offset in Hz (-9999..9999)")
    p = sub.add_parser("scan"); p.add_argument("aktion", choices=SCANS)
    p.add_argument("--span", type=int, choices=range(1, 8), default=4, help="dF-Scan: 1=+-5k 2=+-10k 3=+-20k 4=+-50k 5=+-100k 6=+-500k 7=+-1M")
    p = sub.add_parser("mem", help="Speicherkanaele lesen, abrufen und schreiben")
    p.add_argument("aktion", choices=("list", "recall", "write"),
                   help="list: anzeigen, recall: Kanal ins VFO laden, write: Kanal schreiben (ohne --ja nur Vorschau)")
    p.add_argument("gruppe", help="IC-9700: Band 144, 430 oder 1296; IC-705: Speichergruppe 0-99")
    p.add_argument("kanal", type=int); p.add_argument("letzter", type=int, nargs="?", help="list: letzter Kanal")
    p.add_argument("--name"); p.add_argument("--freq", help="write: Frequenz, z. B. 144.3M"); p.add_argument("--mode")
    p.add_argument("--filter", type=int, choices=(1, 2, 3)); p.add_argument("--duplex", choices=("off", "dup-", "dup+"))
    p.add_argument("--offset", help="write: Duplex-Ablage, z. B. 7.6M")
    p.add_argument("--ur"); p.add_argument("--r1"); p.add_argument("--r2")
    p.add_argument("--aktuell", action="store_true", help="write: Frequenz und Modus des Empfaengers uebernehmen")
    p.add_argument("--ja", action="store_true", help="write: wirklich schreiben (sonst nur Vorschau)")
    sub.add_parser("meters", help="Po SWR ALC COMP Vd Id")
    p = sub.add_parser("relaistest", help="Testlauf an den FM-Relais im Umkreis: kurz mit Traeger tasten, Antwort als Feldstaerke in eine CSV-Tabelle (IC-9700)")
    p.add_argument("--km", type=float, default=10.0, help="Umkreis in km um das QTH (relais_einstellungen.json), Vorgabe 10")
    p.add_argument("--watt", default="max", help="Sendeleistung in W oder 'max' (Vorgabe: max; je Band begrenzt auf 100/75/10 W)")
    p.add_argument("--sekunden", type=float, default=1.0, help="Traegerdauer je Relais (0,3 bis 2 s)")
    p.add_argument("--band", choices=("2 m", "70 cm", "23 cm"))
    p.add_argument("--antenne", help="Angabe zur Antenne fuer die Tabelle (optional)")
    p.add_argument("--csv", help="Tabelle (Vorgabe messungen/relaistest.csv, es wird angehaengt)"); p.add_argument("--datei", help="andere Relaisliste")
    p.add_argument("--hoeren", action="store_true", help="nichts senden, nur die Feldstaerke der Relais messen")
    p.add_argument("--subton", choices=("fragen", "ja", "nein"), default="fragen", help="Relais ohne Reaktion mit Subton nochmal versuchen: fragen (Vorgabe), ja, nein")
    p.add_argument("--ja", action="store_true", help="wirklich ausfuehren (sonst nur Plan); ohne --hoeren wird dann GESENDET")
    p = sub.add_parser("relais_test", help="Testsendung ueber ein D-STAR-Relais der Liste (IC-9700), prueft die digitale Rueckmeldung")
    p.add_argument("relais", nargs="?", default="DB0VOX"); p.add_argument("--call", default="DG7NDV", help="dein Rufzeichen (MY)")
    p.add_argument("--sekunden", type=float, default=1.5, help="Sendedauer (0,5 bis 3 s)"); p.add_argument("--datei")
    p.add_argument("--watt", type=float, help="Sendeleistung in W (Vorvorgabe Minimum; hoechstens 10)")
    p.add_argument("--hoeren", type=float, metavar="SEK", help="nur mithoeren (SEK Sekunden, 0 = unbegrenzt), nichts senden; liest die Rufzeichen der anderen")
    p.add_argument("--log", help="Logdatei fuer --hoeren (Vorgabe: hoerlog_<Relais>.log im Programmordner)")
    p.add_argument("--ja", action="store_true", help="wirklich senden (sonst nur Plan)")
    p = sub.add_parser("dstar_liste", help="D-STAR-Relaisliste (dstar_liste.json) ab einem Startkanal in den Speicher schreiben")
    p.add_argument("--ab", type=int, help="Startkanal (Vorgabe: start_kanal in der Datei, 20)")
    p.add_argument("--datei", help="andere Listendatei")
    p.add_argument("--gruppe", default="0", help="IC-705: Speichergruppe (Vorgabe 0)")
    p.add_argument("--auch-unbestaetigte", action="store_true", dest="auch_unbestaetigte", help="auch Relais mit bestaetigt=false schreiben")
    p.add_argument("--ueberschreiben", action="store_true", help="belegte Plaetze mit anderem Inhalt ersetzen")
    p.add_argument("--ja", action="store_true", help="wirklich schreiben (sonst nur Plan)")
    p = sub.add_parser("scope", help="feste Scope-Bereiche (SCOPE > Fixed Edges), IC-9700")
    p.add_argument("aktion", choices=("edges", "edge"), help="edges: alle anzeigen; edge: einen setzen (ohne --ja nur Vorschau)")
    p.add_argument("band", nargs="?", choices=ic9700_scope.FIXED_BANDS); p.add_argument("nr", nargs="?", type=int, choices=(1, 2, 3, 4))
    p.add_argument("von", nargs="?"); p.add_argument("bis", nargs="?")
    p.add_argument("--ja", action="store_true", help="wirklich schreiben")
    p = sub.add_parser("config", help="Einstellungen der Konfigurationsseite (IC-9700, CI-V 1A 05)")
    p.add_argument("aktion", choices=("list", "get", "set")); p.add_argument("arg", nargs="?"); p.add_argument("wert", nargs="?")
    p.add_argument("--werte", action="store_true", help="list: aktuelle Werte mitlesen (dauert)")
    a = ap.parse_args()

    civ, ini, has_sub = RADIOS[a.radio]
    global RADIO
    RADIO = a.radio
    ic9700_ctl.HAS_BAND_SETTINGS = a.radio == "9700"
    if a.radio == "705":
        ic9700_ctl.ATT_ON = 0x20
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
        if a.m2min:  # 2 m: 144.300 MHz (SSB-Anruffrequenz) und Sendeleistung auf Minimum; Modus bleibt, gesendet wird nicht
            set_cmd(rig, LEVELS["power"], 0, 0)
            rig.set_freq(144_300_000)
            time.sleep(0.2)
            v = level(rig, "power")
            print(f"-2mmin: {get_freq(rig) / 1e6:.6f} MHz, Sendeleistung {v} = {power_text(v, get_freq(rig), a.radio, vd_volts(rig, a.radio), supply_type(rig, a.radio))}", flush=True)
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
        elif a.cmd == "atu":
            if a.radio != "705":
                sys.exit("Der Antennentuner-Befehl (1C 01) gilt nur fuer den IC-705")
            if a.wert:
                set_cmd(rig, (0x1C, 0x01), 1 if a.wert == "on" else 0)
            d = data(rig, 0x1C, 0x01)
            print({0: "aus", 1: "an", 2: "Abstimmlauf"}.get(d[0], d[0]) if d else "-")
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
            mem_cmd(rig, a, has_sub)
        elif a.cmd == "scope":
            only_9700(a)
            scope_cmd(rig, a)
        elif a.cmd == "relaistest":
            only_9700(a)
            relaistest(rig, a)
        elif a.cmd == "relais_test":
            only_9700(a)
            relais_test(rig, a)
        elif a.cmd == "dstar_liste":
            dstar_liste(rig, a)
        elif a.cmd == "meters":
            meters(rig, a.radio)
        elif a.cmd == "config":
            only_9700(a)
            config_cmd(rig, a)
        elif a.cmd == "level":
            if a.wert is not None:
                if not set_cmd(rig, LEVELS[a.name], *bytes.fromhex(f"{max(0, min(255, a.wert)):04d}")):
                    sys.exit("Geraet hat abgelehnt")
            v = level(rig, a.name)
            if v is not None and a.name == "power":
                print(f"{v}  {power_text(v, get_freq(rig), a.radio, vd_volts(rig, a.radio), supply_type(rig, a.radio))}")
            else:
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
    except PermissionError as e:
        sys.exit(f"{e}. Benutzer/Passwort in der ini-Datei pruefen; ist schon ein anderes Programm (GUI, wfview, zweites Terminal) "
                 "am Geraet angemeldet? Es ist nur ein Client erlaubt.")
    except TimeoutError as e:  # Aussetzer mitten im Befehl (WLAN): kurze Meldung statt Traceback
        sys.exit(f"Das Geraet hat nicht geantwortet ({e}). Bitte noch einmal versuchen.")
