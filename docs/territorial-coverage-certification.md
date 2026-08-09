# Certificazione della copertura territoriale

Revisione dataset: `202608090012`
Data del controllo: 9 agosto 2026, ore 21:52 CEST
Esito: `pass` e `release_ready: true`

## Perimetro certificato

Il controllo usa lo stesso motore di risposta dell'app e attraversa l'intero
prodotto cartesiano tra:

- 3.495 concetti canonici di rifiuto;
- 10 gruppi di alias approvati;
- 81 esiti delle domande condizionali;
- 273 comuni toscani;
- 417 zone di servizio registrate in 270 comuni.

Livorno, Caprese Michelangelo e Sestino non hanno una suddivisione in zone
pubblicata nel dataset e sono quindi controllati a livello comunale. Il totale
e di 420 contesti territoriali e 1.506.120 risposte eseguite.

Nessun concetto canonico, comune toscano o zona registrata e escluso.

## Risultato

| Controllo | Esito |
| --- | ---: |
| Risposte eseguite | 1.506.120 |
| Risposte risolte | 864.846 |
| Domande definite | 641.274 |
| `not_found` per concetti noti | 0 |
| Conflitti | 0 |
| Domande incomplete | 0 |
| Errori strutturali | 0 |
| Risposte risolte senza fonte | 0 |
| Percorsi portabili con dettagli locali inventati | 0 |
| Materiali pericolosi instradati verso flussi o EER non pericolosi | 0 |
| Destinazioni locali verificate ma omesse | 0 |
| Duplicati in attesa di decisione | 0 |

Una domanda e considerata definita soltanto se presenta opzioni non vuote con
identificatori esistenti. Ognuno degli 81 esiti selezionabili viene inoltre
interrogato autonomamente in tutti i 420 contesti; una domanda non nasconde
quindi un ramo privo di risposta.

3.479 concetti hanno almeno una destinazione territoriale osservata. I restanti
14 hanno una classificazione portabile revisionata. Complessivamente 184.704
casi riguardano un concetto con evidenza nel territorio selezionato e 1.321.416
casi un concetto che non possiede evidenza specifica in quel territorio.

Il percorso portabile puo indicare flusso, EER e canali compatibili, ma non
inventa contenitore, colore, sacchetto, centro o servizio locale. Se questi
dettagli non sono pubblicati, la risposta li dichiara non verificati e invita a
controllare le istruzioni del gestore.

Cinque profili trasversali coprono piombo, mercurio, amianto, cadmio, pile e
batterie. Quando uno di essi si attiva, flussi, contenitori ed EER non
pericolosi vengono soppressi. Se non resta un EER pericoloso verificato, la
risposta conserva soltanto la gestione separata e non assegna alcun codice.

## Qualita delle destinazioni

Un audit indipendente confronta ogni risposta col catalogo dei centri
accessibili. Un centro e considerato verificato soltanto se pubblica uno degli
EER compatibili oppure una descrizione completa del materiale. Sono state
osservate 115.473 risposte con centro locale verificato, corrispondenti a
69.218 coppie concetto-comune. Le omissioni bloccanti sono zero.

Le lacune delle fonti sono rendicontate separatamente: non diventano
destinazioni dedotte. Il report registra 143.707 coppie concetto-comune con un
percorso portabile privo di dettaglio locale, 155.657 con EER ma senza servizio
locale pubblicato e 21.516 con il solo canale di operatore specializzato. Sono
indicatori per le prossime acquisizioni, non errori di copertura logica.

Quando un centro nomina esplicitamente un materiale ma non pubblica l'EER, il
centro puo essere mostrato senza attribuire un codice alla fonte. Quando
accetta piu EER plausibili, nessuno viene scelto implicitamente: restano
alternative con le rispettive condizioni.

## Geolocalizzazione

La revisione comprende 273 confini comunali ISTAT al 1 gennaio 2026. Tutti i
comuni registrati hanno un confine e non risultano geometrie inattese. Il
comune puo essere individuato soltanto su richiesta esplicita; la posizione
non viene persistita e puo sempre essere corretta manualmente. Le coordinate
ordinano per distanza i servizi gia verificati, senza inventarne
l'accettazione.

## Deduplicazione

Il confronto lessicale ha esaminato 246 coppie candidate:

- 186 hanno lo stesso percorso portabile e sono registrate come varianti
  equivalenti, senza produrre risposte incompatibili;
- 60 sono soltanto simili nel nome e restano concetti distinti;
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
  SHA-256 `94d5223724091de1e17d770ee716d1d94efa4db1b962b7cb1fc4a7744864c397`
- `outputs/destination-quality-report.json`
  SHA-256 `cfa19dbaa22e0643727964c99a01a27b3483a7b22320cc378e66f875a5612784`
- `outputs/waste-routing-coverage-report.json`
  SHA-256 `aff39d520a149ca0a70b689006765b3c3424956b17188db933f56ee64564d840`
- `outputs/municipality-boundaries-report.json`
  SHA-256 `8715fe0d8d3a6ac1e10c4b5cc590a32b95cf27f8ede3d2898a90857940c83cb4`
- `outputs/distribution/release-report.json`
  SHA-256 `d104a617dd682e6b10c59c128e8df9e5d88959e0a218280e99b2fc9c141a4f4d`

Lo snapshot firmato della revisione contiene 157.574 entita. Il client locale
ha applicato con successo il delta firmato da `202608090011` a
`202608090012`, composto dalle 273 geometrie comunali.

## Limiti della certificazione

La certificazione riguarda tutti i concetti e territori presenti nel dataset e
garantisce che l'app abbia un percorso definito dopo il riconoscimento del
concetto. Non certifica l'esistenza di zone o servizi che le fonti competenti
non hanno pubblicato, ne la capacita di riconoscere qualunque formulazione
libera non ancora inclusa nei termini di ricerca. Questi due aspetti restano
oggetto degli aggiornamenti delle fonti e dell'ampliamento del vocabolario.
