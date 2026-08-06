# Sincronizzazione remota dei dati

Versione: 0.1.0
Data: 6 agosto 2026

## 1. Obiettivo

L'applicazione e il dataset hanno cicli di rilascio separati. Una modifica a un
orario, a una regola comunale o a un centro di raccolta deve poter raggiungere
l'app senza richiedere una nuova versione del software e senza scaricare
l'intera base dati.

Il protocollo deve:

- aggiornare un client a partire da qualsiasi revisione ancora supportata;
- trasferire soltanto le entita cambiate quando questo e conveniente;
- applicare insieme tutte le modifiche correlate;
- non lasciare mai riferimenti interrotti nel database locale;
- distinguere pubblicazione, osservazione e periodo di validita dei fatti;
- consentire verifica, ripresa, rollback e controllo della provenienza.

## 2. Revisione globale e identificatori

Ogni pubblicazione valida riceve una revisione globale intera e crescente. La
revisione identifica uno stato coerente dell'intero dataset, non una singola
tabella. Un formato leggibile come `202608060003` puo essere usato purche il
valore rimanga monotono.

Ogni entita canonica ha un identificatore stabile che non dipende dal nome
visualizzato, dalla posizione in un array o dall'URL della fonte. Esempi:

- `municipality:053011`, basato sul codice ISTAT;
- `eer:200138`, basato sul codice ufficiale;
- `facility:sei-toscana:grosseto:nomadelfia`;
- `opening-period:sei-toscana:grosseto:nomadelfia:ordinario-1`.

Un record conserva inoltre la revisione in cui e stato modificato l'ultima
volta. Un cambio di denominazione non cambia l'identita. Una fusione o una
separazione di entita viene rappresentata esplicitamente con sostituzioni e
riferimenti, non riutilizzando un ID con un significato diverso.

## 3. Manifest, snapshot e pacchetti

Il punto di ingresso e un manifest conforme a
`schemas/data-manifest.schema.json`. Dichiara:

- revisione corrente e versione dello schema canonico;
- revisione minima aggiornabile in modo incrementale;
- snapshot completo corrente;
- pacchetti incrementali gia preparati;
- dimensione, compressione, SHA-256 e firma di ogni artefatto.

Un pacchetto conforme a `schemas/data-update-package.schema.json` contiene una
transazione ordinata di `upsert` e `delete`. Gli `upsert` trasportano il record
canonico completo, non una patch JSON dipendente dalla forma precedente del
record. Questo rende il pacchetto idempotente e riduce la fragilita durante
l'evoluzione dei dati.

Le cancellazioni sono tombstone con ID, tipo, revisione e data. Il backend le
conserva almeno per tutta la finestra di aggiornamento incrementale, affinche
anche un client rimasto offline apprenda che l'entita non esiste piu.

## 4. Delta da qualsiasi revisione

Il backend conserva un changelog canonico append-only. Ricevuta la revisione
del client, calcola lo stato finale di tutte le entita modificate dopo quella
revisione e genera un unico delta fino alla revisione corrente. Modifiche
intermedie gia superate non devono essere inviate.

I percorsi comuni vengono preparati e messi in cache:

- delta giornalieri per i client quasi aggiornati;
- consolidati settimanali;
- consolidati mensili;
- checkpoint annuali;
- snapshot completo corrente.

Una revisione meno comune puo essere servita generando e memorizzando il delta
su richiesta. Non si producono in anticipo tutte le coppie possibili di
revisioni. Il piano di aggiornamento minimizza i byte complessivi e puo
scegliere un singolo delta, una sequenza di pacchetti oppure uno snapshot.

La finestra incrementale prevista e di cinque anni. Per un client piu vecchio,
per una revisione sconosciuta o per uno schema non migrabile, il server propone
lo snapshot corrente.

## 5. Applicazione atomica sul client

La base locale consigliata e SQLite con chiavi esterne abilitate. Il client:

