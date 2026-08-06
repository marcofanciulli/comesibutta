# Registro ufficiale EER

Versione: 0.1.0
Ultimo aggiornamento: 6 agosto 2026

## Fonti e validita

Il registro italiano deriva esclusivamente da tre documenti EUR-Lex conservati
in `data/sources/eer/`:

- testo consolidato della decisione 2000/532/CE al 6 dicembre 2023,
  CELEX `02000D0532-20231206`;
- decisione delegata (UE) 2025/934, CELEX `32025D0934`;
- rettifica del 19 agosto 2025, CELEX `32025D0934R(01)`.

La decisione 2025 pubblicata originariamente indicava il 9 novembre 2026. La
rettifica sostituisce tale data con il **9 dicembre 2026**. Il dataset viene
distribuito subito come edizione futura con `valid_from: 2026-12-09`; l'app non
deve presentarlo come gia applicabile prima di quel giorno.

Ogni fonte e immutabile e accompagnata dalla propria impronta SHA-256 nel
registro generato.

## Costruzione

```sh
PYTHONPATH=src python3 -m dovelobutto.cli build-eer-register \
  --base-html data/sources/eer/02000D0532-20231206-it.html \
  --amendment-html data/sources/eer/32025D0934-it.html \
  --corrigendum-html data/sources/eer/32025D0934R01-it.html \
  --input-dir outputs/sei-toscana \
  --input-dir outputs/ato-toscana-costa \
  --generated-at 2026-08-06T23:00:00+02:00 \
  --output outputs/eer-register.json \
  --report outputs/eer-register-report.json
```

Il parser legge la tabella consolidata, applica sostituzioni, inserimenti e
soppressioni dell'atto 2025 e ricava la data corretta dalla rettifica. Non usa
un elenco di codici trascritto manualmente.

## Contenuto

Il risultato segue `schemas/eer-register.schema.json` e contiene:

- 20 capitoli e 112 sottocapitoli;
- 880 voci EER nell'edizione futura;
- codice a sei cifre, codice visuale, titolo italiano e flag di pericolosita;
- collegamenti stabili a capitolo e sottocapitolo;
- rinvii ad altre voci con titolo e pericolosita espansi;
- quattro voci ritirate con ultimo giorno di validita;
- confronto riproducibile con la base: 42 aggiunte e 6 modifiche.

La fonte consolidata contiene un rinvio non risolvibile: `11 01 12` cita la
voce inesistente `10 01 11`. Il rapporto lo segnala senza trasformarlo
arbitrariamente in un altro codice.

## Confronto con i centri

Sono state controllate 6.266 indicazioni di conferimento dotate o meno di EER:

- 5.646 indicazioni usano codici presenti nell'edizione futura;
- 252 usano `20 01 33` o `20 01 34`, validi oggi ma ritirati dal 9 dicembre;
- nessun codice normalizzato risulta sconosciuto;
- 368 indicazioni non pubblicano un codice, soprattutto nelle pagine REA, e
  restano distinte dai codici errati.

Il rapporto non tratta i codici ritirati come errori attuali. Sono transizioni
future che richiederanno una nuova acquisizione delle fonti dei gestori vicino
alla data di applicazione.
