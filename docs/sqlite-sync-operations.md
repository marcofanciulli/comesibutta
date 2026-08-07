# SQLite canonico e aggiornamenti

Versione: 0.1.0
Data: 7 agosto 2026

## Scopo

Questa implementazione rende eseguibile il protocollo descritto in
`docs/data-synchronization.md`. Trasforma i record acquisiti in entita
canoniche, mantiene lo stato editoriale del backend in SQLite e distribuisce
snapshot e delta applicabili atomicamente a un database client.

Il livello e intenzionalmente generico: conserva senza perdita tutti i tipi di
record correnti mentre il modello di dominio definitivo viene affinato. La
provenienza e gia normalizzata; concetti, regole condivise e applicabilita
territoriale restano entita generiche da specializzare.

## Struttura SQLite

Entrambi i ruoli usano lo stesso schema e attivano le chiavi esterne:

- `metadata`: dataset, versione dello schema, revisione e ruolo;
- `entities`: stato canonico corrente, corpo JSON compresso, hash e campi di
  ricerca, territorio, destinazione, flusso e centro immediatamente leggibili;
- `waste_search_terms`: etichette normalizzate dei concetti, aggiornate
  atomicamente con le entita per la ricerca tollerante dell'app;
- `entity_templates`: contenuto condiviso delle regole e delle voci territoriali;
- `source_documents`: documenti sorgente deduplicati tramite SHA-256;
- `source_evidence`: evidenze deduplicate e collegate al documento;
- `entity_sources`: collegamenti ordinati tra entita ed evidenze;
- `entity_dependencies`: riferimenti differiti tra entita;
- `tombstones`: cancellazioni da propagare ai client rimasti indietro;
- `package_applications`: pacchetti gia applicati e relativo hash;
- `changelog`: operazioni append-only, compresse e conservate solo dal backend.

Il client non duplica il changelog. Ogni pacchetto viene applicato in una
transazione `BEGIN IMMEDIATE`; sequenza, revisione, dipendenze e chiavi esterne
sono controllate prima del commit. Un errore ripristina integralmente la
revisione precedente. Riapplicare lo stesso pacchetto e un'operazione nulla;
riutilizzare lo stesso ID con contenuto diverso e un errore.

Le relazioni interne usano chiavi numeriche compatte. Gli identificatori
canonici pubblici restano invariati e vengono ricostruiti quando si legge il
database o si genera un nuovo pacchetto. La versione del formato SQLite e
distinta dalla versione del contratto distribuito: un database locale creato
con un formato precedente deve essere ricostruito da uno snapshot firmato,
senza richiedere modifiche al pacchetto.

La versione 5 dello storage introduce l'indice di ricerca dell'app. Come per le
precedenti modifiche strutturali, i database locali in versione 4 richiedono
una ricostruzione dallo snapshot; i pacchetti e gli ID canonici non cambiano.

Le entita `waste_lookup`, `collection_rule` e `service_zone` separano il
contenuto comune dall'applicabilita. Il modello conserva termine, destinazione,
modalita e istruzioni; la riga dell'entita conserva ID, comune e zona. La
lettura ricostruisce il JSON canonico originario, mentre aggiornamento e
cancellazione eliminano automaticamente i modelli non piu referenziati.
La pulizia incrementale controlla soltanto evidenze e modelli toccati dal
pacchetto; un delta vuoto avanza la revisione senza scandire tutte le entita.

## Identita e collisioni

La chiave naturale del record acquisito diventa l'ID canonico quando e
univoca. Se una fonte usa la stessa chiave per asserzioni operative diverse,
ogni variante viene conservata con un suffisso deterministico derivato dal suo
contenuto. Nessuna riga viene eliminata per far sembrare univoco il dataset.

Il collaudo sul dataset completo produce 155.946 entita, 159.719 dipendenze e
134 entita variantate. Questo e il livello di pubblicazione verificabile; la
successiva revisione editoriale potra fondere soltanto le entita realmente
equivalenti.

## Firme e artefatti