1. scarica il manifest e ne verifica firma e versione;
2. seleziona il piano compatibile con la propria revisione e lo spazio libero;
3. scarica ogni artefatto in un file temporaneo riprendibile;
4. verifica dimensione, SHA-256 e firma prima di aprirlo;
5. controlla `dataset_id`, schema e revisione di partenza;
6. applica tutte le operazioni in una singola transazione SQLite;
7. verifica chiavi esterne, conteggi e revisione finale;
8. aggiorna la revisione locale e rende visibili i dati con il commit.

Qualsiasi errore produce un rollback completo. Il pacchetto resta separato dal
database attivo finche tutte le verifiche non sono superate. Riapplicare un
pacchetto gia concluso non modifica il risultato.

Gli inserimenti e gli aggiornamenti sono ordinati prima delle cancellazioni;
le dipendenze dichiarate nel pacchetto permettono ulteriori controlli. Una
cancellazione referenziata deve essere accompagnata nello stesso pacchetto
dalla modifica o cancellazione delle entita dipendenti.

## 6. Schema e compatibilita

`schema_version` e distinto dalla revisione dei dati. Le migrazioni SQLite sono
distribuite con l'app e non come SQL remoto eseguibile. Il manifest dichiara le
versioni minime e massime del client quando una modifica non e retrocompatibile.

Una nuova proprieta facoltativa puo essere distribuita ai client che la
ignorano. Una modifica incompatibile richiede prima una versione dell'app che
conosca la relativa migrazione. Il backend continua a offrire, per un periodo
definito, l'ultima linea dati compatibile con i client supportati.

## 7. Temporalita e provenienza

La revisione dice quando un fatto e entrato nel dataset, non quando diventa
vero. Ogni fatto mantiene separatamente:

- `observed_at`: quando la fonte e stata controllata;
- `published_at`: quando il dataset lo ha pubblicato;
- `valid_from` e `valid_to`: periodo di efficacia;
- riferimenti e impronte delle fonti.

Questo consente, per esempio, di distribuire nell'agosto 2026 una voce EER
aggiornata che abbia `valid_from: 2026-11-09`, mostrandola come futura fino a
quella data.

## 8. Sicurezza e recupero

Gli artefatti sono immutabili e identificati da hash. Il manifest e i pacchetti
sono firmati con Ed25519; l'app contiene soltanto le chiavi pubbliche ammesse e
supporta la rotazione tramite identificatore della chiave. HTTPS resta
obbligatorio, ma non sostituisce firma e checksum.

Il client conserva almeno l'ultimo stato valido o un backup transazionale
finche il nuovo stato non e attivo. Il backend registra metriche aggregate su
revisioni richieste, errori di verifica e uso degli snapshot, senza richiedere
dati personali o posizione precisa dell'utente.

## 9. Conservazione lato backend

Per almeno cinque anni si conservano:

- changelog canonico e tombstone;
- manifest pubblicati;
- checkpoint annuali e mensili;
- pacchetti consolidati necessari ai percorsi supportati;
- fonti e prove che hanno prodotto ogni revisione.

I delta giornalieri e settimanali possono essere compattati quando non servono
piu come percorso ottimale, pur mantenendo il changelog necessario a rigenerare
un delta da qualunque revisione supportata. La storia editoriale canonica non
viene eliminata insieme ai pacchetti di distribuzione.

## 10. Contratti iniziali

- `schemas/data-manifest.schema.json`: indice delle revisioni distribuibili;
- `schemas/data-update-package.schema.json`: snapshot e delta atomici;
- `examples/data-manifest.json`: manifest illustrativo;
- `examples/data-update-package.json`: aggiornamento illustrativo di un orario.

Questi contratti sono indipendenti dal trasporto. In produzione gli artefatti
JSON possono essere compressi con Zstandard; durante sviluppo e debug possono
restare JSON non compresso.
