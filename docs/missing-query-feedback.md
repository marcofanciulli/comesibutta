# Ricerche senza risposta

Le formulazioni che il vocabolario non riconosce alimentano una coda editoriale
separata dal dataset distribuito. Il backend registra una voce soltanto quando
`POST /api/answer` restituisce `not_found`; suggerimenti, domande di chiarimento
e risposte risolte non incrementano la coda.

## Dati conservati

Le occorrenze uguali vengono aggregate per formulazione normalizzata, comune,
zona, tipo di utenza e motivo. Ogni voce conserva testo rappresentativo, prima
e ultima osservazione, prima e ultima revisione dati e contatore. Non vengono
conservati IP, coordinate, account o identificativi del dispositivo. Testi con
email, URL o sequenze di almeno sette cifre vengono scartati.

I due motivi distinti sono:

- `unknown_term`: il vocabolario non riconosce la formulazione;
- `known_without_route`: il concetto e noto ma manca ancora un percorso.

La frequenza serve a ordinare il lavoro, non autorizza una risposta. Una voce
puo diventare `accepted`, `rejected` o `mapped` soltanto dopo controllo di
liceita, significato, sinonimi, pericolosita, EER e fonti territoriali.

## Esercizio

`serve-app` usa per impostazione predefinita
`data/feedback/missing-queries.sqlite`, escluso da Git e dai pacchetti dati. Il
percorso puo essere cambiato con `--feedback-database`.

La coda aggregata si esporta in JSON:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli export-missing-queries \
  --database data/feedback/missing-queries.sqlite \
  --min-count 2 \
  --output outputs/missing-query-report.json
```

Dopo la valutazione, una voce si aggiorna tramite il fingerprint esportato:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli review-missing-query \
  --database data/feedback/missing-queries.sqlite \
  --fingerprint HASH \
  --status accepted \
  --note "Aggiungere come sinonimo dopo verifica delle fonti"
```

Il formato dell'esportazione e definito da
`schemas/missing-query-report.schema.json`. In produzione il database deve
avere backup, accesso limitato e una politica di conservazione coerente con
l'informativa privacy del servizio.
