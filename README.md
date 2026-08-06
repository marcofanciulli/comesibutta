# Come si butta?

Sistema informativo per rispondere alla domanda "Dove lo butto?" nei comuni
della Toscana. Il progetto collega i nomi quotidiani dei rifiuti alle regole
territoriali di raccolta, ai centri di conferimento e ai codici EER/CER.

La prima fase riguarda i 104 comuni di ATO Toscana Sud gestiti da SEI Toscana.
Il repository contiene il modello dati, gli estrattori, gli snapshot di test e
i dataset verificati del pilota.

## Contenuti

- `docs/data-architecture.md`: modello canonico, acquisizione, geografia e
  strategia del pilota SEI Toscana.
- `docs/project-status.md`: registro persistente di decisioni, risultati,
  verifiche, limiti e prossimi passi.
- `docs/crawl-operations.md`: esecuzione, ripresa e controllo della scansione
  dei comuni SEI Toscana.
- `docs/source-access-policy.md`: verifica delle condizioni pubblicate e
  regole obbligatorie di accesso alle fonti.
- `schemas/acquisition-record.schema.json`: formato JSON Lines prodotto dagli
  estrattori.
- `schemas/disposal-answer.schema.json`: contratto della risposta letta
  dall'app.
- `examples/`: esempi illustrativi basati sulle pagine SEI Toscana di Manciano.
- `explorer/`: interfaccia locale per controllare comuni, centri, codici EER,
  regole, punti di raccolta, fonti e anomalie.

Il checkpoint corrente, comprese decisioni e prossimi passi, e mantenuto in
`docs/project-status.md`. I dati di esempio non costituiscono ancora un dataset
validato e completo per l'intera Toscana.

## Requisiti

- Python 3.11 o successivo;
- nessuna dipendenza esterna per l'estrattore corrente.

## Pilota Manciano

Il primo estrattore usa soltanto la libreria standard di Python e legge sia
snapshot locali sia pagine live. Per riprodurre l'acquisizione verificata:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli scrape-sei \
  --municipality Manciano \
  --istat 053014 \
  --slug manciano \
  --retrieved-at 2026-08-05T10:00:00+02:00 \
  --fixture-dir tests/fixtures/sei_toscana/manciano \
  --output outputs/manciano-acquisition.jsonl \
  --report outputs/manciano-report.json
```

Per una raccolta live si omette `--fixture-dir` e si specifica un
`--user-agent` identificabile, comprensivo di un contatto del progetto. Il
downloader consulta `robots.txt` e rispetta il relativo intervallo di visita.

I test si eseguono con:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Il pilota comprende anche Castagneto Carducci, Siena, Campiglia Marittima e la
pagina di Sassetta che documenta l'accesso intercomunale al centro di
Castagneto. I dataset e i rapporti generati si trovano in `outputs/`.

## Registro SEI Toscana

Lo snapshot dell'indice SEI e stato incrociato con l'elenco ufficiale ISTAT
aggiornato al 21 febbraio 2026. Il registro riproducibile dei 104 comuni si
genera con:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli build-sei-registry \
  --index-html tests/fixtures/sei_toscana/index/comuni.html \
  --istat-csv data/sources/istat/toscana-comuni-2026-02-21.csv \
  --retrieved-at 2026-08-05T12:30:00+02:00 \
  --output outputs/sei-toscana-municipalities.jsonl \
  --report outputs/sei-toscana-municipalities-report.json
```

Il file XLSX ISTAT originale e conservato in `data/sources/istat/` insieme al
CSV toscano derivato usato dalla pipeline.

## Scansione controllata

Il comando `sweep-sei` costruisce una coda dai 104 comuni, rispetta
`robots.txt`, applica un intervallo fra le richieste, usa richieste condizionali
e conserva snapshot identificati dalla loro impronta. Le istruzioni operative
complete sono in `docs/crawl-operations.md`.

Il collaudo locale sui quattro comuni completi ha visitato 12 pagine e prodotto
338 record senza avvisi. Una seconda passata ha riconosciuto tutte le pagine
come invariate senza creare nuovi snapshot.

## Esploratore dati

L'esploratore e una console di verifica statica. Il pacchetto dati viene
rigenerato esclusivamente dagli output acquisiti:

```sh
PYTHONPATH=src python3 -m dovelobutto.explorer \
  --input-dir outputs/sei-toscana \
  --batch-report outputs/sei-toscana-grosseto-01-report.json \
  --batch-report outputs/sei-toscana-grosseto-02-report.json \
  --batch-report outputs/sei-toscana-arezzo-report.json \
  --batch-report outputs/sei-toscana-siena-report.json \
  --batch-report outputs/sei-toscana-livorno-ato-sud-report.json \
  --registry outputs/sei-toscana-municipalities.jsonl \
  --generated-at 2026-08-06T11:25:00+02:00 \
  --output explorer/data.js
```

L'interfaccia in `explorer/index.html` permette di filtrare per ATO e provincia,
esplorare i record per comune, cercare materiali e codici EER e risalire alla
fonte di ogni fatto. Il dataset corrente copre tutti i 104 comuni di ATO
Toscana Sud.
