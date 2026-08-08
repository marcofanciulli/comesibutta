# Come si butta?

Sistema informativo per rispondere alla domanda "Dove lo butto?" nei comuni
della Toscana. Il progetto collega i nomi quotidiani dei rifiuti alle regole
territoriali di raccolta, ai centri di conferimento e ai codici EER/CER.

Il perimetro censito comprende i 104 comuni di ATO Toscana Sud, i 100 comuni
di ATO Toscana Costa, i 65 comuni di ATO Toscana Centro e i quattro comuni
toscani assegnati ad ATO extra-regionali. Il repository
contiene il modello dati, gli estrattori, gli snapshot di test, i dataset
verificati e un esploratore locale.

## Contenuti

- `docs/data-architecture.md`: modello canonico, acquisizione, geografia e
  strategia del pilota SEI Toscana.
- `docs/project-status.md`: registro persistente di decisioni, risultati,
  verifiche, limiti e prossimi passi.
- `docs/crawl-operations.md`: esecuzione, ripresa e controllo della scansione
  dei comuni SEI Toscana.
- `docs/ato-costa-operations.md`: registro, fonti e acquisizioni multi-gestore
  di ATO Toscana Costa.
- `docs/ato-centro-operations.md`: perimetro e acquisizione delle fonti
  pubbliche AliaEstra per ATO Toscana Centro.
- `docs/toscana-boundary-operations.md`: acquisizione dei quattro comuni
  toscani appartenenti agli ATO Emilia-Romagna e Marche.
- `docs/source-access-policy.md`: verifica delle condizioni pubblicate e
  regole obbligatorie di accesso alle fonti.
- `docs/data-synchronization.md`: revisioni, snapshot e aggiornamenti atomici
  della futura base dati locale.
- `docs/sqlite-sync-operations.md`: pubblicazione firmata, database SQLite,
  scelta del percorso minimo e applicazione atomica degli aggiornamenti.
- `docs/app-query.md`: ricerca tollerante e composizione della risposta
  territoriale letta da sito, app e backend.
- `docs/facility-resolution.md`: accesso, accettazione, distanza, orari e
  scelta prudente dei centri di raccolta.
- `docs/channel-services.md`: ritiri, punti mobili, compatibilita e canali
  conservati soltanto come indicazioni sorgente.
- `docs/waste-curation.md`: registro revisionato di sinonimi, flussi e canali
  di conferimento, controlli e distribuzione alle app.
- `docs/eer-register.md`: importazione normativa, validita e controllo dei
  codici EER pubblicati dai centri.
- `docs/packaging-material-register.md`: registro europeo dei materiali di
  imballaggio e relativa provenienza normativa.
- `docs/visual-recognition.md`: pipeline unificata PyTorch, Core ML e LiteRT
  per il riconoscimento sul dispositivo.
- `docs/vision-corpus.md`: tassonomia, diritti, privacy, split e regole di
  annotazione del corpus fotografico.
- `docs/vision-bootstrap.md`: tavole MASE, varianti sintetiche e riproduzione
  del primo corpus tecnico.
- `docs/vision-training.md`: addestramento sperimentale, metriche, artefatti e
  limiti del primo detector.
- `docs/photo-capture-guide.md`: prontuario per fotografare e classificare gli
  imballaggi prima dell'annotazione.
- `docs/ppwr-monitoring.md`: fonti e regole del controllo quotidiano sui nuovi
  pittogrammi armonizzati europei.
- `schemas/acquisition-record.schema.json`: formato JSON Lines prodotto dagli
  estrattori.
- `schemas/disposal-answer.schema.json`: contratto della risposta letta
  dall'app.
- `schemas/data-manifest.schema.json` e
  `schemas/data-update-package.schema.json`: protocollo di distribuzione dei
  dati indipendente dalle versioni dell'app.
