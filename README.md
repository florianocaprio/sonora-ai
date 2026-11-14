# SONORA AI

Intelligent Audio Restoration Studio · Studio locale per la separazione, il restauro e il mix di audio cinematografico su Apple Silicon.

Per una prima prova, segui il [manuale rapido di SONORA AI](docs/MANUALE.md).

## Avvio su macOS

Servono Python 3.11 ARM64, Node 22.12 o successivo e pnpm 10.34.5. L'installazione crea una venv e scarica dipendenze Python e JavaScript bloccate. Nessun account è necessario per lo studio.

```sh
scripts/bootstrap-macos.sh
scripts/build-ffmpeg-macos.sh
scripts/start.sh
```

Apri [lo studio locale](http://127.0.0.1:8765). Lo script stampa l'indirizzo effettivo. Arresta con Ctrl+C o `scripts/stop.sh` da un altro terminale. La compilazione FFmpeg è isolata nel workspace, abilita AAC/M4A e le misure loudness/true peak. FFmpeg e ffprobe già disponibili nel PATH sono utilizzabili direttamente.

I dati sono in `~/Library/Application Support/SONORA AI` e i checkpoint in `~/Library/Caches/SONORA AI/models`. Imposta `SONORA_DATA_DIR` e `SONORA_MODEL_DIR` per un SSD esterno, usando virgolette per i percorsi con spazi. Usa `SONORA_PORT` per cambiare la porta API.

## Avvio con Docker Desktop

```sh
docker compose up --build -d --wait
```

Apri [lo studio in Docker](http://127.0.0.1:8765). Compose avvia i container `api` e `worker` con volumi separati per progetti e checkpoint. Il worker Docker usa CPU. Il percorso nativo sopra abilita MPS su Apple Silicon. Guida ai volumi, allo stop e alle verifiche in [docs/CONTAINERS.md](docs/CONTAINERS.md).

## Prima sessione

1. Crea un progetto e importa WAV, FLAC, AIFF, MP3 o AAC/M4A. Scegli la frequenza sorgente o di progetto. Consulta codec, canali e durata nello studio.
2. In **Modelli** scarica DBS-TIGER DnR o Bandit V2 e verifica SHA-256. Seleziona modello e backend nello studio. Per il restauro neurale installa anche **Diffusion inpainting · Pianoforte**.
3. Seleziona **Dialoghi**, **Musica** o **Effetti**. Analizza il segnale, scegli una regione o conferma un'anomalia. Consulta il grafico, l'ispettore e lo spettrogramma.
4. In **Restauro** scegli Basic, Medium o High. Proponi una catena o aggiungi un processore con intervallo e parametri espliciti. Genera l'anteprima, ascolta la differenza e approva la versione che vuoi usare.
5. In **Console DSP**, scegli le versioni approvate per Dialoghi, Musica ed Effetti. Usa **Ascolta mix live** per regolare EQ, compressione, limiter, livelli, pan, mute e solo. Premi **Remix** per creare il master con le sorgenti selezionate. Il residuo parte in mute.
6. In **Report** esporta WAV float32, WAV PCM 24 bit o FLAC 24 bit. Scarica master, tracce, manifest JSON e report HTML dallo studio. Gli stessi file restano nell'archivio locale.

Il motore elabora l'audio in locale. La rete serve durante l'installazione iniziale e nelle operazioni esplicite di download dei modelli. Stereo dei due modelli significa elaborazione L/R indipendente. High include l’inpainting neurale contestuale per Dialoghi (20–80 ms) ed Effetti (20–120 ms). Il modello si adatta localmente al segnale adiacente. Per Musica è disponibile il checkpoint sperimentale per pianoforte solo (20–250 ms). Ascolta e approva ogni candidato. Consulta [inpainting](docs/INPAINTING.md), [limiter](docs/LIMITER.md) e [mix live](docs/LIVE_MIX.md) per condizioni d'uso e verifiche.

## Comandi

```sh
scripts/sonora doctor
scripts/sonora models list
scripts/sonora models install dbs-tiger-dnr
scripts/sonora models verify dbs-tiger-dnr
scripts/sonora benchmark --model dbs-tiger-dnr --backend mps --input "/percorso/clip.wav"
scripts/sonora selftest
scripts/dev.sh
```

`doctor` distingue disponibilità Metal, binari, codec, percorsi, porte e stato del modello. `benchmark` misura la pipeline del checkpoint sul proprio file. Vite in sviluppo ascolta su `127.0.0.1:5173`.

Consulta [architettura e API](docs/ARCHITECTURE.md), [motore audio e parametri](docs/AUDIO_ENGINE.md), [modelli e licenze](docs/MODELS.md), [test](docs/TEST_REPORT.md), [troubleshooting](docs/TROUBLESHOOTING.md) e [stato dei requisiti](docs/REQUIREMENTS.md).
