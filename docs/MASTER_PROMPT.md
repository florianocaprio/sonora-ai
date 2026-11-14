# SONORA AI — MASTER PROMPT PER CODEX

**Progetto:** SONORA AI — Intelligent Audio Restoration Studio  
**Committente:** Floriano  
**Repository desiderato:** `sonora-ai`, privato  
**Cartella locale proposta:** `~/Developer/SONORA-AI`  
**Hardware di riferimento:** MacBook Pro M2 Max con 32 GB di memoria unificata; secondo target dichiarato dal committente: MacBook M5 Max con 64 GB, in arrivo.  
**Modalità di lavoro:** sviluppo cooperativo multi-agente, orientato a una soluzione end-to-end funzionante.  
**Lingua dell'interfaccia e della documentazione utente:** italiano. Identificatori del codice in inglese.  
**Versione del brief:** 1.0 — 14 novembre 2026.

---

## 1. Mandato operativo: costruisci il prodotto, non soltanto il progetto sulla carta

Agisci come principal engineer, architetto software, specialista audio e coordinatore di un gruppo di agenti di sviluppo. Devi creare e iniziare a implementare **SONORA AI**, una piattaforma professionale locale per separare, analizzare, restaurare e rimixare audio cinematografico.

Non limitarti a una proposta architetturale, a un piano, a una raccolta di notebook o a un mockup. Crea il workspace, il repository, il codice, le configurazioni, la documentazione, i test e un'applicazione avviabile. Lavora concretamente sul filesystem e sugli strumenti disponibili.

Non impostare il lavoro come una roadmap a fasi da sottoporre ogni volta all'utente. Scomponi internamente il problema in attività e dipendenze, delega agli agenti e integra continuamente verso l'intero flusso. Le sezioni di questo documento sono requisiti del prodotto, non tranche di consegna. Non fermarti dopo aver costruito soltanto l'upload o la separazione per chiedere di passare al resto.

L'obiettivo funzionale è:

```text
IMPORTAZIONE AUDIO
        ↓
SEPARAZIONE AI LOCALE
        ↓
DIALOGHI / MUSICA / EFFETTI SONORI
        ↓
DIAGNOSTICA COMUNE + TRE PROFILI SPECIALIZZATI
        ↓
TIMELINE DEI DIFETTI + PIANO DI INTERVENTO MODIFICABILE
        ↓
RESTAURO BASIC / MEDIUM / HIGH, CONFIGURABILE PER STEM E REGIONE
        ↓
ASCOLTO, CONFRONTO, APPROVAZIONE E VERSIONAMENTO
        ↓
MIXER DSP CLASSICO + MASTERING CONTROLLATO
        ↓
STEM RESTAURATI + MASTER + REPORT + PROGETTO RIPRODUCIBILE
```

Le elaborazioni AI del prodotto devono avvenire localmente. Non usare API audio commerciali, servizi cloud di separazione, plugin proprietari da fonico o abbonamenti esterni come dipendenze obbligatorie. Sono ammessi download iniziali trasparenti di dipendenze e pesi autorizzati. Dopo la preparazione dell'ambiente, il flusso audio deve poter funzionare offline.

Gli agenti di sviluppo di Codex sono distinti dai componenti audio del prodotto: non introdurre una dipendenza da un servizio LLM nel runtime per dimostrare che lo sviluppo è multi-agente.

Procedi autonomamente sulle decisioni tecniche reversibili, documentandole. Chiedi intervento soltanto per credenziali, autorizzazioni mancanti, spese, operazioni distruttive o ambiguità davvero bloccanti. Non chiedere nuovamente nome, hardware o requisiti già specificati.

## 2. Contesto della conversazione e tracciabilità dei requisiti

Questo brief deriva dalla conversazione ChatGPT con Floriano sul progetto **SONORA AI**, nata dalla separazione di un estratto cinematografico in parlato, musica ed effetti.

**Consulta questa stessa chat per ulteriori informazioni soltanto se il tuo ambiente dispone realmente dell'accesso autorizzato al thread, di un collegamento fornito dall'utente o di una sua esportazione.** Non presumere di poter leggere automaticamente altre conversazioni ChatGPT. Non inventare un URL della chat, non cercare di renderla pubblica e non bloccare lo sviluppo se il collegamento non è disponibile.

Salva il contesto disponibile in `docs/PROJECT_CONTEXT.md`. Conserva questo prompt integrale in `docs/MASTER_PROMPT.md`; crea `docs/REQUIREMENTS.md` con identificativi stabili e criteri verificabili. Prevedi un campo opzionale `source_chat_url`, lasciato vuoto se non conosciuto. Non confondere il riassunto dei requisiti con una trascrizione integrale della conversazione.

Decisioni già confermate:

- Il nome definitivo è **SONORA AI**; sottotitolo **Intelligent Audio Restoration Studio**.
- L'utente vuole un programma reale: portale locale, inferenza locale, controlli professionali, salvataggio dei progetti e gestione completa dell'audio.
- Le tre categorie sono **Dialoghi/Parlato**, **Musica**, **Effetti sonori**: non sono gli stem musicali voce, batteria, basso e altro.
- Bandit V2 è già stato utilizzato nel lavoro precedente dell'utente: il parlato era soddisfacente, mentre musica ed effetti si contaminavano. Il benchmark deve concentrarsi anche su questa separazione, senza peggiorare inutilmente il dialogo.
- DBS-TIGER e Bandit V2 sono candidati discussi; MVSEP-CDX23 è stato citato come confronto, non come dipendenza remota autorizzata né come checkpoint locale sicuramente disponibile.
- Ogni stem deve avere diagnostica e restauro dedicati, con manopole e parametri modificabili.
- Basic significa restauro conservativo; Medium include miglioramento controllato dell'ascolto; High può includere ricostruzione dei segmenti mancanti, sempre dichiarata e approvata.
- I preset devono essere configurabili anche nei singoli parametri e nelle singole regioni, non soltanto selezionabili con tre pulsanti.
- Il mixer finale deve essere DSP classico, con controlli, automazioni e misure audio professionali.
- L'M2 Max 32 GB è il target attuale; il MacBook M5 Max 64 GB è un secondo target fornito dall'utente. Rileva l'hardware effettivo: non dedurre prestazioni, supporto dei modelli o accelerazioni da un nome commerciale.
- Non è richiesta una garanzia di inferenza AI in tempo reale. Ascolto e interazione devono essere fluidi; separazione e restauro possono avvenire offline.

Le precedenti affermazioni della chat su elaborazioni eseguite, qualità, modelli utilizzati o compatibilità non sostituiscono evidenze riproducibili. Per questa implementazione fanno fede codice, pesi identificati, configurazioni, test e log realmente disponibili. Non dichiarare di riprodurre una precedente pipeline se non ne possiedi gli artefatti.

