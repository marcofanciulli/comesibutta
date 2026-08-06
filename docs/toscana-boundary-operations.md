# Comuni toscani in ATO extra-regionali

## Perimetro

Il lotto completa il perimetro amministrativo della Toscana con quattro comuni
che appartengono ad ambiti con sede fuori regione:

- Firenzuola, Marradi e Palazzuolo sul Senio (FI), nel bacino bolognese
  dell'ATO unico dell'Emilia-Romagna;
- Sestino (AR), nell'ATO 1 Marche - Pesaro e Urbino.

Il registro conserva separatamente regione, provincia, ATO e gestore. Gli ATO
extra-regionali comprendono nell'app soltanto i comuni situati in Toscana.

## Fonti e limiti

Per i tre comuni fiorentini la pipeline usa le API JSON di sola lettura
richiamate dall'interfaccia pubblica `Il Rifiutologo` di Hera. Il sottodominio
API pubblica un `robots.txt` senza divieti. L'acquisizione comprende:

- rifiutario e sinonimi ufficiali;
- destinazioni e istruzioni, compreso il tipo di sacchetto quando pubblicato;
- punti di raccolta geolocalizzati;
- stazioni ecologiche, accesso, orari, chiusure, materiali e limiti.

Le modalità di raccolta possono dipendere dall'indirizzo. La pipeline interroga
un indirizzo campione dichiarato per ciascun comune e marca queste regole a
confidenza media e con ambito `named_area`; non le presenta come valide per
l'intero territorio. Le schede dei centri mantengono invece il loro ambito
autonomo.

Per Sestino le fonti pubbliche del gestore consentono di verificare il servizio
di ritiro domiciliare. Il rifiutario e le schede dei centri sono dichiarati
disponibili nell'app Marche Multiservizi, ma non in una versione web acquisibile
individuata. Inoltre il `robots.txt` del sito istituzionale del Comune vieta
l'acquisizione automatica dell'intero sito. Questi limiti sono avvisi espliciti
nel rapporto e nell'esploratore; non vengono sostituiti con regole generali del
gestore attribuite arbitrariamente al comune.

## Esecuzione

```sh
PYTHONPATH=src python3 -m dovelobutto.cli build-boundary-registry \
  --istat-csv data/sources/istat/toscana-comuni-2026-02-21.csv \
  --retrieved-at 2026-08-07T12:00:00+02:00 \
  --output outputs/toscana-boundary-municipalities.jsonl \
  --report outputs/toscana-boundary-municipalities-report.json

PYTHONPATH=src python3 -m dovelobutto.cli fetch-boundary \
  --bundle data/crawl/toscana-boundary/bundle.json \
  --report outputs/toscana-boundary-fetch-report.json \
  --observed-at 2026-08-07T12:00:00+02:00 \
  --user-agent 'DoveLoButtoData/0.1 (+mailto:marcofanciulli@me.com)' \
  --delay 0.5

PYTHONPATH=src python3 -m dovelobutto.cli materialize-boundary \
  --registry outputs/toscana-boundary-municipalities.jsonl \
  --bundle data/crawl/toscana-boundary/bundle.json \
  --retrieved-at 2026-08-07T12:00:00+02:00 \
  --output-dir outputs/toscana-boundary \
  --report outputs/toscana-boundary-report.json
```

Il bundle di lavoro viene aggiornato atomicamente dopo ogni voce del
rifiutario. Un'esecuzione interrotta riparte dalle sole richieste mancanti.
