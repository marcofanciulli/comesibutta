# Stato del progetto

Ultimo aggiornamento: 7 agosto 2026
Fase: ATO Toscana Sud, Costa e Centro acquisite

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
   ciascuna societa operativa locale; ATO Toscana Centro usa le fonti pubbliche
   AliaEstra.
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
17. I codici UE degli imballaggi identificano il materiale, non la destinazione
    locale: non implicano mai cassonetto, sacchetto o preparazione.
18. Il riconoscimento visivo usa un checkpoint PyTorch autorevole ed esporta
    artefatti Core ML e LiteRT verificati sullo stesso corpus.
19. La ricerca lessicale propone concetti, ma la risposta deriva soltanto da
    destinazioni e regole territoriali citabili; una somiglianza incerta
    richiede conferma dell'utente.
20. Sinonimi e nomi dei flussi entrano nelle risposte soltanto tramite un
    registro revisionato e distribuibile; i concetti sorgente e le differenze
    territoriali non vengono eliminati dalla curatela.
21. Flusso di materiale e canale di consegna sono dimensioni distinte. Le
    destinazioni composte espongono tutte le alternative controllate e il testo
    sorgente; non vengono ridotte per somiglianza a una regola di cassonetto.
22. Un centro viene proposto soltanto con accesso esplicito e accettazione
    verificata per EER o descrizione. GPS e distanza ordinano candidati gia
    validi, ma non possono colmare l'assenza di queste relazioni.
23. Esistenza e compatibilita di un servizio sono fatti distinti. Ritiri e
    punti non verificati restano visibili con avviso; riuso, rivenditore e
    operatore specializzato restano canali sorgente senza entita inventate.
24. Una regola generale del gestore puo essere applicata ai suoi punti soltanto
    quando la fonte dichiara esplicitamente quell'ambito. Un elenco specifico
    del punto ha sempre la precedenza e ogni fonte conserva la propria data.

## Artefatti persistenti

- `docs/data-architecture.md`: architettura, modello e strategia di raccolta.
- `docs/crawl-operations.md`: procedura di scansione e ripresa.
- `docs/source-access-policy.md`: verifica legale-operativa delle fonti.
- `docs/data-synchronization.md`: distribuzione remota e aggiornamenti atomici.
- `docs/eer-register.md`: fonti, importazione e validazione del registro EER.
- `docs/facility-resolution.md`: selezione, accesso, accettazione e distanza
  dei centri di raccolta.
- `docs/channel-services.md`: risoluzione di ritiri e punti, compatibilita e
  canali disponibili soltanto come testo sorgente.
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

- 76 test automatici superati;
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

- pacchetto statico generato in modo riproducibile da 152.698 record logici;
- filtri gerarchici per ATO e provincia, seguiti dall'elenco dei comuni;
- 273 comuni censiti e 273 con almeno una fonte materializzata;
- navigazione per comune e viste dedicate a centri, EER, regole, punti e ritiro;
- vista rifiutario per le coppie nome quotidiano-destinazione;
- ricerca trasversale, provenienza, evidenze e record JSON consultabili;
- anomalie e pagine equivalenti esposte senza alterare i dati acquisiti.

Catalogo canonico corrente:

- 138.342 record di rifiutario ridotti a 3.880 indicazioni sorgente distinte;
- 3.124 concetti consultabili nell'esploratore;
- 331 concetti con EER concordante indicato dalla fonte e zero conflitti sui
  termini coincidenti;
- 2.553 concetti senza EER e 411 con piu destinazioni locali osservate;
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

Completamento ATO Toscana Centro:

- costruito il registro ufficiale di 65 comuni: 38 FI, 7 PO e 20 PT;
- esclusi correttamente Firenzuola, Marradi e Palazzuolo sul Senio, che non
  appartengono al perimetro di ATO Toscana Centro;
- verificato `robots.txt` di AliaEstra: nessuna URL pubblica usata dalla
  pipeline e bloccata; il sottodominio API non pubblica un proprio file e
  questa assenza resta dichiarata nel rapporto;
- acquisiti 502 prefissi derivati dal catalogo toscano e 1.722 dettagli
  Junker/AliaEstra, con checkpoint riprendibile e zero errori finali;
- acquisiti 34 ecocentri, 135 ecofurgoni e 167 schede Sitecore con orari,
  materiali e collegamenti alle regole di accesso; due elementi della mappa
  non hanno una scheda pubblicata;
- acquisita la pagina generale Ecofurgoni con 11 categorie: 134 postazioni
  usano la regola condivisa e una conserva il proprio elenco specifico;
