# Architettura e contratti

```
React/Vite → FastAPI /api/v1 → SQLite WAL + archivio di file
                                  ↑
                       worker Python separato
                    ↙              ↓             ↘
               PyTorch        NumPy/SciPy         FFmpeg
```

- `apps/web` contiene lo studio e un trasporto browser con richieste Range per i file e PCM a blocchi per l’AudioWorklet multitraccia. Il WAV prodotto dal worker offre l’ascolto autorevole dei processori del render.
- `packages/contracts` definisce i corpi Pydantic. Gli intervalli sono semiaperti e il backend usa interi fino a 64 bit. I numeri in TypeScript richiedono un valore rappresentabile esattamente, ampiamente sopra la durata dei media supportati.
- `services/storage.py` applica lo schema SQLite v1 al primo avvio. Il database indicizza progetti, asset/versioni, analisi, job ed export. Ogni regione e risultato porta collegamenti di provenienza. I file inviati rimangono byte per byte in `uploads`, gli artefatti canonici in `work/<job-id>`. Una copia di progetto riusa l'audio immutabile tramite riferimento e possiede i propri identificativi e review.
- `services/worker` reclama il job in transazione, aggiorna heartbeat e pubblica righe degli artefatti nella stessa transazione che completa il job. Il worker recupera gli interrotti all'avvio. Un retry riparte dall'input, rimuove il proprio staging parziale e conserva gli artefatti già pubblicati degli altri job. SQLite è autorevole per la visibilità degli output.
- Il catalogo usa manifest statici versionati con origine e SHA-256. Il worker fa una sola inferenza per directory dei modelli tramite lock locale. Il database e l'archivio sono fuori dal repository per impostazione predefinita.

## ADR 001 · DSP autorevole in Python

Il renderer unico NumPy/SciPy mantiene stato per blocchi e consente di verificare la corrispondenza tra mix ascoltato ed export. Il monitor live usa un clock AudioWorklet e applica livello, pan, solo, mute, polarità e automazioni alla somma in riproduzione. EQ, compressore e limiter agiscono nel renderer autorevole. La conversione interattiva al rate del dispositivo non entra nel file esportato.

## ADR 002 · Job e sicurezza su una sola macchina

FastAPI e worker si avviano come processi nativi. Coda persistente SQLite, file in staging, associazione di progetto, token casuale per sessione e verifica Host/Origin. Il token viene consegnato dalla stessa origine su loopback. Il cookie HttpOnly serve per eventi, download e media. Gli endpoint mutanti richiedono l'header. Le API di upload accettano Content-Length e limitano la dimensione prima di elaborare il multipart. Il file sorgente resta consultabile via API autenticata.

## API v1

La specifica OpenAPI è generata dal codice. `scripts/openapi.sh > /tmp/sonora-api.json` la esporta. `GET /api/v1/openapi.json` richiede sessione. Il frontend usa tipi TypeScript e test del percorso reale, con verifiche dei campi consumati durante l'esecuzione. Le richieste per operazioni lunghe restituiscono `202` e un job. `Idempotency-Key` riusa la stessa richiesta o produce conflitto su payload differente. `GET /jobs/{id}/events` emette snapshot JSON SSE e il dettaglio HTTP resta autorevole per la riconnessione.

Cambi di schema futuri richiedono migrazione SQLite, revisione OpenAPI e verifica dei tipi frontend. I processi e i percorsi sono configurati con le variabili in `.env.example`.