Il file discusso nella chat aveva nome `bladerunner1.mp3.mpeg`. Usalo soltanto se l'utente lo rende disponibile nel tuo workspace. Non presumere che un percorso `/mnt/data/...` della chat esista sul suo Mac. Non committare o redistribuire estratti cinematografici dell'utente.

## 3. Workspace locale, Git e repository GitHub

Prima delle modifiche, identifica ambiente reale, directory corrente, permessi, architettura, disponibilità di Git, GitHub CLI o connettore GitHub, Python, Node, strumenti di compilazione e FFmpeg.

Se lavori realmente sul Mac dell'utente e non è già stato selezionato un workspace, usa `~/Developer/SONORA-AI`. Se sei già dentro il workspace SONORA AI, riutilizzalo. Se operi in un sandbox o in un ambiente remoto, crea il progetto nell'area autorizzata e dichiara il percorso reale: non affermare di aver creato cartelle sul Mac quando non hai tale accesso.

Ispeziona cartelle e repository eventualmente esistenti prima di inizializzarli. Non sovrascrivere file, non cambiare remote altrui e non annullare modifiche dell'utente.

Crea un repository GitHub **privato** chiamato `sonora-ai`, usando l'account autenticato e un proprietario identificato con certezza. Non inventare account o organizzazioni. Descrizione proposta: `Local-first cinematic audio separation, diagnostics, restoration and DSP mixing for Apple Silicon`.

Usa gli strumenti GitHub disponibili o `gh`, dopo aver controllato autenticazione, permessi ed eventuale esistenza del repository. La creazione da una directory esistente è supportata da GitHub CLI; verifica la sintassi della versione installata prima di eseguirla [R7]. Se manca l'accesso, continua il lavoro locale e documenta precisamente il solo blocco della pubblicazione. Non fingere un push riuscito.

Imposta `main` come ramo principale per il nuovo repository. Utilizza branch o worktree per il lavoro parallelo degli agenti e un ramo di integrazione. Non aggirare protezioni esistenti, non usare force-push e non creare commit contenenti dati o segreti. Verifica i file staged prima del push.

Escludi dal repository: audio caricati, output, modelli, cache, log sensibili, database runtime, credenziali, `.env`, directory degli ambienti e grandi file generati. Mantieni `.env.example` privo di valori reali. Non scegliere unilateralmente una licenza di distribuzione per il codice originale dell'utente: registra la decisione ancora da confermare; conserva invece tutte le licenze obbligatorie delle dipendenze integrate.

## 4. Organizzazione multi-agente effettiva

Usa le capacità native di delega e subagent disponibili nella tua versione di Codex; consulta la documentazione ufficiale e le opzioni effettivamente installate [R1]. Non simulare una squadra scrivendo soltanto nomi di ruoli nei log. Se la sessione non consente agenti paralleli, dichiaralo e applica la stessa separazione di responsabilità con esecuzione seriale, senza interrompere il lavoro.

Adatta numero e concorrenza alla complessità, ai limiti dell'ambiente e al consumo di risorse. Le responsabilità da coprire sono:

| Responsabilità | Compito principale |
|---|---|
| Coordinamento e integrazione | Contratti condivisi, dipendenze, decisioni, merge e verifica del prodotto completo. |
| Separazione AI / Apple Silicon | Adattatori, checkpoint, compatibilità CPU/MPS, segmentazione, stereo e benchmark. |
| Diagnostica e restauro | Rilevatori, profili per stem, riparazioni, ricostruzione controllata e validazione. |
| DSP e riproduzione | Mixer, automazioni, clock, buffering, meter, rendering e precisione temporale. |
| Backend e persistenza | API, coda persistente, filesystem, cache, versioni, annullamento e ripartenza. |
| Frontend e UX audio | Studio, timeline, spettrogrammi, inspector, manopole, console e accessibilità. |
| QA / sicurezza / release | Test, licenze, dipendenze, regressioni, setup macOS e documentazione verificata. |

Un agente può coprire più responsabilità. Il coordinatore deve assegnare per ogni attività obiettivo, percorsi modificabili, contratti, test e criteri di accettazione. Evita modifiche concorrenti non coordinate a lockfile, schema dati e configurazioni condivise.

Crea `AGENTS.md` sintetico in root con invarianti, comandi e collegamenti ai documenti; aggiungi istruzioni locali solo dove utili. Non incollare tutto questo brief in `AGENTS.md`: conserva il documento integrale sotto `docs/` e richiedine la lettura. Codex utilizza `AGENTS.md` come istruzione persistente del progetto [R2].

Mantieni uno stato condiviso leggibile, per esempio `docs/WORK_STATE.md`, con attività, proprietari, dipendenze, decisioni e blocchi. Le configurazioni dei custom agent devono usare il formato realmente supportato dalla versione installata, non uno schema immaginato.

Gli agenti devono produrre codice integrabile e testarlo, non consegnare componenti isolati incompatibili. Il coordinatore esegue anche il flusso completo e risolve le divergenze.

## 5. Architettura locale: modulare, non inutilmente distribuita

Progetta un monorepo con componenti separati da interfacce tipizzate, ma un'installazione leggera per un singolo Mac. Non rendere obbligatori Kubernetes, Redis, Celery, PostgreSQL o MinIO: in questo contesto usa preferibilmente SQLite per metadati e coda persistente, filesystem locale per gli asset e un worker separato dall'API.

Stack di riferimento:

| Area | Impostazione |
|---|---|
| Interfaccia | React, TypeScript, Vite, componenti accessibili e stato tipizzato. |
| API locale | Python, FastAPI, Pydantic e OpenAPI. |
| Worker audio | Processo Python separato; job persistenti, isolamento dei modelli e lock GPU. |
| AI | PyTorch con backend MPS quando verificato; CPU come alternativa esplicita. |
| DSP / analisi | NumPy, SciPy, soundfile, FFmpeg/ffprobe; altre librerie solo se motivate. |
| Mixer | Motore deterministico CPU, con definizione condivisa del grafo DSP e test fra preview e render. |
| Persistenza | SQLite, migrazioni e filesystem con manifest e checksum. |
| Frontend audio | Un solo clock di riproduzione; AudioWorklet/Web Audio con buffering controllato. |
| Tooling | Ambiente Python isolato con lockfile; package manager JavaScript con lockfile; test e lint. |

PyTorch espone un device MPS per accelerare operazioni su GPU Apple; questo non prova che qualsiasi modello sia supportato integralmente [R3]. Verifica versioni di Python, PyTorch, macOS e dipendenze insieme. Non installare pacchetti CUDA sul percorso Apple Silicon.

