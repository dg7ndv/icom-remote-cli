#!/usr/bin/env python3
"""Speicherkanaele des IC-9700 per CI-V lesen (Befehl 1A 00, nur lesend).

Pro Band (Gruppe 1 = 144 MHz, 2 = 430 MHz, 3 = 1296 MHz) gibt es:
  001-099  normale Speicherkanaele
  100-105  Scan-Raender (3 Paare)
  106      FM-Call-Kanal, 107 DV-Call-Kanal
Ein leerer Platz antwortet mit dem Byte FF.
"""
import json
import time
from pathlib import Path

BANDS = {1: "144 MHz", 2: "430 MHz", 3: "1296 MHz"}
MODES = {0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CW", 0x04: "RTTY", 0x05: "FM",
         0x07: "CW-R", 0x08: "RTTY-R", 0x17: "DV", 0x22: "DD"}
DUPLEX = {0: "OFF", 1: "DUP-", 2: "DUP+"}
TONE = {0: "OFF", 1: "TONE", 2: "TSQL", 3: "DTCS", 4: "DTCS-T", 5: "TONE-D", 6: "DTCS-T"}
SPECIAL = {100: "Scan-Rand 1A", 101: "Scan-Rand 1B", 102: "Scan-Rand 2A", 103: "Scan-Rand 2B",
           104: "Scan-Rand 3A", 105: "Scan-Rand 3B", 106: "FM-Call", 107: "DV-Call"}


def _bcd(b):
    return (b >> 4) * 10 + (b & 0x0F)


def freq_from_bcd(data):
    return sum(_bcd(b) * 100 ** i for i, b in enumerate(data))


