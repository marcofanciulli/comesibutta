# Riconoscimento visivo degli imballaggi

Versione: 0.1.0
Ultimo aggiornamento: 7 agosto 2026

## Principio

Il riconoscimento avviene sul dispositivo e produce osservazioni, non regole di
conferimento. Il materiale riconosciuto viene risolto nel registro normativo e
soltanto dopo combinato con comune, zona e regola locale.

La pipeline usa un solo modello PyTorch sorgente e genera due artefatti:

- Core ML `mlpackage` per iOS;
- LiteRT `tflite` per Android.

Dataset, tassonomia, preprocessing, output e corpus di verifica sono condivisi.
Le ottimizzazioni binarie possono essere specifiche della piattaforma.

## Contratti

- `schemas/vision-model-contract.schema.json`: input, output, soglie e artefatti;
- `examples/vision-model-contract.json`: contratto iniziale a 640 x 640;
- `schemas/visual-recognition-observation.schema.json`: risultato di detector,
  OCR, parser e risoluzione normativa.

Le coordinate delle bounding box sono normalizzate in formato `xyxy`. Ogni
osservazione dichiara modello, tassonomia, runtime e SHA-256 dell'artefatto.

## Pipeline

1. Il detector individua le regioni con marcature.
2. Classifica la famiglia generale del segno.
3. OCR nativo legge abbreviazioni, numeri e istruzioni.
4. Un parser deterministico confronta i token con il registro.
5. Il client richiede conferma per risultati ambigui o sotto soglia.
6. Il motore territoriale determina il conferimento.

Le famiglie iniziali sono:

- identificazione del materiale;
- istruzione di raccolta;
- prodotto regolamentato;
- dichiarazione ambientale;
- certificazione o sistema consortile;
- segno sconosciuto.

Il modello non deve apprendere che `PET 1` significa un particolare cassonetto.

## Addestramento ed esportazione

Il checkpoint autorevole e PyTorch. La conversione Core ML usa Core ML Tools
direttamente dal modello PyTorch; la conversione LiteRT usa AI Edge Torch. ONNX
puo essere prodotto per diagnosi, ma non e la sorgente di rilascio.

Documentazione ufficiale:
[conversione PyTorch con Core ML Tools](https://apple.github.io/coremltools/docs-guides/source/convert-pytorch.html),
[conversione PyTorch con AI Edge Torch](https://ai.google.dev/edge/litert/models/convert_pytorch).

Ogni build deve superare:

- conversione in entrambi i formati;
- confronto sullo stesso corpus di immagini;
- equivalenza di classi e bounding box entro tolleranze dichiarate;
- benchmark di latenza, memoria e dimensione su dispositivi reali;
- verifica delle soglie di conferma;
- firma, manifest, installazione e rollback.

## Dataset e annotazione

Le immagini e le annotazioni saranno versionate separatamente dal codice con
DVC e object storage. CVAT e lo strumento iniziale di annotazione. Ogni immagine
deve avere licenza o consenso, origine, condizioni di acquisizione e split
stabile tra addestramento, validazione e test.

Le annotazioni descrivono la regione e la famiglia del segno. Sigla e numero
restano target OCR; il codice normativo risolto e un risultato del parser.
Tassonomia, provenienza, licenze, privacy, split e istruzioni operative sono
definiti in `docs/vision-corpus.md`.

## Privacy e aggiornamenti

L'immagine non viene conservata per impostazione predefinita e il contratto
imposta `image_retention: not_retained`. L'eventuale invio volontario per
migliorare il modello richiedera un consenso separato.

Ogni app include un modello di base e puo scaricare un modello piu recente con
manifest firmato, hash, versione della tassonomia, versione minima dell'app e
rollback. Database e modello hanno revisioni indipendenti: una nuova tassonomia
puo richiedere entrambi, e il manifest deve dichiararne la compatibilita.
