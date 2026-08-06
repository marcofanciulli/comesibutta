# Catalogo canonico dei rifiuti

Versione: 0.1.0  
Ultimo aggiornamento: 6 agosto 2026

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
  --generated-at 2026-08-06T21:30:00+02:00 \
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

- 14.711 record locali di rifiutario analizzati;
- 995 indicazioni sorgente distinte dopo la deduplicazione;
- 818 concetti canonici iniziali;
- 331 concetti con un EER concordante pubblicato dalla fonte;
- nessun conflitto EER per i termini coincidenti;
- 487 concetti ancora senza EER;
- 135 concetti con piu destinazioni locali osservate.

`source_consensus` significa che tutte le fonti che pubblicano un EER per quel
termine indicano lo stesso codice. Non significa ancora che il codice sia
stato validato contro l'elenco EER ufficiale. Per questo l'esploratore usa la
dicitura "EER indicato dalla fonte".

## Arricchimento generale

Materiale, componenti, condizioni, sinonimi semantici, domande decisionali e
note ambientali sono presenti nel modello ma restano null o vuoti finche non
sono sostenuti da una fonte o da una revisione. Il prossimo ciclo deve:

1. importare l'elenco EER ufficiale completo e collegare titoli, pericolosita,
   capitoli, sottocapitoli e riferimenti;
2. produrre candidati di sinonimia senza applicarli automaticamente;
3. modellare le condizioni che cambiano la risposta, come contenuto residuo,
   materiale, dimensione o presenza di componenti pericolosi;
4. aggiungere spiegazioni ed effetti ambientali da fonti istituzionali;
5. introdurre una coda di revisione con autore, motivazione e data.
