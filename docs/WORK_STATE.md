# Stato del lavoro

| Responsabilità | Agente | File principali |
|---|---|---|
| Integrazione, API, worker, release e QA | Coordinatore | `services/`, `packages/contracts`, `scripts/`, `tests/test_api.py`, `tests/e2e/`, configurazioni, documentazione |
| Separazione AI e Apple Silicon | models | `packages/model_adapters`, `configs/models`, `tests/test_models.py`, `docs/MODELS.md` |
| Segnale, diagnostica, restauro e mixer | audio | `packages/audio_core`, `packages/dsp_core`, `tests/test_audio.py`, `docs/AUDIO_ENGINE.md` |
| Studio e accessibilità | web | `apps/web` |
| Immagine CPU e Compose | audio, coordinatore | `Dockerfile`, `compose.yaml`, lock Linux, `docs/CONTAINERS.md` |

Gli agenti hanno usato aree non sovrapposte nel workspace inizialmente vuoto. Git era protetto durante le operazioni del sandbox. Il coordinatore usa il ramo di integrazione `codex/sonora-ai` e pubblica il ramo principale `main`. I risultati, i comandi e i limiti sono in [TEST_REPORT.md](TEST_REPORT.md). Il registro tecnico dei requisiti e delle lacune è in [REQUIREMENTS.md](REQUIREMENTS.md).

## Estensione High, mastering e monitor live

Il ramo `codex/restoration-live-release` integra tre contributi paralleli. I riferimenti sono [inpainting](INPAINTING.md), [limiter](LIMITER.md) e [mix live](LIVE_MIX.md). Il coordinatore possiede contratto API, collegamento dei job, collaudo lungo e rilascio. SQLite resta allo schema v1. I nuovi parametri serializzati sono opzionali e la patch neurale usa la revisione delle versioni già prevista.

Restano aperti il trasferimento di una sorgente alternativa con provenienza, il denoising specifico per dialoghi, la validazione dell’inpainting in altri domini, i processori dinamici nel monitor e l’estensione del confronto a un corpus più ampio.
