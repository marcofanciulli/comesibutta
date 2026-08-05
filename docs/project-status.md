# Stato del progetto

Ultimo aggiornamento: 6 agosto 2026
Fase: primo lotto live acquisito, ripresa pronta

Questo documento e il punto di ripartenza del progetto. Va aggiornato al termine
di ogni fase sostanziale, insieme ai dataset e ai rapporti prodotti.

## Obiettivo

Realizzare un'app per tutti i comuni della Toscana che risponda alla domanda
"Dove lo butto?" usando regole territoriali citabili. Il sistema deve collegare
il linguaggio quotidiano degli utenti alle modalita locali di raccolta e, per i
centri di raccolta, ai codici EER/CER accettati.

La risposta deve poter indicare:

- cassonetto, raccolta porta a porta o centro di raccolta;
- tipo e colore del contenitore;
- conferimento sfuso oppure tipo di sacchetto;
- eventuali operazioni preliminari e calendario;
- centro comunale o centro limitrofo utilizzabile;
- codice EER/CER, esempi, condizioni e rischi di un conferimento scorretto;
- fonte, territorio e periodo di validita della regola.

## Decisioni consolidate

1. Le fonti vengono conservate separatamente dai dati estratti e dai dati
   canonici usati dall'app.
2. Il formato di acquisizione e JSON Lines, secondo
   `schemas/acquisition-record.schema.json`.
3. Il contratto della futura risposta dell'app e descritto in
   `schemas/disposal-answer.schema.json`.
4. La sigla tecnica interna e EER; CER resta un alias da mostrare agli utenti e
   da riconoscere nelle fonti.
5. La modalita di conferimento e una regola territoriale e temporale, non una
   proprieta assoluta del rifiuto.
6. Ogni fatto mantiene URL, data di acquisizione, evidenza testuale, impronta
   della fonte, affidabilita e validita.
7. I duplicati apparenti nelle tabelle dei centri non vengono eliminati durante
   l'acquisizione: possono rappresentare raggruppamenti operativi distinti.
8. Le coordinate pubblicate dalla fonte hanno priorita sulla geocodifica; il
   metodo e l'accuratezza devono sempre essere espliciti.
9. Il pilota iniziale copre ATO Toscana Sud e le pagine SEI Toscana.

## Artefatti persistenti

- `docs/data-architecture.md`: architettura, modello e strategia di raccolta.
- `docs/crawl-operations.md`: procedura di scansione e ripresa.
- `docs/source-access-policy.md`: verifica legale-operativa delle fonti.
- `schemas/`: schemi JSON dell'acquisizione e della risposta applicativa.
- `src/dovelobutto/`: estrattore riproducibile e interfaccia a riga di comando.
- `tests/fixtures/`: copie immutabili delle porzioni rilevanti delle fonti HTML.
- `tests/`: verifiche automatiche dei casi reali e delle varianti di pagina.
- `outputs/`: record JSONL estratti e rapporti di copertura per comune.
- `examples/`: esempi illustrativi del formato dati.

## Stato verificato

Comuni pilota gia acquisiti:

| Comune | Record | Contenuti principali |
| --- | ---: | --- |
| Manciano | 66 | centro, EER, due zone, regole, 27 punti, ritiro |
| Castagneto Carducci | 68 | centro, EER, tre zone, calendari, area verde |
| Siena | 126 | centro, EER, nove zone, calendari e 20 punti |
| Campiglia Marittima | 78 | centro, EER, quattro zone, orari stagionali, ritiro |
| Sassetta | 1 | accesso intercomunale al centro di Castagneto |

Verifiche completate al 6 agosto 2026:

- 31 test automatici superati;
- compilazione dei moduli Python riuscita;
- validita sintattica JSON verificata per schemi, record e rapporti;
- relazione Sassetta-Castagneto risolta sullo stesso identificatore stabile;
- nessuno snapshot di test contiene marcatori di trasferimento troncato.

Registro iniziale SEI Toscana:

- 104 comuni riconciliati con l'elenco ISTAT aggiornato al 21 febbraio 2026;
- 35 comuni di Arezzo, 28 di Grosseto, 6 di Livorno e 35 di Siena;
- 104 pagine di raccolta, 104 collegamenti ai centri, 79 pagine di
  spazzamento e 19 ulteriori collegamenti classificati;
- nessun nome SEI privo di corrispondenza ISTAT.

Scansione controllata:

- coda iniziale di 208 pagine ufficiali, due per ciascun comune;
- scoperta automatica delle pagine di ritiro ingombranti;
- rispetto di robots.txt, intervallo seriale e richieste HTTP condizionali;
- stato atomico riprendibile e snapshot immutabili identificati da SHA-256;
- normalizzazione di frammenti, slash e reindirizzamenti;
- collaudo su 12 pagine di quattro comuni: 338 record e zero avvisi;
- seconda passata: 12 pagine invariate e nessun nuovo snapshot.

Primo lotto live `grosseto-01`:

- preflight robots consentito per tutte le 20 URL iniziali;
- 30 pagine acquisite, 10 comuni materializzati e 700 record estratti;
- 3 coppie di URL SEI con contenuto utile equivalente individuate per Capalbio,
  Grosseto e Monte Argentario; gli snapshot restano distinti ma i record non
  vengono duplicati;
- rigenerazione offline di controllo: 586 record e 3 avvisi reali;
- la voce EER `15106` di Grosseto viene conservata come dato malformato, con
  `150106` marcato soltanto come candidato da revisionare;
- le altre 2 segnalazioni sono tabelle di conferimento non pubblicate dalla
  fonte per Isola del Giglio e per il centro riservato ai manutentori del verde
  di Grosseto;
- 3 pagine lasciate in coda dal limite operativo di 30 richieste;
- dalla versione successiva al primo passaggio, la coda pendente viene salvata
  integralmente e ricostruita dagli snapshot per migrare lo stato precedente.

## Limiti e questioni aperte

- Le pagine di ritiro ingombranti non sono collegate dall'indice generale e
  devono essere scoperte dalle pagine comunali o durante la scansione.
- I PDF, le guide e i calendari allegati non sono ancora inclusi nella pipeline.
- Manca il livello canonico in PostgreSQL/PostGIS e la coda di revisione umana.
- Il repository Git e inizializzato e collegato al remoto GitHub del progetto;
  snapshot e stato live restano esclusi per dimensione e variabilita.
- La scansione live usa il contatto autorizzato `marcofanciulli@me.com` nello
  user-agent, esclusivamente per questo progetto.

## Prossimi passi

1. Riprendere `grosseto-01` con un limite di 60 pagine per completare la coda.
2. Validare e versionare gli output completi del lotto.
3. Inserire le 3 segnalazioni nella futura coda di revisione umana.
4. Estendere progressivamente la scansione ai 104 comuni.
5. Aggiungere la raccolta e la classificazione di PDF, guide e calendari.

## Regola di continuita

Al termine di ogni fase si aggiornano questo documento, i test e gli output.
Le decisioni nuove o modificate devono essere registrate qui oppure in una
specifica dedicata collegata da questa pagina. Gli stati transitori del browser
o del terminale non sono considerati patrimonio del progetto: ogni informazione
necessaria a riprodurre il lavoro deve finire in un file del workspace.
