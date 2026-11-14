# Dipendenze e licenze di terze parti

Il codice originale SONORA AI ha licenza di distribuzione da confermare. I componenti incorporati mantengono licenze e avvisi propri.

| Componente | Licenza / origine |
|---|---|
| DBS-TIGER codice | Apache-2.0 e avviso MIT per il codice ereditato incluso. [Licenze incorporate](packages/model_adapters/_vendor/dbs/) |
| DBS-TIGER-DnR checkpoint | Apache-2.0 secondo la [scheda del modello](https://huggingface.co/JusperLee/DBS-TIGER-DnR) |
| Bandit V2 codice | Apache-2.0. [Licenza incorporata](packages/model_adapters/_vendor/bandit/LICENSE) |
| Bandit V2 checkpoint | CC BY-SA 4.0 secondo il [record Zenodo](https://zenodo.org/records/12701995) |
| PyTorch / Torchaudio | BSD-3-Clause secondo le licenze dei [sorgenti PyTorch](https://github.com/pytorch/pytorch) e [Torchaudio](https://github.com/pytorch/audio) |
| Safetensors / einops | Apache-2.0 / MIT. [Safetensors](https://github.com/huggingface/safetensors), [einops](https://github.com/arogozhnikov/einops) |
| NumPy / SciPy | BSD-3-Clause. [NumPy](https://numpy.org/doc/stable/license.html), [SciPy](https://scipy.org/) |
| SoundFile / libsndfile | BSD-3-Clause / LGPL-2.1-or-later. [SoundFile](https://github.com/bastibe/python-soundfile), [libsndfile](https://libsndfile.github.io/libsndfile/) |
| python-soxr / libsoxr | LGPL-2.1-or-later. [python-soxr](https://github.com/dofuuz/python-soxr), [libsoxr](https://sourceforge.net/projects/soxr/) |
| FFmpeg compilato da script | Configurazione LGPL, senza componenti GPL o nonfree esplicitamente attivati. [FFmpeg Legal](https://ffmpeg.org/legal.html) |
| FastAPI, Uvicorn, Starlette, Pydantic | Metadati e avvisi forniti dalle distribuzioni bloccate in `requirements-macos-arm64.lock` |
| React, React DOM, Vite, TypeScript, Playwright | Metadati e avvisi forniti dai pacchetti bloccati in `pnpm-lock.yaml` |

I checkpoint e i binari sono scaricati o compilati localmente e non sono inclusi nel repository.
