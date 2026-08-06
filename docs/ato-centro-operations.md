# Operazioni ATO Toscana Centro

Versione: 0.1.0
Ultimo aggiornamento: 6 agosto 2026

## Perimetro

ATO Toscana Centro comprende 65 comuni: 38 nella citta metropolitana di
Firenze, 7 in provincia di Prato e 20 in provincia di Pistoia. Firenzuola,
Marradi e Palazzuolo sul Senio appartengono amministrativamente a Firenze ma
sono esclusi dal perimetro ufficiale dell'ATO.

Il registro viene costruito dall'elenco ISTAT e dalla dichiarazione di ambito
pubblicata da ATO Toscana Centro:

```sh
PYTHONPATH=src python3 -B -m dovelobutto.cli build-ato-centro-registry \
  --istat-csv data/sources/istat/toscana-comuni-2026-02-21.csv \
  --retrieved-at 2026-08-06T23:00:00+02:00 \
  --output outputs/ato-toscana-centro-municipalities.jsonl \
  --report outputs/ato-toscana-centro-municipalities-report.json
```

## Fonti AliaEstra

Il portale pubblico AliaEstra espone tre insiemi complementari:

- il rifiutario Junker, interrogato con il codice ISTAT del comune;
- la mappa pubblica di ecocentri ed ecofurgoni, con coordinate e indirizzi;
- le schede Sitecore collegate alla mappa, con orari, materiali conferibili e
  collegamento alle regole di accesso.

La pipeline non accede all'area cliente. Usa soltanto le richieste di lettura
effettuate dall'interfaccia pubblica e rimuove le icone codificate in base64,
che non sono necessarie al dataset.

Il rifiutario richiede almeno tre caratteri. Per ottenere una copertura ampia
e riproducibile, i prefissi sono derivati dalle parole gia presenti nel
catalogo canonico toscano. Il rapporto conserva il numero dei prefissi
interrogati e delle voci scoperte: la copertura e dichiarata come corpus-based,
non come esportazione ufficiale completa del database Junker.

```sh
PYTHONPATH=src python3 -B -m dovelobutto.cli fetch-alia \
  --catalog outputs/waste-catalog.json \
  --bundle data/crawl/ato-toscana-centro/2026-08-06/aliaestra-bundle.json \
  --report outputs/ato-toscana-centro-fetch-report.json \
  --observed-at 2026-08-06T23:00:00+02:00 \
  --user-agent 'DoveLoButtoData/0.1 (+mailto:marcofanciulli@me.com)' \
  --delay 1.0
```

Il bundle e un checkpoint atomico: una nuova esecuzione salta prefissi e
dettagli gia acquisiti e riprende quelli mancanti.

## Normalizzazione

```sh
PYTHONPATH=src python3 -B -m dovelobutto.cli materialize-alia \
  --registry outputs/ato-toscana-centro-municipalities.jsonl \
  --bundle data/crawl/ato-toscana-centro/2026-08-06/aliaestra-bundle.json \
  --retrieved-at 2026-08-06T23:00:00+02:00 \
  --output-dir outputs/ato-toscana-centro \
  --report outputs/ato-toscana-centro-report.json
```

Le descrizioni dei materiali accettati dagli ecocentri sono conservate anche
quando AliaEstra non pubblica il codice EER. In quel caso lo stato e
`unmapped_description`: il codice non viene dedotto. Colori e destinazioni del
rifiutario diventano regole territoriali; sacchetto, calendario e sistema di
raccolta restano non specificati quando dipendono dall'indirizzo.

Un comune senza ecocentro nel proprio territorio riceve un avviso esplicito,
ma mantiene rifiutario, regole e servizio di ritiro. Gli ecocentri dei comuni
vicini restano disponibili nel dataset geolocalizzato per la futura ricerca di
prossimita, senza attribuire automaticamente un diritto di accesso.

## Copertura corrente

La passata verificata del 6 agosto 2026 ha prodotto:

- 65 comuni acquisiti su 65;
- 502 prefissi interrogati e 1.722 dettagli del rifiutario, senza errori;
- 34 ecocentri in 30 comuni e 135 ecofurgoni in 34 comuni;
- 169 schede Sitecore; la mappa contiene un ecocentro e un ecofurgone privi di
  scheda di dettaglio, entrambi dichiarati nei rapporti;
- 114.352 record normalizzati e 37 avvisi: 35 comuni senza centro nel proprio
  territorio e i due dettagli appena indicati.

Le risposte campionate per Firenze, Prato, Pistoia e Scandicci coincidono anche
per voci potenzialmente ambigue come Tetra Pak e bottiglie di vetro. Il bundle
dell'esploratore tratta quindi il rifiutario come condiviso nell'ambito Plures
Alia; questa deduplicazione non modifica i file comunali e dovra essere
ricontrollata se il gestore introduce configurazioni comunali differenti.
