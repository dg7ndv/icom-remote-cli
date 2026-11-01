#!/usr/bin/env python3
"""Bedienelemente des IC-9700 per CI-V lesen und setzen (Schalter, Regler, Filter).

Alle Befehle wirken auf den gerade gewaehlten Empfaenger (Main oder Sub); die Auswahl macht der Aufrufer.
Am Geraet gelesen und getestet: Duplex (0F), Preamp (16 02), AGC (16 12), NB (16 22), NR (16 40),
Auto-Notch (16 41), RIT (21), Pegel (14 xx), Filter (04/06).
"""
SWITCHES = {  # Name -> CI-V-Befehl; Wert 0/1
    "preamp": (0x16, 0x02), "sat": (0x16, 0x5A), "nb": (0x16, 0x22), "nr": (0x16, 0x40), "notch": (0x16, 0x41), "rit": (0x21, 0x01),
}
LEVELS = {  # Name -> CI-V-Befehl; Wert 0..255
    "af": (0x14, 0x01), "rf": (0x14, 0x02), "sql": (0x14, 0x03), "nr_level": (0x14, 0x06),
    "power": (0x14, 0x0A), "nb_level": (0x14, 0x12),
    "pbt1": (0x14, 0x07), "pbt2": (0x14, 0x08), "notch_pos": (0x14, 0x0D),
    "cw_pitch": (0x14, 0x09), "cw_speed": (0x14, 0x0C),
}
# Menueeinstellungen je Band (1A 05 xxxx), nur IC-9700: externer Vorverstaerker und ACC-SEND-Ausgang
BAND_SETTINGS = {"extpre": ("1A050093", "1A050094", "1A050095"), "accsend": ("1A050117", "1A050118", "1A050119")}
HAS_BAND_SETTINGS = True  # beim IC-705 ausschalten: dort bedeuten diese Nummern etwas anderes
BANDS = ((144e6, 148e6), (430e6, 450e6), (1240e6, 1300e6))
AGC = {1: "FAST", 2: "MID", 3: "SLOW"}
DUPLEX_CODES = {"OFF": 0x10, "DUP-": 0x11, "DUP+": 0x12}


def band_index(hz):
    """0 = 144 MHz, 1 = 430 MHz, 2 = 1200 MHz; None ausserhalb."""
    return next((i for i, (lo, hi) in enumerate(BANDS) if lo <= hz <= hi), None)


def _bcd2(v):
    return bytes.fromhex(f"{int(v):04d}")


def _data(frame, n):
    """Nutzdaten hinter dem Befehl (n = Laenge des Befehls) oder None bei NG."""
    return None if frame[4] == 0xFA else bytes(frame[4 + n:-1])


def read_all(rig):
    """Zustand des gewaehlten Empfaengers als dict (fehlende/abgelehnte Werte werden weggelassen)."""
    out = {}

    def get(cmd):
        try:
            return _data(rig.civ(*cmd), len(cmd))
        except TimeoutError:
            return None

    for name, cmd in SWITCHES.items():
        d = get(cmd)
        if d:
            out[name] = bool(d[0])
    for name, cmd in LEVELS.items():
        d = get(cmd)
        if d and len(d) >= 2:
            out[name] = int(d.hex())
    if HAS_BAND_SETTINGS:  # gelten fuer das Band, auf dem der gewaehlte Empfaenger steht
        try:
            i = band_index(rig.freq())
        except TimeoutError:
            i = None
        if i is not None:
            for name, keys in BAND_SETTINGS.items():
                d = get(tuple(bytes.fromhex(keys[i])))
                if d:
                    out[name] = bool(d[0])
    d = get((0x11,))  # Daempfer: 00 = aus, 10 = 10 dB
    if d:
        out["att"] = bool(d[0])
    d = get((0x16, 0x12))
    if d:
        out["agc"] = d[0]
    d = get((0x0F,))
    if d is not None and len(d) >= 1:
        out["duplex"] = {0x11: "DUP-", 0x12: "DUP+"}.get(d[0], "OFF")
        out["split"] = d[0] == 0x01
    d = get((0x21, 0x00))
    if d and len(d) >= 3:
        hz = int(f"{d[1]:02x}{d[0]:02x}")
        out["rit_offset"] = -hz if d[2] else hz
    try:
        m = rig.civ(0x04)
        out["filter"] = m[6]
    except TimeoutError:
        pass
    return out


def set_control(rig, name, value):
    """Einen Schalter oder Regler setzen. Gibt True zurueck, wenn das Geraet mit OK (FB) antwortet."""
    if name in SWITCHES:
        r = rig.civ(*SWITCHES[name], 1 if value else 0)
    elif name in LEVELS:
        r = rig.civ(*LEVELS[name], *_bcd2(max(0, min(255, int(value)))))
    elif name in BAND_SETTINGS:
        i = band_index(rig.freq())
        if i is None or not HAS_BAND_SETTINGS:
            return False
        r = rig.civ(*bytes.fromhex(BAND_SETTINGS[name][i]), 1 if value else 0)
    elif name == "att":
        r = rig.civ(0x11, 0x10 if value else 0x00)
    elif name == "agc":
        r = rig.civ(0x16, 0x12, int(value))
    elif name == "duplex":
        r = rig.civ(0x0F, DUPLEX_CODES[value])
    elif name == "split":
        r = rig.civ(0x0F, 0x01 if value else 0x00)
    elif name == "rit_offset":
        hz = max(-9999, min(9999, int(value)))
        digits = f"{abs(hz):04d}"
        r = rig.civ(0x21, 0x00, int(digits[2:], 16), int(digits[:2], 16), 1 if hz < 0 else 0)
    elif name == "filter":
        return set_filter(rig, int(value))
    else:
        raise KeyError(name)
    return r[4] == 0xFB


def set_filter(rig, n):
    """Filter 1-3 des gewaehlten Empfaengers; Modus und Daten-Modus bleiben erhalten."""
    mode = rig.civ(0x04)[5]
    data = rig.civ(0x1A, 0x06)
    ok = rig.civ(0x06, mode, n)[4] == 0xFB
    if len(data) >= 9 and data[6]:  # DATA-Modus an: dessen Filter gleich mitsetzen
        ok = rig.civ(0x1A, 0x06, data[6], n)[4] == 0xFB and ok
    return ok