- materializzati 114.352 record: 111.930 voci del rifiutario, 1.300 regole,
  755 materiali accettati, 34 centri, 135 punti mobili e 65 servizi di ritiro;
- i materiali degli ecocentri privi di EER restano
  `unmapped_description`; nessun codice e stato inventato;
- 35 comuni senza un ecocentro nel proprio territorio e due punti privi di
  scheda di dettaglio sono esposti come avvisi, non come dati mancanti
  silenziosi;
- l'esploratore deduplica soltanto la copia browser del rifiutario condiviso:
  41.087 record fisici e circa 50 MB, mantenendo 151.295 record logici e i
  file comunali completi.

Completamento dei comuni toscani in ATO extra-regionali:

- aggiunti Firenzuola, Marradi e Palazzuolo sul Senio al bacino bolognese
  dell'ATO Emilia-Romagna e Sestino all'ATO 1 Marche - Pesaro e Urbino;
- il perimetro censito raggiunge tutti i 273 comuni della Toscana;
- acquisiti 883 prodotti e altrettante risposte del Rifiutologo Hera, tre
  schede di stazione ecologica e tre pagine pubbliche Marche Multiservizi,
  senza errori di rete finali;
- materializzati 1.403 record: 883 voci di rifiutario, 102 regole legate a un
  indirizzo campione, 102 punti geolocalizzati, 300 materiali accettati, tre
  centri con accesso e orari e un servizio di ritiro per Sestino;
- le regole Hera dipendenti dall'indirizzo sono marcate a confidenza media e
  non vengono presentate come valide per l'intero comune;
- il sito del Comune di Sestino vieta ogni acquisizione automatica; rifiutario,
  regole locali e centri disponibili soltanto nell'app del gestore restano
  quattro lacune esplicite, non assenze silenziose;
- l'esploratore espone cinque ATO, limitando quelli extra-regionali alle sole
  province e ai soli comuni toscani interessati;
- il dataset conta 152.698 record logici e il catalogo 3.124 concetti, con
  331 concetti associati a un EER concordante;
- 80 test automatici superati.

SQLite canonico e sincronizzazione remota:

- materializzate 155.946 entita canoniche e 159.719 dipendenze dal dataset
  regionale completo; 134 asserzioni variantate preservano le collisioni di
  chiave senza perdita di dati;
- aggiunti database SQLite distinti per backend e client, con chiavi esterne,
  tombstone, pacchetti applicati e changelog backend compresso;
- snapshot e delta gzip sono firmati Ed25519; anche il manifest e firmato e la
  CLI client richiede la chiave pubblica;
- il pianificatore sceglie il percorso di delta con meno byte oppure uno
  snapshot, che viene costruito separatamente e sostituito atomicamente;
- la pubblicazione usa un manifest `.pending` e recupera un'interruzione tra
  aggiornamento del backend e pubblicazione del nuovo manifest;
- collaudo completo: snapshot da 7,7 MB, delta di una singola modifica da 711
  byte, 155.946 entita applicate e zero violazioni relazionali;
- documenti ed evidenze di provenienza sono deduplicati: 152.485 collegamenti
  fanno riferimento a 524 documenti e 14.232 evidenze distinte;
- i corpi JSON sono compressi e le relazioni SQLite usano chiavi numeriche,
  mantenendo invariati gli identificatori canonici pubblici;
- 142.575 voci territoriali sono ricondotte a 5.360 modelli condivisi: 4.424
  voci di rifiutario, 794 regole di raccolta e 142 zone;
- il SQLite client occupa circa 97 MB, contro i 259 MB iniziali e i 129 MB
  della sola deduplicazione delle fonti, senza modificare snapshot e delta;
- una seconda pubblicazione dell'intero dataset invariato produce un delta di
  zero operazioni, verificando la ricostruzione esatta dei record;
- i database locali nel vecchio formato vengono rifiutati con una richiesta
  esplicita di ricostruzione dallo snapshot;
- 91 test automatici superati.

Registro UE dei materiali e riconoscimento visivo:

- importati PDF e HTML ufficiali della Decisione 97/129/CE, testo estratto e
  trascrizione controllata, tutti identificati tramite SHA-256;
- materializzati tutti i 99 slot normativi: 31 assegnati e 68 non assegnati,
  ripartiti nelle sette famiglie ufficiali;
- i 13 codici per materiali composti conservano la regola `C/` seguita
  dall'abbreviazione del materiale predominante, senza sigle inventate;
- nessuna destinazione di conferimento e dedotta dal codice del materiale;
- aggiunti i contratti JSON del registro, del modello e delle osservazioni
  fotografiche, con immagini non conservate per impostazione predefinita;