def read_channel(rig, group, ch):
    """dict mit Kanaldaten oder None, wenn der Platz leer ist."""
    frame = rig.civ(0x1A, 0x00, group, ch // 100, (ch % 100) // 10 * 16 + ch % 10)
    if len(frame) < 74 or frame[-2] == 0xFF and len(frame) < 20:
        return None
    d = frame[9:-1]
    return {
        "group": group, "ch": ch,
        "scan": d[0], "freq": freq_from_bcd(d[1:6]),
        "mode": MODES.get(d[6], f"?{d[6]:02x}"), "filter": f"FIL{d[7]}",
        "data": bool(d[8]),
        "duplex": DUPLEX.get(d[9] >> 4, "?"), "tone": TONE.get(d[9] & 0x0F, "?"),
        "name": bytes(d[-16:]).decode("ascii", "replace").strip(),
    }


def _addr(ch):
    return ch // 100, (ch % 100) // 10 * 16 + ch % 10


def read_raw(rig, group, ch):
    """Rohdaten eines Kanals (ohne Kopf und FD) oder None, wenn leer."""
    frame = rig.civ(0x1A, 0x00, group, *_addr(ch))
    return bytes(frame[9:-1]) if len(frame) >= 74 else None


def write_raw(rig, group, ch, data):
    """Kanal schreiben (gleiches Format wie beim Lesen). Gibt True bei OK (FB) zurueck."""
    if len(data) != 64:
        raise ValueError("Kanaldaten muessen 64 Byte lang sein")
    return rig.civ(0x1A, 0x00, group, *_addr(ch), *data)[4] == 0xFB


def read_range(rig, group, first, last, specials=False):
    """Liste von Kanaldaten (leere Plaetze als {"ch": n, "empty": True})."""
    chans = list(range(first, last + 1)) + (list(SPECIAL) if specials else [])
    out = []
    for ch in chans:
        try:
            c = read_channel(rig, group, ch)
        except TimeoutError:
            c = None
        out.append(c or {"group": group, "ch": ch, "empty": True})
    return out


MODE_CODES = {v: k for k, v in MODES.items()}
DUP_CODES = {v: k for k, v in DUPLEX.items()}
SCAN_CODES = {"-": 0, "*1": 1, "*2": 2, "*3": 3}
BAND_RANGES = {1: (144_000_000, 148_000_000), 2: (430_000_000, 450_000_000), 3: (1_240_000_000, 1_300_000_000)}
LOG = Path(__file__).with_name("speicher_aenderungen.jsonl")


def bcd5(hz):
    digits = f"{int(hz):010d}"
    return bytes(int(digits[i:i + 2], 16) for i in range(8, -1, -2))


def group_of(hz):
    """Speichergruppe (1 = 144, 2 = 430, 3 = 1296 MHz) zu einer Frequenz oder None."""
    for g, (lo, hi) in BAND_RANGES.items():
        if lo <= hz <= hi:
            return g
    return None


def apply_fields(raw, f):
    """64 Byte Kanaldaten mit geaenderten Feldern (nur diese werden angefasst, Rest bleibt wie er ist).

    Felder: name, freq (Hz), mode ("USB" ...), filter (1-3), data (bool), duplex ("OFF"/"DUP-"/"DUP+"), scan ("-","*1",...).
    Ton-Einstellungen, Ablagefrequenz u. a. werden unveraendert uebernommen."""
    d = bytearray(raw)
    if "scan" in f:
        d[0] = SCAN_CODES[f["scan"]]
    if "freq" in f:
        d[1:6] = bcd5(f["freq"])
    if "mode" in f:
        d[6] = MODE_CODES[f["mode"]]
    if "filter" in f:
        d[7] = int(f["filter"])
    if "data" in f:
        d[8] = 1 if f["data"] else 0
    if "duplex" in f:
        d[9] = (DUP_CODES[f["duplex"]] << 4) | (d[9] & 0x0F)
    if "name" in f:
        d[-16:] = f["name"].encode("ascii", "replace")[:16].ljust(16)
    return bytes(d)


def write_channel(rig, group, ch, fields):
    """Kanal aendern: lesen, Felder setzen, schreiben, zuruecklesen, Aenderung protokollieren.

    Ein leerer Platz nimmt die Scan-Rand-Daten (Kanal 100) desselben Bandes als Vorlage.
    Gibt dict(ok, msg, old, new, readback) zurueck; wirft ValueError bei ungueltigen Eingaben."""
    if "freq" in fields:
        lo, hi = BAND_RANGES[group]
        if not lo <= fields["freq"] <= hi:
            raise ValueError(f"{fields['freq'] / 1e6:.6f} MHz liegt nicht im Band {BANDS[group]}")
    old = read_raw(rig, group, ch)
    base = old or read_raw(rig, group, 100)
    if base is None:
        raise RuntimeError("keine Vorlage fuer leeren Platz (Kanal 100 nicht lesbar)")
    new = apply_fields(base, fields)
    accepted = write_raw(rig, group, ch, new)
    time.sleep(0.3)
    back = read_raw(rig, group, ch)
    ok = accepted and back is not None and back == new
    msg = ("gespeichert und zurueckgelesen" if ok else
           "Geraet hat den Schreibbefehl abgelehnt" if not accepted else
           "geschrieben, aber der Rueckleswert weicht ab (bitte pruefen)" if back else "nach dem Schreiben nicht lesbar")
    with LOG.open("a") as fh:
        fh.write(json.dumps({"zeit": time.strftime("%Y-%m-%d %H:%M:%S"), "gruppe": group, "kanal": ch,
                             "alt": old.hex() if old else None, "neu": new.hex(), "ok": ok}) + "\n")
    return {"ok": ok, "msg": msg, "old": old, "new": new, "readback": back}


def scan_text(n):
    return {0: "-", 1: "*1", 2: "*2", 3: "*3"}.get(n, "?")


def format_row(c):
    if c.get("empty"):
        return f"{c['ch']:03d}  (leer)"
    return (f"{c['ch']:03d}  {c['name'][:16]:<16}  {c['freq'] / 1e6:>12.6f} MHz  {c['mode']:<6} {c['filter']:<5}"
            f" {c['duplex']:<5} {c['tone']:<5} {'DATA' if c['data'] else '    '} {scan_text(c['scan'])}")