Il worker GPU deve essere nativo macOS. Docker può essere usato per test CPU o componenti opzionali, ma non deve essere il percorso necessario dell'inferenza Metal.

Preferisci un core DSP piccolo e condivisibile tra rendering nativo e anteprima, eventualmente Rust o C++ con binding e WebAssembly. Scegli con un ADR l'implementazione concreta. Non introdurre un framework enorme solo per disegnare un mixer. Se alcuni processori non sono riproducibili nell'anteprima live, usa una preview prerenderizzata dal renderer autorevole e segnalalo: non far ascoltare un algoritmo diverso da quello esportato senza avvisare.

La struttura indicativa, adattabile senza perdere responsabilità, è:

```text
SONORA-AI/
  AGENTS.md
  README.md
  .github/workflows/
  apps/web/
  services/api/
  services/worker/
  packages/contracts/
  packages/audio_core/
  packages/dsp_core/
  packages/model_adapters/
  configs/models/
  configs/restoration_profiles/
  configs/analysis_profiles/
  scripts/
  tests/unit/
  tests/integration/
  tests/e2e/
  tests/audio_regression/
  tests/fixtures/
  docs/
```

I dati runtime devono stare fuori dal repository, per esempio sotto `~/Library/Application Support/SONORA AI/`; cache sotto `~/Library/Caches/SONORA AI/`. Rendi configurabili le destinazioni, anche su SSD esterno, e gestisci percorsi con spazi, permessi, volume non disponibile e spazio insufficiente.

## 6. Contratti dati, versionamento e riproducibilità

Definisci prima dell'implementazione parallela i contratti condivisi. Evita duplicazioni manuali incoerenti: genera i tipi frontend dagli schemi o verifica automaticamente la compatibilità.

Entità minime: `Project`, `AudioAsset`, `Stem`, `AnalysisRun`, `DefectEvent`, `RestorationPlan`, `RestorationOperation`, `PatchCandidate`, `AudioVersion`, `MixerSession`, `AutomationLane`, `Job`, `ModelManifest`, `ExportArtifact`, `QualityReport`.

Usa identificativi stabili, versioni di schema, timestamp e riferimenti di provenienza. Gli asset originali sono immutabili. Ogni output deve indicare input, hash, algoritmo, versione, parametri, backend e stato di approvazione.

La timeline autorevole è in campioni interi a 64 bit alla frequenza di progetto. Definisci intervalli come `[start_sample, end_sample)`. Millisecondi e timecode sono rappresentazioni derivate; non usare soltanto float in secondi per allineamenti e patch.

Per `DefectEvent` includi almeno: stem e versione sorgente; tipo; intervallo; eventuale banda di frequenza; gravità; confidenza e suo significato; rilevatore/versione; misure di supporto; origine stimata `source`, `separation` o `unknown`; proposta; stato `unreviewed`, `confirmed`, `dismissed`, `repaired`.

Una confidenza euristica non è una probabilità calibrata: registrala come tale. I campi non misurabili devono essere null con motivazione, non zero o numeri inventati.

Per i modelli registra autore, repository, revisione, checkpoint, SHA-256, licenze distinte di codice e pesi, formato d'ingresso, ordine delle uscite, frequenza, canali, precisioni, backend verificati, limiti delle finestre, memoria misurata e test eseguiti.

Le cache devono dipendere da input, regione, configurazione, modello/revisione e versione degli algoritmi. Una modifica invalidi solo i discendenti interessati. Salva i risultati con scritture atomiche; un crash non deve trasformare un file incompleto in un output valido.

## 7. Acquisizione audio e invarianti del segnale

Accetta almeno WAV, FLAC, AIFF, MP3 e AAC/M4A tramite decoder verificati. Controlla il contenuto reale con ffprobe o equivalente, non soltanto l'estensione. Supporta il caso di nome insolito `*.mp3.mpeg` senza assumere che sia un video.

Mostra prima dell'elaborazione durata, codec, frequenza, canali/layout, campioni decodificati e proprietà disponibili. Conserva il file originale e il suo checksum. Un bitrate compresso non deve essere presentato come bit depth PCM.

Usa PCM floating-point per le lavorazioni. Proponi 48 kHz come preset cinematografico, ma consenti di mantenere la frequenza sorgente o sceglierne una differente. Gli adattatori devono convertire alla frequenza richiesta dal modello e riportare gli output alla timeline comune con compensazione documentata.

Non fare normalizzazione indipendente degli stem, compressione, limiter, taglio dei silenzi, conversione in mono o dithering impliciti durante importazione e separazione. Gestisci esplicitamente priming/padding dei codec quando disponibile e conserva la durata decodificata autorevole.

Sono obbligatori: stesso numero di campioni degli stem esportati, ordine dei canali documentato, sincronizzazione, nessun cambio di velocità involontario, controllo NaN/Inf e gestione del headroom. Non confondere un picco oltre 0 dBFS in float con clipping già inciso nel file: impedisci però saturazione involontaria nelle conversioni PCM intere.

Supporta realmente mono e stereo. Prevedi schemi dati multicanale, ma non etichettare come 5.1/7.1 una separazione non validata per quel layout. Per layout non supportati conserva l'originale e richiedi una conversione esplicita o segnala il limite.

Elabora file lunghi a blocchi, senza caricare l'intero film e tutti gli stem in RAM. Considera formati di esportazione adeguati ai file grandi, per esempio RF64, quando i limiti del WAV classico lo richiedono.

## 8. Separazione AI: modelli veri, classificazione corretta e stereo controllato

Implementa un'interfaccia di separazione con `probe_capabilities`, `load`, `separate`, `cancel` e `unload`; firme e risultati devono essere tipizzati e testati. Rendi selezionabile il modello e mostra le capacità realmente disponibili.

**DBS-TIGER** e **Bandit V2** sono i primi candidati da integrare e confrontare tramite fonti ufficiali [R4, R5]. Il sistema deve usare checkpoint preaddestrati identificati e deve fallire chiaramente su mapping dei pesi errato o modello non caricato. Non sostituire la separazione AI con filtri passa-banda, copia dell'originale o pesi casuali.

La model card DBS-TIGER-DnR descrive ingresso **mono a 44,1 kHz** [R4]. Non dichiararlo stereo nativo. Un adattamento L/R separato mantiene due canali ma non garantisce di preservare l'immagine stereo. Se lo implementi, rendilo riconoscibile, misura le alterazioni fra i canali e confrontalo con alternative che trattano lo stereo congiuntamente. Non usare di nascosto la media L/R, non duplicare il mono su due canali spacciandolo per stereo preservato.

