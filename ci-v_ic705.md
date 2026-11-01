# IC-705: CI-V-Funktionen im Vergleich zum IC-9700

Quelle: `IC-705_ENG_CI-V_1_20200721.pdf` (Befehlstabelle), gelesen als Text. Stand CLI: `icom_cli.py -r 705`, 2026-11-01.
Wo "gleich" steht, habe ich Befehlsnummer und Beschreibung in beiden Tabellen verglichen, nicht jedes Datenformat Byte fuer Byte.
"CLI" = in `icom_cli.py` eingebaut. "gleich" = Befehl und Daten wie beim IC-9700 (siehe `ci-v_funktionen.md`).
Am echten IC-705 geprueft sind nur: Frequenz, Modus, S-Meter, AF/RF/SQL/Leistung, Preamp, NB/NR/Notch (lesen), Vd, `1A 0B`.

| Gruppe | Befehl | IC-705 | Unterschied zum IC-9700 | CLI |
|---|---|---|---|---|
| **Frequenz / Modus** | 00, 03, 05 | Frequenz lesen/setzen | gleich | ja |
| | 01, 04, 06 | Modus lesen/setzen | kein DD; Modi: LSB USB AM CW RTTY FM WFM CW-R RTTY-R DV | ja |
| | 02 | Bandkanten lesen | gleich | nein |
| | 10 | Abstimmschritt 00..13 | zusaetzlich 8,33 und 9 kHz | nein |
| **VFO** | 07 00, 01, A0 | VFO A/B, A=B | gleich | ja |
| | 07 B0 | **VFO A und B tauschen** | beim IC-9700 tauscht B0 Main und Sub | ja (`vfo exchange` nutzt es) |
| | 08, 08 A0 | Speichermodus, Kanal 0000-0099, Speichergruppe | andere Kanalzaehlung als beim IC-9700 | `vfo mem` ja, Kanalwahl nein |
| | 09, 0A, 0B | Speicher schreiben, ins VFO, loeschen | gleich | nein |
| **Scan** | 0E | Programm-, Speicher-, Select-, dF-, Mode-Select-Scan, Stopp | gleich | ja (`scan`) |
| **Split / Duplex** | 0F | Split, DUP-, DUP+, Simplex | kein DD-Repeater-Simplex | ja |
| | 0C, 0D | Ablage lesen/setzen | gleich | nein |
| | 21 00, 01, 02 | RIT, RIT ein/aus, **dTX** | dTX gibt es zusaetzlich | RIT ja, dTX nein |
| **Empfang** | 11 | Daempfer: **0 oder 20 dB**, nur KW und 50 MHz | beim IC-9700 10 dB | ja (`switch att`, Code 0x20) |
| | 16 02 | Preamp: 00 aus, 01 P.AMP1, 02 P.AMP2; auf 144/430 nur 00/01 | IC-9700 hat 00-03 (mit externem) | ja (an/aus) |
| | 16 12 | AGC | gleich | ja |
| | 16 22, 40, 41, 48, 57 | NB, NR, Auto-Notch, manuelles Notch, Breite | gleich | NB, NR, Notch ja |
| | 14 01-03, 06, 12 | AF, RF, SQL, NR-Pegel, NB-Pegel | gleich | ja |
| | 14 07, 08, 0D | PBT 1/2, Notch-Lage | gleich laut Datei; am Geraet im Modus FM abgelehnt ("-") | ja |
| | 14 09, 0C | CW-Tonhoehe, Tempo | gleich | ja |
| | 1A 03, 1A 04 | Filterbreite, AGC-Zeit | gleich | nein |
| **Senden** | 14 0A | HF-Leistung des gewaehlten Bandes | gleich; Maximum **10 W extern, 5 W Akku** | ja (Watt-Anzeige) |
| | 14 0B, 0E, 0F, 15-17 | Mikrofon, COMP, Break-in, Monitor, VOX | gleich | nein (Konfiguration beim IC-9700) |
| | 1C 00 | Senden/Empfangen | gleich | lesen ja |
| | **1C 01** | **Antennentuner: 00 aus, 01 an, 02 Abstimmlauf** | nur IC-705 | `atu` (lesen, an, aus; **kein** Abstimmlauf, der sendet) |
| **CW** | 17 | CW-Text senden | gleich | nein (sendet) |
| **Messwerte** | 15 02, 07, 11-14 | S-Meter, Uebersteuerung, Po, SWR, ALC, COMP | gleich | ja |
| | **15 15** | **Vd: 0=0 V, 75=5 V, 241=16 V** | IC-9700: 13=10 V, 241=16 V | ja (eigene Skala) |
| | **15 16** | **Id: 121=2 A, 241=4 A** | IC-9700: 10 A / 20 A | ja (eigene Skala) |
| **Stromversorgung** | **1A 0B** | **00 extern, 01 Akku** | nur IC-705 | ja (Zeile `Versorgung`) |
| **Speicher** | 1A 00, 1A 01 | Speicherinhalt, Band-Stacking | Datenformat weicht ab | nein |
| **Scope** | 27 xx | Scope-Daten, Span, Referenz, Hold ... | aehnlich; Sweep-Speed (27 1A) zusaetzlich | nein |
| **Sprache** | 13, 28 | Sprachausgabe, Sprachspeicher | gleich | nein |
| **D-STAR** | 1F, 20, 22 | Rufzeichen, DV-Empfangsdaten | gleich; kein DD | nein |
| **GPS** | 23 | Position lesen/setzen | IC-705 hat eingebautes GPS | nein |
| **Geraet** | 18 00, 01 | Aus-/Einschalten | gleich | nein |
| | 19 00 | Geraete-ID | A4 statt A2 | ja (Verbindungstest) |
| | 1A 05 | Menueeinstellungen | andere Nummern als beim IC-9700, Tabelle nicht uebernommen | **nein** |
| **Nur IC-9700** | - | Sub-Empfaenger (07 D0/D1), Satellitenmodus, Dualwatch, externer Vorverstaerker, ACC-SEND je Band | beim IC-705 nicht vorhanden | `config`, `swap`, `sat`, `extpre`, `accsend` dort gesperrt |

## Wichtig fuer das CLI am IC-705

- **`config list/get/set`** gilt nur fuer den IC-9700: Die Menue-Nummern (1A 05 xxxx) sind beim IC-705 andere.
- **Antennentuner:** Ein Abstimmlauf (`1C 01 02`) sendet einen Traeger. Das CLI sendet nie; deshalb nur lesen, ein- und ausschalten.
- **Watt-Anzeige:** 0,5 W bis 10 W extern (13,8 V), bis 5 W mit Akku (BP-272), laut Datenblatt.
