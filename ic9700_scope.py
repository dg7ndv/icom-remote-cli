#!/usr/bin/env python3
"""Scope-Daten (Spektrum) des IC-9700: Frames auswerten und Scope-Einstellungen setzen.

Das Geraet sendet nach `27 11 01` ca. 30 Frames pro Sekunde, jeder mit einem kompletten
Spektrum (475 Messpunkte, Werte 0..160):
  FE FE E0 A2 27 00 <rx> <seq> <max> <modus> <f1:5> <f2:5> <ausserhalb> <475 Werte> FD
  rx: 00 = Main, 01 = Sub; modus: 00 Center, 01 Fixed, 02 Scroll-C, 03 Scroll-F
  Center: f1 = Mittenfrequenz, f2 = halbe Spanne (+-); Fixed: f1 = untere, f2 = obere Grenze
Einstellen: 27 14 <rx> <modus> (Modus), 27 15 <rx> <f:5 BCD> (halbe Spanne), 27 12 <rx> (Scope-Empfaenger).
"""
from ic9700_mem import freq_from_bcd

SPANS = [2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000]  # halbe Spanne (+-) in Hz
MODES = {0: "Center", 1: "Fixed", 2: "Scroll-C", 3: "Scroll-F"}


def _bcd2(b):
    return (b >> 4) * 10 + (b & 0x0F)


def bcd5(hz):
    """Frequenz/Spanne als 5-Byte-BCD, niederwertigstes Byte zuerst."""
    digits = f"{int(hz):010d}"
    return bytes(int(digits[i:i + 2], 16) for i in range(8, -1, -2))


def parse(frame):
    """Scope-Frame -> dict(rx, mode, lo, hi, center, half, oor, wave) oder None."""
    if len(frame) < 30 or frame[4] != 0x27 or frame[5] != 0x00:
        return None
    seq, seq_max = _bcd2(frame[7]), _bcd2(frame[8])
    if seq != 1 or seq_max != 1:  # der IC-9700 liefert das Spektrum in einem Frame
        return None
    mode = frame[9]
    f1, f2 = freq_from_bcd(frame[10:15]), freq_from_bcd(frame[15:20])
    if mode in (0, 2):
        center, half = f1, f2
        lo, hi = f1 - f2, f1 + f2
    else:
        lo, hi = f1, f2
        center, half = (f1 + f2) // 2, (f2 - f1) // 2
    return {"rx": frame[6], "mode": mode, "lo": lo, "hi": hi, "center": center, "half": half,
            "oor": bool(frame[20]), "wave": list(frame[21:-1])}


def nearest_span(half_hz):
    return min(SPANS, key=lambda s: abs(s - half_hz))


def set_span(rig, rx, half_hz):
    rig.civ(0x27, 0x15, rx, *bcd5(half_hz))


def set_mode(rig, rx, mode):
    rig.civ(0x27, 0x14, rx, mode)


def select_receiver(rig, rx):
    rig.civ(0x27, 0x12, rx)


# ---- Feste Scope-Bereiche (SCOPE > Fixed Edges): je Band No.1 bis No.4, im Menue gespeichert (1A 05 xxxx) ----
FIXED_BANDS = ("144", "430", "1200")
FIXED_KEYS = {  # Band -> Menuenummern von No.1 ... No.4 (No.4 gibt es erst mit neuerer Firmware, CI-V-Referenz 2021)
    "144": ("1A050202", "1A050203", "1A050204", "1A050348"),
    "430": ("1A050205", "1A050206", "1A050207", "1A050349"),
    "1200": ("1A050208", "1A050209", "1A050210", "1A050350"),
}
FIXED_LIMITS = {"144": (144_000_000, 148_000_000), "430": (430_000_000, 450_000_000), "1200": (1_240_000_000, 1_300_000_000)}


def decode_edge(d):
    """8 Byte (untere und obere Kante, je 4 Byte BCD, 1-kHz-Auflösung) -> (von_Hz, bis_Hz).
    Byte je Kante: [1 kHz|100 Hz], [100 kHz|10 kHz], [10 MHz|1 MHz], [1 GHz|100 MHz]."""
    def one(b):
        digits = [b[0] >> 4, b[1] >> 4, b[1] & 15, b[2] & 15, b[2] >> 4, b[3] & 15, b[3] >> 4]  # 1k,100k,10k,1M,10M,100M,1G
        return (digits[0] * 1_000 + digits[1] * 100_000 + digits[2] * 10_000 + digits[3] * 1_000_000
                + digits[4] * 10_000_000 + digits[5] * 100_000_000 + digits[6] * 1_000_000_000)
    return one(d[:4]), one(d[4:8])


def encode_edge(lo, hi):
    def one(hz):
        k = int(round(hz / 1000))  # in kHz
        g, m, kk = k // 1_000_000, (k // 1000) % 1000, k % 1000
        return bytes([(kk % 10) << 4, ((kk // 100) << 4) | ((kk // 10) % 10), ((m // 10 % 10) << 4) | (m % 10),
                      (g << 4) | (m // 100)])
    return one(lo) + one(hi)


def read_fixed(rig, band, n):
    """(von_Hz, bis_Hz) von Bereich n (1..4) im Band, oder None, wenn das Geraet ihn nicht kennt."""
    cmd = bytes.fromhex(FIXED_KEYS[band][n - 1])
    f = rig.civ(*cmd)
    d = bytes(f[4 + len(cmd):-1])
    return None if f[4] == 0xFA or len(d) != 8 else decode_edge(d)


def write_fixed(rig, band, n, lo, hi):
    """Bereich setzen und zuruecklesen; True bei Erfolg. Prueft Bandgrenzen und lo < hi."""
    bl, bh = FIXED_LIMITS[band]
    if not (bl <= lo < hi <= bh):
        raise ValueError(f"Bereich muss im {band}-MHz-Band liegen ({bl / 1e6:g}-{bh / 1e6:g} MHz) und von < bis sein")
    cmd = bytes.fromhex(FIXED_KEYS[band][n - 1])
    ok = rig.civ(*cmd, *encode_edge(lo, hi))[4] == 0xFB
    return ok and read_fixed(rig, band, n) == (round(lo / 1000) * 1000, round(hi / 1000) * 1000)
