# Prontuario fotografico

Versione: 0.1.0
Ultimo aggiornamento: 7 agosto 2026

La versione A5 pronta per telefono e stampa e disponibile in
`output/pdf/prontuario-fotografico-imballaggi.pdf`.

## Identificativo dell'imballaggio

Assegna un solo identificativo a ogni imballaggio fisico:

`PKG-AAAAMMGG-NNN`, per esempio `PKG-20260807-001`.

Tutte le foto dello stesso imballaggio mantengono questo identificativo, anche
se mostrano lati o componenti diversi. Non riutilizzarlo per un altro oggetto.

## Categorie rapide

| Sigla | Categoria | Esempi |
| --- | --- | --- |
| `MI` | Identificazione materiale | `PET 1`, `PAP 22`, `GL 70`, `C/PAP 84` |
| `RI` | Istruzione di raccolta | `Raccolta plastica`, `Verifica il tuo Comune` |
| `PR` | Prodotto regolamentato | Bidone barrato RAEE o batterie |
| `DA` | Dichiarazione ambientale | Ciclo di Mobius, riciclabile, contenuto riciclato |
| `CS` | Certificazione o sistema | FSC, PEFC, compostabilita certificata, consorzi |
| `NEG` | Immagine negativa | Nessuna marcatura rilevante o simbolo simile ma estraneo |

Se una foto contiene piu categorie, usa nel nome quella al centro dello scatto
e registra le altre nelle note. Non indovinare: in caso di dubbio usa `NEG` e
descrivi cio che vedi.

## Nome del file

`IDENTIFICATIVO__CATEGORIA__NUMERO.jpg`

Esempi:

- `PKG-20260807-001__MI__01.jpg`
- `PKG-20260807-001__RI__02.jpg`
- `PKG-20260807-001__CS__03.jpg`

## Sequenza minima

Per ogni imballaggio acquisisci almeno:

1. una vista complessiva fronte o lato principale;
2. una vista complessiva del retro;
3. un primo piano frontale di ogni marcatura;
4. un primo piano leggermente obliquo;
5. una foto separata per ogni componente separabile, come tappo, etichetta,
   vaschetta o involucro.

Sono utili anche condizioni difficili reali: superficie curva, stampa piccola,
riflessi, pieghe, usura e luce scarsa. Conserva sempre almeno uno scatto nitido
e frontale; non produrre soltanto foto difficili.

## Cosa registrare

- forma dell'imballaggio: bottiglia, vaschetta, scatola, sacchetto ecc.;
- componente fotografato;
- testo effettivamente leggibile, senza completarlo per intuizione;
- eventuale riferimento normativo, soltanto se certo;
- luce, angolo, messa a fuoco, riflesso e occlusione;
- autore della fotografia e base dei diritti.

Il formato completo e definito in
`schemas/photo-capture-record.schema.json`; un record di esempio e in
`examples/photo-capture-ledger.jsonl`.

## Privacy e sicurezza

- non fotografare persone, targhe, indirizzi, ricevute o documenti;
- usa un fondo neutro senza oggetti personali;
- non aprire contenitori pericolosi, taglienti o contaminati;
- non pulire o alterare una marcatura se questo modifica il suo aspetto reale;
- conserva le fotografie complete soltanto nell'area privata del corpus.

## Controllo prima di chiudere

- identificativo uguale su tutte le foto dello stesso oggetto;
- categoria nel nome del file;
- almeno una vista generale e un primo piano nitido;
- componenti separabili documentati;
- testo visibile registrato senza inferenze;
- nessun dato personale nell'immagine.
