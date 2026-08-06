# Stato del progetto

Ultimo aggiornamento: 6 agosto 2026
Fase: ATO Toscana Sud e ATO Toscana Costa acquisite

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
9. ATO Toscana Sud e completa; ATO Toscana Costa usa adattatori distinti per
   ciascuna societa operativa locale.
10. Comune, provincia, ATO, gestore unico e societa operativa locale sono
    dimensioni separate. Il codice ISTAT identifica il comune.
11. Una voce di rifiutario senza destinazione viene conservata come irrisolta,
    non eliminata.
12. App e dataset hanno cicli di rilascio indipendenti. I dati usano revisioni
    globali, ID stabili, snapshot e pacchetti incrementali atomici.
13. Il backend puo generare un delta minimo da qualsiasi revisione supportata;
    i percorsi comuni giornalieri, settimanali e mensili vengono precalcolati.
14. La finestra incrementale prevista e di cinque anni. Client piu vecchi o
    incompatibili ripartono da uno snapshot completo.
15. Pubblicazione e validita sono distinte: un dato futuro puo essere
    distribuito indicando `valid_from` senza essere presentato come gia attivo.
16. Il registro EER importa la decisione 2025/934 e la rettifica ufficiale. La
    nuova edizione e futura e si applica dal 9 dicembre 2026.

## Artefatti persistenti

- `docs/data-architecture.md`: architettura, modello e strategia di raccolta.
- `docs/crawl-operations.md`: procedura di scansione e ripresa.
- `docs/source-access-policy.md`: verifica legale-operativa delle fonti.
- `docs/data-synchronization.md`: distribuzione remota e aggiornamenti atomici.
- `docs/eer-register.md`: fonti, importazione e validazione del registro EER.
- `schemas/`: schemi JSON dell'acquisizione e della risposta applicativa.
- `src/dovelobutto/`: estrattore riproducibile e interfaccia a riga di comando.
- `tests/fixtures/`: copie immutabili delle porzioni rilevanti delle fonti HTML.
- `tests/`: verifiche automatiche dei casi reali e delle varianti di pagina.
- `outputs/`: record JSONL estratti e rapporti di copertura per comune.
- `examples/`: esempi illustrativi del formato dati.
- `explorer/`: console statica di esplorazione e controllo dei dati acquisiti.

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

- 70 test automatici superati;
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
- ripresa completata il 6 agosto: 33 pagine disponibili, coda residua zero,
  nessun errore e 590 record dopo la revisione dell'estrattore;
- la voce sorgente `15106` di Grosseto viene riconciliata automaticamente con
  `150106` tramite la descrizione univoca presente nel lotto;
- il centro riservato ai manutentori del verde espone nel testo il solo EER
  `200201`, acquisito anche in assenza di tabella;
- resta 1 segnalazione: l'elenco dei conferimenti non pubblicato per Isola del
  Giglio; il centro risulta temporaneamente chiuso per lavori di adeguamento;
- le 3 pagine di ritiro inizialmente pendenti sono state acquisite per Monte
  Argentario, Orbetello e Pitigliano;
- la coda pendente viene salvata integralmente e ricostruita dagli snapshot per
  migrare gli stati creati da versioni precedenti.

Completamento ATO Toscana Sud:

- acquisiti e materializzati tutti i 104 comuni: 35 di Arezzo, 28 di Grosseto,
  6 di Livorno e 35 di Siena;
- 328 pagine controllate, coda residua zero e 5.090 record finali;
- 8 URL restituiscono `404` e restano dichiarati nei rapporti: 5 in provincia
  di Grosseto e 3 in provincia di Arezzo;
- 4 elenchi dei conferimenti non risultano pubblicati: Isola del Giglio,
  Chitignano, Terranuova Bracciolini e Pienza;
- Caprese Michelangelo resta visibile come comune acquisito con zero record:
  la pagina disponibile non produce fatti e gli URL di centro e ritiro sono
  entrambi `404`;
- ogni provincia ha un file di selezione e un rapporto autonomo; l'esploratore
  fonde i cinque lotti senza perdere il perimetro e la provenienza.

Esploratore dati:

- pacchetto statico generato in modo riproducibile da 36.943 record;
- filtri gerarchici per ATO e provincia, seguiti dall'elenco dei comuni;
- 204 comuni censiti e 204 con almeno una fonte materializzata;
- navigazione per comune e viste dedicate a centri, EER, regole, punti e ritiro;
- vista rifiutario per le coppie nome quotidiano-destinazione;
- ricerca trasversale, provenienza, evidenze e record JSON consultabili;
- anomalie e pagine equivalenti esposte senza alterare i dati acquisiti.

Catalogo canonico iniziale:

- 26.412 record di rifiutario ridotti a 2.158 indicazioni sorgente distinte;
- 1.311 concetti consultabili nell'esploratore;
- 331 concetti con EER concordante indicato dalla fonte e zero conflitti sui
  termini coincidenti;
- 980 concetti senza EER e 330 con piu destinazioni locali osservate;
- materiale, condizioni, sinonimi semantici e note ambientali restano
  esplicitamente da verificare, senza riempimenti automatici.

Registro ufficiale EER:

- tre fonti EUR-Lex italiane conservate con impronta: base consolidata 2023,
  decisione 2025/934 e rettifica del 19 agosto 2025;
