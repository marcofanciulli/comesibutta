# Ricerca e risposta dell'app

Versione: 0.1.0
Ultimo aggiornamento: 7 agosto 2026

## Scopo

Il livello di lettura risponde alla domanda "Dove lo butto?" usando il database
SQLite sincronizzato. La somiglianza lessicale seleziona candidati; soltanto le
destinazioni territoriali pubblicate dalle fonti possono formare una risposta.
Il motore non deduce mai un cassonetto dal nome del rifiuto.

## Indice sincronizzato

La versione 5 del formato SQLite aggiunge `waste_search_terms`, un indice
derivato dalle etichette e dai sinonimi dei concetti. Viene aggiornato nella
stessa transazione degli snapshot e dei delta, ha una chiave esterna verso
l'entita canonica e viene eliminato automaticamente insieme al concetto.

L'indice non e un artefatto autonomo e non introduce una nuova revisione. Un
client col precedente formato deve essere ricostruito dallo snapshot corrente,
come gia previsto per le modifiche dello storage locale.

## Strategia di risposta

1. Normalizza accenti, maiuscole e punteggiatura.
2. Confronta sequenza e parole, tollerando piccoli errori di digitazione.
3. Applica i gruppi di sinonimi approvati dal registro di curatela.
4. Mantiene distinti punteggio semantico e disponibilita nel comune.
5. Per una corrispondenza incerta propone soltanto le interpretazioni che hanno
   una destinazione pubblicata nel territorio, se disponibili.
6. Dopo la scelta del concetto legge la destinazione territoriale.
7. Se il rifiutario locale manca, cerca un EER concordante accettato con lo
   stesso codice da un centro accessibile; in assenza di EER usa una descrizione
   del centro soltanto quando identifica un unico codice senza ambiguita.
8. Normalizza destinazione e regola tramite il vocabolario controllato dei
   flussi.
9. Scompone gli eventuali canali di conferimento approvati e conserva il testo
   originale con condizioni e alternative.
10. Collega, quando possibile, la destinazione alla regola locale per ricavare
   contenitore, colore, modalita, sacchetto e istruzioni.
11. Per il canale centro usa soltanto accessi pubblicati e verifica
    l'accettazione tramite EER o descrizione.
12. Collega ritiri e punti territoriali, mantenendo distinta l'esistenza del
    servizio dalla compatibilita col rifiuto.
13. Conserva riuso, rivenditore e operatore specializzato come indicazioni
    sorgente finche non esiste un servizio acquisito.
14. Se regole di zone diverse producono risposte differenti chiede la zona.
15. Restituisce fonti, data di verifica e revisione del dataset.

Gli stati sono:

- `resolved`: concetto e destinazione territoriale sono determinati;
- `needs_question`: serve scegliere concetto o zona;
- `not_found`: manca una corrispondenza o una destinazione per il comune;
- `conflict`: le fonti territoriali pubblicano destinazioni differenti;
- `outdated`: riservato a dati non piu applicabili.

Una risposta `not_found` ha fonti vuote: l'assenza di un risultato non viene
presentata come fatto attestato da una pagina. Risposte risolte, in conflitto o
scadute devono invece conservare almeno una fonte.

## Uso

```sh
PYTHONPATH=src python3 -m dovelobutto.cli query-disposal \
  --database data/canonical/client.sqlite \
  --text "confezzione del latte" \
  --municipality 048017 \
  --as-of 2026-08-07
```

## Audit di copertura territoriale

Prima di pubblicare un dataset, l'audit attraversa tutte le combinazioni fra
voci con una destinazione pubblicata, comuni coperti e zone di servizio, e per
ognuna esegue il compositore di risposta usato dall'app. Verifica anche che gli
alias approvati siano ricercabili in modo esatto e che nessun riferimento
territoriale punti a un comune assente:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli audit-query-coverage \
  --database data/canonical/client.sqlite \
  --generated-at 2026-08-08T19:30:00+02:00 \
  --output outputs/query-coverage-report.json
```

`status: pass` certifica gli invarianti strutturali delle risposte territoriali.
`release_ready` resta invece falso quando la coda `review_queue` contiene coppie
di termini molto simili con coperture diverse: possono essere sinonimi da
riconciliare oppure rifiuti distinti, e richiedono una decisione esplicita.
Risposte definite ma non risolte, come conflitti pubblicati dalle fonti, sono
conservate con il loro contesto in `defined_non_resolved`.

L'audit non estende una regola locale a una voce generale priva di evidenza per
quel territorio. Una simile estensione inventerebbe una destinazione non
pubblicata dalla fonte competente.

Il client puo aggiungere la posizione della singola richiesta:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli query-disposal \
  --database data/canonical/client.sqlite \
  --text "armadio" \
  --municipality 048017 \
  --latitude 43.7954 \
  --longitude 11.2281 \
  --as-of 2026-08-07
```

Se la risposta e `needs_question`, il client ripete la richiesta passando
l'identificatore scelto:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli query-disposal \
  --database data/canonical/client.sqlite \
  --text "confezzione del latte" \
  --concept waste-alias:beverage-carton \
  --municipality 048017 \
  --as-of 2026-08-07
```

Il parametro `--zone` permette la seconda fase di disambiguazione territoriale.
Sito, app e backend possono usare direttamente `DisposalQueryService` e
ricevono lo stesso oggetto definito da `schemas/disposal-answer.schema.json`.

## Collaudo regionale e limiti

Il collaudo ha materializzato 156.045 entita e 3.124 termini indicizzati. Ha
verificato ricerca esatta, errori di digitazione, scelta guidata, differenze di
zona, conflitti, aggiornamento incrementale dell'indice e assenza di risposte
inventate.

Con il registro di curatela il dataset sale a 156.062 entita. Il risultato
espone anche `stream_id`, stabile tra gestori: per esempio `Sacco carta` e
`Carta e cartone` diventano `stream:paper` pur conservando le etichette
originali nelle fonti.

Il risultato separa inoltre `source_destination` da `delivery_channels`. Nel
caso reale di Firenze, `Armadio` conserva la destinazione pubblicata
`Ecocentro, Ritiro ingombranti` ed espone sia il centro sia il ritiro come
alternative. Finche non viene risolta la struttura o il servizio concreto, il
campo `stream` resta vuoto: un canale non viene presentato come materiale.

Il canale centro e ora risolto tramite le relazioni di accesso esplicite. La
risposta include accettazione, stato, distanza, indirizzo, accesso, contatti e
orari. Senza GPS piu centri equivalenti restano in `facility_alternatives`;
con il GPS il piu vicino tra quelli compatibili e non chiusi diventa
`facility`. La politica completa e descritta in `docs/facility-resolution.md`.

Ritiri e punti vengono restituiti in `channel_services`, con prenotazione,
limiti, istruzioni, posizione e stato di compatibilita. I canali privi di un
servizio dimostrabile entrano in `unresolved_channels`; la loro formulazione
originale non viene persa. La politica e descritta in
`docs/channel-services.md`.

Il primo livello risolve destinazioni e preparazione quando i due fatti sono
collegabili. Restano da completare:

- estensione progressiva del registro oltre i primi gruppi approvati;
- pulizia conservativa dei testi di accesso che includono parti redazionali;
- acquisizione delle schede materiali richiamate dai punti mobili AliaEstra;
- vicinanza geografica, orari, stato del servizio e procedura di accesso;
- arricchimento delle regole di preparazione non pubblicate in forma
  strutturata dai gestori.
