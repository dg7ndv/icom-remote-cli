#!/usr/bin/env python3
"""D-STAR-Relaisliste fuer Deutschland: aus zwei Webseiten holen und zusammenfuehren.

  DARC-Relaisliste  https://relaislisten.darc.de/cgi-bin/relais.pl   Koordinaten, Modul (A/B/C), Eingabefrequenz
  RepeaterBook      https://www.repeaterbook.com/row_repeaters/Display_SS.php?mode=4&state_id=DE   Ort, Modi, Betriebszustand

Ergebnis: daten/dstar_deutschland.json (wird von der GUI-Maske "D-STAR-Relais" und vom CLI benutzt).
Aufruf:  relais_daten.py       holt alles neu (ca. 1,5 Minuten, hoeflich: eine Abfrage alle 2 s)
"""
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).with_name("daten")
OUT = DATA / "dstar_deutschland.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) icom-remote-cli"
DARC_URL = "https://relaislisten.darc.de/cgi-bin/relais.pl"
RB_URL = "https://www.repeaterbook.com/row_repeaters/Display_SS.php?mode=4&state_id=DE"
STAEDTE = ["Nürnberg", "Hamburg", "Berlin", "Köln", "München", "Stuttgart", "Frankfurt", "Dresden", "Hannover", "Leipzig", "Bremen", "Kiel",
           "Rostock", "Saarbrücken", "Freiburg", "Münster", "Kassel", "Erfurt", "Magdeburg", "Regensburg", "Trier", "Passau", "Konstanz", "Flensburg"]


def darc_url(lat=None, lon=None, stadt="Nürnberg", maxgateways=100):
    """Adresse der DARC-Seite fuer eine D-STAR-Abfrage; mit Koordinaten (Grad, Dezimal) oder Stadtname. Zum Oeffnen im Browser."""
    p = {"sel": "latlon", "lat_deg": "", "lat_min": "", "lat_NS": "Nord", "lon_deg": "", "lon_min": "", "lon_EW": "Ost", "city": "" if lat is not None else stadt,
         "gs": "", "ctrcall": "", "dxcc": "all", "maxgateways": maxgateways, "printas": "html", "type": "ds", "kmmls": "km"}
    if lat is not None:
        p.update(lat_deg=int(lat), lat_min=int((lat % 1) * 60), lon_deg=int(lon), lon_min=int((lon % 1) * 60))
    return DARC_URL + "?" + urllib.parse.urlencode(p, encoding="latin-1")


def _get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8", "replace")


def _clean(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x)).replace("\xa0", " ")).strip()


def _num(x):
    try:
        return float(x.replace("km.", "").replace("km", "").replace(",", ".").strip())
    except ValueError:
        return None


def darc_abfrage(stadt):
    rows = []
    for r in re.split(r"<TR>\s*", _get(darc_url(stadt=stadt, maxgateways=1000))):
        m = re.search(r"lat=\s*([+-][\d.]+)&lng=\s*([+-][\d.]+)", r)
        tds = re.findall(r"<TD[^>]*>(.*?)</TD>", r, re.S | re.I)
        if m and len(tds) >= 9:
            c = [_clean(x) for x in tds]
            rows.append({"call": c[1], "ausgabe": _num(c[4]), "eingabe": _num(c[5]), "info": c[6], "modul": c[7],
                         "lat": float(m.group(1)), "lon": float(m.group(2))})
    return rows


def darc_holen(progress=None):
    """Alle D-STAR-Eintraege der DARC-Liste (je Stadt die 100 naechsten, zusammengefuehrt)."""
    alle = {}
    for i, s in enumerate(STAEDTE, 1):
        try:
            for x in darc_abfrage(s):
                alle.setdefault((x["call"], round(x["ausgabe"] or 0, 4)), x)
        except Exception as e:  # eine fehlgeschlagene Stadt ist nicht schlimm
            if progress:
                progress(f"DARC {s}: Fehler {e}")
        if progress:
            progress(f"DARC-Liste {i}/{len(STAEDTE)} ({s}): {len(alle)} Eintraege")
        time.sleep(2)
    return list(alle.values())


