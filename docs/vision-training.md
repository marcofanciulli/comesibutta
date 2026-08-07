# Addestramento del detector visivo

Versione: 0.1.0-bootstrap
Ultimo aggiornamento: 7 agosto 2026
Stato: esperimento tecnico, non distribuibile

## Scopo

Il primo addestramento verifica l'intera pipeline PyTorch del detector: lettura
del manifest, conservazione delle bounding box, addestramento, checkpoint,
valutazione a soglie multiple e controllo visivo. Non misura ancora il
riconoscimento su confezioni reali.

Il corpus usato comprende 150 immagini sintetiche annotate per il training e
36 per la validazione. Le 20 pagine MASE prive di bounding box sono escluse. La
sola classe osservata e `mark.material_identification`; le altre quattro classi
della tassonomia restano senza esempi e quindi non sono ancora addestrate.

## Ambiente riproducibile

L'ambiente separato si prepara con Python 3.12 e il lock file conservato nel
repository:

```sh
python3.12 -m venv .vision-venv
.vision-venv/bin/pip install -r requirements/vision-training.lock.txt
```

Il modello e `SSDLite320 MobileNetV3 Large` di torchvision. Usa i pesi ImageNet
V2 del backbone, congelato in questa prima prova, e una testa di rilevamento per
le cinque classi della tassonomia piu lo sfondo.

## Riproduzione

```sh
PYTHONPATH=src .vision-venv/bin/python -m dovelobutto.cli \
  train-vision-bootstrap \
  --manifest outputs/vision-bootstrap-manifest.json \
  --taxonomy data/vision/taxonomy-v1.json \
  --assets-root data/vision/assets \
  --output-dir outputs/models/packaging-mark-bootstrap-v0.1.0 \
  --generated-at 2026-08-07T21:00:00+02:00 \
  --epochs 3 --batch-size 4 --learning-rate 0.001 \
  --seed 20260807 --device cpu

PYTHONPATH=src .vision-venv/bin/python -m dovelobutto.cli \
  evaluate-vision-checkpoint \
  --checkpoint outputs/models/packaging-mark-bootstrap-v0.1.0/model.pt \
  --manifest outputs/vision-bootstrap-manifest.json \
  --taxonomy data/vision/taxonomy-v1.json \
  --assets-root data/vision/assets \
  --output-dir outputs/models/packaging-mark-bootstrap-v0.1.0 \
  --generated-at 2026-08-07T21:10:00+02:00
```

Su CPU Apple Silicon l'addestramento di tre epoche ha richiesto 173 secondi.
La loss media e scesa da 6,891 a 2,650. Sulle sole immagini sintetiche, la
soglia 0,4 massimizza F1 a 0,500, con precisione 0,571 e recall 0,444 a IoU
0,5. La soglia 0,3 privilegia invece il richiamo: recall 0,806 e precisione
0,290.

I risultati completi sono in `training-report.json` e
`evaluation-report.json`; `validation-preview.png` sovrappone in verde le
annotazioni e in rosso le predizioni. Il checkpoint `model.pt` pesa circa
15,4 MB, ha SHA-256
`9998b9c14d436ac1c99ea20e8dc92a670a41bc45050ed658e8a61034a96a38e7` e
resta locale per evitare di appesantire Git. Prima di condividere modelli verra
introdotto lo storage DVC previsto dall'architettura.

## Limiti e criterio di avanzamento

Queste metriche servono soltanto come controllo tecnico: train e validation
derivano dallo stesso generatore e non rappresentano illuminazione, pieghe,
riflessi, usura, sfondi o fotocamere reali. Il checkpoint non deve essere
esportato in Core ML o LiteRT come modello di rilascio.

Il passo successivo e importare fotografie classificate col prontuario,
separarle per confezione e sessione di scatto, annotarle in CVAT e creare un
test reale mai usato per scegliere modello o soglia. Solo quel test potra
sostenere una decisione di rilascio.
