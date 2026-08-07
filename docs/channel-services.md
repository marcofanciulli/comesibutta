# Servizi dei canali di conferimento

Versione: 1
Ultimo aggiornamento: 7 agosto 2026

## Scopo

Il motore collega i canali controllati ai servizi operativi pubblicati per il
comune. Ritiri e punti di raccolta sono entita territoriali strutturate; riuso,
restituzione al rivenditore e operatore specializzato restano indicazioni della
fonte finche non esiste un servizio autonomo acquisito.

L'esistenza di un servizio non dimostra da sola che accetti il rifiuto cercato.
La risposta separa quindi sempre disponibilita territoriale e compatibilita.

## Servizi strutturati

`channel:home-pickup` viene collegato ai record `pickup_service` compatibili
con comune, tipo di utenza e zona. La risposta espone prenotazione, telefono,
URL, applicazione o sportello, limiti quantitativi e istruzioni di esposizione.

`channel:mobile-collection` usa soltanto punti con tipo `mobile`.
`channel:collection-point` usa punti speciali, fissi, temporanei o stazioni di
contenitori. Quando e disponibile il GPS, i punti sono ordinati per distanza;
in caso contrario restano ordinati in modo deterministico.

## Stati di compatibilita

Ogni servizio usa uno dei seguenti stati:

- `verified_description`: rifiuto o categoria coincidono esplicitamente con
  l'elenco o le istruzioni del servizio;
- `acceptance_not_published`: il servizio esiste, ma la fonte rinvia a una
  scheda senza riportare i materiali nel dato acquisito;
- `not_verified`: il servizio esiste, ma nessun elemento pubblicato consente
  di collegarlo al rifiuto.

Un servizio non verificato resta consultabile, accompagnato da un avviso. Non
viene presentato come soluzione certa.

Se un canale non dispone di alcun servizio territoriale, compare in
`unresolved_channels` con stato `not_published`. Riuso, rivenditore e operatore
specializzato usano `source_only`: l'app puo mostrare il testo originale, ma
non inventa nome, indirizzo o procedura.

## Copertura corrente

Il dataset del 7 agosto 2026 contiene:

- 294 servizi di ritiro in 247 comuni;
- 758 punti in 123 comuni, dei quali 137 mobili;
- 414 associazioni territoriali che indicano il ritiro;
- 381 associazioni che indicano un servizio mobile;
- 189 associazioni che indicano un punto di raccolta;
- 63 indicazioni di restituzione al rivenditore, 66 di riuso e 123 di ricorso
  a operatori specializzati, oggi conservate come canali sorgente.

## Casi verificati

Per `Armadio` a Firenze il servizio OnDemand viene collegato come ritiro
compatibile, con prenotazione web e istruzioni pubblicate. Per `Accessori
cellulari` vengono restituiti 18 ecofurgoni ordinabili per distanza; il campo
materiali rinvia pero alla scheda AliaEstra, quindi la compatibilita resta
`acceptance_not_published`.

`Assi da stiro` a Marradi conserva il riuso come `source_only` e segnala
l'assenza di un ritiro strutturato. `Asciugacapelli` a Bientina mantiene il canale
uno-contro-uno come `source_only`; i servizi di ritiro esistenti restano
`not_verified`. `Bitumi` a Firenzuola conserva l'indicazione verso
operatori specializzati senza trasformarla in un'azienda specifica.

## Limiti

Le descrizioni di alcuni servizi Alia includono porzioni redazionali della
pagina. Sono conservate per non perdere istruzioni e provenienza, ma dovranno
essere ripulite con un estrattore specifico. Le schede dei materiali degli
ecofurgoni devono essere acquisite prima di poter confermare i singoli rifiuti.
