# Operazioni di scansione SEI Toscana

Versione: 0.1.0  
Ultimo aggiornamento: 5 agosto 2026

## Scopo

Il comando `sweep-sei` visita in modo controllato le pagine pubblicate da SEI
Toscana, conserva gli snapshot e genera i record di acquisizione per comune.
La scansione puo essere interrotta e ripresa senza perdere quanto gia ottenuto.

## Coda iniziale

La coda viene costruita da `outputs/sei-toscana-municipalities.jsonl`. Per ogni
comune parte esclusivamente da:

- pagina della raccolta rifiuti;
- pagina del centro o dei centri di raccolta.

Durante la visita segue soltanto collegamenti pertinenti allo stesso comune e
alle tre categorie `collection`, `facilities` e `pickup`. In questo modo scopre
le pagine di ritiro ingombranti anche quando non sono presenti nell'indice
generale. Frammenti come `#cdrUtenzeCommerciali`, slash finali e URL finali dei
reindirizzamenti vengono normalizzati per evitare visite duplicate.

## Comportamento di rete

La scansione live:

- richiede un user-agent identificabile con un contatto del progetto;
- legge e applica `robots.txt` in un preflight unico prima delle pagine
  comunali; se il file non e leggibile o una URL iniziale e vietata, non visita
  alcuna pagina del lotto;
- usa una sola richiesta alla volta;
- attende almeno un secondo, o il crawl delay maggiore indicato dal sito;
- invia `If-None-Match` e `If-Modified-Since` quando disponibili;
- non automatizza form, prenotazioni o aree riservate.

## Persistenza

Gli snapshot sono immutabili e hanno un nome derivato dall'impronta SHA-256:

```text
data/snapshots/sei-toscana/YYYY-MM-DD/<comune>/<categoria>-<hash>.html
```

Lo stato corrente associa ogni URL a esito, URL finale, data dell'ultimo
controllo, ETag, Last-Modified, hash e percorso dello snapshot. Viene scritto
in modo atomico dopo ogni pagina:

```text
data/crawl/sei-toscana-state.json
```

Una pagina invariata non crea un nuovo file. Gli URL di ritiro scoperti in una
scansione precedente vengono reinseriti nella coda anche quando la pagina che
li conteneva risponde `304 Not Modified`.

La coda non completata viene salvata integralmente in `pending_jobs` dopo ogni
pagina. Il rapporto espone sia `pages_remaining` sia `remaining_pages`, con
comune, categoria e URL. Alla ripresa, questi lavori hanno priorita sulle
visite periodiche ordinarie. Per gli stati creati da versioni precedenti, i
collegamenti pendenti vengono ricostruiti dagli snapshot disponibili.

## Avvio live

Il contatto autorizzato per questo progetto e `marcofanciulli@me.com`:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli sweep-sei \
  --registry outputs/sei-toscana-municipalities.jsonl \
  --snapshot-root data/snapshots/sei-toscana \
  --state data/crawl/sei-toscana-state.json \
  --report outputs/sei-toscana-sweep-report.json \
  --output-dir outputs/sei-toscana \
  --observed-at 2026-08-05T15:00:00+02:00 \
  --user-agent 'DoveLoButtoData/0.1 (+mailto:marcofanciulli@me.com)' \
  --delay 1
```

Opzioni utili:

- `--municipality manciano`: limita la scansione a uno slug o codice ISTAT;
- `--municipality ...` ripetuto: seleziona un lotto di comuni;
- `--municipality-file config/sweep-batches/grosseto-01.txt`: legge un lotto
  da file, ignorando righe vuote e commenti;
- `--max-pages 20`: interrompe ordinatamente la passata dopo venti pagine;
- rilanciare lo stesso comando e stato: riprende e ricontrolla la coda.

## Modalita locale

La modalita fixture sostituisce la rete con gli snapshot di test:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli sweep-sei \
  --registry outputs/sei-toscana-municipalities.jsonl \
  --snapshot-root data/snapshots/sei-toscana-pilot \
  --state data/crawl/sei-toscana-pilot-state.json \
  --report outputs/sei-toscana-pilot-sweep-report.json \
  --output-dir outputs/sweep-pilot \
  --observed-at 2026-08-05T13:30:00+02:00 \
  --fixture-root tests/fixtures/sei_toscana \
  --municipality manciano \
  --municipality castagneto-carducci \
  --municipality siena \
  --municipality campiglia-marittima
```

## Rapporti

Il rapporto di passata contiene pagine controllate, coda residua, categorie,
esiti, errori e riepilogo dell'estrazione. Per ciascun comune vengono generati:

- `<slug>-acquisition.jsonl` con i record normalizzati;
- `<slug>-report.json` con pagine disponibili, record per tipo e avvisi.

Un errore di rete o parsing resta nello stato e nel rapporto. Non cancella lo
snapshot o l'output valido della passata precedente.

Se il preflight trova divieti in `robots.txt`, il rapporto contiene
`access_preflight.allowed: false`, l'elenco completo `blocked_urls` e un errore
`blocked_by_robots` per ogni URL. Il lotto termina prima di acquisire pagine:
non esistono esclusioni silenziose.

## Primo lotto Grosseto

```sh
PYTHONPATH=src python3 -m dovelobutto.cli sweep-sei \
  --registry outputs/sei-toscana-municipalities.jsonl \
  --snapshot-root data/snapshots/sei-toscana \
  --state data/crawl/sei-toscana-state.json \
  --report outputs/sei-toscana-grosseto-01-report.json \
  --output-dir outputs/sei-toscana \
  --observed-at 2026-08-05T18:30:00+02:00 \
  --municipality-file config/sweep-batches/grosseto-01.txt \
  --max-pages 30 \
  --user-agent 'DoveLoButtoData/0.1 (+mailto:marcofanciulli@me.com)' \
  --delay 1
```
