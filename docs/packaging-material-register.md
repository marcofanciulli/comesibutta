# Registro UE dei materiali di imballaggio

Versione: 0.1.0
Ultimo aggiornamento: 7 agosto 2026

## Scopo

Il registro traduce in dati strutturati la Decisione 97/129/CE, CELEX
`31997D0129`. La decisione istituisce numeri e abbreviazioni che identificano
la natura dei materiali di imballaggio. Non stabilisce il cassonetto, il
sacchetto o la modalita di raccolta: questi restano regole territoriali.

## Fonti

In `data/sources/packaging-marks/` sono conservati:

- PDF italiano ufficiale EUR-Lex, che contiene gli allegati completi;
- HTML italiano ufficiale, che sostituisce le tabelle con segnaposto;
- testo ottenuto dal PDF con `pdftotext -layout`;
- trascrizione CSV controllata delle sole righe assegnate.

Il registro contiene l'impronta SHA-256 di ogni artefatto. L'importatore
verifica che tutte le 31 denominazioni trascritte compaiano nel testo estratto
dal PDF e rifiuta codici duplicati, famiglie incoerenti e compositi privi della
regola del materiale predominante.

Fonte ufficiale:
[Decisione 97/129/CE](https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:31997D0129).

## Costruzione

```sh
PYTHONPATH=src python3 -m dovelobutto.cli build-packaging-material-register \
  --transcription-csv data/sources/packaging-marks/31997D0129-it.csv \
  --source-pdf data/sources/packaging-marks/31997D0129-it.pdf \
  --source-html data/sources/packaging-marks/31997D0129-it.html \
  --extracted-text data/sources/packaging-marks/31997D0129-it.txt \
  --generated-at 2026-08-07T18:00:00+02:00 \
  --output outputs/packaging-material-register.json \
  --report outputs/packaging-material-register-report.json
```

Il risultato segue `schemas/packaging-material-register.schema.json`.

## Contenuto

La decisione assegna intervalli continui da 1 a 99:

| Famiglia | Intervallo | Assegnati |
| --- | ---: | ---: |
| Plastica | 1-19 | 6 |
| Carta e cartone | 20-39 | 3 |
| Metalli | 40-49 | 2 |
| Legno | 50-59 | 2 |
| Tessili | 60-69 | 2 |
| Vetro | 70-79 | 3 |
| Composti | 80-99 | 13 |

Il registro conserva tutti i 99 slot: 31 sono `assigned` e 68 sono
`unassigned`. Un numero non assegnato non viene interpretato per analogia.

Per i composti la fonte non impone una sigla fissa per ogni codice. Prescrive
`C/` seguito dall'abbreviazione del materiale predominante. Il registro salva
quindi la formula `C/{predominant_material_abbreviation}` e non inventa una
sigla universale.

## Transizione PPWR

Il Regolamento (UE) 2025/40 si applica in generale dal 12 agosto 2026 e prevede
etichette armonizzate per imballaggi e contenitori. L'obbligo parte dal 12
agosto 2028 oppure, se successiva, dalla scadenza calcolata sugli atti di
esecuzione. Il nuovo catalogo grafico non viene anticipato nel registro: sara
importato come schema versionato quando gli atti e gli asset ufficiali saranno
disponibili.

Fonti:
[Regolamento (UE) 2025/40](https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:32025R0040),
[orientamenti della Commissione 2026](https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=OJ:C_202603084).

## Limite grafico

La Decisione 97/129/CE definisce numeri e abbreviazioni, non un'unica geometria
grafica obbligatoria. Il detector deve quindi trovare una marcatura di
identificazione; OCR e parser riconciliano sigla e numero con il registro.
Triangoli, frecce e cornici sono varianti visive, non l'identita normativa.
