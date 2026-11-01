#!/usr/bin/env python3
"""Tabelle der einstellbaren Geraete-Parameter des IC-9700 (nach dem CI-V-Handbuch, Abschnitt 1A 05 und 14/16).

Bewusst NICHT enthalten: Netzwerk (IP, Ports, Passwoerter), Uhrzeit, CI-V-Adresse, GPS-Position, SD-Karte, Farben,
alles mit Sonderformat. Eintrag: (Gruppe, Schluessel, Text, Art, Angabe)
  Art "b" = aus/ein, "e" = Auswahl (Angabe = Liste, Wert = Index), "n" = Zahl (Angabe = (von, bis, Bytes)).
Der Schluessel ist der CI-V-Befehl als Hex-Text, z. B. "1A050027" oder "1644".
"""
OFFON = ["aus", "ein"]
DELAY = ["aus", "10 ms", "15 ms", "20 ms", "25 ms", "30 ms"]
TONE = (0, 10, 1)       # -5 ... +5
LV = (0, 255, 2)        # 0000 ... 0255

ENTRIES = [
    # ---- Sprache / Senden (wirken auf den gewaehlten Empfaenger bzw. das Geraet) ----
    ("Senden", "1644", "Sprachkompressor", "b", None),
    ("Senden", "1645", "Monitor (MONI)", "b", None),
    ("Senden", "1646", "VOX", "b", None),
    ("Senden", "1647", "Break-in (CW)", "e", ["aus", "Semi", "Voll"]),
    ("Senden", "140B", "Mikrofonverstaerkung (MIC Gain)", "n", LV),
    ("Senden", "140A", "Sendeleistung (je Band!)", "n", LV),
    ("Senden", "140E", "Kompressor-Pegel", "n", LV),
    ("Senden", "1416", "VOX-Verstaerkung", "n", LV),
    ("Senden", "1415", "Monitor-Lautstaerke", "n", LV),
    ("Senden", "140F", "Break-in-Verzoegerung", "n", LV),
    ("Senden", "1A050215", "Sprachspeicher: Sendepegel (VOICE TX)", "n", LV),
    ("Senden", "1A050038", "TX-Verzoegerung 144 MHz", "e", DELAY),
    ("Senden", "1A050039", "TX-Verzoegerung 430 MHz", "e", DELAY),
    ("Senden", "1A050040", "TX-Verzoegerung 1200 MHz", "e", DELAY),
    ("Senden", "1A050041", "Time-Out-Timer", "e", ["aus", "3 min", "5 min", "10 min", "20 min", "30 min"]),
    ("Senden", "1A050042", "PTT-Sperre (PTT Lock)", "b", None),
    ("Senden", "1A050062", "MIC Up/Down-Geschwindigkeit", "e", ["langsam", "schnell"]),
    ("Senden", "1A050093", "Externer Vorverstaerker 144 MHz", "b", None),
    ("Senden", "1A050094", "Externer Vorverstaerker 430 MHz", "b", None),
    ("Senden", "1A050095", "Externer Vorverstaerker 1200 MHz", "b", None),
    ("Senden", "1A050117", "ACC SEND-Ausgang 144 MHz", "b", None),
    ("Senden", "1A050118", "ACC SEND-Ausgang 430 MHz", "b", None),
    ("Senden", "1A050119", "ACC SEND-Ausgang 1200 MHz", "b", None),
    # ---- Empfang ----
    ("Empfang", "1642", "Repeaterton", "b", None),
    ("Empfang", "1643", "Tonsquelch", "b", None),
    ("Empfang", "1648", "Manuelles Notch", "b", None),
    ("Empfang", "164A", "AFC", "b", None),
    ("Empfang", "1650", "Abstimmknopf sperren (Dial Lock)", "b", None),
    ("Empfang", "1656", "DSP-ZF-Filter", "e", ["SHARP", "SOFT"]),
    ("Empfang", "1657", "Manuelles Notch: Breite", "e", ["WIDE", "MID", "NAR"]),
    ("Empfang", "1658", "SSB-Sendebandbreite", "e", ["WIDE", "MID", "NAR"]),
    ("Empfang", "140D", "Notch-Position", "n", LV),
    ("Empfang", "1407", "PBT1", "n", LV),
    ("Empfang", "1408", "PBT2", "n", LV),
    ("Empfang", "1A050036", "RF/SQL-Regler", "e", ["Auto", "SQL", "RF+SQL"]),
    ("Empfang", "1A050037", "FM/DV Center-Fehler-Anzeige", "b", None),
    ("Empfang", "1A050061", "Haupt-Abstimmknopf Auto-TS", "e", ["aus", "niedrig", "hoch"]),
    ("Empfang", "1A050063", "AFC-Grenze", "b", None),
    ("Empfang", "1A050064", "NOTCH-Taste (SSB)", "e", ["Auto", "Manuell", "Auto/Manuell"]),
    ("Empfang", "1A050065", "NOTCH-Taste (AM)", "e", ["Auto", "Manuell", "Auto/Manuell"]),
    ("Empfang", "1A050066", "SSB/CW synchron abstimmen", "b", None),
    ("Empfang", "1A050067", "CW normale Seite", "e", ["LSB", "USB"]),
    ("Empfang", "1A050072", "Referenzoszillator (REF Adjust)", "n", LV),
    ("Empfang", "1A050073", "Referenzoszillator fein (REF Adjust FINE)", "n", LV),
    # ---- Klang ----
    ("Klang", "1A050002", "SSB RX Bass", "n", TONE), ("Klang", "1A050003", "SSB RX Hoehen", "n", TONE),
    ("Klang", "1A050005", "AM RX Bass", "n", TONE), ("Klang", "1A050006", "AM RX Hoehen", "n", TONE),
    ("Klang", "1A050008", "FM RX Bass", "n", TONE), ("Klang", "1A050009", "FM RX Hoehen", "n", TONE),
    ("Klang", "1A050011", "DV RX Bass", "n", TONE),
    ("Klang", "1A050015", "SSB TX Bass", "n", TONE), ("Klang", "1A050016", "SSB TX Hoehen", "n", TONE),
    ("Klang", "1A050021", "AM TX Bass", "n", TONE), ("Klang", "1A050022", "AM TX Hoehen", "n", TONE),
    ("Klang", "1A050023", "FM TX Bass", "n", TONE), ("Klang", "1A050024", "FM TX Hoehen", "n", TONE),
    ("Klang", "1A050025", "DV TX Bass", "n", TONE), ("Klang", "1A050026", "DV TX Hoehen", "n", TONE),
    # ---- Pieptoene, Sprachausgabe ----
    ("Ton", "1A050027", "Piepton-Lautstaerke", "n", LV),
    ("Ton", "1A050028", "Piepton-Lautstaerke begrenzen", "b", None),
    ("Ton", "1A050029", "Piepton bei Bestaetigung", "b", None),
    ("Ton", "1A050030", "Bandgrenzen-Piepton", "b", None),
    ("Ton", "1A050031", "Piepton-Tonhoehe Main", "n", (50, 200, 2)),
    ("Ton", "1A050032", "Piepton-Tonhoehe Sub", "n", (50, 200, 2)),
    ("Ton", "1A050033", "Sub stumm beim Senden: Lautsprecher/Kopfhoerer", "b", None),
    ("Ton", "1A050034", "Sub stumm beim Senden: USB", "b", None),
    ("Ton", "1A050035", "Sub stumm beim Senden: LAN", "b", None),
    ("Ton", "1A050050", "Sprachausgabe: Sprache", "e", ["Englisch", "Japanisch"]),
    ("Ton", "1A050051", "Sprachausgabe: Alphabet", "e", ["normal", "phonetisch"]),
    ("Ton", "1A050052", "Sprachausgabe: Geschwindigkeit", "e", ["langsam", "schnell"]),
    ("Ton", "1A050053", "Rufzeichen ansagen", "e", ["aus", "Kerchunk", "alle"]),
    ("Ton", "1A050055", "S-Wert ansagen", "b", None),
    ("Ton", "1A050056", "Betriebsart ansagen", "b", None),
    ("Ton", "1A050057", "Sprachausgabe-Lautstaerke", "n", LV),
    ("Ton", "1A050096", "Externer Lautsprecher", "e", ["getrennt", "gemischt"]),
    ("Ton", "1A050097", "Kopfhoerer-Pegel (00=-15 dB, 30=+15 dB)", "n", (0, 30, 1)),
    ("Ton", "1A050098", "Kopfhoerer L/R", "e", ["getrennt", "gemischt", "Auto"]),
    # ---- Anschluesse und Ausgaenge ----
    ("Anschluesse", "1A050099", "ACC-Ausgabe: Empfaenger", "e", ["Main", "Sub"]),
    ("Anschluesse", "1A050100", "ACC-Ausgabe", "e", ["AF", "IF"]),
    ("Anschluesse", "1A050101", "ACC AF-Pegel", "n", LV),
    ("Anschluesse", "1A050102", "ACC AF-Squelch", "b", None),
    ("Anschluesse", "1A050103", "ACC: Piepton/Sprache ausgeben", "b", None),
    ("Anschluesse", "1A050104", "ACC ZF-Pegel", "n", LV),
    ("Anschluesse", "1A050105", "USB-Ausgabe", "e", ["AF", "IF"]),
    ("Anschluesse", "1A050106", "USB AF-Pegel", "n", LV),
    ("Anschluesse", "1A050107", "USB AF-Squelch", "b", None),
    ("Anschluesse", "1A050108", "USB: Piepton/Sprache ausgeben", "b", None),
    ("Anschluesse", "1A050109", "USB ZF-Pegel", "n", LV),
    ("Anschluesse", "1A050110", "LAN-Ausgabe", "e", ["AF", "IF"]),
    ("Anschluesse", "1A050111", "LAN AF-Squelch", "b", None),
    ("Anschluesse", "1A050112", "ACC-Modulationspegel", "n", LV),
    ("Anschluesse", "1A050113", "USB-Modulationspegel", "n", LV),
    ("Anschluesse", "1A050114", "LAN-Modulationspegel", "n", LV),
    ("Anschluesse", "1A050115", "Modulationsquelle (ohne DATA)", "e", ["MIC", "ACC", "MIC+ACC", "USB", "MIC+USB", "LAN"]),
    ("Anschluesse", "1A050116", "Modulationsquelle (DATA)", "e", ["MIC", "ACC", "MIC+ACC", "USB", "MIC+USB", "LAN"]),
    ("Anschluesse", "1A050123", "USB-Sendesperre-Timer", "b", None),
    ("Anschluesse", "1A050124", "Externe Tastatur: VOICE", "b", None),
    ("Anschluesse", "1A050125", "Externe Tastatur: KEYER", "b", None),
    ("Anschluesse", "1A050126", "Externe Tastatur: RTTY", "b", None),
    ("Anschluesse", "1A050127", "CI-V Transceive", "b", None),
    ("Anschluesse", "1A050130", "CI-V USB Echo Back", "b", None),
    ("Anschluesse", "1A050131", "CI-V DATA Echo Back", "b", None),
    # ---- Anzeige und Scope ----
    ("Anzeige", "1A050152", "LCD-Helligkeit", "n", LV),
    ("Anzeige", "1A050153", "Anzeigetyp", "e", ["A", "B"]),
    ("Anzeige", "1A050154", "Schriftart", "e", ["Basis", "Rund"]),
    ("Anzeige", "1A050155", "Meter-Spitzenwert halten", "b", None),
    ("Anzeige", "1A050156", "Speichername anzeigen", "b", None),
    ("Anzeige", "1A050158", "Bandbreiten-Popup (PBT)", "b", None),
    ("Anzeige", "1A050159", "Bandbreiten-Popup (FIL)", "b", None),
    ("Anzeige", "1A050160", "RX-Rufzeichen-Anzeige", "e", ["aus", "normal", "RX halten", "halten"]),
    ("Anzeige", "1A050162", "RX-Positionsanzeige", "e", ["aus", "Main/Sub", "nur Main"]),
    ("Anzeige", "1A050167", "Bildschirmschoner", "e", ["aus", "15 min", "30 min", "60 min"]),
    ("Anzeige", "1A050168", "Startmeldung", "b", None),
    ("Anzeige", "1A050169", "Einschalt-Check", "b", None),
    ("Anzeige", "1A050188", "Scope: Max Hold", "e", ["aus", "10 s", "ein"]),
    ("Anzeige", "1A050192", "Scope: Mittelung", "e", ["aus", "2", "3", "4"]),
    ("Anzeige", "1A050193", "Scope: Kurvenart", "e", ["Flaeche", "Flaeche+Linie"]),
    ("Anzeige", "1A050197", "Scope: Wasserfall", "b", None),
    ("Anzeige", "1A050198", "Wasserfall-Geschwindigkeit", "e", ["langsam", "mittel", "schnell"]),
    ("Anzeige", "1A050199", "Wasserfall-Groesse", "e", ["klein", "mittel", "gross"]),
    # ---- CW und Suchlauf ----
    ("CW / Scan", "140C", "CW-Geschwindigkeit (0=6, 255=48 WPM)", "n", LV),
    ("CW / Scan", "1409", "CW-Tonhoehe (0=300, 255=900 Hz)", "n", LV),
    ("CW / Scan", "1A050221", "Mithoerton-Pegel", "n", LV),
    ("CW / Scan", "1A050222", "Mithoerton-Pegel begrenzen", "b", None),
    ("CW / Scan", "1A050223", "Keyer-Wiederholzeit (s)", "n", (1, 60, 1)),
    ("CW / Scan", "1A050224", "Punkt/Strich-Verhaeltnis (28=1:2,8 ... 45=1:4,5)", "n", (28, 45, 1)),
    ("CW / Scan", "1A050225", "Anstiegszeit", "e", ["2 ms", "4 ms", "6 ms", "8 ms"]),
    ("CW / Scan", "1A050226", "Paddle-Polaritaet", "e", ["normal", "umgekehrt"]),
    ("CW / Scan", "1A050227", "Tastenart", "e", ["Handtaste", "Bug", "Paddle"]),
    ("CW / Scan", "1A050228", "MIC Up/Down als Keyer", "b", None),
    ("CW / Scan", "1A050251", "Scan: Pausenzeit (10=Hold)", "n", (0, 10, 1)),
    ("CW / Scan", "1A050252", "Scan: Fortsetzzeit (6=Hold)", "n", (0, 6, 1)),
    ("CW / Scan", "1A050254", "Scan: Abstimmknopf bedienbar", "b", None),
    # ---- erst in der CI-V-Referenz von 2021 (neuere Firmware) ----
    ("Recorder / GPS", "1A050242", "QSO-Recorder: TX-Aufnahme", "e", ["direkt", "Monitor"]),
    ("Recorder / GPS", "1A050244", "QSO-Recorder: Datei teilen (File Split)", "b", None),
    ("Recorder / GPS", "1A050248", "QSO-Player: Sprungzeit", "e", ["3 s", "5 s", "10 s", "30 s"]),
    ("Recorder / GPS", "1A050267", "GPS D-PRS: Positions-Kommentar", "e", ["Kommentar 1", "Kommentar 2", "Kommentar 3", "Kommentar 4"]),
]

