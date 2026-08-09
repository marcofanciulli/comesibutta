# Perimetro funzionale del prodotto

Versione: 1.0
Ultimo aggiornamento: 10 agosto 2026

Questo documento e il contratto funzionale di ComeSiButta. Distingue una
capacita presente nei dati o nel backend da una funzione realmente disponibile
all'utente. Una voce puo diventare `completa` soltanto quando il percorso e
visibile sulla piattaforma prevista, usa dati verificati, gestisce gli stati
incompleti ed e coperto da test.

Stati usati:

- `completa`: percorso utente disponibile e verificato;
- `parziale`: esiste soltanto una parte del percorso o dell'infrastruttura;
- `da realizzare`: nessun percorso utente distribuibile.

## Esperienza territoriale

| Funzione concordata | Stato | Situazione al 10 agosto 2026 | Chiusura richiesta |
| --- | --- | --- | --- |
| Scelta manuale del comune | completa | Ricerca fra tutti i 273 comuni toscani | Collaudo continuo |
| Ricordo del comune e della zona | parziale | Preferenza locale sul dispositivo | Account opzionale e sincronizzazione fra dispositivi |
| Regole della posizione corrente | completa | GPS risolve il comune; la zona resta correggibile | Migliorare la risoluzione sotto-comunale quando le fonti la consentono |
| Ricerca per nome di oggetto o materiale | completa | Ricerca tollerante, sinonimi e chiarimenti | Curatela continua delle ricerche mancanti |
| Destinazione locale | completa | Cassonetto, porta a porta, centro, punto o ritiro secondo le evidenze | Collaudo continuo |
| Tipo di sacchetto e preparazione | parziale | Mostrato quando pubblicato e filtrabile nelle regole | Percorso autonomo `Come prepararlo` e ricerca dedicata |
| Filtro per categoria di rifiuto | da realizzare | Le frazioni locali sono filtrabili, le categorie del rifiutario no | Tassonomia navigabile di oggetti, materiali e famiglie |
| Elenco dei centri e dei servizi | completa | Centri, punti e ritiri accessibili al comune | Estendere la verifica ai servizi limitrofi |
| Centro comunale o limitrofo compatibile | parziale | Il motore sceglie fra i centri con accesso pubblicato per il comune | Ricerca esplicita nei comuni vicini e motivazione dell'accessibilita |
| Dettaglio del centro | completa | Stato, distanza, accesso, orari, contatti, prenotazione e accettazioni | Collaudo continuo |
| Dettaglio del rifiuto | parziale | Risultato completo nella pagina | Modale dedicata con identita, materiali, EER, varianti e fonti |
| Dettaglio del conferimento | parziale | Destinazione e preparazione sono nella risposta | Modale dedicata con zona, condizioni, alternative e motivazione |
| Pericoli ambientali del conferimento errato | parziale | Pericolosita EER e avvertenze prudenziali | Schede revisionate sul rischio e sulle azioni da evitare |
| Consultazione delle fonti senza lasciare l'app | parziale | Modale interna sul web con uscita di riserva | Verificare i domini che vietano l'incorporamento e offrire estratti locali |

## Identificazione assistita

| Funzione concordata | Stato | Situazione al 10 agosto 2026 | Chiusura richiesta |
| --- | --- | --- | --- |
| Prontuario dei simboli europei e italiani | parziale | Registro normativo e asset di bootstrap disponibili | Vista utente ricercabile con simboli autorizzati e spiegazioni |
| Riconoscimento dei simboli con fotocamera | parziale | Pipeline, contratti e modello tecnico non distribuibile | Fotografie reali, validazione, modelli Core ML e LiteRT di rilascio |
| Conferma dei riconoscimenti incerti | da realizzare | Prevista nel contratto del modello | Interazione nativa e web con soglie verificate |

## Profilo e continuita

| Funzione concordata | Stato | Situazione al 10 agosto 2026 | Chiusura richiesta |
| --- | --- | --- | --- |
| Registrazione opzionale | da realizzare | Nessun account | Backend identita, consenso e recupero account |
| Preferenze sincronizzate | da realizzare | Solo memoria locale del browser | Comune, zona e impostazioni sincronizzati |
| Uso senza registrazione | completa | Tutta la verticale web corrente e anonima | Deve restare disponibile |
| Raccolta aggregata delle ricerche mancanti | completa | Backend privo di IP, GPS, account e dispositivo | Revisione editoriale periodica |
| Aggiornamenti dati incrementali | completa | Snapshot e delta firmati con applicazione atomica | Consolidati e backend di distribuzione operativo |

## Piattaforme

| Piattaforma concordata | Stato | Perimetro previsto |
| --- | --- | --- |
| Sito web | parziale | Deve coprire tutto il nucleo funzionale, esclusa la fotocamera nativa quando non supportata |
| Applicazione iOS | da realizzare | Nucleo completo, GPS, fotocamera, Core ML e comandi vocali |
| Applicazione Android | da realizzare | Nucleo completo, GPS, fotocamera, LiteRT e comandi vocali |
| Skill Alexa | da realizzare | Ricerca del rifiuto e ricerca del centro |
| Siri e HomePod | da realizzare | App Intents per ricerca del rifiuto e del centro |
| Assistente Google su Android | da realizzare | App Actions equivalenti ai percorsi vocali limitati |

## Ordine di completamento

1. Chiudere il sito web: categorie, preparazione, schede del rifiuto e del
   conferimento, rischi ambientali, centro limitrofo e fonti interne.
2. Aggiungere account opzionale e sincronizzazione senza limitare l'uso anonimo.
3. Pubblicare il prontuario dei simboli e completare il corpus fotografico.
4. Costruire le app iOS e Android sullo stesso contratto dati e di risposta.
5. Esporre i percorsi ridotti ad Alexa, Siri/HomePod e Assistente Google.

Ogni aggiornamento dello stato deve citare test, interfaccia e piattaforma che
giustificano il passaggio. Il solo completamento del backend non cambia lo stato
di una funzione rivolta all'utente.
