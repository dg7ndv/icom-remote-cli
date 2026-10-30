#!/usr/bin/env python3
"""Frequenz und S-Meter von Main UND Sub des IC-9700 per rohem CI-V ueber das wfview-PTY.

Voraussetzung: wfview mit Virtual Serial Port (rig-pty1), rigctld darf NICHT gleichzeitig
auf dem PTY laufen (`pkill rigctld`). Zum Lesen wird kurz zwischen Main (07 D0) und Sub
(07 D1) umgeschaltet; danach steht wieder das Band, das vorher gewaehlt war.

Beispiele:
  pegel2.py                          einmal Main und Sub ausgeben
  pegel2.py -n                       laufend ausgeben, Strg+C beendet
  pegel2.py -n | tee pegel.txt       laufend, Ausgabe mitschreiben
  pegel2.py --retune sub 144.3M      Sub kurz auf 144,3 MHz stellen, messen, zurueckstellen
  pegel2.py --retune sub 1296.1M     dasselbe auf 23 cm
  pegel2.py --retune main 432.1M     Main kurz auf 432,1 MHz stellen und zurueck
  pegel2.py --retune sub 145.5M      Frequenz in Hz geht auch: 145500000

Pegel: dB relativ zu S9 (-54 = S0, 0 = S9, +60 = S9+60 dB), dahinter der Rohwert 0..255.
Beim Lesen wird kurz zwischen Main und Sub umgeschaltet; danach steht wieder das Band,
das vorher gewaehlt war. Kein rigctld gleichzeitig am PTY (pkill rigctld).
"""
import argparse
import os
import select
import subprocess
import sys
import termios
import time

CIV_RIG, CIV_CTRL = 0xA2, 0xE0


def wfview_pty():
    pids = subprocess.run(["pgrep", "-x", "wfview"], capture_output=True, text=True).stdout.split()
    if not pids:
        sys.exit("wfview laeuft nicht")
    for fd in os.listdir(f"/proc/{pids[0]}/fd"):
        try:
            target = os.readlink(f"/proc/{pids[0]}/fd/{fd}")
        except OSError:
            continue
        if target.startswith("/dev/pts/"):
            return target
    sys.exit("wfview hat kein PTY offen (Settings > External Control > Virtual Serial Port)")


class Rig:
    def __init__(self, pty):
        self.fd = os.open(pty, os.O_RDWR | os.O_NOCTTY)
        a = termios.tcgetattr(self.fd)
        a[0] = a[1] = a[3] = 0
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        a[4] = a[5] = termios.B19200
        termios.tcsetattr(self.fd, termios.TCSANOW, a)

    def civ(self, *cmd):
        frame = bytes([0xFE, 0xFE, CIV_RIG, CIV_CTRL, *cmd, 0xFD])
        termios.tcflush(self.fd, termios.TCIFLUSH)
        os.write(self.fd, frame)
        out, end = b"", time.time() + 1.0
        while time.time() < end:
            if select.select([self.fd], [], [], 0.05)[0]:
                out += os.read(self.fd, 256)
            if out.startswith(frame) and out.endswith(b"\xfd") and len(out) > len(frame):
                break
        return out[len(frame):] if out.startswith(frame) else out

    def freq(self):
        r = self.civ(0x03)
        return int("".join(f"{b:02x}" for b in reversed(r[5:10])))

    def smeter_raw(self):
        return int(self.civ(0x15, 0x02)[6:8].hex())

    def select(self, band):  # "main" oder "sub"
        self.civ(0x07, 0xD0 if band == "main" else 0xD1)
        time.sleep(0.15)

    def set_freq(self, hz):
        digits = f"{hz:010d}"
        bcd = bytes(int(digits[i:i + 2], 16) for i in range(8, -1, -2))
        self.civ(0x05, *bcd)

    def get_mode(self):
        r = self.civ(0x04)
        d = self.civ(0x1A, 0x06)
        return r[5], r[6], d[6], d[7]  # Modus, Filter, Data an/aus, Data-Filter

    def set_mode(self, mode, filt, data, dfilt):
        self.civ(0x06, mode, filt)
        self.civ(0x1A, 0x06, data, dfilt)