- 880 voci future, 20 capitoli, 112 sottocapitoli e 435 voci pericolose;
- applicabilita corretta al 9 dicembre 2026, distinta dalla pubblicazione;
- 42 codici aggiunti, 6 modificati e 4 ritirati rispetto alla base;
- 6.266 indicazioni dei centri controllate: nessun codice normalizzato
  sconosciuto, 252 occorrenze di codici che saranno ritirati e 368 materiali
  per i quali la fonte non pubblica un EER;
- un rinvio inesistente gia presente nella fonte ufficiale resta segnalato nel
  rapporto, senza correzione congetturale;
- vista globale del registro aggiunta all'esploratore e catalogo dei nomi
  quotidiani arricchito con titolo e pericolosita ufficiali.

Completamento ATO Toscana Costa:

- importata la tabella ufficiale 2026 dei 100 comuni e delle 12 SOL;
- riconciliati tutti i comuni con ISTAT: 13 LI, 33 LU, 17 MS e 37 PI;
- conservati separatamente RetiAmbiente, SOL e stato del subentro; Porto
  Azzurro e Peccioli risultano da completare, Lucca in transizione entro 2029;
- acquisiti tutti i 100 comuni e 31.853 record attraverso le 12 SOL;
- ESA: 292 voci del rifiutario per comune, cinque regole generali porta a porta
  e dieci centri complessivi associati ai comuni, 2.106 record senza avvisi;
- REA: 425 URL di servizi, centri e allegati controllate; 423 snapshot, 73 PDF,
  11 centri, nessun blocco robots e due vecchi PDF oggi `404` documentati;
- REA: 3.828 record complessivi, con 110 regole, 46 ritiri, 19 relazioni
  comune-centro complete di orario e accesso e 368 materiali ammessi; le
  descrizioni prive di EER restano marcate come codice non pubblicato;
- REA: sette voci del rifiutario prive di destinazione restano visibili; i 73
  PDF sono inventariati ma i calendari non sono ancora estratti in forma
  strutturata;
- AAMPS: 125 coppie estratte dal PDF 2017; cinque probabili continuazioni di
  colonna restano a confidenza media e sono elencate nel rapporto;
- GEOFOR: 178 URL controllati, 176 snapshot e due `404`; 13.631 record per 25
  comuni, inclusi 9.700 termini del rifiutario, 125 regole, 24 centri, 3.672
  associazioni centro-EER e 37 servizi di ritiro;
- GEOFOR: i calendari PDF sono inventariati ma non ancora strutturati; Peccioli
  e materializzato dal rifiutario condiviso, mentre la sua pagina comunale
  restituisce `404` e il centro resta dichiarato come non pubblicato;
- ASCIT: 12 comuni, 6.888 termini, 36 regole e 33 relazioni di accesso ai
  centri comunali o ai due centri Salanetti indicati per tutti i comuni;
- Lunigiana Ambiente: 14 comuni, 4.130 termini e accesso intercomunale al
  centro di Boceda; Novoleto e associato prudenzialmente al solo Pontremoli;
- ERSU: sei comuni, 23 relazioni di accesso e 301 conferimenti EER estratti
  dalle schede dei centri; il vecchio collegamento Colmate restituisce `404`;
- GEA, ASMIU, Carrara, SEA Ambiente e Sistema Ambiente: acquisite le pagine
  pubbliche disponibili, comprese regole, contatti, centri e orari quando
  presenti; le fonti prive di rifiutario sono segnalate esplicitamente;
- Montignoso dispone delle regole SEA, ma il collegamento intergestore al
  centro ERSU Ciocche deve ancora essere rappresentato nel modello;
- tutti i 13 comuni livornesi di ATO Costa hanno ora almeno un rifiutario;
  l'esploratore mostra ora anche servizi, centri intercomunali, orari, accesso
  e materiali accettati REA.

## Limiti e questioni aperte

- Le pagine di ritiro ingombranti non sono collegate dall'indice generale e
  devono essere scoperte dalle pagine comunali o durante la scansione.
- L'acquisizione PDF e iniziata con AAMPS, ma guide e calendari delle altre SOL
  non sono ancora generalizzati nella pipeline.
- Manca il livello canonico in PostgreSQL/PostGIS e la coda di revisione umana.
- Il repository Git e inizializzato e collegato al remoto GitHub del progetto;
  snapshot e stato live restano esclusi per dimensione e variabilita.
- La scansione live usa il contatto autorizzato `marcofanciulli@me.com` nello
  user-agent, esclusivamente per questo progetto.

## Prossimi passi

1. Estrarre e normalizzare i calendari contenuti nei 73 PDF REA acquisiti.
2. Acquisire i dettagli dei centri ESA e cercare una guida AAMPS piu recente.
3. Modellare l'accesso intergestore Montignoso-ERSU e approfondire i centri non
   pubblicati o non attribuiti esplicitamente dalle fonti.
4. Definire il livello canonico e il vocabolario unificato dei nomi quotidiani.
5. Prototipare manifest, generazione dei delta e applicazione transazionale su
   una base SQLite locale.

## Regola di continuita

Al termine di ogni fase si aggiornano questo documento, i test e gli output.
Le decisioni nuove o modificate devono essere registrate qui oppure in una
specifica dedicata collegata da questa pagina. Gli stati transitori del browser
o del terminale non sono considerati patrimonio del progetto: ogni informazione
necessaria a riprodurre il lavoro deve finire in un file del workspace.
