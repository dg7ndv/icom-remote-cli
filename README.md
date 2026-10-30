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
| `status` | alles auslesen: Frequenz, Modus, Filter, S-Meter, Regler (AF, RF, SQL, Leistung, NR, NB), Schalter (Preamp, NB, NR, Notch), AGC, Versorgungsspannung, Sendestatus |
| `freq [WERT]` | Frequenz lesen bzw. setzen (`145.5M`, `1296.1M`, `7100k` oder Hz) |
| `mode [MODUS]` | Modus lesen bzw. setzen: LSB USB AM CW RTTY FM WFM CW-R RTTY-R (IC-9700 zusätzlich DV, DD) |
| `smeter [-n]` | S-Meter einmal bzw. laufend (`-n`), in dB relativ zu S9 und als Rohwert |
| `pegel` | S-Meter mit Frequenz: IC-9700 Main **und** Sub zusammen, IC-705 der eine Empfänger |
| `level NAME [WERT]` | Regler lesen/setzen 0..255: `af rf sql power nr_level nb_level` |
| `switch NAME 0\|1` | Schalter: `preamp nb nr notch` |

Nur IC-9700: `--rx main\|sub` wählt den Empfänger für den Befehl. `--host IP` überschreibt den Host aus der ini-Datei.

```bash
./icom_cli.py -r 705 status
./icom_cli.py -r 705 freq 145.5M
./icom_cli.py -r 9700 --rx sub mode FM
./icom_cli.py -r 9700 pegel
./icom_cli.py -r 705 smeter -n
./icom_cli.py -r 9700 level af 120
```

## Weitere Dateien

- `pegel_lan.py` – ältere Kommandozeile für Main/Sub-Pegel des IC-9700 (`-n` laufend, `--retune sub 144.3M`).
- `ic9700_lan.py` – Bibliothek `LanRig` (Handshake, Login, CI-V über UDP 50001/50002, Audio 50003).
- `pegel2.py` – CI-V-Hilfsfunktionen (Frequenz, S-Meter, Umrechnung in dB).

## Hinweise

- Der IC-9700 schaltet beim Lesen von Sub kurz zwischen Main und Sub um; danach steht das vorher gewählte Band wieder.
- Der IC-705 hat nur einen Empfänger (CI-V-Adresse 0xA4, IC-9700: 0xA2).
- Getestet mit IC-9700 und IC-705 im eigenen Netz; Setzen von Frequenz, Modus und Reglern wurde am Gerät geprüft.

Lizenz: MIT