def repeaterbook_holen():
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", _get(RB_URL), re.S)[1:]:
        c = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if len(c) < 7 or not re.match(r"[\d.]+ [+-]", c[1]):
            continue
        f, sign = c[1].split()
        out.append({"call": c[4], "freq_mhz": float(f), "ablage": sign, "ort": c[3], "zugang": c[2], "modes": c[5],
                    "status": {"🟢": "online", "🟡": "eingeschraenkt", "🔴": "offline"}.get(c[6], c[6])})
    return out


def band_von(mhz):
    return "2 m" if mhz < 200 else "70 cm" if mhz < 600 else "23 cm"


def zusammenfuehren(darc, rb):
    """DARC (Koordinaten, Modul, Eingabe) und RepeaterBook (Ort, Modi, Zustand) zu einer Liste."""
    deutsch = [x for x in darc if x["call"].upper().startswith("D") and 47.2 <= x["lat"] <= 55.1 and 5.8 <= x["lon"] <= 15.1 and x["ausgabe"]]
    out, benutzt = [], set()
    for x in deutsch:
        aus, ein, pruefen = x["ausgabe"], x["eingabe"], ""
        if ein and aus < 435 < ein:  # in der DARC-Zeile vertauscht eingetragen
            aus, ein, pruefen = ein, aus, "DARC: Ausgabe und Eingabe vertauscht, bitte pruefen"
        m = next((i for i, r in enumerate(rb) if r["call"] == x["call"] and abs(r["freq_mhz"] - aus) < 0.003), None)
        r = rb[m] if m is not None else None
        if m is not None:
            benutzt.add(m)
        ab = round(abs(aus - ein), 4) if ein else None
        out.append({"call": x["call"], "freq_mhz": aus, "eingabe_mhz": ein, "modul": x["modul"], "lat": x["lat"], "lon": x["lon"],
                    "ort": (r["ort"] if r else x["info"]), "modes": (r["modes"] if r else "D-STAR"), "status": (r["status"] if r else "unbekannt"),
                    "band": band_von(aus), "ablage": ("-" if ein is not None and ein < aus else "+") if ab else "", "ablage_mhz": ab if ab is not None else 0.0,
                    "zugang": (r["zugang"] if r else ""), "darc": True, "rb": r is not None, "pruefen": pruefen})
    for i, r in enumerate(rb):
        if i in benutzt:
            continue
        mhz = r["freq_mhz"]
        out.append({"call": r["call"], "freq_mhz": mhz, "eingabe_mhz": None, "modul": "", "lat": None, "lon": None, "ort": r["ort"], "modes": r["modes"],
                    "status": r["status"], "band": band_von(mhz), "ablage": r["ablage"], "ablage_mhz": {"2 m": 0.6, "70 cm": 7.6, "23 cm": 28.0}[band_von(mhz)],
                    "zugang": r["zugang"], "darc": False, "rb": True, "pruefen": "nur RepeaterBook: nicht in der DARC-D-STAR-Liste"})
    return sorted(out, key=lambda e: (e["call"], e["freq_mhz"]))


def aktualisieren(progress=None):
    """Beide Seiten neu lesen, zusammenfuehren und speichern. Gibt (Anzahl, Meldung) zurueck."""
    if progress:
        progress("RepeaterBook wird gelesen ...")
    rb = repeaterbook_holen()
    darc = darc_holen(progress)
    liste = zusammenfuehren(darc, rb)
    DATA.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"quelle": "DARC-Relaisliste + RepeaterBook", "abgerufen": time.strftime("%Y-%m-%d %H:%M"),
                               "hinweis": "Ablage aus der DARC-Eingabefrequenz; ohne DARC-Eintrag Standardwert je Band. Modul A=23 cm, B=70 cm, C=2 m.",
                               "relais": liste}, ensure_ascii=False, indent=1), encoding="utf-8")
    n_darc = sum(1 for e in liste if e["darc"])
    return len(liste), f"{len(liste)} Relais ({n_darc} mit DARC-Koordinaten, {len(liste) - n_darc} nur RepeaterBook), Stand {time.strftime('%d.%m.%Y %H:%M')}"


if __name__ == "__main__":
    print(aktualisieren(print)[1])
