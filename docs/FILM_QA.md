# Collaudo integrale di Sintel

Sintel (Blender Foundation, 2010), durata 14 min 48,032 s, CC BY 3.0. È stato usato il [master ufficiale 1080p](https://download.blender.org/durian/movies/Sintel.2010.1080p.mkv) con audio AC-3 5.1, convertito in stereo a 48 kHz prima dell'importazione. Il film include i titoli di coda. Il film e gli stem sono in un archivio locale di prova. [Crediti e licenza Blender Foundation](https://durian.blender.org/sharing/)

| Dato | Valore |
|---|---|
| SHA-256 MKV | `97f1dbc66231df42ad49bd8c29aa174b8f48933058e47e7157d4ba63d93a8efa` |
| SHA-256 FLAC stereo importato | `7512d492a4d479a6c5ffe5429dce35077aab653bfdc8362a2529a6a4ce323306` |
| Timeline completa | 42.625.536 frame stereo a 48.000 Hz |
| Separazione integrale | DBS-TIGER DnR, 296 finestre, Apple M2 Max MPS, 1.194,64 s di elaborazione, fattore 1,345× |
| Monitor live | Chromium su Docker Linux ARM64, audio PCM a blocchi sugli stem effettivi, avvio a 40 s, seek a metà e a 885,417 s, mute/solo, meter, loop, pausa e stop |
| Verifica sintetica del clock | Due tracce in OfflineAudioContext a 44,1 kHz su progetto a 48 kHz, tolleranza di 2 × 10⁻⁷, blocchi obsoleti scartati |
| Limiter sul master | −1,19954 dBTP nativo, −1,20 dBTP FFmpeg, ceiling −1,0 dBTP, attenuazione massima 4,05 dB. |
| Master finale | WAV PCM 24 bit stereo a 48 kHz, −1,19954 dBTP nativo e −1,20 dBTP FFmpeg, 42.625.536 frame. Tre stem esportati con gli stessi parametri e verifica SHA-256 di tutti gli artefatti. |
| True peak | 8 test del limiter in Docker ARM64, incluse le sinusoidi 15–19 sintetizzate da EBU Tech 3341 e verifica indipendente FFmpeg |
| Patch sul film | 75,000–75,100 s, seed 17, 49,31 s d'inferenza CPU Docker, 4.800 frame modificati. I 42.620.736 frame esterni sono identici a livello binario. Il mix ha rifiutato la patch prima dell'approvazione. |
| Ricombinazione degli stem grezzi e del residuo | Errore assoluto massimo 3,33 × 10⁻⁸ nel dominio float sull’intera timeline. |
| Inpainting | 5 test con pesi ufficiali sia su CPU nativa sia in Docker ARM64. Su fixture di pianoforte RMSE 0,0520 rispetto a 0,0669 per 80 ms di silenzio. |

## Procedura

```sh
ffmpeg -hide_banner -nostdin -i Sintel.2010.1080p.mkv -map 0:a:0 -ac 2 -ar 48000 -c:a flac sintel-full.flac
```

Importa il FLAC e separa tutta la traccia con DBS-TIGER. Nel collaudo la separazione ha usato il percorso nativo MPS, quindi l'archivio di prova è stato riaperto dai container aggiornati. Il test Chromium su un progetto preparato è ripetibile con:

```sh
SONORA_LIVE_TEST_PROJECT=Sintel SONORA_LIVE_TEST_START_SAMPLE=1920000 \
SONORA_LIVE_TEST_END_SAMPLE=42500000 pnpm exec playwright test tests/e2e/live.spec.ts
```

Indica `SONORA_E2E_URL` se lo studio ascolta su una porta diversa. L'inpainting su 100 ms dello stem Musica del film è un collaudo del flusso e dell'integrità dei campioni. Per la qualità della ricostruzione fanno fede le prove separate con pianoforte. Il limiter opera nel render del master. La prova copre l'intero cortometraggio e punti rappresentativi del monitor live. [Dettagli inpainting](INPAINTING.md) · [Metodo limiter](LIMITER.md) · [Test browser](LIVE_MIX.md)
