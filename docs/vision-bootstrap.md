# Bootstrap visivo delle marcature

Versione: 0.1.0
Ultimo aggiornamento: 7 agosto 2026

## Risultato

Il bootstrap contiene 206 immagini locali:

- 20 pagine di riferimento, dalla pagina numerata 20 alla 39 delle Linee guida
  adottate con DM 360/2022;
- 186 varianti sintetiche: sei per ciascuno dei 31 codici assegnati dalla
  Decisione 97/129/CE.

Le immagini sintetiche hanno un riquadro e una trascrizione esatti. Sono 150
nel training e 36 nella validazione; le 20 pagine documentali restano nel
training come riferimento non annotato. Nessuna immagine sintetica o
documentale entra nel test di rilascio.

Il manifest e `outputs/vision-bootstrap-manifest.json`; il rapporto e
`outputs/vision-bootstrap-report.json`. Le immagini, circa 6 MB, sono generate
in `data/vision/assets/` e non sono conservate in Git: verranno affidate a DVC
quando sara scelto il deposito remoto.

## Fonti

Sono conservati in `data/sources/packaging-labeling/`:

- decreto MASE 360/2022, tre pagine;
- allegato tecnico adottato, 48 pagine, nella copia integrale pubblicata dal
  portale Etichetta CONAI;
- testo estratto da entrambi i documenti;
- note legali MASE che indicano CC BY 4.0 salvo diversa indicazione;
- Noto Sans e relativa SIL Open Font License 1.1.

Il decreto disponibile all'URL MASE non incorpora materialmente le 48 pagine
dell'allegato. Manifest e rapporto mantengono quindi separati URL, ruoli e
SHA-256 del provvedimento e della copia integrale dell'allegato.

## Generazione

Richiede Poppler e l'extra Python `vision`:

```sh
python3 -m pip install -e '.[vision]'
```

```sh
PYTHONPATH=src python3 -m dovelobutto.cli build-vision-bootstrap \
  --register outputs/packaging-material-register.json \
  --taxonomy data/vision/taxonomy-v1.json \
  --guidelines-pdf data/sources/packaging-labeling/dm-360-2022-adopted-guidelines-it.pdf \
  --decree-pdf data/sources/packaging-labeling/dm-360-2022-guidelines-it.pdf \
  --legal-notice-pdf data/sources/packaging-labeling/mase-legal-notice.pdf \
  --font data/sources/packaging-labeling/NotoSans-variable.ttf \
  --assets-root data/vision/assets \
  --generated-at 2026-08-07T20:00:00+02:00 \
  --manifest outputs/vision-bootstrap-manifest.json \
  --report outputs/vision-bootstrap-report.json
```

La generazione e deterministica rispetto a sorgenti, font, tassonomia e codice.
Le marcature composte usano forme plausibili come `C/PAP`, `C/GL` e diverse
abbreviazioni plastiche. Sono esempi per detector e OCR, non dichiarazioni sulla
composizione di un prodotto reale.

## Limiti

Le pagine ministeriali documentano esempi e non definiscono un unico aspetto
grafico obbligatorio. Le varianti sintetiche non riproducono superficie,
curvatura, stampa, sporco e illuminazione di un imballaggio reale. Questo
bootstrap serve a collaudare pipeline, OCR e annotazioni, ma non autorizza il
rilascio del modello fotografico.