- documentata la pipeline condivisa PyTorch verso Core ML e LiteRT e la futura
  transizione alle etichette armonizzate previste dal Regolamento 2025/40;
- il registro aggiunge 99 entita `packaging_material_mark` alle pubblicazioni
  canoniche che lo includono;
- definita la tassonomia v1 del detector con cinque classi e fallback runtime,
  mantenendo codici e destinazioni fuori dalle classi apprese;
- aggiunti manifest del corpus, provenienza e diritti, revisione privacy,
  annotazioni normalizzate e split deterministico per gruppo di cattura;
- il test del modello accetta soltanto fotografie reali; immagini sintetiche e
  ritagli documentali non possono sostenere una valutazione di rilascio;
- il corpus iniziale contiene intenzionalmente zero immagini ed e dichiarato
  non addestrabile, in attesa di fotografie con diritti verificati;
- costruito un bootstrap separato con 20 pagine delle Linee guida adottate col
  DM 360/2022 e 186 varianti sintetiche dei 31 codici assegnati;
- 170 immagini di bootstrap appartengono al training e 36 alla validazione;
  nessuna immagine non fotografica entra nel test di rilascio;
- conservati decreto, allegato tecnico integrale, note legali MASE, font Noto
  Sans e relative impronte; immagini e manifest sono rigenerabili;
- prodotto il prontuario A5 e il contratto del registro fotografico con sei
  categorie rapide, nomi stabili e controlli di privacy;
- attivato il controllo quotidiano degli atti PPWR agli articoli 12(6), 12(7)
  e 13(2), con importazione solo da fonti primarie;
- addestrato su CPU il primo SSDLite320 MobileNetV3 di bootstrap: 150 immagini
  sintetiche di training, 36 di validazione e 20 pagine MASE escluse perche
  prive di annotazioni;
- la loss media e scesa da 6,891 a 2,650 in tre epoche; sulla validazione
  sintetica la soglia 0,4 ottiene F1 0,500, precisione 0,571 e recall 0,444;
- checkpoint locale da 15,4 MB, report riproducibili e anteprima delle
  predizioni prodotti; il modello e marcato esplicitamente non distribuibile;
- 141 test automatici superati.

Ricerca e risposta applicativa:

- aggiunto allo SQLite v5 l'indice derivato dei 3.124 concetti, aggiornato
  atomicamente da snapshot e delta e privo di un ciclo di versione autonomo;
- implementata la ricerca tollerante a errori di digitazione, con conferma per
  somiglianze incerte e priorita territoriale senza alterare la similarita;
- composta la prima risposta conforme al contratto con destinazione,
  contenitore, colore, preparazione, EER, avvisi, fonti e revisione dataset;
- differenze tra zone e destinazioni in conflitto restano domande o conflitti,
  mentre termini sconosciuti non producono regole inventate;
- collaudo sul dataset completo: 156.045 entita e 3.124 termini indicizzati;
  corretti i casi reali di bottiglia di vetro, guscio di cozze e confezione del
  latte con errore di digitazione;
- documentate le lacune su sinonimi, collegamento destinazione-flusso e scelta
  dei centri accessibili.

Curatela di sinonimi e flussi:

- creato il registro v1 con 3 gruppi approvati, 29 concetti membri e 14 termini
  di ricerca per cartoni da bevande, tappi di vero sughero e bottiglie di vetro
  generiche;
- aggiunti 7 flussi canonici e 34 alias controllati; lo stesso alias non puo
  assumere due significati e un concetto non puo appartenere a due gruppi;
- 1.938 delle 4.065 associazioni di destinazione, pari al 47,7%, sono ora
  riconducibili a un flusso stabile; nessun gruppo approvato crea conflitti
  territoriali;
- gruppi e flussi sono 10 entita sincronizzate con dipendenze verificabili; il
  dataset di collaudo raggiunge 156.055 entita;
- la ricerca aggrega termini, fonti ed EER dei membri, ma risolve soltanto le
  destinazioni presenti nel comune; finto sughero e qualificatori specifici
  restano distinti;
- il collegamento controllato ha unito, nel caso reale di Aulla, `Sacco carta`
  alla regola `Carta e cartone`, recuperando istruzioni e provenienza locale;
- aggiunti 7 canali e 26 alias controllati: 102 etichette e 1.750 delle 4.065
  associazioni territoriali sono scomposte senza confonderle con i flussi;
- 41 etichette, pari a 807 associazioni, espongono piu alternative; testo
  sorgente e formulazioni non interpretate restano integralmente disponibili;
