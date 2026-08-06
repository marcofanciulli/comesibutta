# Architettura dei dati

Versione: 0.2.0
Ambito corrente: ATO Toscana Sud e ATO Toscana Costa

## 1. Perimetro del pilota

ATO Toscana Sud comprende 104 comuni: i 98 comuni delle province di Arezzo,
Grosseto e Siena, oltre a Campiglia Marittima, Castagneto Carducci, Piombino,
San Vincenzo, Sassetta e Suvereto, in provincia di Livorno.

Il pilota parte dalle pagine comunali pubblicate da SEI Toscana. La pagina del
comune e i collegamenti presenti al suo interno sono il punto di ingresso; non
si presume che URL singolari e plurali come `centro-di-raccolta` e
`centri-di-raccolta` siano uniformi.

## 2. Tre livelli separati

### Livello sorgente

Conserva la prova di ciò che è stato pubblicato:

- URL finale e URL di provenienza;
- data e ora del prelievo;
- codice HTTP, tipo MIME, lingua e impronta SHA-256;
- contenuto originale o riferimento allo snapshot;
- data di pubblicazione o aggiornamento, quando disponibile;
- licenza e condizioni di riutilizzo, quando dichiarate.

Lo snapshot non viene modificato dopo l'acquisizione.

### Livello di acquisizione

Ogni estrattore produce record JSON Lines conformi a
`schemas/acquisition-record.schema.json`. I record sono tipizzati ma hanno una
busta comune con provenienza, evidenza testuale, versione dell'estrattore e
grado di affidabilita.

Un estrattore non decide la risposta finale per il cittadino. Registra quanto
afferma la fonte, comprese denominazioni locali, apparenti duplicati e
contraddizioni.

### Livello canonico

Un processo di normalizzazione risolve i riferimenti, collega i codici EER,
deduplica le strutture, assegna le aree territoriali e sottopone le anomalie a
controllo. Il database consigliato e PostgreSQL con PostGIS.

L'app legge esclusivamente viste/API derivate dal livello canonico. Il
contratto principale e descritto in `schemas/disposal-answer.schema.json`.
Il primo catalogo canonico materializzato segue inoltre
`schemas/waste-catalog.schema.json`; metodo e limiti sono descritti in
`docs/waste-catalog.md`.

## 3. Entita canoniche

### Territorio e organizzazione

| Entita | Identificatore stabile | Funzione |
| --- | --- | --- |
| `authority` | ID interno | Regione, ATO, comune |
| `municipality` | codice ISTAT | Comune e provincia |
| `operator` | ID interno + identificativi fiscali | Gestore del servizio |
| `service_zone` | ID interno | Frazione, quartiere o area con regole proprie |
| `service_assignment` | ID interno | Gestore e servizio validi in un territorio e periodo |

Una `service_zone` puo essere descritta inizialmente con nomi di localita e in
seguito dotata di geometria PostGIS. Deve sempre esistere una zona predefinita
per la parte del comune non coperta da zone piu specifiche.

ATO, provincia e gestore non sono gerarchie coincidenti. Il comune, identificato
dal codice ISTAT, e l'entita territoriale canonica; l'appartenenza ATO, il
gestore unico e la societa operativa locale sono assegnazioni distinte e
datate. Questo consente di rappresentare province divise tra piu ATO e ATO che
operano attraverso piu societa locali.

### Vocabolario dei rifiuti

| Entita | Funzione |
| --- | --- |
| `waste_concept` | Oggetto o famiglia comprensibile al cittadino |
| `waste_term` | Sinonimo, nome popolare, errore frequente o marchio generico |
| `waste_lookup` | Coppia nome-destinazione pubblicata da un gestore locale |
| `material` | Vetro, carta, sughero, bioplastica, ceramica ecc. |
| `component` | Parte separabile di un oggetto composto |
| `condition` | Vuoto, contaminato, rotto, contenente residui ecc. |
| `decision_question` | Domanda necessaria per risolvere un'ambiguita |
| `eer_entry` | Voce ufficiale dell'Elenco europeo dei rifiuti |

`eer_entry` contiene codice a sei cifre, titolo ufficiale, flag di
pericolosita, capitolo, sottocapitolo e riferimenti espansi ad altre voci. La
sigla CER puo essere mostrata nell'interfaccia perche ancora molto usata; il
modello usa `eer` come nome tecnico.

