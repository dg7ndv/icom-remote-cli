#!/usr/bin/env python3
"""D-STAR-Direkttest ohne Relais (Simplex) zwischen IC-9700 und IC-705, beide per LAN/WLAN.

Ein Geraet sendet DV (kurz, ohne Sprache), das andere empfaengt und liest ueber CI-V die Rufzeichen (20 00 02), die Nachricht (20 01 02) und den
Status mit Paketverlust (20 02 02); dazu die Feldstaerke am Empfaenger. Ergebnis als Tabellenzeile in messungen/dstar_lokal.csv (wird angehaengt).

Beispiele (<MHz> = eine von dir gewaehlte freie Simplex-Frequenz):
  dstar_lokaltest.py --freq <MHz>                 nur Plan (es wird nichts gesendet)
  dstar_lokaltest.py --freq <MHz> --ja            beide Richtungen testen (SENDET, kurz, minimale Leistung)
  dstar_lokaltest.py --freq <MHz> --ja --richtung 9700-705 --watt 5 --antenne "Diskone"
Die Frequenz waehlst du (freier Kanal im 2-m- oder 70-cm-Band, kein Relaiskanal); das Skript prueft vorher, dass beide Geraete nichts hoeren.
"""
import argparse
import configparser
import csv
import sys
import time
from pathlib import Path

import icom_cli as C
import pegel2

HERE = Path(__file__).parent
GERAETE = {"9700": (0xA2, "ic9700.ini", 75.0), "705": (0xA4, "ic705.ini", 10.0)}  # CI-V-Adresse, Zugangsdatei, Maximalleistung W (70 cm)
KOPF = ["Datum", "Zeit", "Richtung", "Frequenz_MHz", "Leistung_W", "Po_roh", "SWR_roh", "Empfang", "MY", "UR", "RPT1", "RPT2", "Nachricht", "Paketverlust",
        "Feldstaerke_roh", "Feldstaerke_dB_S9", "S_Stufe", "Rauschen_roh", "Antenne", "Bemerkung"]


def verbinden(name):
    civ, ini, _pmax = GERAETE[name]
    c = configparser.ConfigParser()
    c.read(HERE / ini)
    r = c["radio"]
    return C.connect(r["host"], r["user"], r["password"], civ_addr=civ)


def f8(t, n=8):
    return t.upper().ljust(n)[:n].encode("ascii", "replace")


def einrichten(rig, name, mhz, my, nachricht, watt):
    """Simplex-DV auf der Frequenz, MY mit Kennung des Geraets, UR CQCQCQ, RPT1/RPT2 leer (direkt), Leistung."""
    if name == "9700":
        rig.select("main")
        time.sleep(0.1)
    rig.set_freq(int(round(mhz * 1e6)))
    C.set_cmd(rig, (0x06,), 0x17, 2)
    C.set_cmd(rig, (0x0F,), 0x10)  # Simplex
    ok1 = C.set_cmd(rig, (0x1F, 0x01), *f8("CQCQCQ"), *f8(""), *f8(""))
    ok0 = C.set_cmd(rig, (0x1F, 0x00), *f8(my), *f8(name, 4))
    okm = C.set_cmd(rig, (0x1F, 0x02), *f8(nachricht, 20))
    pmax = GERAETE[name][2]
    raw = 0 if watt is None else max(0, min(255, round(watt / pmax * 255)))
    C.set_cmd(rig, C.LEVELS["power"], *bytes.fromhex(f"{raw:04d}"))
    time.sleep(0.3)
    return ok1 and ok0, okm


def merken(rig):
    md = C.data(rig, 0x04)
    return {"hz": C.get_freq(rig), "md": md, "dm": C.data(rig, 0x1A, 0x06), "dup": (C.data(rig, 0x0F) or b"\x10")[0], "pw": C.level(rig, "power")}


def zurueck(rig, z):
    try:
        rig.set_freq(z["hz"])
        if z["md"]:
            C.set_cmd(rig, (0x06,), z["md"][0], z["md"][1])
        if z["dm"]:
            C.set_cmd(rig, (0x1A, 0x06), z["dm"][0], z["md"][1] if z["md"] else 1)
        C.set_cmd(rig, (0x0F,), z["dup"])
        if z["pw"] is not None:
            C.set_cmd(rig, C.LEVELS["power"], *bytes.fromhex(f"{z['pw']:04d}"))
    except Exception as e:
        print("Zustand nicht ganz wiederhergestellt:", e)


def rx_nachricht(rig):
    f = rig.civ(0x20, 0x01, 0x02)
    d = bytes(f[7:-1])
    if f[4] == 0xFA or len(d) < 20 or d[0] == 0xFF:
        return ""
    return d[:20].decode("ascii", "replace").strip()


