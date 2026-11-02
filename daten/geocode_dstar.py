#!/usr/bin/env python3
"""Koordinaten der Relais-Orte (daten/dstar_deutschland.json) einmalig ueber Nominatim (OpenStreetMap) holen und zwischenspeichern.
Hoeflich: ein Aufruf pro Sekunde, eigener User-Agent, Ergebnisse in daten/orte_geocode.json (nichts wird zweimal abgefragt)."""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / "orte_geocode.json"
UA = "icom-remote-cli/1.0 (Amateurfunk-Relaisliste, einmaliger Abruf)"


def umlaute(t):
    for a, b in (("ae", "ä"), ("oe", "ö"), ("ue", "ü"), ("Ae", "Ä"), ("Oe", "Ö"), ("Ue", "Ü")):
        t = t.replace(a, b)
    return t.replace("Bad Saeckingen", "Bad Säckingen")


def suche(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1, "countrycodes": "de"})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
        d = json.load(r)
    time.sleep(1.1)
    return (float(d[0]["lat"]), float(d[0]["lon"]), d[0].get("display_name", "")[:60]) if d else None


def main():
    orte = sorted({x["ort"] for x in json.load(open(HERE / "dstar_deutschland.json"))["relais"]})
    cache = json.load(open(CACHE)) if CACHE.exists() else {}
    for i, ort in enumerate(orte, 1):
        if ort in cache:
            continue
        first = ort.split(",")[0].strip()
        for q in (ort, first, umlaute(first), re.split(r"[ /]", first)[0]):
            try:
                r = suche(f"{q}, Deutschland")
            except Exception as e:
                print("Fehler", ort, e, file=sys.stderr)
                r = None
            if r:
                break
        cache[ort] = list(r) if r else None
        print(f"{i:3}/{len(orte)} {ort:<36} {r[:2] if r else 'nicht gefunden'}", flush=True)
        json.dump(cache, open(CACHE, "w"), ensure_ascii=False, indent=0)
    print("fertig:", sum(1 for v in cache.values() if v), "von", len(orte))


if __name__ == "__main__":
    main()
