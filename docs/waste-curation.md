# Curatela di sinonimi e flussi

Versione: 1
Ultimo aggiornamento: 7 agosto 2026

## Scopo

Il registro `data/curation/waste-curation-v1.json` collega varianti linguistiche
dello stesso rifiuto e normalizza i nomi dei flussi usati dai gestori. Non
modifica ne elimina i concetti sorgente: ogni membro, destinazione territoriale
ed evidenza resta disponibile e aggiornabile in modo indipendente.

La curatela risolve due problemi distinti:

- sinonimi come `Tetra Pak`, `brick latte` e `cartone del latte` devono condurre
  allo stesso oggetto di ricerca;
- etichette come `Sacco carta` e `Carta e cartone` devono essere confrontabili
  senza dedurre il flusso da una somiglianza generica.

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

## Contenuto iniziale

Il registro comprende:

- 3 gruppi approvati e 29 concetti membri;
- 14 termini di ricerca approvati;
- 7 flussi canonici e 34 alias di flusso;
- cartoni per bevande, tappi di vero sughero e bottiglie di vetro generiche;
- organico, carta, vetro, multimateriale, residuo, plastica e metalli.

La validazione sul catalogo corrente conta 189 etichette di destinazione e
4.065 associazioni. I primi alias mappano 28 etichette e 1.938 associazioni,
pari al 47,7%, senza conflitti territoriali nei gruppi approvati.

## Validazione

```sh
PYTHONPATH=src python3 -m dovelobutto.cli validate-waste-curation \
  --register data/curation/waste-curation-v1.json \
  --catalog outputs/waste-catalog.json \
  --report outputs/waste-curation-report.json
```

Il rapporto elenca copertura, conflitti e destinazioni ancora non mappate. Le
piu frequenti tra queste ultime sono percorsi composti, come ecocentro piu
ritiro o stazione ecologica piu ecomobile: devono essere scomposti in canali di
conferimento, non trasformati in un singolo flusso.

## Distribuzione

Gruppi e flussi diventano normali entita canoniche, rispettivamente
`waste_alias_group` e `collection_stream`. I gruppi dipendono dai concetti
membri; snapshot e delta impediscono quindi di pubblicare riferimenti mancanti.

La pubblicazione include il registro con:

```sh
--waste-curation-register data/curation/waste-curation-v1.json
```

Le app ricevono la curatela con la stessa revisione atomica del resto dei dati.
Un aggiornamento puo aggiungere un alias o correggere un gruppo senza richiedere
una nuova versione dell'app.
