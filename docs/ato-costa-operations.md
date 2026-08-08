# Operazioni ATO Toscana Costa

Versione: 0.1.0  
Ultimo aggiornamento: 6 agosto 2026

## Perimetro e registro

ATO Toscana Costa comprende 100 comuni: 13 in provincia di Livorno, 33 di
Lucca, 17 di Massa-Carrara e 37 di Pisa. RetiAmbiente e il gestore unico; il
servizio e svolto attraverso 12 societa operative locali (SOL).

La fonte ufficiale 2026 e conservata in
`data/sources/ato-toscana-costa/`. Il CSV normalizzato mantiene le 100 righe e
gli stati particolari di Porto Azzurro, Peccioli e Lucca. Il registro si genera
con:

```sh
PYTHONPATH=src python3 -m dovelobutto.cli build-ato-costa-registry \
  --assignment-csv data/sources/ato-toscana-costa/municipalities-sol-2026.csv \
  --istat-csv data/sources/istat/toscana-comuni-2026-02-21.csv \
  --retrieved-at 2026-08-06T14:00:00+02:00 \
  --output outputs/ato-toscana-costa-municipalities.jsonl \
  --report outputs/ato-toscana-costa-municipalities-report.json
```

L'alias ufficiale ATO `Vagli di Sotto` viene riconciliato esplicitamente con
la denominazione ISTAT `Vagli Sotto`.

## ESA

L'acquisizione ESA parte dalle pagine condivise della raccolta differenziata e
dei centri, poi segue le dieci schede dei centri e i sette cartelli ufficiali
collegati. La passata dell'8 agosto 2026 ha controllato 19 URL: 19 snapshot,
nessun blocco `robots.txt` e nessun errore. I cartelli sono conservati come
fonti immagine e la loro impronta SHA-256 deve coincidere con quella verificata:
se ESA sostituisce un cartello, i vecchi codici EER non vengono applicati al
nuovo documento senza revisione.

```sh
PYTHONPATH=src python3 -m dovelobutto.cli fetch-local-operator \
  --operator esa \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --snapshot-root data/crawl/ato-toscana-costa/2026-08-08/esa \
  --manifest data/crawl/ato-toscana-costa/2026-08-08/esa-manifest.json \
  --report outputs/ato-toscana-costa-esa-fetch-report.json \
  --observed-at 2026-08-08T10:30:00+02:00 \
  --user-agent 'DoveLoButtoData/0.1 (+mailto:marcofanciulli@me.com)'

PYTHONPATH=src python3 -m dovelobutto.cli materialize-esa \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --manifest data/crawl/ato-toscana-costa/2026-08-08/esa-manifest.json \
  --snapshot-root data/crawl/ato-toscana-costa/2026-08-08/esa \
  --retrieved-at 2026-08-08T10:30:00+02:00 \
  --output-dir outputs/ato-toscana-costa \
  --report outputs/ato-toscana-costa-esa-report.json
```

I sette comuni dell'Elba ricevono 292 coppie nome-destinazione e cinque regole
generali ciascuno. I dieci centri sono associati soltanto ai comuni pertinenti,
con indirizzi, accessi e 18 periodi di apertura. I sette cartelli producono 163
associazioni esatte materiale/EER; per i due centri mobili restano inoltre
quattro esempi senza codice, dichiarati come descrizioni non riconciliate.

## REA

Il rifiutario REA e dinamico. `fetch-rea-rifiutario` controlla `robots.txt`,
interroga serialmente le 26 iniziali e produce un JSON sorgente e un rapporto.
La passata verificata ha trovato 190 voci, sei iniziali senza risultati e zero
errori. Sette voci approvate non hanno una destinazione: vengono conservate con
`resolution_status: missing_destination`, non scartate.

`fetch-rea-services` parte dalle 17 schede comunali e dall'indice dei centri,
segue soltanto servizi e allegati pubblicati da REA, rispetta `robots.txt` e
salva un manifesto completo. Se il manifesto esiste, la ripresa riusa gli
snapshot riusciti e visita soltanto le nuove URL. La passata verificata ha
controllato 425 URL: 423 snapshot, nessun blocco robots e due PDF del 2023
rimossi dal server (`404`). Ha censito 317 pagine di servizio, 73 riferimenti
ad allegati comunali, 11 centri e le due pagine dell'indice. Gli snapshot
comprendono 70 PDF unici: non tutti gli allegati sono calendari.