- il caso reale `Armadio` a Firenze restituisce separatamente ecocentro e
  ritiro ingombranti, con `stream` vuoto finche non e noto un vero flusso;
- canali, flussi e gruppi formano 17 entita sincronizzate; il dataset di
  collaudo raggiunge 156.062 entita.

Risoluzione dei centri:

- il dataset espone 211 strutture, 384 accessi per 218 comuni, 195 periodi di
  apertura, 6.716 conferimenti e 156 strutture geolocalizzate;
- la risposta considera soltanto accessi consentiti per comune e utenza e
  distingue accettazione EER, descrittiva, non pubblicata e non riconciliata;
- stato `active` dei gestori viene normalizzato in `open`, conservando la forma
  sorgente; chiusure e chiusure temporanee non diventano proposte primarie;
- senza GPS piu centri equivalenti restano alternative; con entrambe le
  coordinate viene proposto il piu vicino tra quelli compatibili e non chiusi;
- verificato il caso reale di Firenze: `Armadio` collega ecocentro e ritiro,
  propone San Donato presso viale Guidoni e mantiene Sesto Fiorentino come
  alternativa; Isola del Giglio resta `temporarily_closed` per lavori;
- struttura, accesso, accettazione e orari contribuiscono tutti alla
  provenienza della risposta.

Risoluzione degli altri canali:

- collegati 294 servizi di ritiro in 247 comuni e 758 punti in 123 comuni, dei
  quali 137 mobili;
- ritiri e punti espongono prenotazione, limiti, istruzioni, orari, posizione e
  distanza quando disponibili;
- compatibilita verificata, elenco non pubblicato e servizio non verificato
  sono stati distinti e producono avvisi diversi;
- `Armadio` a Firenze collega il ritiro OnDemand; `Radio` restituisce 18
  ecofurgoni ordinati per distanza e verificati tramite la categoria ufficiale
  dei piccoli RAEE;
- `Accessori cellulari` vede gli stessi servizi ma resta `not_verified`, perche
  il collegamento semantico ai piccoli RAEE non viene inventato;
- riuso per `Assi da stiro`, uno-contro-uno per `Asciugacapelli` e operatore
  specializzato per `Bitumi` restano indicazioni `source_only` citabili;
- tutti i fatti di servizio utilizzati entrano nella provenienza della risposta.
- 142 test automatici superati.

## Limiti e questioni aperte

- Le pagine di ritiro ingombranti non sono collegate dall'indice generale e
  devono essere scoperte dalle pagine comunali o durante la scansione.
- L'acquisizione PDF e iniziata con AAMPS, ma guide e calendari delle altre SOL
  non sono ancora generalizzati nella pipeline.
- Manca il livello canonico in PostgreSQL/PostGIS e la coda di revisione umana.
- Alcuni requisiti di accesso Alia includono parti redazionali della pagina e
  richiedono una pulizia conservativa senza perdita dell'evidenza originale;
- Le categorie Ecofurgone sono generali: le equivalenze tra nomi quotidiani e
  categorie tecniche richiedono ancora curatela quando non sono testuali;
- Il repository Git e inizializzato e collegato al remoto GitHub del progetto;
  snapshot e stato live restano esclusi per dimensione e variabilita.
- La scansione live usa il contatto autorizzato `marcofanciulli@me.com` nello
  user-agent, esclusivamente per questo progetto.

## Prossimi passi

1. Estrarre e normalizzare i calendari contenuti nei 73 PDF REA acquisiti.
2. Acquisire i dettagli dei centri ESA e cercare una guida AAMPS piu recente.
3. Modellare l'accesso intergestore Montignoso-ERSU e approfondire i centri non
   pubblicati o non attribuiti esplicitamente dalle fonti.
4. Estendere il registro alle formule ancora prive di flusso o canale solo dopo
   revisione delle relative evidenze territoriali.
5. Ripulire i testi di accesso estratti da pagine con contenuto redazionale,
   mantenendo il testo integrale nella provenienza.
6. Aggiungere consolidati settimanali, mensili e annuali con conservazione e
   compattazione automatica nella finestra incrementale di cinque anni.
7. Importare il primo lotto fotografico classificato col prontuario, annotarlo
   in CVAT e fissare le soglie quantitative del primo dataset addestrabile.

## Regola di continuita

Al termine di ogni fase si aggiornano questo documento, i test e gli output.
Le decisioni nuove o modificate devono essere registrate qui oppure in una
specifica dedicata collegata da questa pagina. Gli stati transitori del browser
o del terminale non sono considerati patrimonio del progetto: ogni informazione
necessaria a riprodurre il lavoro deve finire in un file del workspace.