Per Bandit V2 verifica checkpoint, configurazione esatta, mapping delle sorgenti e gestione canali, non solo il nome del repository. Usa un estratto di prova per controllare che `dialogue`, `music` e `effects` non siano scambiati.

Preferisci il modello che offre il miglior compromesso verificato per questo materiale, non automaticamente quello con il maggior numero di parametri. Il benchmark deve evidenziare in particolare musica negli effetti ed effetti nella musica. Non promettere assenza di contaminazione.

Usa inferenza a finestre con overlap-add normalizzato, padding e crop documentati, gestione dei bordi e contesto sufficiente. Segui inizialmente il profilo d'inferenza ufficiale del modello; ogni modifica per ragioni di memoria va tracciata e verificata. Un cambio di finestra può influenzare il risultato: non presentarlo come sempre neutro.

Prevedi un'anteprima su regione selezionata, elaborazione completa, annullamento e confronto fra risultati mantenendo versioni separate. Un eventuale ensemble è opt-in, sequenziale sul target 32 GB e giustificato da prove: non sommare o mediare stem senza verificarne guadagno, fase e allineamento.

Gestisci separatamente il residuo:

```text
residual = canonical_original - (dialogue + music + effects)
```

Calcolalo sul medesimo dominio, con gli stem non restaurati e senza normalizzazioni autonome. Mostralo come **residuo di ricostruzione**, non come quarto stem semanticamente pulito. La ricostruzione esatta con il residuo non dimostra che la separazione sia buona.

Non assegnare automaticamente il residuo agli effetti e non reinserirlo di nascosto nel mix restaurato: può reintrodurre rumore e contaminazioni. Nel mixer deve essere una traccia opzionale, disattivata di default, con avviso e audit della scelta.

## 9. Gestione risorse Apple Silicon

Crea un `ResourceManager` che rilevi macchina, architettura, memoria, macOS, disponibilità MPS e spazio disco. Non trattare i 32/64 GB unificati come VRAM interamente libera.

Impostazione iniziale: una sola inferenza pesante alla volta su entrambi i target, fino a benchmark che giustifichino diversamente. Separa la concorrenza degli agenti di sviluppo dalla concorrenza dei modelli audio.

Carica i modelli quando servono; libera riferimenti, buffer e processi al termine quando necessario. Non promettere che svuotare una cache basti sempre a restituire tutta la memoria al sistema. Mantieni margine per macOS, browser, API e playback.

Implementa budget configurabili, monitoraggio della pressione memoria, rilevamento OOM, tentativi limitati con chunk ammessi dal modello, cancellazione pulita e ripartenza dal checkpoint. Non disabilitare protezioni MPS per forzare l'allocazione.

La scelta CPU/MPS e i fallback devono apparire nel job e nel report. Valida operazioni FFT, tensori complessi, precisione e trasferimenti; usa float32 come riferimento finché precisioni ridotte non siano validate. Non attivare fallback globali silenziosi nascondendo che una parte rilevante gira su CPU.

Il resource manager può adattare esecuzione e proporre alternative; non deve cambiare modello, profilo di restauro o qualità richiesta senza renderlo evidente. Registra i parametri effettivamente usati. Sul 64 GB consenti configurazioni più impegnative solo dopo misura, senza inventare fattori di velocità rispetto all'M2 Max.

Misura tempo di caricamento, wall-clock, real-time factor definito esplicitamente, memoria del processo e memoria GPU disponibile tramite API affidabili. Indica dati non accessibili invece di simularli.

## 10. Diagnostica: motore comune, tre profili e confronto con la sorgente

Analizza sia il mix originale sia gli stem non restaurati e restaurati. Questo serve anche a distinguere difetti già presenti da possibili artefatti della separazione. Non attribuire automaticamente clipping, fruscio o distorsione all'età del supporto.

Per ogni rilevatore definisci algoritmo, parametri con unità, campo di validità, costo computazionale, evidenze, test e limiti. Dove non puoi diagnosticare con affidabilità, formula una segnalazione da verificare e non una certezza.

| Famiglia | Fenomeni e misure richiesti |
|---|---|
| Livelli e integrità | Sample peak, rischio di clipping, flat-top compatibili con clipping, DC offset, NaN/Inf, discontinuità. |
| Rumori stazionari | Fruscio, noise floor stimato, ronzio 50/60 Hz e armoniche, rumble, interferenze tonali. |
| Disturbi impulsivi | Click, pop, crackle; distinzione prudente dai transienti artistici. |
| Continuità | Dropout, buchi, muting anomalo, giunzioni; distinzione dal silenzio intenzionale. |
| Spettro | Limitazione di banda stimata, notch sospetti, squilibri e artefatti di compressione/separazione. |
| Dinamica | RMS, crest factor, loudness, LRA quando applicabile, pumping o compressione sospetta. |
| Stereo | Bilanciamento, correlazione, polarità e variazioni dell'immagine stereo. |
| Temporali | Possibile wow/flutter o instabilità; distinguere stima cieca da misura su riferimento noto. |
| Contenuto | Contaminazione fra stem, intelligibilità vocale stimata, riverbero e transienti alterati. |

**Dialoghi:** priorità a intelligibilità, identità timbrica, consonanti, respiri, sibilanti, continuità della frase e ambiente. Un sibilante o un respiro non è automaticamente un difetto. Eventuale ASR/VAD deve essere locale e facoltativo; l'assenza di trascrizione non prova l'assenza di parlato residuo.

**Musica:** tutela attacchi, armoniche, sustain, riverberi, basso, dinamica e stereo. Non trattare strumenti sostenuti come ronzio o la coda di un piatto come fruscio da sopprimere.

**Effetti:** tutela impatti, esplosioni, ambienti, rumori narrativi e spazialità. Pioggia, vento, motori e rumori elettronici possono essere contenuto intenzionale. Non applicare un denoiser vocale generalizzato.

Implementa controlli distinti per sensibilità, risoluzione temporale/spettrale, profondità computazionale, soglia di segnalazione e severità minima mostrata. Le modalità Rapida / Standard / Approfondita devono corrispondere a impostazioni reali e documentate. Non usare l'etichetta “forense” come garanzia non verificata.

Ogni manopola deve avere campo numerico, unità, tooltip, reset e limiti. Lo slider 0–100, quando utile, deve mappare a parametri effettivi visibili nell'inspector avanzato. Una modifica dell'analisi non modifica il segnale.

Le anomalie devono comparire sulla timeline e nell'elenco filtrabile. Consenti conferma, esclusione, modifica della regione, annotazione e rianalisi locale. Una decisione dell'utente deve sopravvivere a refresh e riavvio.

