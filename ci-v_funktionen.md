# IC-9700: CI-V-Funktionen und Stand in der GUI

Quelle: IC-9700 CI-V Reference Guide (Befehlstabelle). Stand der GUI: 2026-11-01.
"ja" = in `gui_ic9700.py` eingebaut, "nein" = noch nicht.

| Gruppe | Befehl | Was es kann | In der GUI |
|---|---|---|---|
| **Frequenz / Modus** | 00, 03, 05 | Frequenz lesen und setzen | ja |
| | 01, 04, 06 | Modus lesen und setzen (inkl. DV, DD), Filter 1-3 | ja |
| | 02 | Bandkanten lesen | nein |
| | 25, 26 | Frequenz und Modus des nicht gewaehlten VFO lesen und setzen | nein |
| | 10 | Abstimmschritt | nur in der GUI selbst |
| | 1C 03, 1E | Sendefrequenz und TX-Bandkanten lesen | nein |
| **VFO / Band** | 07 00, 01, A0 | VFO A/B, A=B (A<>B ueber Lesen und Schreiben) | ja |
| | 07 B0, D0, D1, D2 | Main/Sub tauschen, waehlen, lesen | ja |
| | 08 | Speichermodus und Kanal waehlen | V/M ja, Kanalwahl nein |
| | 16 59, 16 5A | Dualwatch, Satellitenmodus | SAT ja, Dualwatch nein |
| **Speicher** | 08, 09, 0A, 0B | Kanal waehlen, schreiben, ins VFO kopieren, loeschen | Lesen und Schreiben ja |
| | 1A 00, 1A 01 | Speicherinhalt, Band-Stacking-Register | Speicher ja, Stacking nein |
| **Scan** | 0E | Programm-, Speicher-, Select-, dF-, Mode-Select-Scan, Stopp, Fortsetzung | ja (Menue Scan) |
| **Split / Duplex** | 0F | Split ein/aus, DUP-, DUP+, Simplex, DD-RPS | ja (Split, DUP+/-) |
| | 0C, 0D | Ablagefrequenz lesen und setzen | nein |
| | 16 42, 43, 4B, 1B 00-02 | Ton, Tonsquelch, DTCS, Tonfrequenzen | nein |
| | 21 | RIT ein/aus und Offset | ja |
| **Empfang: Schalter** | 16 02 | Preamp (inkl. extern) | ja |
| | 11 | Daempfer 0/10 dB | ja (ATT) |
| | 16 12 | AGC | ja |
| | 16 22, 40, 41, 48, 57 | NB, NR, Auto-Notch, manuelles Notch, Notch-Breite | NB, NR, Notch ja |
| | 16 4F, 56 | Twin-Peak-Filter, Filtertyp | nein (Filtertyp ueber Konfiguration) |
| | 16 4A | AFC | ueber Konfiguration |
| **Empfang: Regler** | 14 01-03, 06, 12 | AF, RF, Squelch, NR-Pegel, NB-Pegel | ja |
| | 14 07, 08, 0D | PBT 1/2, Notch-Lage | ja (Feineinstellung) |
| | 14 09 | CW-Tonhoehe | ja (Feineinstellung) |
| | 1A 03, 1A 04 | Filterbreite, AGC-Zeitkonstante | nein |
| **Senden: Regler** | 14 0A, 0B, 0E | HF-Leistung, Mikrofon, COMP-Pegel | Leistung und Mikrofon ja |
| | 14 15-17 | Monitor-Pegel, VOX-Gain, Anti-VOX | ueber Konfiguration |
| | 16 44-47, 58 | Kompressor, Monitor, VOX, BK-IN, SSB-Sendebandbreite | ueber Konfiguration |
| | 1C 00 | Senden/Empfangen lesen und PTT setzen | ja |
| | 1C 02 | Sendefrequenz-Monitor | nein |
| **CW** | 17 | CW-Text senden | ja (CW-Fenster) |
| | 14 0C, 0F | Tempo, Break-in-Verzoegerung | Tempo ja (Feineinstellung), Verzoegerung ueber Konfiguration |
| | 1A 02 | Speichertasten (Keyer) | nein |
| **Sprache** | 28 | Sprachspeicher senden (1-8) | ja |
| | 13 | Sprachausgabe von Frequenz, S-Meter, Modus | nein |
| **Messwerte** | 15 01, 02, 05, 07 | Squelch offen, S-Meter, Rauschsquelch, Uebersteuerung | S-Meter ja |
| | 15 11-16 | Po, SWR, ALC, COMP, Vd, Id | ja |
| **Scope** | 27 00-1E | Scope-Daten, Ein/Aus, Mitte/Fix, Span, Referenzpegel, Hold, Randfrequenzen | ja |
| **D-STAR / DV / DD** | 1F 00-02 | MY-Rufzeichen, UR/R1/R2, TX-Nachricht | ja |
| | 20, 22 | DV-Empfangsdaten (Rufzeichen, Nachricht, GPS), DV-Sendedaten | nein |
| **GPS** | 23 | GPS-Position lesen, GPS-Quelle, manuelle Position | nein |
| **Geraet** | 18 00, 01 | Aus- und Einschalten | nein |
| | 19 00 | Geraete-ID lesen | nein |
| | 24 | Sendeleistung-Ausgabe fuer Transceive | nein |
| | 1A 05 | ueber 600 Menueeinstellungen | 134 davon in der Konfiguration (siehe konfiguration_liste.md) |
| **Nicht per CI-V** | - | Gehaeuse-Temperatur, Menueanzeige, AUTO TUNE, SD-Karte, Bildschirmfoto | - |