### Servizi e conferimento

| Entita | Funzione |
| --- | --- |
| `collection_stream` | Carta, organico, vetro, multimateriale ecc. |
| `collection_rule` | Destinazione e istruzioni valide per zona/utenza/periodo |
| `container_type` | Cassonetto, mastello, sacco, campana, box ecc. |
| `facility` | Centro di raccolta, stazione ecologica o area temporanea |
| `facility_access` | Comuni e tipi di utenza autorizzati, tessere e documenti |
| `facility_acceptance` | Voce EER o raggruppamento operativo accettato |
| `opening_period` | Intervallo stagionale e ricorrenza settimanale |
| `collection_schedule` | Calendario ordinario, quindicinale o per date esplicite |
| `collection_point` | Punto stradale speciale o batteria di cassonetti |
| `pickup_service` | Ritiro domiciliare, limiti e prenotazione |

La modalita di conferimento non e una proprieta intrinseca del rifiuto. E una
regola applicata a territorio, servizio, utenza e periodo. Deve poter indicare:

- sfuso, sacco di carta, sacco compostabile o sacco non compostabile;
- colore e tipo del contenitore;
- volume massimo del sacco;
- operazioni richieste: svuotare, piegare, separare, chiudere;
- calendario ed eventuale orario di esposizione;
- necessita di tessera o altra credenziale.

## 4. Provenienza e ciclo di vita

Ogni fatto acquisito e canonico deve avere:

- `source_url` e `retrieved_at`;
- `evidence` con testo, tabella, selettore o pagina PDF;
- `valid_from` e `valid_to`, anche se inizialmente null;
- `observed_at`, distinto dalla data di validita;
- `confidence`: `high`, `medium` o `low`;
- `review_status`: `automatic`, `reviewed`, `rejected` o `superseded`;
- versione dell'estrattore e impronta del documento sorgente.

Una nuova acquisizione con contenuto diverso apre una revisione. Non cancella
la regola precedente. Una regola senza data esplicita e considerata valida alla
data di osservazione, ma viene marcata come validita inferita.

## 5. Geolocalizzazione

Ordine delle fonti per i centri di raccolta:

1. coordinate pubblicate dal gestore o incorporate nel collegamento alla mappa;
2. dataset ufficiale di ATO, Regione o comune;
3. geocodifica dell'indirizzo pubblicato;
4. verifica manuale su ortofoto o mappa.

Ogni coordinata conserva `location_method`, fonte, accuratezza stimata e data
di verifica. Un indirizzo geocodificato non deve essere presentato come
posizione ufficiale.

I punti stradali sono una categoria distinta dai centri. Possono essere:

- una singola raccolta speciale, come olio, farmaci, pile o piccoli RAEE;
- una postazione completa di cassonetti;
- un punto mobile o temporaneo.

Molte pagine SEI descrivono questi punti soltanto in testo. In una prima fase
si memorizzano indirizzo e localita; la geocodifica avviene in un secondo
passaggio. Non si deduce la posizione di tutti i cassonetti quando la fonte
pubblica solo una descrizione generale del servizio.

## 6. Strategia di acquisizione SEI Toscana

### 6.1 Registro iniziale

1. Importare l'elenco ufficiale dei 104 comuni e i relativi codici ISTAT.
2. Individuare la pagina SEI di ciascun comune dalla pagina `comuni` o da un
   indice ufficiale.
3. Registrare i collegamenti effettivi a raccolta, centri e ritiro domiciliare.
4. Salvare anche Carta della qualita, guide, calendari e modulistica collegati.

### 6.2 Crawler

Il crawler deve essere cortese e ripetibile:

- rispettare `robots.txt`, condizioni d'uso e limiti del sito;
- usare un user-agent identificabile e un contatto;
- limitare frequenza e concorrenza per dominio;
- usare richieste condizionali con ETag e Last-Modified quando disponibili;
- non scaricare nuovamente contenuti con la stessa impronta;
- conservare errori, reindirizzamenti e data dell'ultimo tentativo;
- non automatizzare form di prenotazione o aree riservate.

### 6.3 Estrattori HTML