## 11. Motore di restauro e piano di intervento

Implementa un grafo di operazioni non distruttive con ordine esplicito, dipendenze, bypass e versionamento. Il motore propone una catena in base a stem, difetti e profilo; l'utente può modificarla, confrontarla e approvarla.

I preset sono tre profili configurabili, non tre percentuali generiche di aggressività. Devono esistere preset separati per dialoghi, musica ed effetti, salvabili come preset personali e applicabili a tutto lo stem o a regioni.

Ogni operazione deve esporre ciò che effettivamente supporta: soglia, intensità, riduzione massima in dB, smoothing, attacco/rilascio, banda, wet/dry, contesto, protezione transienti, vincoli di durata, modello e modalità di calcolo. Non mostrare controlli non collegati al motore.

### BASIC — Conservativo

Riduci difetti tecnici senza riscrivere il contenuto: de-click/de-crackle selettivo, de-hum mirato, rimozione DC quando necessaria, denoise prudente e declipping limitato ai campioni danneggiati quando supportato e validato.

Il declipping richiede una ricostruzione delle porzioni saturate: un limiter o una riduzione del volume non recuperano i picchi già tagliati. Non presentare un semplice abbassamento del gain come riparazione.

Niente generazione semantica, estensione artificiale di banda automatica, ricostruzione di parole o compressione artistica obbligatoria. Conserva ambiente e dinamica. Non sopprimere indiscriminatamente i silenzi con gate aggressivi.

### MEDIUM — Miglioramento controllato

Comprende gli interventi conservativi e può aggiungere denoising neurale specializzato, miglioramento della chiarezza, EQ correttiva, controllo di sibilanti e riverbero indesiderato dove esiste un algoritmo adatto e realmente testato.

Non usare lo stesso modello sui tre stem. DeepFilterNet è un candidato per speech enhancement, non un restauratore universale di musica ed effetti; verifica il percorso a 48 kHz e la compensazione dei ritardi della concreta integrazione [R6].

Per musica ed effetti usa processori coerenti con il contenuto e vincoli di preservazione di transienti, code e stereo. Evita rielaborazioni aggressive delle parti sane. Non inventare parole o ricostruire arbitrariamente brani mancanti in questo livello.

### HIGH — Ricostruzione assistita, esplicita e reversibile

Aggiungi funzionalità per ricostruire regioni mancanti o molto degradate, con maschera temporale/spettrale, contesto, parametri e controllo umano. Distingui almeno:

- riparazione di micro-gap con interpolazione o predizione locale, entro limiti validati;
- sostituzione da una sorgente alternativa autentica fornita dall'utente, con allineamento e provenienza;
- inpainting neurale/generativo dei segmenti mancanti;
- eventuale ricostruzione della banda mancante, separata dall'inpainting temporale.

AudioSR è un candidato per super-risoluzione audio/estensione di banda, non la prova di un motore generale di ricostruzione dei buchi [R8]. Per l'inpainting valuta implementazioni e checkpoint dedicati, ad esempio quelli elencati in [R11], controllando dominio di addestramento, licenze, canali, durata validata e fattibilità CPU/MPS. Non confondere una demo su pianoforte o voce con supporto universale di qualsiasi colonna sonora.

Implementa un percorso reale di ricostruzione selettiva, non un pulsante senza backend. Una patch generativa deve produrre candidati ascoltabili, mantenere il materiale esterno alla regione approvata, consentire confronto e rifiuto, registrare seed e parametri e non sostituire l'originale.

Non promettere recupero autentico di contenuto non presente nei dati. Etichetta `GENERATO` o `RICOSTRUITO`, distinguendo algoritmo e origine. Per parole mancanti non dedurre e inserire automaticamente un testo plausibile: richiedi contenuto verificato e approvazione esplicita; la clonazione vocale non è una dipendenza del prodotto.

Il profilo High deve esistere nel progetto, ma ogni sua capacità deve indicare lo stato effettivo. Se un modello specifico non è utilizzabile, cerca un'alternativa compatibile; se resta un blocco reale, esponilo chiaramente con diagnostica e test mancanti, senza dichiarare completata quella funzione e senza sostituirla con audio casuale.

## 12. Patch, approvazione umana e confronto

Elabora le regioni con contesto sufficiente, non soltanto il singolo campione difettoso. Gestisci padding, lookahead, allineamento, raccordi e stato dei filtri. Una riparazione di 300 ms può richiedere contesto molto più lungo: il modello deve dichiararlo.

Mantieni identici i campioni esterni alla regione di modifica e ai raccordi esplicitamente autorizzati, entro tolleranze documentate. Evita che un'interpolazione alteri la durata o sposti il labiale.

Consenti `Ascolta originale`, `Ascolta restaurato`, `Ascolta differenza`, A/B sincronizzato, loop, bypass per processore e confronto fra candidati. Il confronto a loudness abbinata deve essere una modalità di monitoraggio esplicita, senza modificare gli asset.

Prevedi stato proposto/approvato/rifiutato per le patch, undo/redo persistente e ritorno a qualsiasi versione. Un'esportazione definitiva non deve incorporare ricostruzioni generative non approvate. Un'anteprima sperimentale può contenerle solo con etichetta e manifest inequivocabili.

Dopo il restauro ricalcola i controlli pertinenti e segnala nuovi artefatti, eccessiva sottrazione, alterazioni stereo o picchi introdotti. Non dedurre automaticamente qualità superiore dal solo calo di energia o del numero di anomalie.

## 13. Mixer DSP professionale e rendering

Crea una console con Dialoghi, Musica, Effetti, Residuo opzionale e Master. Mantieni distinti stem grezzi e versioni restaurate selezionabili per canale. Nessun modello generativo nel percorso del mixer.

Ogni canale deve avere gain/trim, fader in dB, mute, solo, bypass, pan per mono o balance per stereo, polarità ove utile, EQ parametrico, compressore e processori di protezione esplicitamente attivabili. Esporre frequenza/gain/Q dell'EQ e threshold/ratio/knee/attack/release/makeup del compressore. Compensare le latenze.

Prevedi automazioni modificabili almeno per volume, mute e pan/balance, con interpolazione documentata e transizioni prive di click. Il master deve offrire trim, EQ opzionale, gestione della dinamica, limiter validato, loudness e true-peak metering.

Il rendering deve essere deterministico per la catena DSP a parità di ambiente e impostazioni; per modelli neurali documenta eventuali limiti di riproducibilità. Non attivare normalizzazioni di somma nascoste. La catena in bypass deve ricostruire matematicamente la somma dei canali abilitati.