def richtung(a, tx_name, rx_name, tx, rx, w):
    basis = C.dv_rx_info(rx)
    msg0 = rx_nachricht(rx)
    raw0, _ = C.messen(rx, 1.0)
    print(f"\n{tx_name} -> {rx_name}: Empfaenger hoert vorher: Rauschen roh {raw0}; Kanal wird 3 s abgehoert ...")
    peak0, sq0 = C.messen(rx, 3.0)
    peakt, sqt = C.messen(tx, 3.0)
    if peak0 > 20 or sq0 or peakt > 20 or sqt:
        print("  Kanal belegt, nicht gesendet.")
        return None
    print(f"  SENDE {a.sekunden:g} s ...", flush=True)
    vals = C.tasten(tx, a.sekunden)
    got, peak, loss, sq, end = None, 0, False, False, time.time() + 6
    while time.time() < end:
        info = C.dv_rx_info(rx)
        peak = max(peak, C.smeter(rx)[0])
        st = C.data(rx, 0x20, 0x02, 0x02)
        loss = loss or bool(st and st[0] & 1)
        sqd = C.data(rx, 0x15, 0x01)
        sq = sq or bool(sqd and sqd[0])
        if info and info != basis:
            got = info
            break
        time.sleep(0.2)
    msg = rx_nachricht(rx)
    jetzt = time.localtime()
    ok = got is not None
    if ok:
        print(f"  EMPFANGEN: MY '{got['mycall']}'  UR '{got['ur']}'  RPT1 '{got['rxrpt1']}'  RPT2 '{got['rxrpt2']}'  Nachricht '{msg if msg != msg0 else ''}'  Paketverlust {'ja' if loss else 'nein'}  "
              f"Feldstaerke {C.s_stufe(peak)} (roh {peak})")
    else:
        print(f"  Nichts dekodiert (S-Meter Spitze roh {peak}, Squelch {'offen' if sq else 'zu'}).")
    return [time.strftime("%Y-%m-%d", jetzt), time.strftime("%H:%M:%S", jetzt), f"{tx_name}->{rx_name}", f"{a.freq:g}", "" if w is None else f"{w:g}",
            vals.get("Po", ""), vals.get("SWR", ""), "ja" if ok else "nein", got["mycall"] if ok else "", got["ur"] if ok else "", got["rxrpt1"] if ok else "",
            got["rxrpt2"] if ok else "", msg if ok and msg != msg0 else "", "ja" if loss else "nein", peak, f"{pegel2.raw_to_db(peak):.1f}", C.s_stufe(peak), raw0,
            a.antenne or "", ""]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--freq", type=float, required=True, help="Simplex-Frequenz in MHz (2 m oder 70 cm, kein Relaiskanal)")
    ap.add_argument("--richtung", choices=("beide", "9700-705", "705-9700"), default="beide")
    ap.add_argument("--call", default="DG7NDV", help="dein Rufzeichen (MY)")
    ap.add_argument("--nachricht", default="D-STAR Test", help="Sendenachricht (max. 20 Zeichen)")
    ap.add_argument("--sekunden", type=float, default=2.0, help="Sendedauer je Richtung (0,5 bis 4 s)")
    ap.add_argument("--watt", type=float, help="Sendeleistung in W (Vorgabe: Minimum beider Geraete)")
    ap.add_argument("--antenne", help="Angabe zur Antenne fuer die Tabelle (optional)")
    ap.add_argument("--csv", help="Tabelle (Vorgabe messungen/dstar_lokal.csv)")
    ap.add_argument("--ja", action="store_true", help="wirklich ausfuehren (SENDET); ohne nur Plan")
    a = ap.parse_args()
    a.sekunden = max(0.5, min(4.0, a.sekunden))
    if not (144.0 <= a.freq <= 146.0 or 430.0 <= a.freq <= 440.0):
        sys.exit("Frequenz ausserhalb von 144-146 und 430-440 MHz: bitte eine Amateurfunk-Frequenz fuer Simplex waehlen")
    paare = [("9700", "705"), ("705", "9700")] if a.richtung == "beide" else [tuple(a.richtung.split("-"))]
    print(f"Plan: D-STAR direkt (Simplex) auf {a.freq:g} MHz, MY {a.call}, UR CQCQCQ, RPT1/RPT2 leer, Nachricht '{a.nachricht}'")
    for t, r in paare:
        print(f"  IC-{t} sendet {a.sekunden:g} s (Leistung " + ("Minimum" if a.watt is None else f"{a.watt:g} W") + f"), IC-{r} empfaengt und liest Rufzeichen, Nachricht, Paketverlust, Feldstaerke")
    if not a.ja:
        print("Nur Plan. Zum Ausfuehren denselben Befehl mit --ja wiederholen (dann wird GESENDET).")
        return
    csvp = Path(a.csv or HERE / "messungen" / "dstar_lokal.csv")
    csvp.parent.mkdir(exist_ok=True)
    neu = not csvp.exists()
    rigs, zust = {}, {}
    try:
        for n in {x for p in paare for x in p}:
            rigs[n] = verbinden(n).__enter__()
            zust[n] = merken(rigs[n])
            ok, okm = einrichten(rigs[n], n, a.freq, a.call, a.nachricht, a.watt)
            print(f"IC-{n}: {a.freq:g} MHz DV simplex, Rufzeichen {'gesetzt' if ok else 'ABGELEHNT'}, Nachricht {'gesetzt' if okm else 'abgelehnt'}")
        with csvp.open("a", encoding="utf-8-sig" if neu else "utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            if neu:
                w.writerow(KOPF)
            for t, r in paare:
                zeile = richtung(a, t, r, rigs[t], rigs[r], a.watt)
                if zeile:
                    w.writerow(zeile)
                    fh.flush()
                time.sleep(2)
    finally:
        for n, rig in rigs.items():
            try:
                C.set_cmd(rig, (0x1C, 0x00), 0)
            except Exception:
                pass
            zurueck(rig, zust[n])
            rig.close()
    print(f"Fertig. Tabelle: {csvp}")


if __name__ == "__main__":
    main()
