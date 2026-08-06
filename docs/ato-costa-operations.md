# Operazioni ATO Toscana Costa

Versione: 0.1.0  
Ultimo aggiornamento: 6 agosto 2026

## Perimetro e registro

ATO Toscana Costa comprende 100 comuni: 13 in provincia di Livorno, 33 di
Lucca, 17 di Massa-Carrara e 37 di Pisa. RetiAmbiente e il gestore unico; il
servizio e svolto attraverso 12 societa operative locali (SOL).

La fonte ufficiale 2026 e conservata in
`data/sources/ato-toscana-costa/`. Il CSV normalizzato mantiene le 100 righe e
gli stati particolari di Porto Azzurro, Peccioli e Lucca. Il registro si genera
con:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli build-ato-costa-registry \
  --assignment-csv data/sources/ato-toscana-costa/municipalities-sol-2026.csv \
  --istat-csv data/sources/istat/toscana-comuni-2026-02-21.csv \
  --retrieved-at 2026-08-06T14:00:00+02:00 \
  --output outputs/ato-toscana-costa-municipalities.jsonl \
  --report outputs/ato-toscana-costa-municipalities-report.json
```

L'alias ufficiale ATO `Vagli di Sotto` viene riconciliato esplicitamente con
la denominazione ISTAT `Vagli Sotto`.

## ESA

Le due pagine condivise ESA contengono 292 coppie nome-destinazione, le regole
generali porta a porta e l'indice dei centri. Sono materializzate per i sette
comuni dell'Elba, associando a ciascuno soltanto i propri centri. Gli snapshot
live restano in `data/crawl/`, escluso da Git; output e rapporti sono
riproducibili con `materialize-esa`.

## REA

Il rifiutario REA e dinamico. `fetch-rea-rifiutario` controlla `robots.txt`,
interroga serialmente le 26 iniziali e produce un JSON sorgente e un rapporto.
La passata verificata ha trovato 190 voci, sei iniziali senza risultati e zero
errori. Sette voci approvate non hanno una destinazione: vengono conservate con
`resolution_status: missing_destination`, non scartate.

`materialize-rea-rifiutario` applica il dizionario ai 17 comuni REA, producendo
190 record e un avviso riepilogativo per comune. I dati comunali su centri,
calendari, sacchetti e ritiri richiedono un estrattore successivo.

## AAMPS

La guida AAMPS di Livorno e un PDF del 2017 a due colonne. Il comando esterno:

```sh
pdftotext -bbox-layout dove-lo-butto.pdf dove-lo-butto-bbox.html
```

preserva le coordinate necessarie. `materialize-aamps-rifiutario` ricostruisce
125 coppie. Cinque righe con probabili continuazioni di colonna restano a
confidenza media e sono elencate nel rapporto; non vengono corrette a mano.

## Copertura corrente

- 100 comuni censiti;
- 25 comuni con almeno una fonte acquisita: 7 ESA, 17 REA e Livorno AAMPS;
- 5.461 record ATO Costa;
- tutti i 13 comuni livornesi hanno almeno un rifiutario acquisito;
- soltanto ESA dispone gia di regole generali e centri materializzati.

Prossimo ordine operativo: pagine comunali e centri REA, dettagli dei centri
ESA, fonti AAMPS aggiornate, quindi GEOFOR, ASCIT e le restanti SOL.
