# Politica di accesso alle fonti

Versione: 0.1.0  
Verifica iniziale: 5 agosto 2026

## Esito della verifica SEI Toscana

Non e stato individuato un divieto esplicito di scraping, crawling, estrazione
o riuso nelle pagine legali pubblicamente collegate dal sito SEI Toscana.

Fonti esaminate:

- homepage e footer: https://seitoscana.it/
- indice delle informative: https://seitoscana.it/privacy
- privacy policy del sito: https://seitoscana.it/privacy/privacy-policy
- policy completa collegata, ultima modifica 9 aprile 2026:
  https://www.iubenda.com/app/privacy-policy/59671259/legal
- condizioni dell'Area Bollette:
  https://seitoscana.it/condizioni-generali-informativa-privacy-area-bollette

La privacy policy regola il trattamento dei dati personali e di navigazione;
non contiene clausole sull'estrazione dei contenuti pubblici. Le condizioni
dell'Area Bollette riguardano il servizio autenticato e non vengono estese alle
pagine informative pubbliche. Il progetto non accede all'Area Bollette.

Questa e una verifica operativa delle condizioni pubblicate, non un parere
legale ne una dichiarazione generale sulla titolarita dei contenuti.

## Pagine comunali

Le pagine dei 104 comuni presenti nel registro corrente sono pubblicate sotto
`https://seitoscana.it/comuni/` e appartengono quindi allo stesso dominio e
alla stessa verifica. Non stiamo ancora acquisendo i siti web autonomi dei
Comuni.

Prima di aggiungere un nuovo dominio comunale o istituzionale occorre
registrare separatamente:

- URL delle condizioni d'uso o note legali;
- URL e contenuto di `robots.txt`;
- licenza o indicazione sul riuso, se pubblicata;
- data della verifica e percorsi consentiti;
- eventuali limiti di frequenza o altre restrizioni.

L'assenza di un divieto su SEI Toscana non autorizza automaticamente la
scansione di domini diversi.

## Regole obbligatorie del crawler

1. Leggere `robots.txt` all'inizio di ogni esecuzione live.
2. Non proseguire se il file non puo essere acquisito o vieta la URL.
3. Usare un'identita e un contatto riconoscibili:
   `DoveLoButtoData/0.1 (+mailto:marcofanciulli@me.com)`.
4. Eseguire richieste seriali con almeno un secondo di intervallo, elevandolo
   quando `robots.txt` richiede un tempo maggiore.
5. Usare ETag e Last-Modified per evitare trasferimenti non necessari.
6. Visitare soltanto pagine informative pubbliche pertinenti al progetto.
7. Non compilare form, eseguire prenotazioni o accedere ad aree riservate.
8. Non raccogliere dati personali degli utenti e non aggirare misure tecniche.
9. Conservare provenienza e brevi evidenze; non ripubblicare impaginazione,
   immagini o interi documenti come contenuto editoriale proprio.
10. Sospendere il dominio se cambiano condizioni, robots o comportamento del
    server, fino a una nuova verifica.

## Stato di robots.txt

Il file `https://seitoscana.it/robots.txt` deve essere verificato dalla
pipeline live, non presunto da questa analisi documentale. La passata viene
considerata autorizzata operativamente solo dopo che il parser ha confermato
che le URL comunali selezionate sono consentite. L'esito e conservato nel
rapporto di scansione.

## Verifica ATO Toscana Costa

Verifica operativa eseguita il 6 agosto 2026 sulle fonti iniziali ATO Toscana
Costa, AAMPS, ESA, REA e GEOFOR. Non sono state individuate condizioni d'uso che
vietino esplicitamente l'acquisizione delle pagine informative pubbliche; i
footer collegano principalmente informative privacy e cookie. Questa
conclusione resta qualificata e non costituisce un parere legale.

Esiti `robots.txt` osservati:

- ATO Toscana Costa: vietato `/wp-admin/`, consentito
  `/wp-admin/admin-ajax.php`; il PDF Comune-SOL e servito da un percorso
  pubblico del plugin allegati;
- AAMPS: vietati `/wp-json/` e `/?rest_route=`; le pagine HTML e il PDF pubblico
  "Dove lo butto?" non ricadono nei percorsi vietati;
- ESA: nessun percorso vietato;
- REA: nessun percorso vietato;
- GEOFOR: nessun percorso vietato; il file dichiara una direttiva `Disallow`
  vuota per gli agenti generici.

Il rifiutario REA usa il punto pubblico `wp-admin/admin-ajax.php` esclusivamente
in lettura. La pipeline interroga una volta ciascuna iniziale alfabetica,
applica un intervallo seriale, conserva le iniziali vuote e registra
separatamente gli errori. Non vengono usate le funzioni del sito che inviano
suggerimenti o dati personali.
