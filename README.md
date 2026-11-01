# icom-remote-cli

Kommandozeilen-Werkzeuge, um einen **Icom IC-9700** und einen **IC-705** direkt über das Netzwerk
(LAN bzw. WLAN) zu lesen und einzustellen – ohne wfview, ohne USB-Kabel, ohne virtuellen seriellen Port.
Nur Python 3 (Standardbibliothek), keine weiteren Pakete.

> Inoffiziell, kein Icom-Produkt. Das Netzwerkprotokoll ist proprietär und hier nach den Beschreibungen der
> Open-Source-Clients [kappanhang](https://github.com/nonoo/kappanhang) und wfview nachgebaut, nicht nach Icom-Quellcode.
> Benutzung auf eigene Gefahr. **Die Skripte senden nie** (kein PTT, keine Modulation).

## Voraussetzungen am Gerät

- **IC-9700:** MENU › SET › Connectors › Network: Netzwerk-Benutzer (ID + Passwort) anlegen, Gerät per LAN anschließen.
- **IC-705:** MENU › SET › WLAN SET › Remote Settings: *Network Control* einschalten, *Network User 1* (ID + Passwort) setzen.
- Das Gerät lässt **nur einen** Netzwerk-Client gleichzeitig zu: wfview, RS-BA1 u. ä. vorher beenden.
  Nach einem harten Abbruch (Strg+C) hält das Gerät die alte Sitzung kurz fest; der nächste Login kann einmal fehlschlagen.

## Einrichtung

```bash
cp ic9700.ini.example ic9700.ini     # und/oder
cp ic705.ini.example  ic705.ini
chmod 600 *.ini                      # Dateien enthalten ein Passwort, sie sind in .gitignore
$EDITOR ic9700.ini ic705.ini         # Host, Benutzer, Passwort eintragen
```

## icom_cli.py – was geht

Gerät wählen mit `-r 9700` (Vorgabe, oder Umgebungsvariable `ICOM_RADIO`) oder `-r 705`.

| Befehl | Wirkung |
|---|---|
| `status` | alles auslesen: Frequenz, Modus, Filter, S-Meter, Regler, Schalter, AGC, Versorgungsspannung, Sendestatus |
| `freq [WERT]` | Frequenz lesen bzw. setzen (`145.5M`, `1296.1M`, `7100k` oder Hz) |
| `mode [MODUS]` | Modus lesen bzw. setzen: LSB USB AM CW RTTY FM WFM CW-R RTTY-R (IC-9700 zusätzlich DV, DD) |
| `smeter [-n]` | S-Meter einmal bzw. laufend (`-n`), in dB relativ zu S9 und als Rohwert |
| `pegel` | S-Meter mit Frequenz: IC-9700 Main **und** Sub zusammen, IC-705 der eine Empfänger |
| `meters` | Po, SWR, ALC, COMP, Vd, Id (Po, SWR, ALC nur beim Senden sinnvoll) |
| `level NAME [WERT]` | Regler 0..255: `af rf sql power nr_level nb_level pbt1 pbt2 notch_pos cw_pitch cw_speed` |
| `switch NAME 0\|1` | Schalter: `preamp nb nr notch rit split sat att`, IC-9700 zusätzlich `extpre` (externer Vorverstärker) und `accsend` (ACC-SEND-Ausgang) für das Band des Empfängers |
| `agc [fast\|mid\|slow]`, `filter [1\|2\|3]`, `duplex [off\|dup-\|dup+]`, `rit [HZ]` | lesen bzw. setzen |
| `vfo a\|b\|equal\|exchange\|mem\|vfo` | VFO A/B, A=B, A<>B (über Lesen und Schreiben), Speicher-/VFO-Betrieb |
| `swap` | Main und Sub tauschen (IC-9700) |
| `atu [on\|off]` | IC-705: Antennentuner-Status (1C 01) lesen, ein- und ausschalten; ein Abstimmlauf fehlt bewusst, weil er sendet |
| `scan stop\|prog\|mem\|select\|modesel\|df [--span 1..7]\|resume-on\|resume-off` | Scan starten und stoppen; ob gerade gescannt wird, lässt sich per CI-V nicht lesen |
| `mem list\|recall\|write GRUPPE KANAL [LETZTER]` | Speicherkanäle anzeigen (`list`; `write` kann auch `--offset`, `--ur`, `--r1`, `--r2` für D-STAR), ins VFO laden (`recall`), schreiben (`write`, ohne `--ja` nur Vorschau, der alte Inhalt wird protokolliert). IC-9700: Band 144, 430 oder 1296; IC-705: Speichergruppe 0-99 |
| `config list [GRUPPE] [--werte]` | die 138 Menüeinstellungen (CI-V 1A 05) nach Gruppen, mit `--werte` samt aktuellem Wert; Liste in `konfiguration_liste.md` |
| `config get SCHLÜSSEL` / `config set SCHLÜSSEL WERT` | eine Einstellung lesen bzw. setzen (IC-9700), z. B. `config set 1A050027 5` |
| `scope edges [BAND]` / `scope edge BAND NR VON BIS` | feste Scope-Bereiche (SCOPE > Fixed Edges) je Band No.1-4 lesen bzw. setzen (IC-9700; ohne `--ja` nur Vorschau) |
| `serve [--port P] [--bind IP]` | **rigctld-Server** (Hamlib *NET rigctl*, Modell 2) für WSJT-X, Logbuch- und Rotorprogramme, Vorgabe Port 4532, nur lokal |

`-2mmin` stellt vor dem Befehl 144,300 MHz und die Sendeleistung auf Minimum ein (sendet nicht; Modus bleibt), z. B. `./icom_cli.py -r 705 -2mmin status`.

Nur IC-9700: `--rx main\|sub` wählt den Empfänger für den Befehl. `--host IP` überschreibt den Host aus der ini-Datei.

```bash
./icom_cli.py -r 705 status
./icom_cli.py -r 705 freq 145.5M
./icom_cli.py -r 9700 --rx sub mode FM
./icom_cli.py -r 9700 pegel
./icom_cli.py -r 705 smeter -n
./icom_cli.py -r 9700 level af 120
```

## rigctld-Server (`serve`)

```bash
./icom_cli.py -r 705 serve --port 4532          # nur lokal (127.0.0.1)
./icom_cli.py -r 9700 --rx sub serve --port 4533 --bind 0.0.0.0   # im ganzen Netz, anderer Empfänger
rigctl -m 2 -r localhost:4532 f                 # Test: Frequenz lesen
```

In WSJT-X / Log-Programmen als Rig *Hamlib NET rigctl* mit `localhost:4532` einstellen. Unterstützt: Frequenz und Modus
lesen/setzen, S-Meter (`l STRENGTH`), AF/RF/SQL/Leistung. Bedient wird ein Empfänger (beim IC-9700 der mit `--rx` gewählte).
**Senden ist gesperrt:** `T 1` wird mit einem Fehler abgelehnt. Mit der Offline-Prüfung (Schein-Gerät + `rigctl`) getestet,
am echten Gerät noch nicht. Mit `--bind 0.0.0.0` kann jeder im Netz Frequenz und Modus verstellen.

## Weitere Dateien

- `ic9700_rigctld.py` – der rigctld-Server (Hamlib-Protokoll), von `serve` benutzt.

- `ci-v_ic705.md` – CI-V-Funktionen des IC-705 im Vergleich zum IC-9700 (Unterschiede, was im CLI drin ist).
- `ci-v_funktionen.md` – alle CI-V-Funktionen des IC-9700, gruppiert, mit Stand der Umsetzung.
- `konfiguration_liste.md` – die 138 Menüeinstellungen (Schlüssel und Bezeichnung).
- `ic9700_ctl.py`, `ic9700_setup.py`, `ic9700_mem.py` – Schalter/Regler, Menüeinstellungen und Speicherkanäle des IC-9700.
- `pegel_lan.py` – ältere Kommandozeile für Main/Sub-Pegel des IC-9700 (`-n` laufend, `--retune sub 144.3M`).
- `ic9700_lan.py` – Bibliothek `LanRig` (Handshake, Login, CI-V über UDP 50001/50002, Audio 50003).
- `pegel2.py` – CI-V-Hilfsfunktionen (Frequenz, S-Meter, Umrechnung in dB).

## Hinweise

- Der IC-9700 schaltet beim Lesen von Sub kurz zwischen Main und Sub um; danach steht das vorher gewählte Band wieder.
- Der IC-705 hat nur einen Empfänger (CI-V-Adresse 0xA4, IC-9700: 0xA2).
- Getestet am IC-9700: Lesen aller Werte, VFO A/B und A<>B, Swap, Scan stoppen, ATT und externer Vorverstärker, Speicher lesen. Am IC-705 wurden nur Lesen sowie Frequenz, Modus und Regler geprüft; die übrigen Befehle sind für den IC-9700 geschrieben und können dort abgelehnt werden. Scan-Start, SAT und V/M sind nicht ausprobiert. `mem recall` am IC-9700 geprueft, `mem write` nur als Vorschau; am IC-705 sind alle `mem`-Befehle ungeprueft.

Lizenz: MIT