Manifest, snapshot e delta sono firmati con Ed25519 tramite OpenSSL. Il
manifest firma la propria rappresentazione canonica priva del campo
`signature`; la firma copre quindi anche hash, dimensioni e firme degli
artefatti elencati. Il client richiede una chiave pubblica e verifica:

1. firma del manifest;
2. dimensione e SHA-256 del file;
3. firma Ed25519 dell'artefatto compresso;
4. contratto, dataset, schema e revisione di partenza;
5. integrita relazionale dopo l'applicazione.

Le chiavi private sono escluse da Git. Una coppia di sviluppo si crea con:

```sh
mkdir -p data/keys
openssl genpkey -algorithm Ed25519 -out data/keys/distribution-private.pem
openssl pkey -in data/keys/distribution-private.pem -pubout \
  -out data/keys/distribution-public.pem
chmod 600 data/keys/distribution-private.pem
```

## Pubblicazione

```sh
PYTHONPATH=src python3 -m dovelobutto.cli publish-data-release \
  --input-dir outputs/sei-toscana \
  --input-dir outputs/ato-toscana-costa \
  --input-dir outputs/ato-toscana-centro \
  --input-dir outputs/toscana-boundary \
  --registry outputs/sei-toscana-municipalities.jsonl \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --registry outputs/ato-toscana-centro-municipalities.jsonl \
  --registry outputs/toscana-boundary-municipalities.jsonl \
  --catalog outputs/waste-catalog.json \
  --eer-register outputs/eer-register.json \
  --packaging-material-register outputs/packaging-material-register.json \
  --waste-curation-register data/curation/waste-curation-v1.json \
  --database data/canonical/publisher.sqlite \
  --artifact-dir outputs/distribution \
  --manifest outputs/distribution/manifest.json \
  --revision 202608070001 \
  --generated-at 2026-08-07T15:00:00+02:00 \
  --private-key data/keys/distribution-private.pem \
  --key-id distribution-2026-08 \
  --base-url https://data.example.it/comesibutta/ \
  --report outputs/distribution/release-report.json
```

La prima pubblicazione crea uno snapshot. Le successive confrontano lo stato
desiderato con SQLite e aggiungono un delta contenente soltanto lo stato finale
delle entita cambiate e le tombstone. Il manifest e la barriera di visibilita:
viene preparato come `.pending`, il database viene aggiornato e soltanto dopo
il manifest sostituisce atomicamente quello pubblico. Una ripartenza completa
automaticamente una pubblicazione interrotta tra gli ultimi due passaggi.

## Aggiornamento client

Il comando consigliato non richiede un package ID:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli apply-data-plan \
  --database data/canonical/client.sqlite \
  --manifest outputs/distribution/manifest.json \
  --artifact-root outputs/distribution \
  --public-key data/keys/distribution-public.pem
```

Il pianificatore legge la revisione locale e trova nel grafo dei delta il
percorso valido con meno byte, confrontandolo con lo snapshot corrente. Un
client troppo vecchio o senza un percorso incrementale usa lo snapshot. In
questo caso viene creato e verificato un nuovo SQLite, sostituito al database
attivo soltanto a operazione conclusa.

`apply-data-update` resta disponibile per collaudi e applicazioni esplicite di
un singolo pacchetto.

## Collaudo completo

Sul dataset del 7 agosto 2026:

- snapshot: 155.946 operazioni, 7,7 MB compressi;
- database client: 155.946 entita e 159.719 dipendenze valide;
- provenienza: 152.485 collegamenti, 524 documenti e 14.232 evidenze distinte;
- applicabilita: 142.575 entita territoriali usano 5.360 modelli condivisi,
  composti da 4.424 voci di rifiutario, 794 regole e 142 zone;
- delta simulato per la modifica di una voce territoriale: una operazione,
  711 byte;
- applicazione snapshot e delta con firma verificata e nessuna violazione di
  chiave esterna.

Il database client generico occupa circa 97 MB, contro i 259 MB della prima
materializzazione e i 129 MB ottenuti con la sola normalizzazione della
provenienza. La riduzione complessiva e del 63%, senza modificare il protocollo
di aggiornamento. Una pubblicazione senza variazioni genera zero operazioni,
confermando che la ricostruzione dei record e esatta sull'intero dataset.