def raw_to_db(raw):
    """0..120 = S0..S9 (-54..0 dB), 121..241 = S9..S9+60 dB (grobe Naeherung)."""
    return -54 + raw * 54 / 120 if raw <= 120 else (raw - 120) * 60 / 121


def read_both(rig):
    vorher = rig.freq()
    res = {}
    for band in ("main", "sub"):
        rig.select(band)
        res[band] = (rig.freq(), rig.smeter_raw())
    # zurueck auf das vorher gewaehlte Band
    if res["main"][0] == vorher and res["sub"][0] != vorher:
        rig.select("main")
    elif res["sub"][0] == vorher:
        rig.select("sub")
    return res


def parse_hz(text):
    t = text.strip().lower()
    mult = {"k": 1e3, "m": 1e6, "g": 1e9}.get(t[-1], 1)
    return int(round(float(t[:-1] if t[-1] in "kmg" else t) * mult))


def goto(rig, band, expected, tries=6):
    """Band waehlen und pruefen, dass wirklich der Empfaenger mit `expected` Hz gewaehlt ist."""
    for _ in range(tries):
        rig.select(band)
        time.sleep(0.2)
        if abs(rig.freq() - expected) <= 10:
            return
    raise RuntimeError(f"{band} nicht waehlbar (erwartet {expected / 1e6:.6f} MHz)")


def retune(rig, band, hz, n=5):
    """Empfaenger `band` kurz auf `hz` stellen, S-Meter mitteln, alles zurueckstellen.

    Prueft die Auswahl und das Ergebnis; stehen Main/Sub danach nicht wie vorher,
    werden sie zurueckgestellt. Bei Fehlern wird abgebrochen (RuntimeError)."""
    snap = read_both(rig)
    selected = rig.freq()
    f0 = snap[band][0]
    other = "main" if band == "sub" else "sub"
    goto(rig, band, f0)
    m0 = rig.get_mode()
    raws, error = [], None
    try:
        rig.set_freq(hz)
        time.sleep(0.6)
        if abs(rig.freq() - hz) > 1000:
            raise RuntimeError(f"{band} ging nicht auf {hz / 1e6:.6f} MHz (steht auf {rig.freq() / 1e6:.6f} MHz)")
        for _ in range(n):
            raws.append(rig.smeter_raw())
            time.sleep(0.1)
    except RuntimeError as e:
        error = e
    finally:
        # alles auf den Ausgangszustand: beide Empfaenger auf ihre alten Frequenzen
        for slot in (band, other):
            now = read_both(rig)
            if abs(now[slot][0] - snap[slot][0]) > 10:
                rig.select(slot)
                time.sleep(0.2)
                rig.set_freq(snap[slot][0])
                time.sleep(0.3)
        rig.select(band)
        rig.set_mode(*m0)
        # zuletzt das Band waehlen, das vorher gewaehlt war
        rig.select(band if abs(selected - snap[band][0]) <= 10 else other)
        time.sleep(0.2)
    if error:
        raise error
    return round(sum(raws) / len(raws)), f0


def line(res):
    parts = []
    for band in ("main", "sub"):
        f, raw = res[band]
        parts.append(f"{band.capitalize():4} {f / 1e6:12.6f} MHz  {raw_to_db(raw):+6.1f} dB (raw {raw:3d})")
    return "  |  ".join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", action="store_true", help="laufend ausgeben")
    ap.add_argument("--retune", nargs=2, metavar=("BAND", "FREQ"),
                    help="Empfaenger main|sub kurz auf FREQ stellen, Pegel messen, zurueckstellen")
    a = ap.parse_args()
    rig = Rig(wfview_pty())
    if a.retune:
        band, hz = a.retune[0].lower(), parse_hz(a.retune[1])
        if band not in ("main", "sub"):
            sys.exit("BAND muss main oder sub sein")
        raw, f0 = retune(rig, band, hz)
        print(f"{band.capitalize()} {hz / 1e6:.6f} MHz  {raw_to_db(raw):+6.1f} dB (raw {raw:3d})"
              f"   [{band} wieder auf {f0 / 1e6:.6f} MHz]")
        return
    while True:
        print(line(read_both(rig)), flush=True)
        if not a.n:
            break
        time.sleep(0.3)


if __name__ == "__main__":
    main()
