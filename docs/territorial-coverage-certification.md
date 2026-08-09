# Certificazione della copertura territoriale

Revisione dataset: `202608090007`  
Data del controllo: 9 agosto 2026, ore 10:45 CEST  
Esito: `pass` e `release_ready: true`

## Perimetro certificato

Il controllo usa lo stesso motore di risposta dell'app e attraversa l'intero
prodotto cartesiano tra:

- 3.493 concetti canonici di rifiuto;
- 10 gruppi di alias approvati;
- 81 esiti delle domande condizionali;
- 273 comuni toscani;
- 417 zone di servizio registrate in 270 comuni.

Livorno, Caprese Michelangelo e Sestino non hanno una suddivisione in zone
pubblicata nel dataset e sono quindi controllati a livello comunale. Il totale
e di 420 contesti territoriali e 1.505.280 risposte eseguite.

Nessun concetto canonico, comune toscano o zona registrata e escluso.

## Risultato

| Controllo | Esito |
| --- | ---: |
| Risposte eseguite | 1.505.280 |
| Risposte risolte | 774.120 |
| Domande definite | 731.160 |
| `not_found` per concetti noti | 0 |
| Conflitti | 0 |
| Domande incomplete | 0 |
| Errori strutturali | 0 |
| Risposte risolte senza fonte | 0 |
| Percorsi portabili con dettagli locali inventati | 0 |
| Duplicati in attesa di decisione | 0 |

Una domanda e considerata definita soltanto se presenta opzioni non vuote con
identificatori esistenti. Ognuno degli 81 esiti selezionabili viene inoltre
interrogato autonomamente in tutti i 420 contesti; una domanda non nasconde
quindi un ramo privo di risposta.

3.479 concetti hanno almeno una destinazione territoriale osservata. I restanti
14 hanno una classificazione portabile revisionata. Complessivamente 184.704
casi riguardano un concetto con evidenza nel territorio selezionato e 1.320.576
casi un concetto che non possiede evidenza specifica in quel territorio.

Il percorso portabile puo indicare flusso, EER e canali compatibili, ma non
inventa contenitore, colore, sacchetto, centro o servizio locale. Se questi
dettagli non sono pubblicati, la risposta li dichiara non verificati e invita a
controllare le istruzioni del gestore.

## Deduplicazione

Il confronto lessicale ha esaminato 246 coppie candidate:

- 193 hanno lo stesso percorso portabile e sono registrate come varianti
  equivalenti, senza produrre risposte incompatibili;
- 53 sono soltanto simili nel nome e restano concetti distinti;
- 0 richiedono una decisione manuale.

I 10 gruppi di alias comprendono 40 termini di ricerca approvati. Tutti i 40
termini restituiscono esattamente il proprio gruppo canonico.

## Blocco di pubblicazione

`publish-data-release` costruisce prima un database client temporaneo con lo
stato candidato. La revisione viene pubblicata soltanto se superano entrambi:

1. l'audit di classificazione portabile di concetti e alias;
2. l'audit territoriale esaustivo descritto in questo documento.

Un solo `not_found`, conflitto, riferimento invalido, domanda incompleta o
duplicato da revisionare interrompe la pubblicazione prima della modifica del
database autorevole e del manifest.

## Artefatti verificabili

- `outputs/query-coverage-report.json`  
  SHA-256 `c1fd7955b76b8eca0fc56859fe2a07b1e96809a396d3c4b15d14f4897e39fa2c`
- `outputs/waste-routing-coverage-report.json`  
  SHA-256 `e2238613909fb3c1d5ae44e630b6ed53a7ebb6a3fca850451639f4eaed8ba0bb`
- `outputs/distribution/release-report.json`  
  SHA-256 `e706eb475f28696d1177e497a88fa8d77bb189c66153d873dd8538556fe00d28`

Lo snapshot firmato della revisione contiene 157.354 entita. Il client locale
ha applicato con successo il delta firmato da `202608090006` a
`202608090007`.

## Limiti della certificazione

La certificazione riguarda tutti i concetti e territori presenti nel dataset e
garantisce che l'app abbia un percorso definito dopo il riconoscimento del
concetto. Non certifica l'esistenza di zone o servizi che le fonti competenti
non hanno pubblicato, ne la capacita di riconoscere qualunque formulazione
libera non ancora inclusa nei termini di ricerca. Questi due aspetti restano
oggetto degli aggiornamenti delle fonti e dell'ampliamento del vocabolario.