Implementa meter RMS, sample peak, hold/reset, true peak, gain reduction, loudness momentary/short-term/integrata, LRA quando applicabile e correlazione stereo. Le grandezze devono provenire dal segnale reale, non da animazioni decorative.

Per loudness e true peak usa implementazioni verificabili rispetto a ITU-R BS.1770; per il preset broadcast considera EBU R 128 [R9]. Un preset EBU non è automaticamente lo standard di ogni consegna cinematografica. Rendi configurabili target e ceiling e non applicare una normalizzazione di default a tutti i progetti.

Un semplice `max(abs(samples))` è sample peak, non true peak. Valida oversampling, filtro e risultati con segnali di riferimento. FFmpeg fornisce filtri e strumenti utilizzabili come backend o riferimento, ma la disponibilità del singolo filtro va verificata nella build installata [R10].

Controlla il master dopo il rendering e dopo l'eventuale conversione al formato finale. Se il ceiling è superato, segnala il problema e applica soltanto una correzione autorizzata. Dither soltanto nel passaggio finale a PCM intero quando appropriato, non a ogni passaggio intermedio.

## 14. Riproduzione multitraccia e file lunghi

Usa un trasporto comune con un solo clock per gli stem. Non implementare la sincronizzazione facendo partire tre elementi HTML audio indipendenti e sperando che restino allineati.

Implementa play/pause, seek, loop di regione, scrubbing ragionevole, solo/mute, volume monitor e switch A/B sincronizzati. Programma gli eventi audio rispetto al clock del motore, non al timer di ridisegno della GUI.

Per audio lungo usa lettura a blocchi, ring buffer, prefetch e cache limitata. Gestisci underrun, cambio dispositivo, sospensione del Mac, ripresa del browser e sample rate effettivo del dispositivo. Non decodificare obbligatoriamente quattro tracce di due ore dentro la memoria del browser.

La waveform deve usare picchi multirisoluzione e lo spettrogramma tile/regioni richieste. Virtualizza la timeline e l'elenco anomalie. Il calcolo degli spettrogrammi non deve monopolizzare il thread della UI né cambiare l'audio.

Il rate del dispositivo di ascolto può differire da quello del progetto: mostra la distinzione e mantieni l'export autorevole indipendente dal ricampionamento di monitoraggio.

## 15. GUI: uno studio audio completo, non una dashboard generica

Progetta una GUI professionale, sobria, dark, leggibile su MacBook e monitor esterno. Nome SONORA AI visibile, nessuna grafica estranea al progetto. Privilegia spazio per timeline, ascolto e controlli rispetto a card decorative.

Proposta cromatica: dialoghi turchese, musica viola, effetti ambra; residuo grigio; originale neutro. Non affidarti al solo colore: aggiungi nomi, icone e stati testuali. Le severità devono rimanere distinguibili anche senza percezione cromatica.

Layout principale:

```text
┌ SONORA AI | Progetto | Salvataggio | CPU/MPS | Memoria | Job ┐
├ Navigazione ┬ Timeline sincronizzata / spettrogramma ┬ Inspector ┤
│ Progetti    │ Originale                               │ Parametri │
│ Studio      │ Dialoghi                                │ Difetti   │
│ Modelli     │ Musica                                  │ Restauro  │
│ Report      │ Effetti                                 │ Versioni  │
│ Impostazioni│ Residuo opzionale                       │           │
├─────────────┴─────────────────────────────────────────┴───────────┤
│ Trasporto: Play · Stop · Loop · Timecode · A/B · Monitor           │
├─────────────────────────────────────────────────────────────────┤
│ Console DSP: Dialoghi | Musica | Effetti | Residuo | Master        │
└─────────────────────────────────────────────────────────────────┘
```

**Progetti e importazione:** nuovo/apri/duplica/archivia; drag-and-drop, selezione file, metadati, destinazione dati e verifica spazio. Non usare duplicazione fisica dell'audio dove bastano riferimenti sicuri.

**Separazione:** modello, stato installazione/licenza, backend, qualità/modalità d'inferenza, regione di prova, avvio, annullamento, progressi reali e confronto delle versioni.

**Studio e analisi:** timeline con originale e tre stem, waveform/spettrogramma, zoom, selezione regione, marker, tooltip, elenco anomalie filtrabile per tipo/stem/severità/stato. Il click su un'anomalia porta al punto esatto e attiva l'ascolto della regione.

**Inspector analisi:** profilo dello stem, rilevatori attivi, sensibilità, profondità, soglie, parametri avanzati, nuova analisi locale o completa. Nessuna modifica audio implicita.

**Inspector restauro:** Basic/Medium/High, spiegazione degli interventi, controlli numerici e manopole, catena riordinabile se valida, wet/dry, bypass, anteprima, applicazione a regione/stem, salvataggio preset, approvazione delle patch.

**Mixer:** fader veri, dB leggibili, mute/solo evidenti, meter del segnale, EQ comprensibile, parametri dinamici, automazioni e pannello master. Distinguere visivamente gain del canale e volume di monitoraggio.

**Modelli e risorse:** installati/disponibili/bloccati, licenze, dimensioni dei download, hash, backend testati, benchmark locali, scarica/rimuovi, budget memoria e percorso cache. Non mostrare un modello come pronto solo perché è elencato nel catalogo.

**Report ed export:** confronto tecnico prima/dopo, limiti, interventi, segmenti generati, formati e destinazione, validazione finale, manifest e download/apertura cartella con i permessi appropriati.

Ogni controllo deve essere collegato a un'azione reale o chiaramente disabilitato con motivo. Implementa stati vuoti, caricamento, errore, ripresa, progresso, modelli mancanti e capacità non verificate. Mai percentuali di completamento simulate: se il totale non è noto, usa stato indeterminato e unità effettivamente elaborate.

Supporta tastiera, focus visibile, etichette accessibili, scale numeriche e tooltip. I rotary knob devono essere regolabili anche con tastiera e input diretto. Prevedi scorciatoie documentate senza intercettare i comandi di editing nei campi testo. Salva layout, dimensioni pannelli e preferenze.

## 16. API, coda persistente e affidabilità

Definisci API versionate per progetti, asset, modelli, job, separazione, analisi, piani di restauro, preview, patch, mixer, export e report. Le richieste lunghe devono restituire un job identificabile, non bloccare una connessione HTTP per l'intera elaborazione.

Usa SSE o WebSocket per eventi tipizzati. La riconnessione deve recuperare lo stato autorevole e non creare job duplicati. Prevedi chiavi di idempotenza per operazioni costose.

