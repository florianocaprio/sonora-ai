# Rapporto di verifica

Ambiente verificato su MacBook Pro Apple M2 Max, 32 GB, macOS 27.2.1 ARM64, Python 3.11.4 in `.venv`, Node 22.23.2, pnpm 10.34.5, PyTorch 2.8.0, libsndfile 1.2.2 e FFmpeg 9.0.2 compilato localmente.

| Verifica | Esito |
|---|---|
| `pnpm install --frozen-lockfile` | Lock risolto e dipendenze installate |
| `.venv/bin/python -m pip check` | Nessuna dipendenza dichiarata mancante |
| `pnpm --filter @workspace/api-server run test` | 30 superati, 2 saltati nella sessione senza checkpoint configurati. 19 test audio superati con FFmpeg |
| Pipeline API con checkpoint DBS-TIGER DnR su CPU | Import, separazione, diagnostica, micro-gap, approvazione, mix e WAV PCM 24 bit verificati |
| Pipeline API con DBS-TIGER DnR e Bandit V2 su MPS | Entrambi verificati su M2 Max. Input 48 kHz mono sintetico e checkpoint degli autori |
| Chromium tramite Playwright, DBS-TIGER DnR su MPS | Progetto, import, playback reale, separazione, analisi, anteprima, approvazione, mix, export e riapertura verificati |
| Docker Desktop Linux ARM64, API e worker | Immagine costruita, API healthy su loopback, runtime UID 10001. Checkpoint DBS-TIGER e Bandit V2 installati da upstream e verificati. Entrambi superano Playwright CPU end-to-end con spettrogramma, riproduzione, mix ed export. Versioni, impostazioni, export e checkpoint ritrovati dopo stop e avvio senza build o pull |
| Benchmark con riferimenti CineAudioDB su MPS | Confronto a parità di estratto stereo, riportato in [MODELS.md](MODELS.md) |

Le fixture verificano conteggio campioni, ricampionamento, canali, residuo, picchi sopra il fondo scala, rumore, clipping probabile, hum, micro-gap e immutabilità fuori regione. Il test API ordinario non esegue inferenza. Il benchmark con stem di riferimento misura una clip e documenta la contaminazione tra musica ed effetti.

## Ripetizione locale

```sh
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm --filter @workspace/api-server run test
scripts/sonora models install dbs-tiger-dnr
SONORA_TEST_MODEL_DIR="$HOME/Library/Caches/SONORA AI/models" \
SONORA_TEST_MODEL=dbs-tiger-dnr SONORA_TEST_BACKEND=mps scripts/test.sh
```

Usa `SONORA_TEST_BACKEND=cpu` per ripetere su CPU. I test reali riportano un salto motivato se backend o pesi mancano. Per il browser, installa Chromium con `pnpm exec playwright install chromium`, avvia lo studio ed esegui `SONORA_E2E_MODEL=dbs-tiger-dnr SONORA_E2E_BACKEND=mps pnpm run test:e2e`. Imposta `SONORA_E2E_URL` se hai cambiato porta. I test browser creano progetti di prova nell'archivio in uso. Usa un `SONORA_DATA_DIR` temporaneo per tenerli separati.

Restano da verificare file di durata cinematografica, browser diversi da Chromium, un corpus più ampio e il Mac M5 Max indicato nel brief.
