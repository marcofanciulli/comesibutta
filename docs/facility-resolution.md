# Risoluzione dei centri di raccolta

Versione: 1
Ultimo aggiornamento: 7 agosto 2026

## Scopo

Il motore collega un canale `channel:collection-centre` alle strutture che la
fonte dichiara accessibili dal comune dell'utente. La presenza geografica di un
centro non implica accesso e la vicinanza non sostituisce mai una relazione
pubblicata dal gestore.

## Condizioni di selezione

Una struttura entra tra i candidati soltanto se esiste un record
`facility_access` con `allowed=true`, comune richiesto e tipo di utenza
compatibile. L'accettazione del rifiuto viene verificata in questo ordine:

1. stesso codice EER pubblicato per il concetto e per il centro;
2. stessa descrizione controllabile nel concetto o nella destinazione sorgente;
3. elenco dei conferimenti non pubblicato;
4. elenco pubblicato nel quale il rifiuto non e stato riconosciuto.

Gli ultimi due stati restano visibili ma non producono una struttura primaria.
`not_listed` significa soltanto che il collegamento non e dimostrato dai dati
correnti, non che il conferimento sia certamente vietato.

I centri chiusi o temporaneamente chiusi non vengono mai scelti come proposta
primaria. Restano tra le alternative con stato e testo originale, affinche una
chiusura pubblicata non venga nascosta.

## Ordinamento e GPS

I candidati vengono ordinati per qualita dell'accettazione, stato operativo,
distanza disponibile, appartenenza al comune e nome. La distanza e calcolata
con la formula di Haversine solo quando il client passa entrambe le coordinate.

Senza GPS il motore sceglie una struttura soltanto se e l'unica compatibile o
se ha una qualita verificabile migliore. Se piu centri sono equivalenti,
`facility` resta nullo e l'elenco completo viene restituito in
`facility_alternatives`. Con il GPS il primo centro compatibile e aperto per
distanza diventa la proposta primaria.

La posizione ricevuta serve alla singola interrogazione ed entra nel contesto
della risposta. Questa fase non introduce alcuna persistenza della posizione.

## Contenuto della risposta

Ogni struttura espone:

- identificatore stabile, nome, indirizzo, coordinate e distanza;
- stato operativo e formulazione originale;
- requisiti di accesso e necessita di prenotazione;
- telefono, email e collegamenti informativi;
- periodi e intervalli settimanali di apertura, con eccezioni;
- stato dell'accettazione, base EER o descrittiva, etichette e limiti;
- provenienza delle informazioni su struttura, accesso, orari e materiali.

## Copertura corrente

Sul dataset completo del 7 agosto 2026 risultano:

- 211 strutture censite;
- 384 relazioni di accesso per 218 comuni e 204 strutture;
- 195 periodi di apertura riferiti a 170 strutture;
- 6.716 conferimenti riferiti a 163 strutture;
- 156 strutture dotate di coordinate.

Il caso reale `Armadio` a Firenze produce due centri compatibili. Senza GPS
restano alternative equivalenti; con una posizione presso viale Guidoni viene
proposto `CDR SAN DONATO`. Il centro dell'Isola del Giglio conserva lo stato
`temporarily_closed` e il testo `Chiuso per lavori di adeguamento`.

## Limiti

Le alternative limitrofe sono mostrate soltanto quando una fonte pubblica
l'accesso intercomunale. Non vengono inferiti accordi tra gestori. Gli elenchi
privi di EER possono essere collegati solo per descrizioni esplicite; le
somiglianze generiche non dimostrano l'accettazione. Alcuni testi di accesso
contengono ancora parti redazionali delle pagine sorgente e richiedono una
successiva pulizia conservativa.
