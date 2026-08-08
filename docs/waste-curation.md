# Curatela di sinonimi, EER, flussi e canali

Versione: 1
Ultimo aggiornamento: 8 agosto 2026

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

## Contenuto iniziale

Il registro comprende:

- 3 gruppi approvati e 30 concetti membri;
- 14 termini di ricerca approvati;
- 4 mappature EER approvate per 14 concetti;
- 7 flussi canonici e 34 alias di flusso;
- 7 canali di conferimento e 28 alias di canale;
- cartoni per bevande, tappi di vero sughero e bottiglie di vetro generiche;
- organico, carta, vetro, multimateriale, residuo, plastica e metalli.

La validazione sul catalogo corrente conta 191 etichette di destinazione e
4.493 associazioni. Gli alias di flusso mappano 27 etichette e 2.124
associazioni, senza conflitti territoriali nei gruppi approvati.

I canali riconoscono 111 etichette e 1.947 associazioni. In 48 etichette, pari
a 867 associazioni, la fonte pubblica piu alternative: centro di raccolta,
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

## Distribuzione

Gruppi, mappature EER, flussi e canali diventano normali entita canoniche,
rispettivamente `waste_alias_group`, `waste_eer_mapping`, `collection_stream`
e `delivery_channel`. Gruppi e mappature dipendono dai concetti e, per le
seconde, dalla voce EER ufficiale; snapshot e delta impediscono quindi di
pubblicare riferimenti mancanti.

La pubblicazione include il registro con:

```sh
--waste-curation-register data/curation/waste-curation-v1.json
```

Le app ricevono la curatela con la stessa revisione atomica del resto dei dati.
Un aggiornamento puo aggiungere un alias o correggere un gruppo senza richiedere
una nuova versione dell'app.