```sh
PYTHONPATH=src python3 -m dovelobutto.cli fetch-rea-services \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --snapshot-root data/crawl/ato-toscana-costa/2026-08-06/rea-services \
  --manifest data/crawl/ato-toscana-costa/2026-08-06/rea-services-manifest.json \
  --report outputs/ato-toscana-costa-rea-fetch-report.json \
  --observed-at 2026-08-06T19:00:00+02:00 \
  --user-agent 'DoveLoButtoData/0.1 (+mailto:marcofanciulli@me.com)'
```

`materialize-rea-services` combina queste pagine con il rifiutario. Produce
4.045 record per i 17 comuni: 3.230 termini, 196 regole, 99 calendari, 46
servizi di ritiro, 34 zone, 19 relazioni comune-centro con orari e accesso e
368 descrizioni di materiali accettati. Quando REA non pubblica il codice EER, la descrizione
resta acquisita con `eer_code_status: unmapped_description`; il codice non
viene dedotto. I centri intercomunali restano associati a tutti i comuni
esplicitamente serviti.

La prima estrazione dei calendari struttura quattro documenti RUR 2026 di
Casale Marittimo e Guardistallo: due per utenze domestiche e due per utenze non
domestiche, per un totale di 149 date. Anno, giorno settimanale e completezza
minima vengono verificati prima di creare il calendario; la validita resta
limitata all'anno dichiarato. Tra i 70 PDF unici, 31 sono classificati come
possibili calendari o guide operative. La copertura residua e esposta come
avviso per comune, non nascosta.

La seconda estrazione struttura cinque calendari Ecomobile 2026: Rosignano
Marittimo, Orciano Pisano, Santa Luce, Montecatini Val di Cecina e Castelnuovo
Val di Cecina. Produce 15 fermate mobili con indirizzo, orario, materiali,
requisiti di accesso e 189 associazioni fermata-data. Il calendario e collegato
al punto mobile, non forzato dentro una regola porta a porta. Nel documento di
Orciano la riga `27 febbraio 2025` resta esclusa dalle date 2026 e segnalata
come anomalia testuale della fonte, senza correzione congetturale.

La terza estrazione struttura 12 calendari settimanali grafici pubblicati da
REA per Bibbona, Collesalvetti, Castellina Marittima, Montecatini Val di
Cecina, Montescudaio, Riparbella, Santa Luce e Volterra. Le icone di utenza e
zona sono state verificate visivamente e producono 17 zone, 84 regole e 80
calendari. Sono conservati i periodi stagionali dei singoli passaggi, gli orari
di esposizione, il conferimento stradale del vetro e le indicazioni su sacchi,
mastelli e conferimento sfuso. Ogni configurazione e legata allo SHA-256 del
PDF controllato: se REA sostituisce il file, il nuovo allegato torna in
revisione invece di ereditare automaticamente la vecchia tabella. Il
calendario Orciano 2023 e gli allegati annuali scaduti non sono resi attivi.

## AAMPS

La pipeline ordinaria `fetch-local-operator --operator aamps` acquisisce la
guida visuale 2023 e il calendario operativo AAMPS 2024, dopo avere verificato
`robots.txt`. L'estrattore legge testo e simboli colorati dal PDF, vincolato
allo SHA-256 verificato: una sostituzione del documento richiede una nuova
revisione visiva. Sono materializzate 408 voci del rifiutario, due centri con
orari e accesso, sei isole ecologiche mobili, nove punti itineranti per gli oli
vegetali e il centro del riuso. Il calendario Pentagono resta una fonte zonale
e non viene esteso all'intero comune.

```sh
PYTHONPATH=src python3 -m dovelobutto.cli fetch-local-operator \
  --operator aamps \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --snapshot-root data/crawl/ato-toscana-costa/2026-08-08/aamps \
  --manifest data/crawl/ato-toscana-costa/2026-08-08/aamps-manifest.json \
  --report outputs/ato-toscana-costa-aamps-fetch-report.json \
  --observed-at 2026-08-08T12:00:00+02:00 \
  --user-agent 'DoveLoButtoData/0.1 (+mailto:marcofanciulli@me.com)'

PYTHONPATH=src python3 -m dovelobutto.cli materialize-local-operator \
  --operator aamps \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --manifest data/crawl/ato-toscana-costa/2026-08-08/aamps-manifest.json \
  --snapshot-root data/crawl/ato-toscana-costa/2026-08-08/aamps \
  --retrieved-at 2026-08-08T12:00:00+02:00 \
  --output-dir outputs/ato-toscana-costa \
  --report outputs/ato-toscana-costa-aamps-report.json
```

## GEOFOR

GEOFOR pubblica 24 schede comunali operative e un rifiutario condiviso
incorporato nel sito. La pipeline acquisisce le schede, le pagine dei centri,
i servizi di ritiro e gli allegati pubblici, quindi materializza 388 termini e
cinque regole generali per ciascun comune attivo.

