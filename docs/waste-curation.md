# Curatela di sinonimi, EER, flussi e canali

Versione: 1
Ultimo aggiornamento: 9 agosto 2026

## Scopo

Il registro `data/curation/waste-curation-v1.json` collega varianti linguistiche
dello stesso rifiuto, registra associazioni oggetto-EER revisionate e
normalizza i nomi dei flussi e dei canali usati dai gestori. Non modifica ne
elimina i concetti sorgente: ogni membro, destinazione territoriale ed evidenza
resta disponibile e aggiornabile in modo indipendente.

La curatela risolve due problemi distinti:

- sinonimi come `Tetra Pak`, `brick latte` e `cartone del latte` devono condurre
  allo stesso oggetto di ricerca;
- etichette come `Sacco carta` e `Carta e cartone` devono essere confrontabili
  senza dedurre il flusso da una somiglianza generica.
- formule come `Ecocentro, Ritiro ingombranti` devono esporre entrambi i canali
  disponibili senza trasformarli in un flusso di materiale.
- termini quotidiani come `tostapane` devono poter usare il codice EER del
  centro soltanto quando la corrispondenza e stata revisionata e delimitata.
- famiglie come RAEE, imballaggi, metalli, plastiche, legno, vetro, oli e
  inerti devono avere una classificazione portabile anche nei comuni privi di
  rifiutario, senza ereditare il cassonetto scelto da un altro gestore.

## Regole di sicurezza

Un gruppo di alias richiede membri esistenti, termini di ricerca espliciti,
motivazione e stato `approved`. Un concetto non puo appartenere a due gruppi.
Il registro iniziale esclude deliberatamente qualificatori che cambiano il
rifiuto: finto sughero, medicinali, residui, profumi e famiglie generiche di
gusci non vengono assorbiti dai gruppi piu ampi.

I flussi usano corrispondenze normalizzate esatte. Lo stesso alias non puo
indicare due flussi. Le differenze territoriali non vengono fuse: il motore
aggrega i membri, poi seleziona esclusivamente le destinazioni pubblicate per
il comune richiesto. Destinazioni diverse nello stesso comune restano un
conflitto, salvo che il registro le riconduca esplicitamente allo stesso flusso.

I canali sono riconosciuti soltanto come frasi complete approvate. Il testo
originale della destinazione resta sempre nella risposta: conserva condizioni,
limitazioni e formulazioni che il primo scompositore non interpreta. Quando una
fonte elenca piu canali, la relazione e `alternatives`; il motore non sceglie al
posto dell'utente e non collega per somiglianza una regola di cassonetto.

Ogni mappatura EER richiede codice normalizzato, concetti esistenti, fonte,
motivazione e stato `approved`. Un concetto non puo ricevere due mappature
concorrenti. Le condizioni, per esempio l'assenza di componenti pericolosi,
sono mostrate nella risposta e non vengono eliminate durante la distribuzione.

Le `waste_classes` descrivono classi EER riutilizzabili. Una classe puo avere
un unico percorso oppure una domanda con esiti EER completi. Le
`family_mappings` collegano categorie sorgente, destinazioni controllate e
pattern terminologici revisionati a queste classi. Le classi della stessa
dimensione sono alternative: prevale la regola con priorita maggiore; una
parita resta un conflitto. Dimensioni compatibili, come materiale e dimensione
fisica, possono invece comporsi.

## Contenuto iniziale

Il registro comprende inoltre 23 classi portabili e 31 regole di famiglia. Le
domande condivise coprono, fra gli altri, RAEE, imballaggi contaminati o misti,
metalli, plastiche, legno, vetro, oli, toner, inerti e recipienti a pressione.

Il nucleo linguistico comprende:

- 4 gruppi approvati e 33 concetti membri;
- 17 termini di ricerca approvati;
- 4 mappature EER approvate per 14 concetti;
- 7 flussi canonici e 34 alias di flusso;
- 7 canali di conferimento e 28 alias di canale;
- cartoni per bevande, tappi di vero sughero, bottiglie di vetro generiche e
  varianti singolare/plurale dei gusci di molluschi;
- organico, carta, vetro, multimateriale, residuo, plastica e metalli.

La validazione sul catalogo corrente conta 191 etichette di destinazione e
4.508 associazioni. Gli alias di flusso mappano 27 etichette e 2.132
associazioni, senza conflitti territoriali nei gruppi approvati.

I canali riconoscono 111 etichette e 1.954 associazioni. In 48 etichette, pari
a 874 associazioni, la fonte pubblica piu alternative: centro di raccolta,
servizio mobile, ritiro, punto di raccolta, rivenditore, operatore specializzato
o riuso vengono restituiti separatamente insieme alla formulazione sorgente.

## Validazione

```sh
PYTHONPATH=src python3 -m dovelobutto.cli validate-waste-curation \
  --register data/curation/waste-curation-v1.json \
  --catalog outputs/waste-catalog.json \
  --report outputs/waste-curation-report.json
```

Il rapporto elenca copertura, conflitti, destinazioni con piu canali e formule
ancora prive sia di flusso sia di canale controllato.

La copertura portabile dell'intero vocabolario si verifica separatamente:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli audit-routing-coverage \
  --catalog outputs/waste-catalog.json \
  --curation data/curation/waste-curation-v1.json \
  --generated-at 2026-08-09T03:45:00+02:00 \
  --output outputs/waste-routing-coverage-report.json
```

Una destinazione osservata presso un gestore non basta a superare questo audit.
Ogni concetto deve avere una classe, un EER revisionato o una domanda completa;
parziali, conflitti e non classificati mantengono `release_ready: false`.

## Distribuzione

Gruppi, mappature EER, classi, regole di famiglia, flussi e canali diventano
normali entita canoniche: `waste_alias_group`, `waste_eer_mapping`,
`waste_class`, `waste_family_mapping`, `collection_stream` e
`delivery_channel`. Le dipendenze verso concetti, classi e voci EER impediscono
a snapshot e delta di pubblicare riferimenti mancanti.

La pubblicazione include il registro con:

```sh
--waste-curation-register data/curation/waste-curation-v1.json
```

Le app ricevono la curatela con la stessa revisione atomica del resto dei dati.
Un aggiornamento puo aggiungere un alias o correggere un gruppo senza richiedere
una nuova versione dell'app.