- `schemas/eer-register.schema.json`: gerarchia e voci ufficiali EER.
- `schemas/packaging-material-register.schema.json`: codici europei dei
  materiali di imballaggio, inclusi gli slot non assegnati.
- `schemas/waste-curation-register.schema.json`: gruppi di sinonimi approvati,
  vocabolario dei flussi e canali di conferimento.
- `schemas/vision-model-contract.schema.json` e
  `schemas/visual-recognition-observation.schema.json`: contratto del modello
  e risultato del riconoscimento fotografico.
- `schemas/vision-taxonomy.schema.json` e
  `schemas/vision-corpus-manifest.schema.json`: classi del detector e manifest
  verificabile delle immagini annotate.
- `schemas/photo-capture-record.schema.json`: registro privato degli scatti
  fotografici e delle loro condizioni.
- `examples/`: esempi illustrativi basati sulle pagine SEI Toscana di Manciano.
- `explorer/`: interfaccia locale per controllare comuni, centri, codici EER,
  regole, punti di raccolta, fonti e anomalie.

Il checkpoint corrente, comprese decisioni e prossimi passi, e mantenuto in
`docs/project-status.md`. I dati di esempio non costituiscono ancora un dataset
validato e completo per l'intera Toscana.

## Requisiti

- Python 3.11 o successivo;
- nessuna libreria Python esterna per gli estrattori correnti;
- `pdftotext` di Poppler per preparare i PDF a colonne come la guida AAMPS;
- OpenSSL 3 con supporto Ed25519 per firmare e verificare i rilasci dati.

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

Il registro ATO Toscana Centro comprende i 65 comuni serviti da Plures Alia,
riconciliati con ISTAT. Le istruzioni e i limiti di copertura del rifiutario
sono documentati in `docs/ato-centro-operations.md`.

Il registro di confine completa la Toscana con Firenzuola, Marradi, Palazzuolo
sul Senio e Sestino. Mantiene gli ATO extra-regionali come dimensioni autonome,
limitandone la vista ai soli comuni toscani. Fonti, comandi e limiti sono in
`docs/toscana-boundary-operations.md`.

## Scansione controllata

Il comando `sweep-sei` costruisce una coda dai 104 comuni, rispetta
`robots.txt`, applica un intervallo fra le richieste, usa richieste condizionali
e conserva snapshot identificati dalla loro impronta. Le istruzioni operative
complete sono in `docs/crawl-operations.md`.

Il collaudo locale sui quattro comuni completi ha visitato 12 pagine e prodotto
338 record senza avvisi. Una seconda passata ha riconosciuto tutte le pagine
come invariate senza creare nuovi snapshot.

## Esploratore dati

Il registro dei materiali di imballaggio viene costruito separatamente dalle
regole locali, conservando anche i numeri che la norma non ha assegnato:

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

Il catalogo regionale viene prima generato dai rifiutari acquisiti:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli build-waste-catalog \
  --input-dir outputs/sei-toscana \
  --input-dir outputs/ato-toscana-costa \
  --input-dir outputs/ato-toscana-centro \
  --input-dir outputs/toscana-boundary \
  --registry outputs/sei-toscana-municipalities.jsonl \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --registry outputs/ato-toscana-centro-municipalities.jsonl \
  --registry outputs/toscana-boundary-municipalities.jsonl \
  --eer-register outputs/eer-register.json \
  --generated-at 2026-08-07T13:00:00+02:00 \
  --output outputs/waste-catalog.json \
  --report outputs/waste-catalog-report.json
