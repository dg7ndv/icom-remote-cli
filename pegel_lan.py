#!/usr/bin/env python3
"""Pegel von Main und Sub des IC-9700 direkt ueber Ethernet (ohne wfview, ohne PTY).

Zugangsdaten: ic9700.ini (Host, Benutzer, Passwort) oder IC9700_HOST/IC9700_USER/IC9700_PASS.
wfview muss beendet sein: das Geraet laesst nur einen Netzwerk-Client zu.

Beispiele:
  pegel_lan.py                        Main und Sub einmal ausgeben
  pegel_lan.py -n                     laufend ausgeben, Strg+C beendet
  pegel_lan.py -n | tee pegel.txt     laufend, Ausgabe mitschreiben
  pegel_lan.py --retune sub 144.3M    Sub kurz auf 144,3 MHz stellen, messen, zurueckstellen
  pegel_lan.py --host 192.168.20.200 --user dg7ndv    ohne ic9700.ini
  pegel_lan.py -v                     Pakete mitprotokollieren (Fehlersuche, zeigt Hex-Daten)

Pegel: dB relativ zu S9 (-54 = S0, 0 = S9), dahinter der Rohwert 0..255.
Hinweis: --retune kann Main verstellen (siehe pegel2.py); danach mit dem Skript ohne Optionen pruefen.
"""
import argparse
import time

import ic9700_lan
import pegel2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", action="store_true", help="laufend ausgeben")
    ap.add_argument("--retune", nargs=2, metavar=("BAND", "FREQ"), help="main|sub kurz auf FREQ stellen und messen")
    ap.add_argument("--host", help="IP des IC-9700 (sonst ic9700.ini)")
    ap.add_argument("--user", help="Benutzername (sonst ic9700.ini)")
    ap.add_argument("-v", action="store_true", help="UDP-Pakete protokollieren")
    a = ap.parse_args()
    ic9700_lan.VERBOSE = a.v

    with ic9700_lan.LanRig(a.host, a.user) as rig:
        print(f"verbunden mit {rig.device}")
        if a.retune:
            band, hz = a.retune[0].lower(), pegel2.parse_hz(a.retune[1])
            raw, f0 = pegel2.retune(rig, band, hz)
            print(f"{band.capitalize()} {hz / 1e6:.6f} MHz  {pegel2.raw_to_db(raw):+6.1f} dB (raw {raw:3d})"
                  f"   [{band} wieder auf {f0 / 1e6:.6f} MHz]")
            return
        while True:
            print(pegel2.line(pegel2.read_both(rig)), flush=True)
            if not a.n:
                break
            time.sleep(0.3)


if __name__ == "__main__":
    main()
