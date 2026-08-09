# Geolocalizzazione e distanza

## Fonte territoriale

Il comune viene determinato con i confini amministrativi generalizzati ISTAT
riferiti al 1 gennaio 2026, in WGS84. Il file nazionale originale e la
conversione GeoJSON limitata ai 273 comuni toscani sono conservati in
`data/sources/istat-boundaries/`.

Fonte ufficiale:
`https://www.istat.it/storage/cartografia/confini_amministrativi/generalizzati/2026/Limiti01012026_g.zip`.

Salvo diversa indicazione, i contenuti ISTAT sono riutilizzabili con licenza
Creative Commons Attribuzione 4.0. L'attribuzione da mostrare nei metadati e:
`Fonte: Istituto nazionale di statistica (ISTAT), confini amministrativi al 1
gennaio 2026`.

La materializzazione controlla che ogni comune del registro abbia esattamente
un confine. La revisione `202608090012` contiene 273 confini, nessun comune
mancante e nessun elemento inatteso.

## Privacy e comportamento

- la localizzazione parte soltanto dopo il comando esplicito dell'utente;
- latitudine, longitudine e accuratezza sono inviate al backend locale con una
  richiesta `POST`, non nella URL;
- la posizione esatta resta soltanto nella memoria della pagina e non viene
  scritta in `localStorage`, nel database delle ricerche mancanti o nei dati
  dell'account;
- il comune selezionato puo essere ricordato e corretto manualmente;
- coordinate sul confine restituiscono piu comuni candidati, senza scelta
  automatica;
- coordinate esterne al perimetro restituiscono `outside_supported_area`;
- la posizione viene riutilizzata per ordinare per distanza centri, punti di
  raccolta e servizi dotati di coordinate, senza modificare l'accettazione.

L'API `POST /api/locate` restituisce sempre `position_stored: false`. Il test
reale della revisione corrente ha riconosciuto Firenze e Manciano; a Manciano
ha ordinato il Centro di Raccolta di San Giovanni a 1,51 km dalla coordinata di
prova.