```

L'esploratore e una console di verifica statica. Il pacchetto dati viene
rigenerato esclusivamente dagli output acquisiti:

```sh
PYTHONPATH=src python3 -m dovelobutto.explorer \
  --input-dir outputs/sei-toscana \
  --input-dir outputs/ato-toscana-costa \
  --input-dir outputs/ato-toscana-centro \
  --input-dir outputs/toscana-boundary \
  --batch-report outputs/sei-toscana-grosseto-01-report.json \
  --batch-report outputs/sei-toscana-grosseto-02-report.json \
  --batch-report outputs/sei-toscana-arezzo-report.json \
  --batch-report outputs/sei-toscana-siena-report.json \
  --batch-report outputs/sei-toscana-livorno-ato-sud-report.json \
  --batch-report outputs/ato-toscana-costa-esa-report.json \
  --batch-report outputs/ato-toscana-costa-rea-report.json \
  --batch-report outputs/ato-toscana-costa-aamps-report.json \
  --batch-report outputs/ato-toscana-costa-geofor-report.json \
  --batch-report outputs/ato-toscana-costa-ascit-report.json \
  --batch-report outputs/ato-toscana-costa-asmiu-report.json \
  --batch-report outputs/ato-toscana-costa-ersu-report.json \
  --batch-report outputs/ato-toscana-costa-gea-report.json \
  --batch-report outputs/ato-toscana-costa-lunigiana-ambiente-report.json \
  --batch-report outputs/ato-toscana-costa-retiambiente-carrara-report.json \
  --batch-report outputs/ato-toscana-costa-sea-ambiente-report.json \
  --batch-report outputs/ato-toscana-costa-sistema-ambiente-report.json \
  --batch-report outputs/ato-toscana-centro-report.json \
  --batch-report outputs/toscana-boundary-report.json \
  --registry outputs/sei-toscana-municipalities.jsonl \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --registry outputs/ato-toscana-centro-municipalities.jsonl \
  --registry outputs/toscana-boundary-municipalities.jsonl \
  --catalog outputs/waste-catalog.json \
  --eer-register outputs/eer-register.json \
  --generated-at 2026-08-07T13:00:00+02:00 \
  --output explorer/data.js
```

L'interfaccia permette di filtrare per ATO e provincia, distinguere comuni
censiti da comuni acquisiti, esplorare centri e regole, consultare il
rifiutario, cercare materiali e codici EER e risalire alla fonte di ogni fatto.
Il pacchetto corrente contiene tutti i 273 comuni toscani censiti, ciascuno con
almeno una fonte materializzata, e 153.102 record logici. Per i sette comuni
ESA comprende anche dieci centri con indirizzi, accessi, orari e codici EER
letti dai cartelli ufficiali verificati. Per i 17 comuni REA
comprende anche pagine di servizio, centri intercomunali, orari, accesso,
ritiri, materiali accettati, quattro calendari RUR, cinque calendari Ecomobile
2026 e 12 calendari settimanali grafici strutturati;
gli EER non pubblicati dalla fonte sono indicati esplicitamente come tali. Per
i 25 comuni GEOFOR comprende 388 voci del rifiutario e cinque regole
generali per comune, oltre a centri, orari e ritiri quando pubblicati. La vista
"Catalogo" espone 3.124 concetti trasversali, 331 dei quali hanno un
EER concordante indicato dalle fonti; le destinazioni restano marcate come
osservazioni locali.

Per ATO Toscana Centro l'esploratore conserva una sola copia delle 1.722 voci
AliaEstra condivise, continuando ad applicarle a ciascuno dei 65 comuni. Il
bundle contiene quindi 42.707 record fisici e pesa circa 55 MiB, mentre i file
di acquisizione comunali restano completi e indipendenti.

## Pubblicazione e aggiornamenti

Il dataset puo essere pubblicato come snapshot e delta gzip firmati Ed25519.
Il backend mantiene stato, changelog e tombstone in SQLite; il client verifica
manifest e artefatti, sceglie automaticamente il percorso con meno byte e
applica ogni pacchetto in una transazione. Documenti ed evidenze condivise sono
deduplicati nel database locale insieme alle regole territoriali equivalenti,
che vengono rappresentate come modelli con applicabilita a comune e zona. Il
dataset completo occupa circa 97 MB. Comandi, gestione delle chiavi e risultati
sono in `docs/sqlite-sync-operations.md`.