BY_KEY = {e[1]: e for e in ENTRIES}
GROUPS = list(dict.fromkeys(e[0] for e in ENTRIES))


def cmd_bytes(key):
    """'1A050027' -> (0x1A, 0x05, 0x00, 0x27); '1644' -> (0x16, 0x44)."""
    return tuple(bytes.fromhex(key))


def read_value(rig, key):
    """Wert lesen (int) oder None, wenn das Geraet ihn nicht kennt/ablehnt."""
    cmd = cmd_bytes(key)
    r = rig.civ(*cmd)
    if r[4] == 0xFA:
        return None
    d = bytes(r[4 + len(cmd):-1])
    return int(d.hex()) if d else None


def write_value(rig, key, value):
    """Wert schreiben (auf den erlaubten Bereich begrenzt); True bei OK."""
    _g, _k, _t, kind, spec = BY_KEY[key]
    cmd = cmd_bytes(key)
    if kind == "n":
        lo, hi, size = spec
    else:
        lo, hi, size = 0, (len(spec) - 1 if kind == "e" else 1), 1
    v = max(lo, min(hi, int(value)))
    data = bytes.fromhex(f"{v:04d}" if size == 2 else f"{v:02d}")  # CI-V-Daten sind BCD (z. B. 10 -> 0x10)
    return rig.civ(*cmd, *data)[4] == 0xFB