```sh
PYTHONPATH=src python3 -m dovelobutto.cli fetch-geofor \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --snapshot-root data/crawl/ato-toscana-costa/2026-08-06/geofor \
  --manifest data/crawl/ato-toscana-costa/2026-08-06/geofor-manifest.json \
  --report outputs/ato-toscana-costa-geofor-fetch-report.json \
  --observed-at 2026-08-06T20:30:00+02:00 \
  --user-agent 'DoveLoButtoData/0.1 (+mailto:marcofanciulli@me.com)'

PYTHONPATH=src python3 -m dovelobutto.cli materialize-geofor \
  --registry outputs/ato-toscana-costa-municipalities.jsonl \
  --snapshot-root data/crawl/ato-toscana-costa/2026-08-06/geofor \
  --retrieved-at 2026-08-06T20:30:00+02:00 \
  --output-dir outputs/ato-toscana-costa \
  --report outputs/ato-toscana-costa-geofor-report.json
```

La passata verificata ha controllato 178 URL, salvato 176 snapshot e dichiarato
due errori: un vecchio PDF di Bientina e la pagina di Peccioli oggi `404`. I
13.631 record comprendono 9.700 termini, 125 regole, 25 zone, 24 centri con orari e accesso,
3.672 associazioni centro-EER e 37 servizi di ritiro. Il flag centro di raccolta
del rifiutario GEOFOR e applicato ai centri pubblicati; eventuali limitazioni
locali restano demandate alla scheda e al regolamento del singolo centro.

I calendari PDF sono acquisiti e inventariati, ma non ancora trasformati in
eventi strutturati. Per Chianni, Crespina Lorenzana, Fauglia, Lajatico, Palaia
e Pisa non e pubblicata una pagina comunale del centro. Peccioli riceve il
rifiutario condiviso ma mantiene l'avviso per la scheda comunale assente.

## Restanti SOL

Il comando generico `fetch-local-operator` acquisisce AAMPS, ASCIT, ASMIU, ERSU, GEA,
Lunigiana Ambiente, RetiAmbiente Carrara, SEA Ambiente e Sistema Ambiente. Usa
una configurazione per dominio, consulta `robots.txt`, salva un manifesto con
ogni tentativo e non elimina URL bloccate o in errore. Il comando
`materialize-local-operator` produce gli stessi record normalizzati delle
pipeline precedenti.

La passata del 6 agosto ha acquisito 50 comuni: 12 ASCIT, 14 Lunigiana
Ambiente, 13 GEA, sei ERSU, due SEA e uno ciascuno per ASMIU, Carrara e Sistema
Ambiente. ASCIT e Lunigiana forniscono rifiutari rispettivamente da 574 e 295
termini per comune. ERSU pubblica schede dettagliate dei centri con ambito di
accesso, orari e codici EER. Le fonti meno strutturate restano utili per regole,
contatti e centri, ma producono avvisi quando rifiutario o dettaglio non sono
pubblicati.

Montignoso conserva le regole di raccolta SEA Ambiente, ma la guida ufficiale
ERSU documenta l'accesso dei residenti ai centri Piedimonte, Olmi e Ciocche e
al centro verde di Pietrasanta. Il supplemento SHA-locked aggiunge quattro
strutture, accessi e orari, 58 associazioni centro-EER e quattro servizi a
domicilio senza attribuire questi centri agli altri comuni SEA.

La guida entra nel manifesto ERSU come `montignoso_guide`. Dopo la
materializzazione SEA, `materialize-montignoso-ersu` la unisce al file del
comune; il percorso del PDF e quello SHA-256 riportato nel manifesto.

Le relazioni centro-comune sono conservatrici: ASCIT usa le attribuzioni
comunali e i due Salanetti dichiarati per tutti; Boceda e intercomunale per i
14 comuni Lunigiana, mentre Novoleto e associato al solo Pontremoli. I centri
di Viareggio non vengono attribuiti a Montignoso. Le relazioni ERSU verso
Montignoso sono invece modellate come accessi intergestore, senza duplicare le
fonti o cambiare il gestore della raccolta comunale.

## Copertura corrente

- 100 comuni censiti;
- 100 comuni con almeno una fonte acquisita;
- 32.651 record ATO Costa;
- tutti i 13 comuni livornesi hanno almeno un rifiutario acquisito;
- tutti i comuni REA hanno pagine di servizio; 14 hanno accesso ad almeno un
  centro pubblicato, mentre Capraia Isola, Orciano Pisano e Santa Luce non
  risultano collegati a un centro nella fonte acquisita.

Restano da approfondire i centri o rifiutari non pubblicati nelle schede
disponibili.
