# Come si butta?

Sistema informativo per rispondere alla domanda "Dove lo butto?" nei comuni
della Toscana. Il progetto collega i nomi quotidiani dei rifiuti alle regole
territoriali di raccolta, ai centri di conferimento e ai codici EER/CER.

Il perimetro censito comprende i 104 comuni di ATO Toscana Sud e i 100 comuni
di ATO Toscana Costa. Il repository contiene il modello dati, gli estrattori,
gli snapshot di test, i dataset verificati e un esploratore locale.

## Contenuti

- `docs/data-architecture.md`: modello canonico, acquisizione, geografia e
  strategia del pilota SEI Toscana.
- `docs/project-status.md`: registro persistente di decisioni, risultati,
  verifiche, limiti e prossimi passi.
- `docs/crawl-operations.md`: esecuzione, ripresa e controllo della scansione
  dei comuni SEI Toscana.
- `docs/ato-costa-operations.md`: registro, fonti e acquisizioni multi-gestore
  di ATO Toscana Costa.
- `docs/source-access-policy.md`: verifica delle condizioni pubblicate e
  regole obbligatorie di accesso alle fonti.
- `docs/data-synchronization.md`: revisioni, snapshot e aggiornamenti atomici
  della futura base dati locale.
- `docs/eer-register.md`: importazione normativa, validita e controllo dei
  codici EER pubblicati dai centri.
- `schemas/acquisition-record.schema.json`: formato JSON Lines prodotto dagli
  estrattori.
- `schemas/disposal-answer.schema.json`: contratto della risposta letta
  dall'app.
- `schemas/data-manifest.schema.json` e
  `schemas/data-update-package.schema.json`: protocollo di distribuzione dei
  dati indipendente dalle versioni dell'app.
- `schemas/eer-register.schema.json`: gerarchia e voci ufficiali EER.
- `examples/`: esempi illustrativi basati sulle pagine SEI Toscana di Manciano.
- `explorer/`: interfaccia locale per controllare comuni, centri, codici EER,
  regole, punti di raccolta, fonti e anomalie.

Il checkpoint corrente, comprese decisioni e prossimi passi, e mantenuto in
`docs/project-status.md`. I dati di esempio non costituiscono ancora un dataset
validato e completo per l'intera Toscana.

## Requisiti

- Python 3.11 o successivo;
- nessuna libreria Python esterna per gli estrattori correnti;
- `pdftotext` di Poppler per preparare i PDF a colonne come la guida AAMPS.

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

## Registri territoriali

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

Il registro ATO Toscana Costa deriva dalla tabella ufficiale Comune-SOL 2026,
riconciliata con ISTAT. Conserva separatamente gestore unico RetiAmbiente,
societa operativa locale e stato del subentro. Le istruzioni sono in
`docs/ato-costa-operations.md`.

## Scansione controllata

Il comando `sweep-sei` costruisce una coda dai 104 comuni, rispetta
`robots.txt`, applica un intervallo fra le richieste, usa richieste condizionali
e conserva snapshot identificati dalla loro impronta. Le istruzioni operative
complete sono in `docs/crawl-operations.md`.

Il collaudo locale sui quattro comuni completi ha visitato 12 pagine e prodotto
338 record senza avvisi. Una seconda passata ha riconosciuto tutte le pagine
come invariate senza creare nuovi snapshot.

## Esploratore dati

Il catalogo regionale viene prima generato dai rifiutari acquisiti:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli build-waste-catalog \
  --input-dir outputs/sei-toscana \
  --input-dir outputs/ato-toscana-costa \
  --registry outputs/sei-toscana-municipalities.jsonl \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --eer-register outputs/eer-register.json \
  --generated-at 2026-08-06T23:00:00+02:00 \
  --output outputs/waste-catalog.json \
  --report outputs/waste-catalog-report.json
```

L'esploratore e una console di verifica statica. Il pacchetto dati viene
rigenerato esclusivamente dagli output acquisiti:

```sh
PYTHONPATH=src python3 -m dovelobutto.explorer \
  --input-dir outputs/sei-toscana \
  --input-dir outputs/ato-toscana-costa \
  --batch-report outputs/sei-toscana-grosseto-01-report.json \
  --batch-report outputs/sei-toscana-grosseto-02-report.json \
  --batch-report outputs/sei-toscana-arezzo-report.json \
  --batch-report outputs/sei-toscana-siena-report.json \
  --batch-report outputs/sei-toscana-livorno-ato-sud-report.json \
  --batch-report outputs/ato-toscana-costa-esa-report.json \
  --batch-report outputs/ato-toscana-costa-rea-report.json \
  --batch-report outputs/ato-toscana-costa-aamps-report.json \
  --batch-report outputs/ato-toscana-costa-geofor-report.json \
  --registry outputs/sei-toscana-municipalities.jsonl \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --catalog outputs/waste-catalog.json \
  --eer-register outputs/eer-register.json \
  --generated-at 2026-08-06T23:00:00+02:00 \
  --output explorer/data.js
```

L'interfaccia permette di filtrare per ATO e provincia, distinguere comuni
censiti da comuni acquisiti, esplorare centri e regole, consultare il
rifiutario, cercare materiali e codici EER e risalire alla fonte di ogni fatto.
Il pacchetto corrente contiene 204 comuni censiti, 153 con almeno una fonte
materializzata e 24.386 record. Per i 17 comuni REA comprende anche pagine di
servizio, centri intercomunali, orari, accesso, ritiri e materiali accettati;
gli EER non pubblicati dalla fonte sono indicati esplicitamente come tali. Per
i 24 comuni GEOFOR attivi comprende 388 voci del rifiutario e cinque regole
generali per comune, oltre a centri, orari e ritiri quando pubblicati. La vista
"Catalogo regionale" espone 818 concetti trasversali, 331 dei quali hanno un
EER concordante indicato dalle fonti; le destinazioni restano marcate come
osservazioni locali.
