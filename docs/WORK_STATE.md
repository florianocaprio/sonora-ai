# Stato del lavoro

| Responsabilità | Agente | File principali |
|---|---|---|
| Integrazione, API, worker, release e QA | Coordinatore | `services/`, `packages/contracts`, `scripts/`, `tests/test_api.py`, `tests/e2e/`, configurazioni, documentazione |
| Separazione AI e Apple Silicon | models | `packages/model_adapters`, `configs/models`, `tests/test_models.py`, `docs/MODELS.md` |
| Segnale, diagnostica, restauro e mixer | audio | `packages/audio_core`, `packages/dsp_core`, `tests/test_audio.py`, `docs/AUDIO_ENGINE.md` |
| Studio e accessibilità | web | `apps/web` |
| Immagine CPU e Compose | audio, coordinatore | `Dockerfile`, `compose.yaml`, lock Linux, `docs/CONTAINERS.md` |

Gli agenti hanno usato aree non sovrapposte nel workspace inizialmente vuoto. Git era protetto durante le operazioni del sandbox. Il coordinatore usa il ramo di integrazione `codex/sonora-ai` e pubblica il ramo principale `main`. I risultati, i comandi e i limiti sono in [TEST_REPORT.md](TEST_REPORT.md). Il registro tecnico dei requisiti e delle lacune è in [REQUIREMENTS.md](REQUIREMENTS.md).

Prossimi interventi verificabili sui requisiti parziali: trasferimento di sorgente allineata con provenienza, adattatore locale di denoising per dialogo, AudioWorklet streaming e prove di sincronizzazione su tracce lunghe, verifica del limiter su vettori di riferimento e benchmark più ampio. Le dipendenze di inpainting e i rispettivi checkpoint vanno qualificati per dominio, licenza e backend prima della loro disponibilità in studio.
