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
- `POST /api/answer`: risposta territoriale completa, con lo stesso payload del
  comando `query-disposal`.

Il browser conserva soltanto il codice ISTAT del comune preferito in
`localStorage`. Le risposte, le fonti e le regole rimangono nel database
sincronizzato. Account, localizzazione automatica del comune e riconoscimento
fotografico restano moduli successivi e non sono simulati dalla prima versione.

## Stati espliciti

L'interfaccia distingue una risposta risolta, una domanda di chiarimento, un
conflitto pubblicato, l'assenza di una risposta certa e un errore tecnico. Un
dato non pubblicato viene mostrato come tale: il client non completa colori,
sacchetti, codici EER o servizi per inferenza.
