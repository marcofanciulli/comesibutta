# Prima applicazione web

La prima verticale utente riusa integralmente il contratto territoriale
`disposal-answer`: non conserva una seconda copia dei dati e non interpreta le
regole nel browser. Il servizio locale apre il database client in sola lettura
per ogni richiesta, quindi un aggiornamento atomico del file SQLite diventa
visibile senza migrazioni dell'interfaccia.

## Endpoint

- `GET /api/health`: verifica di disponibilita del processo;
- `GET /api/municipalities`: elenco alfabetico dei comuni e revisione dati;
- `GET /api/search?q=...&municipality=...`: ricerca approssimata nel catalogo;
- `POST /api/territory`: regole di raccolta, centri, punti e ritiri accessibili
  nel comune e nella zona selezionati;
- `POST /api/answer`: risposta territoriale completa, con lo stesso payload del
  comando `query-disposal`.

Quando `POST /api/answer` non riconosce la ricerca, il backend la aggrega nella
coda editoriale descritta in `docs/missing-query-feedback.md`. Il client riceve
soltanto l'esito `feedback.recorded`, non fingerprint o dati della coda.

Il browser conserva il codice ISTAT del comune preferito e l'eventuale zona in
`localStorage`. Le risposte, le fonti e le regole rimangono nel database
sincronizzato. La posizione viene richiesta solo su azione dell'utente, resta
in memoria per la sessione e viene inviata con `POST`, senza comparire negli
URL. Account e riconoscimento fotografico restano moduli successivi.

## Percorsi disponibili

La navigazione principale offre tre ingressi allo stesso patrimonio dati:

- `Cerca`, per partire dal nome quotidiano di un oggetto o materiale;
- `Regole`, per esplorare frazioni e preparazione, filtrando per zona;
- `Centri e servizi`, per consultare centri, punti di raccolta e ritiri.

Il dettaglio di un centro riporta stato pubblicato, distanza quando disponibile,
accesso, prenotazione, contatti, orari e l'elenco completo delle accettazioni.
Per ogni accettazione conserva separati titolo EER ufficiale, descrizione della
fonte locale, pericolosita, limiti e provenienza dell'informazione.

## Stati espliciti

L'interfaccia distingue una risposta risolta, una domanda di chiarimento, un
conflitto pubblicato, l'assenza di una risposta certa e un errore tecnico. Un
dato non pubblicato viene mostrato come tale: il client non completa colori,
sacchetti, codici EER o servizi per inferenza.
