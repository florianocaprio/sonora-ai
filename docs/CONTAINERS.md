# SONORA AI con Docker Compose

L'immagine Linux contiene l'interfaccia compilata, FastAPI, il worker, FFmpeg e PyTorch CPU. Compose avvia due servizi dalla stessa immagine. L'API serve il portale e pubblica la porta `8765` su `127.0.0.1`. Il worker condivide i volumi e non ha porte pubblicate. I processi usano UID/GID `10001:10001`, con credenziali di sessione generate all'avvio dall’API.

## Avvio

Avvia Docker Desktop su macOS oppure Docker Engine con il plugin Compose su Linux. Verifica l’accesso al motore con `docker info`. Dalla radice del repository esegui:

```sh
docker compose up --build -d --wait
docker compose ps
```

Apri [SONORA AI in locale](http://127.0.0.1:8765). Se `8765` è occupata da una precedente istanza nativa, arrestala con `scripts/stop.sh` prima di avviare Compose.

La prima build scarica le immagini base, le dipendenze npm, i pacchetti Debian e le wheel Python. Il lock JavaScript è installato in modalità frozen. Il lock Linux vincola le dipendenze Python per CPython 3.11 e seleziona wheel PyTorch e TorchAudio 2.8.0 dall’indice CPU ufficiale con marcatori Linux ARM64 e AMD64. Il Dockerfile verifica in build che PyTorch si importi e che il backend CUDA sia assente. [Wheel CPU PyTorch 2.8.0](https://pytorch.org/get-started/previous-versions/) · [Indice CPU TorchAudio](https://download.pytorch.org/whl/cpu/torchaudio/)

## Modelli, dati e manutenzione

Installa dal pannello **Modelli** o esegui nel worker:

```sh
docker compose exec worker python -m services.cli models list
docker compose exec worker python -m services.cli models install dbs-tiger-dnr
docker compose exec worker python -m services.cli models verify dbs-tiger-dnr
```

I checkpoint sono installati su richiesta nel volume `models`, con verifica del checksum. La build parte senza pesi. Dopo la preparazione di immagine e checkpoint, con il motore in esecuzione puoi riavviare in locale tramite `docker compose up -d --wait --no-build --pull never`. L'elaborazione usa CPU sui container Linux. Per MPS usa l’avvio nativo macOS del [README](../README.md).

Database, caricamenti e risultati rimangono nel volume `projects`. I due volumi persistono dopo `docker compose down`. Scarica gli export dal portale. Evita `docker compose down -v` se vuoi conservare progetti e modelli, perché rimuove entrambi i volumi. [Persistenza dei volumi](https://docs.docker.com/engine/storage/volumes/)

```sh
docker compose logs --tail=80 api worker
docker compose exec worker python -m services.cli doctor
docker compose down
```

`doctor` può mostrare `node` e `pnpm` assenti nel runtime. La build web avviene nello stage Node e l'immagine finale contiene gli asset già compilati. La build e il flusso con checkpoint reale sono verificati su `linux/arm64`. Il lock include anche wheel CPU `linux/amd64`, che resta da collaudare. Usa il portale sulla porta pubblicata e lascia i controlli Host e Origin attivi. [Pubblicazione porte Docker](https://docs.docker.com/engine/network/port-publishing/)

## Inpainting e monitor

L'immagine include il motore per l'[inpainting High](INPAINTING.md), il [limiter del master](LIMITER.md) e il bundle AudioWorklet per il [mix live](LIVE_MIX.md). Dialoghi ed Effetti usano inpainting contestuale, disponibile senza download. Musica usa il checkpoint per pianoforte dalla cache `models`, circa 713 MB.

```sh
docker compose up --build -d --wait
docker compose exec worker python -m services.cli models install diffusion-inpaint
docker compose exec worker python -m services.cli models verify diffusion-inpaint
```

Il monitor live usa Web Audio in Chromium da localhost. Il monitor live include EQ, compressore e limiter. Il renderer effettua la verifica true peak sul file.