Stati minimi: `queued`, `running`, `cancelling`, `cancelled`, `succeeded`, `failed`, `blocked`; eventuale `paused` solo quando realmente implementato. Progresso, fase operativa corrente, unità processate e stima residua devono avere semantica chiara. Queste sono attività runtime, non fasi della roadmap.

Conserva heartbeat, tentativi, checkpoint e artefatti completati. Dopo un crash, riconosci i job interrotti e offri ripartenza sicura. Il lock GPU e il reclamo dei job devono impedire due worker concorrenti involontari.

Prevedi annullamento cooperativo ai confini di chunk e terminazione controllata dei processi bloccati. Cancella gli output parziali senza rimuovere originali o versioni valide. Un retry non deve raddoppiare operazioni già completate.

Gli errori devono riportare causa e rimedio: modello mancante, licenza, backend non supportato, RAM insufficiente, disco pieno, formato invalido, dipendenza assente. Non trasformare una failure in un successo con passthrough silenzioso.

## 17. Installazione, avvio e comandi realmente funzionanti

Fornisci un percorso macOS riproducibile, nativo ARM64, con script idempotenti e dipendenze bloccate a versioni compatibili. Controlla l'architettura dei binari e non usare Rosetta inconsapevolmente.

Implementa comandi o equivalenti documentati per:

```text
sonora doctor
sonora models list
sonora models install <model-id>
sonora models verify <model-id>
sonora benchmark --model <model-id> --input <file>
sonora serve
sonora selftest
```

Prevedi `scripts/bootstrap-macos.sh`, `scripts/dev.sh`, `scripts/start.sh`, `scripts/stop.sh` e un comando di test completo. Sono requisiti di implementazione, non nomi da citare nel README senza crearli.

`doctor` deve controllare prerequisiti, versioni, filesystem, porte, codec, MPS, modelli e capacità. Deve restituire un report utile anche quando il sistema non è pronto.

`start` deve avviare i componenti necessari, mostrare l'indirizzo locale reale e gestire shutdown e porte occupate senza terminare processi estranei. L'interfaccia deve poter essere aperta nel browser senza account cloud.

Prima di installazioni globali, privilegi elevati, toolchain mancanti o download importanti, rendi visibili impatto e autorizzazioni richieste. Mantieni gli ambienti isolati. In un ambiente non Apple esegui i test disponibili e prepara quelli macOS senza dichiarare già validato MPS.

## 18. Sicurezza, privacy e licenze

Ascolta su loopback per default. Non esporre il servizio sulla rete locale senza scelta esplicita. Proteggi le operazioni con un token locale di sessione, controlli Origin/Host e mitigazioni contro richieste da pagine estranee. Non usare CORS indiscriminato.

Valida upload, dimensioni, percorsi, directory di esportazione e nomi file. Non consentire traversal, letture arbitrarie fuori dalle aree autorizzate o comandi shell costruiti concatenando input. Gestisci i subprocess con argomenti separati e timeout adeguati.

Niente telemetria, upload automatici di audio, crash report contenenti materiale o chiamate a servizi esterni durante il processamento. Il download dei modelli deve essere un'operazione riconoscibile e verificabile, con provenienza e checksum.

Non abilitare arbitrariamente codice remoto dei modelli. Verifica il formato e i rischi del caricamento dei checkpoint, soprattutto se richiedono deserializzazione legacy. Un processo separato non è automaticamente un sandbox di sicurezza: non descriverlo come tale senza vere restrizioni.

Mantieni `THIRD_PARTY_NOTICES.md` e inventario di dipendenze/pesi con licenze e vincoli di uso e redistribuzione. “Download gratuito”, “codice disponibile” e “utilizzabile commercialmente” non sono sinonimi. Se la licenza dei pesi è ambigua, segnala e blocca la redistribuzione, senza inventare autorizzazioni.

L'audio dimostrativo del repository deve essere sintetico o redistribuibile con provenienza verificata. I materiali cinematografici dell'utente restano locali e fuori da CI, GitHub e pacchetti.

## 19. Validazione del segnale e della qualità: prove, non promesse

Costruisci una suite di test unitari, integrazione, regressione audio, interfaccia e flusso completo. Distingui chiaramente test con mock, fixture sintetiche, modelli reali CPU e modelli reali MPS.

Crea fixture deterministiche con toni, impulsi, transitori, rumore, silenzi intenzionali, offset DC, clipping noto, hum e dropout applicati a una versione pulita. Includi fixture realistiche con diritti verificati per valutare la separazione; non dedurre efficacia sul cinema da una miscela di tre sinusoidi.

Verifica almeno:

- sample count, allineamento e ordine dei canali per tutti i passaggi;
- resampling e compensazione dei ritardi, inclusi bordi e file più corti della finestra;
- overlap-add senza buchi, modulazioni o click di raccordo;
- bypass e somma DSP, residuo pre-restauro e assenza di normalizzazioni nascoste;
- preservazione delle aree non selezionate dalle patch;
- riduzione del difetto introdotto sulle fixture e tutela del contenuto sano;
- stima e misura dei meter, casi di silenzio, audio molto corto e valori non definiti;
- automazioni, seek, A/B, mixer e coerenza fra anteprima ed export;
- annullamento, retry, crash, ripartenza, modello mancante, disco insufficiente e OOM;
- file lunghi con memoria limitata, senza dipendenza lineare dalla durata;
- correttezza delle licenze, manifest, cache e gestione sicura dei percorsi.

Stabilisci tolleranze numeriche esplicite. L'identità senza ricampionamento o quantizzazione richiede uguale numero di campioni e errore vicino alla precisione del calcolo, non soltanto “suona simile”. Per altri percorsi documenta la tolleranza prevista e il motivo.

Misure come SI-SDR, SNR di miglioramento o intelligibilità reference-based richiedono riferimenti puliti appropriati: non calcolarle come certificazione su una colonna sonora reale quando i veri stem non sono disponibili. Per la separazione con ground truth valuta anche errori di guadagno e leakage; il semplice residuo di somma non misura la correttezza semantica.

Per materiale reale combina diagnostica senza riferimento, ascolti A/B a livello controllato e valutazione umana. Un ASR che non trascrive nulla non certifica uno stem privo di dialogo. Un punteggio no-reference non è una garanzia di fedeltà artistica.

Non garantire miglioramenti percentuali, tempi o memoria non misurati. Riporta anche regressioni e limiti. La qualità professionale è un obiettivo da verificare, non uno stato ottenuto aggiungendo la parola “professional” al README.

## 20. Test end-to-end e criteri di accettazione del prodotto