Per ogni pagina comunale estrarre per struttura semantica, non per posizione
visiva:

- titoli delle sezioni e tabelle di raccolta;
- zona o localita a cui si applica ogni tabella;
- flusso, contenitore, colore e modalita di conferimento;
- calendari porta a porta e date di attivazione;
- punti speciali descritti negli elenchi;
- collegamenti ai centri e ai servizi di ritiro;
- avvisi temporanei senza confonderli con la regola ordinaria.

Per i centri estrarre ciascun blocco separatamente: nome, indirizzo, coordinate
dal link mappa, periodi e orari, allegati, tabella EER, accesso e comuni serviti.
Lo stesso codice EER puo comparire piu volte con descrizioni operative diverse;
le righe vanno conservate e collegate a un'unica voce ufficiale.

### 6.4 PDF e documenti

I PDF vengono scaricati, classificati e analizzati dopo l'HTML. Prima si tenta
l'estrazione testuale e delle tabelle; l'OCR viene usato solo per documenti
scansionati. Ogni dato estratto conserva numero di pagina e frammento di testo.

In caso di conflitto, la priorita non e automaticamente assegnata all'HTML:
contano autorita della fonte, data di efficacia e specificita territoriale. Il
conflitto resta visibile finche non viene risolto.

### 6.5 Controlli automatici

- codice EER esistente e flag pericoloso coerente con l'asterisco;
- intervalli orari validi e non sovrapposti;
- coordinate dentro o vicino al territorio atteso;
- comune e centro non duplicati;
- regole sovrapposte per la stessa zona, utenza, flusso e periodo;
- contenitore o modalita mancanti;
- centro indicato come accessibile senza una relazione di accesso;
- link o documento modificato rispetto alla precedente acquisizione.

## 7. Pipeline proposta

```text
registro comuni e fonti
        -> snapshot HTML/PDF
        -> record JSONL tipizzati
        -> controlli sintattici
        -> risoluzione identita e geografia
        -> coda di revisione umana
        -> PostgreSQL/PostGIS canonico
        -> indice di ricerca
        -> API dell'app
```

Per la ricerca si parte da sinonimi e ricerca lessicale tollerante agli errori.
Gli embedding possono aiutare a proporre candidati, ma non devono inventare la
destinazione: la risposta finale deriva sempre da regole canoniche e citabili.

## 8. Sequenza del pilota

1. Manciano: un centro, raccolte territorialmente diverse e punti speciali.
2. Castagneto Carducci: centro comunale, area temporanea per il verde, tre zone
   porta a porta e accesso dei residenti di Sassetta.
3. Siena: nove zone, calendari settimanali, date esplicite per il vetro, punti
   speciali ed ecositi.
4. Campiglia Marittima: verifica degli orari stagionali dei centri. Completata.
5. Estensione automatica ai 104 comuni con rapporto di completezza. Registro
   dei comuni completato; scansione delle pagine da avviare.
6. Revisione delle anomalie e pubblicazione di una prima API in sola lettura.

Il rapporto di copertura deve contare comuni, zone, centri, accettazioni EER,
punti speciali, regole prive di fonte e record in conflitto. La percentuale di
pagine visitate, da sola, non misura la qualita del dataset.

## 9. Stato del pilota al 5 agosto 2026

L'estrattore e verificato su snapshot reali di Manciano, Castagneto Carducci,
Siena e Campiglia Marittima. La pagina del centro di Sassetta viene usata come
prova aggiuntiva per la relazione di accesso intercomunale. L'indice dei 104
comuni e stato riconciliato integralmente con l'elenco ISTAT aggiornato al 21
febbraio 2026.

Sono coperti:

- centri, coordinate da link cartografici, orari e accettazioni EER;
- accesso domestico, non domestico e intercomunale;
- raccolta stradale e porta a porta con zone distinte;
- contenitore, colore, sacchetto e istruzioni di esposizione;
- calendari settimanali e calendari con date esplicite;
- punti speciali, ecositi e aree temporanee;
- ritiro ingombranti e limiti pubblicati.

Gli snapshot sotto `tests/fixtures` contengono soltanto le sezioni DOM utili ai
test, per evitare limiti di trasferimento del browser di sviluppo. Il
downloader HTTP di produzione conserva invece il documento ricevuto per
intero.
