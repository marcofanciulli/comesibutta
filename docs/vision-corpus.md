# Corpus visivo e annotazione

Versione: 0.1.0
Ultimo aggiornamento: 7 agosto 2026

## Scopo

Il corpus serve a localizzare le marcature sugli imballaggi. Non deve insegnare
al modello il cassonetto e non sostituisce OCR, registro normativo o regole
territoriali. La tassonomia autorevole e in `data/vision/taxonomy-v1.json`; il
manifest iniziale e in `data/vision/corpus-manifest.json`.

Il manifest iniziale contiene zero immagini e il rapporto lo dichiara
`trainable: false`. Questo stato intenzionale permette di versionare contratti,
controlli e provenienza prima di acquisire fotografie.

## Tassonomia

Il detector usa cinque classi stabili:

| Classe | Contenuto |
| --- | --- |
| `mark.material_identification` | Sigla o codice che identifica materiale o composizione |
| `mark.collection_instruction` | Istruzione esplicita di raccolta, ancora da verificare localmente |
| `mark.regulated_product` | Marcatura di una filiera regolamentata |
| `mark.environmental_claim` | Dichiarazione ambientale o di riciclabilita |
| `mark.certification_or_scheme` | Certificazione, consorzio o sistema economico |

`unknown_mark` e un esito del runtime, non una classe da addestrare. Le immagini
negative non hanno annotazioni. Il codice, per esempio `PET 1`, non e una
classe: viene trascritto dall'OCR e risolto dal parser nel registro europeo.

## Regole di annotazione

1. Il riquadro comprende l'intera marcatura visibile, inclusi cornice, sigla e
   numero, con il minimo sfondo possibile.
2. Marcature separate sullo stesso imballaggio ricevono annotazioni separate.
3. Un gruppo grafico inscindibile riceve un solo riquadro, anche se contiene
   piu token.
4. La trascrizione conserva maiuscole, numero e barra visibili. Non completa
   lettere nascoste o illeggibili per conoscenza dell'annotatore.
5. `resolved_mark_ref` viene compilato soltanto quando sigla e numero sono
   compatibili con il registro. In caso contrario resta `null`.
6. Riflessi, sfocatura, occlusione e prospettiva descrivono l'immagine, senza
   correggerla mentalmente.
7. Un simbolo simile ma non pertinente resta una negativa oppure appartiene a
   un'altra classe; non viene forzato nella classe piu vicina.

Le coordinate sono normalizzate in formato `xyxy`. Il validatore controlla
che abbiano area positiva e restino nell'immagine.

## Provenienza e diritti

Sono ammesse soltanto queste basi:

- fotografia originale del progetto;
- consenso esplicito documentato;
- licenza aperta verificata, con identificativo, URL e attribuzione;
- pubblico dominio verificato;
- permesso contrattuale.

Ogni fonte deve superare la revisione dei diritti prima che una sua immagine
entri nel corpus. Non si acquisiscono fotografie da motori di ricerca o
cataloghi commerciali presumendo che siano riutilizzabili. La politica di
riuso della Commissione europea non comprende automaticamente marchi, loghi,
disegni registrati o opere di terzi; questi elementi richiedono una verifica
separata.

Riferimento:
[avviso legale della Commissione europea](https://commission.europa.eu/legal-notice_en).

## Privacy

Sono respinte immagini con volti, targhe, indirizzi privati, ricevute o altri
dati personali riconoscibili. I metadati EXIF vengono rimossi prima del
caricamento; data e condizioni utili sono riportate esplicitamente nel
manifest. Le fotografie inviate dagli utenti richiederanno consenso separato e
non entreranno automaticamente nel corpus.

## Separazione dei dati

Lo split e deterministico: SHA-256 del seme e di `capture_group_id` assegna
80 bucket al training, 10 alla validazione e 10 al test. Tutte le viste dello
stesso imballaggio o della stessa breve sessione condividono il gruppo e quindi
lo split. In questo modo rotazioni, raffiche e quasi-duplicati non attraversano
il confine del test.

Il test accetta soltanto fotografie reali. Ritagli di documenti e immagini
sintetiche possono essere usati per preparazione e addestramento, ma non per
misurare la qualita di rilascio.

## Flusso operativo

1. Registrare la fonte e approvarne diritti e privacy.
2. Calcolare SHA-256, rimuovere EXIF e assegnare il gruppo di cattura.
3. Caricare le immagini in CVAT usando le cinque classi della tassonomia.
4. Annotare riquadri, trascrizione e condizioni qualitative.
5. Riesaminare almeno tutte le annotazioni ambigue e il campione di test.
6. Esportare e costruire il manifest canonico.
7. Eseguire il validatore prima di versionare il puntatore DVC.

```sh
PYTHONPATH=src python3 -m dovelobutto.cli validate-vision-corpus \
  --manifest data/vision/corpus-manifest.json \
  --taxonomy data/vision/taxonomy-v1.json \
  --assets-root data/vision/assets \
  --report outputs/vision-corpus-report.json
```

Il codice, la tassonomia, il manifest e i rapporti restano in Git. Le immagini
e gli artefatti di addestramento saranno gestiti con DVC e object storage. Non
si configura un remoto finche non sono stabiliti titolare, localizzazione,
accessi, cifratura, conservazione e procedura di cancellazione.

## Criteri del primo corpus

Il primo addestramento richiede fotografie reali distribuite tra formati,
materiali, produttori, illuminazioni, dimensioni, curvature e livelli di
usura. Prima di un rilascio verranno fissate soglie quantitative a partire da
un pilot; il rapporto dovra comunque mostrare separatamente origini, classi,
gruppi di cattura e split. Un corpus con sole immagini sintetiche o senza test
reale non puo essere dichiarato pronto per il rilascio.
