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
3. Mantiene distinti punteggio semantico e disponibilita nel comune.
4. Per una corrispondenza incerta propone soltanto le interpretazioni che hanno
   una destinazione pubblicata nel territorio, se disponibili.
5. Dopo la scelta del concetto legge la destinazione territoriale.
6. Collega, quando possibile, la destinazione alla regola locale per ricavare
   contenitore, colore, modalita, sacchetto e istruzioni.
7. Se regole di zone diverse producono risposte differenti chiede la zona.
8. Restituisce fonti, data di verifica e revisione del dataset.

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

Se la risposta e `needs_question`, il client ripete la richiesta passando
l'identificatore scelto:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli query-disposal \
  --database data/canonical/client.sqlite \
  --text "confezzione del latte" \
  --concept waste:cartone-del-latte-tetra-pak \
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

Il primo livello risolve destinazioni e preparazione quando i due fatti sono
collegabili. Restano da completare:

- consolidamento editoriale dei sinonimi che oggi formano concetti distinti;
- mappatura controllata tra nomi di destinazione e flussi di raccolta;
- risoluzione del centro accessibile e di eventuali alternative limitrofe;
- vicinanza geografica, orari, stato del servizio e procedura di accesso;
- arricchimento delle regole di preparazione non pubblicate in forma
  strutturata dai gestori.
