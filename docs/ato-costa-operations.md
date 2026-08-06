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

`fetch-rea-services` parte dalle 17 schede comunali e dall'indice dei centri,
segue soltanto servizi e allegati pubblicati da REA, rispetta `robots.txt` e
salva un manifesto completo. Se il manifesto esiste, la ripresa riusa gli
snapshot riusciti e visita soltanto le nuove URL. La passata verificata ha
controllato 425 URL: 423 snapshot, nessun blocco robots e due PDF del 2023
rimossi dal server (`404`). Ha censito 317 pagine di servizio, 73 PDF comunali,
11 centri e le due pagine dell'indice.

```sh
PYTHONPATH=src python3 -m dovelobutto.cli fetch-rea-services \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --snapshot-root data/crawl/ato-toscana-costa/2026-08-06/rea-services \
  --manifest data/crawl/ato-toscana-costa/2026-08-06/rea-services-manifest.json \
  --report outputs/ato-toscana-costa-rea-fetch-report.json \
  --observed-at 2026-08-06T19:00:00+02:00 \
  --user-agent 'DoveLoButtoData/0.1 (+mailto:marcofanciulli@me.com)'
```

`materialize-rea-services` combina queste pagine con il rifiutario. Produce
3.828 record per i 17 comuni: 3.230 termini, 110 regole, 46 servizi di ritiro,
17 zone, 19 relazioni comune-centro con orari e accesso e 368 descrizioni di
materiali accettati. Quando REA non pubblica il codice EER, la descrizione
resta acquisita con `eer_code_status: unmapped_description`; il codice non
viene dedotto. I centri intercomunali restano associati a tutti i comuni
esplicitamente serviti.

I 73 PDF sono conservati e collegati ai comuni, ma i calendari al loro interno
non sono ancora convertiti in eventi strutturati. Questa lacuna e esposta come
avviso per comune, non nascosta.

## AAMPS

La guida AAMPS di Livorno e un PDF del 2017 a due colonne. Il comando esterno:

```sh
pdftotext -bbox-layout dove-lo-butto.pdf dove-lo-butto-bbox.html
```

preserva le coordinate necessarie. `materialize-aamps-rifiutario` ricostruisce
125 coppie. Cinque righe con probabili continuazioni di colonna restano a
confidenza media e sono elencate nel rapporto; non vengono corrette a mano.

## GEOFOR

GEOFOR pubblica 24 schede comunali operative e un rifiutario condiviso
incorporato nel sito. La pipeline acquisisce le schede, le pagine dei centri,
i servizi di ritiro e gli allegati pubblici, quindi materializza 388 termini e
cinque regole generali per ciascun comune attivo.

```sh
PYTHONPATH=src python3 -m dovelobutto.cli fetch-geofor \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --snapshot-root data/crawl/ato-toscana-costa/2026-08-06/geofor \
  --manifest data/crawl/ato-toscana-costa/2026-08-06/geofor-manifest.json \
  --report outputs/ato-toscana-costa-geofor-fetch-report.json \
  --observed-at 2026-08-06T20:30:00+02:00 \
  --user-agent 'DoveLoButtoData/0.1 (+mailto:marcofanciulli@me.com)'

PYTHONPATH=src python3 -m dovelobutto.cli materialize-geofor \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --snapshot-root data/crawl/ato-toscana-costa/2026-08-06/geofor \
  --retrieved-at 2026-08-06T20:30:00+02:00 \
  --output-dir outputs/ato-toscana-costa \
  --report outputs/ato-toscana-costa-geofor-report.json
```

La passata verificata ha controllato 177 URL, salvato 176 snapshot e dichiarato
un solo errore: un vecchio PDF di Bientina oggi `404`. I 13.237 record
comprendono 9.312 termini, 120 regole, 24 zone, 24 centri con orari e accesso,
3.672 associazioni centro-EER e 37 servizi di ritiro. Il flag centro di raccolta
del rifiutario GEOFOR e applicato ai centri pubblicati; eventuali limitazioni
locali restano demandate alla scheda e al regolamento del singolo centro.

I calendari PDF sono acquisiti e inventariati, ma non ancora trasformati in
eventi strutturati. Per Chianni, Crespina Lorenzana, Fauglia, Lajatico, Palaia
e Pisa non e pubblicata una pagina comunale del centro. Peccioli non compare
tra le 24 schede operative e resta correttamente censito come subentro da
completare.

## Copertura corrente

- 100 comuni censiti;
- 49 comuni con almeno una fonte acquisita: 7 ESA, 17 REA, Livorno AAMPS e 24
  GEOFOR;
- 19.296 record ATO Costa;
- tutti i 13 comuni livornesi hanno almeno un rifiutario acquisito;
- tutti i comuni REA hanno pagine di servizio; 14 hanno accesso ad almeno un
  centro pubblicato, mentre Capraia Isola, Orciano Pisano e Santa Luce non
  risultano collegati a un centro nella fonte acquisita.

Prossimo ordine operativo: Lunigiana Ambiente, GEA, ASCIT, ERSU e le restanti
SOL; in parallelo restano l'estrazione dei calendari PDF e l'approfondimento
dei centri non pubblicati nelle schede comunali.