Il percorso di accettazione deve permettere di aprire il portale, creare un progetto, importare audio, installare/verificare un modello, separare realmente tre stem, analizzarli, rivedere un difetto, ascoltare un restauro, approvarlo, rimixare ed esportare master, stem e report. Dopo il riavvio il progetto deve conservare versioni e impostazioni.

Il flusso deve essere provato sia da API sia dalla GUI, per esempio con Playwright per interazioni e screenshot, verificando però che l'audio finale provenga dai backend reali quando il test è dichiarato di inferenza reale.

Includi almeno un test completo con un checkpoint di separazione reale e un test locale Apple Silicon ripetibile. In CI leggera puoi usare fixture/mock per l'orchestrazione, ma tali test devono avere etichette distinte e non essere presentati come verifica del modello.

L'assenza di pesi, una macchina Linux o un runner senza MPS devono produrre `skipped`/`blocked` con motivazione per il test specifico, non `passed`. Il resto dei test deve comunque essere eseguito. Non avviare runner self-hosted che processino automaticamente pull request non fidate.

Requisiti di accettazione trasversali: nessun controllo finto; nessun errore nascosto; niente inferenza cloud; originali intatti; patch generative approvate; metrica con definizione e dati reali; stereo e allineamento documentati; file esportabili e riapribili; installazione riproducibile.

Non chiamare completo ciò che è solo uno scaffold. Una capacità bloccata deve comparire in una matrice requisito → codice → test → stato, insieme al motivo e all'azione precisa necessaria per sbloccarla. Questo non autorizza a rinviare volontariamente i moduli difficili: cerca prima di implementarli davvero.

## 21. Esportazione, report e modalità dimostrativa

Esporta almeno master e stem in WAV PCM 24 bit oppure WAV float32, con frequenza scelta, nomi coerenti e manifest. Prevedi FLAC quando compatibile con le impostazioni. Originale, separato non restaurato e restaurato devono restare distinguibili.

Per ogni export salva progetto/versione, sorgente/hash, modelli e revisioni, catene DSP, parametri, sample rate, sample count, layout, loudness e picchi, avvisi, regioni ricostruite e decisioni sul residuo. Un file float32 non deve essere presentato come recupero dell'informazione perduta nel file compresso originale.

Crea report HTML leggibile offline e JSON strutturato; la stampa del report deve risultare ordinata. Il PDF può essere aggiunto senza rendere indispensabile un servizio esterno.

Il report deve distinguere misure oggettive, indicatori euristici, giudizi dell'operatore, dati non disponibili e differenze generative. Nessun unico “indice di qualità 98%” privo di definizione.

Prevedi una modalità dimostrativa per ascoltare, in modo sincronizzato, originale, tre stem separati, stem restaurati e mix finale. Il confronto a volume abbinato deve essere disponibile ed esplicito. Non rendere il restaurato artificialmente più forte per farlo sembrare migliore.

## 22. Documentazione e consegna operativa

Consegna almeno: README, istruzioni macOS, troubleshooting, architettura, contesto, requisiti, ADR, schema API, documentazione dei parametri, model registry, licenze, protocollo di benchmark, report dei test e stato dei requisiti.

Il README deve consentire a Floriano di installare, avviare, importare un file, scegliere un modello, completare il flusso e ritrovare gli output. Tutti i comandi mostrati devono essere stati verificati nell'ambiente effettivamente disponibile o marcati come non ancora eseguiti sul target.

Mantieni una documentazione minima ma sufficiente nel codice: type hint, docstring per algoritmi non banali, unità di misura, controlli degli input, errori utili. Non lasciare `TODO`, `pass` o `NotImplementedError` nei percorsi presentati come funzionanti.

Alla fine della sessione fornisci un resoconto fattuale con percorso locale reale, URL del repository solo se creato, branch/commit, comandi di avvio, modelli effettivamente verificati, backend usati, test eseguiti, risultati e blocchi residui. Non elencare attività soltanto pianificate come attività completate.

Se la sessione termina per limiti dell'ambiente, salva stato, modifiche e una prosecuzione precisa nel repository. Non dichiarare attività in background che non sono realmente attive e non autorizzare costi per continuare indefinitamente.

**Inizia ora: verifica l'ambiente, crea o riusa in sicurezza il workspace, organizza gli agenti disponibili, definisci i contratti minimi e sviluppa il prodotto end-to-end con integrazione e test continui. Non rispondere soltanto con un piano e non chiedere all'utente quale modulo realizzare per primo.**

---

## Riferimenti tecnici da verificare durante l'implementazione

Questi riferimenti sono punti di partenza, non una certificazione di compatibilità con il Mac del committente. Consulta le versioni correnti, conserva revisioni/commit effettivamente utilizzati e cita le fonti in `docs/TECHNICAL_REFERENCES.md`. Non scaricare ciecamente una branch `main` variabile dentro un'installazione presentata come riproducibile.

**[R1] OpenAI — Subagents / Codex multi-agent**

```text
https://developers.openai.com/codex/multi-agent/
https://learn.chatgpt.com/docs/agent-configuration/subagents
```

**[R2] OpenAI — Istruzioni persistenti AGENTS.md**

```text
https://developers.openai.com/codex/guides/agents-md/
https://learn.chatgpt.com/docs/agent-configuration/agents-md
```

**[R3] PyTorch / Apple — MPS**

```text
https://docs.pytorch.org/docs/stable/notes/mps.html
https://developer.apple.com/metal/pytorch/
```

**[R4] Dynamic Band Splitting / DBS-TIGER — implementazione e model card degli autori**

```text
https://github.com/JusperLee/Dynamic-Band-Splitting
https://huggingface.co/JusperLee/DBS-TIGER-DnR
```

**[R5] Bandit V2 — implementazione e pesi degli autori**

```text
https://github.com/kwatcharasupat/bandit-v2
https://zenodo.org/records/12701995
```

**[R6] DeepFilterNet — implementazione ufficiale**

```text
https://github.com/Rikorose/DeepFilterNet
```

**[R7] GitHub CLI — creazione repository**

```text
https://cli.github.com/manual/gh_repo_create
```

**[R8] AudioSR — implementazione ufficiale**

```text
https://github.com/haoheliu/versatile_audio_super_resolution
```

**[R9] Misure audio e preset broadcast — fonti normative**

```text
https://www.itu.int/rec/R-REC-BS.1770/en
https://tech.ebu.ch/publications/r128
```

**[R10] FFmpeg — documentazione ufficiale dei filtri audio**

```text
https://ffmpeg.org/ffmpeg-filters.html
```

**[R11] Inpainting audio — candidati di ricerca, non compatibilità Apple garantita**

```text
https://github.com/eloimoliner/audio-inpainting-diffusion
https://github.com/iftachShoham/AIDD
```
