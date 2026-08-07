# Catalogo canonico dei rifiuti

Versione: 0.3.0
Ultimo aggiornamento: 7 agosto 2026

## Obiettivo

Il catalogo separa la conoscenza riutilizzabile sul rifiuto dalle regole di
conferimento locali. Un termine, una categoria o un'associazione EER possono
essere condivisi tra territori; cassonetto, sacchetto, centro e ritiro sono
invece fatti validi soltanto per il comune, la zona, l'utenza e il periodo
indicati dalla fonte.

Il contratto e definito in `schemas/waste-catalog.schema.json`. L'output
corrente e `outputs/waste-catalog.json`, accompagnato dal rapporto
`outputs/waste-catalog-report.json`.

## Costruzione

```sh
PYTHONPATH=src python3 -m dovelobutto.cli build-waste-catalog \
  --input-dir outputs/sei-toscana \
  --input-dir outputs/ato-toscana-costa \
  --registry outputs/sei-toscana-municipalities.jsonl \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --eer-register outputs/eer-register.json \
  --generated-at 2026-08-06T23:00:00+02:00 \
  --output outputs/waste-catalog.json \
  --report outputs/waste-catalog-report.json
```

La normalizzazione automatica interviene soltanto su maiuscole, accenti,
spazi e punteggiatura. Non unisce automaticamente parole simili, singolari e
plurali o oggetti semanticamente vicini: questi collegamenti richiedono una
regola esplicita o una revisione.

Le copie dello stesso rifiutario condiviso, materializzate per piu comuni, sono
aggregate in una sola indicazione sorgente mantenendo l'elenco completo dei
comuni coperti. Destinazioni differenti vengono conservate come osservazioni
locali, non trattate come contraddizioni globali.

## Stato corrente

- 138.342 record locali di rifiutario analizzati;
- 3.880 indicazioni sorgente distinte dopo la deduplicazione;
- 3.124 concetti canonici iniziali;
- 331 concetti con un EER concordante pubblicato dalla fonte;
- nessun conflitto EER per i termini coincidenti;
- 2.553 concetti ancora senza EER;
- 411 concetti con piu destinazioni locali osservate.

`source_consensus` significa che tutte le fonti che pubblicano un EER per quel
termine indicano lo stesso codice. Ogni candidato e ora controllato anche
contro `outputs/eer-register.json` e conserva titolo e pericolosita ufficiali.
La destinazione continua invece a essere un'osservazione territoriale.

Il registro collegato e l'edizione futura applicabile dal 9 dicembre 2026. I
codici `20 01 33` e `20 01 34` sono quindi marcati `retired_in_target`, senza
essere descritti come invalidi alla data di acquisizione delle fonti.

## Arricchimento generale

Materiale, componenti, condizioni, sinonimi semantici, domande decisionali e
note ambientali sono presenti nel modello ma restano null o vuoti finche non
sono sostenuti da una fonte o da una revisione. Il prossimo ciclo deve:

1. produrre candidati di sinonimia senza applicarli automaticamente;
2. modellare le condizioni che cambiano la risposta, come contenuto residuo,
   materiale, dimensione o presenza di componenti pericolosi;
3. aggiungere spiegazioni ed effetti ambientali da fonti istituzionali;
4. introdurre una coda di revisione con autore, motivazione e data.

Il primo registro separato di curatela e descritto in
`docs/waste-curation.md`. Consolida soltanto gruppi approvati e mantiene
immutati concetti, destinazioni ed evidenze sorgente.
