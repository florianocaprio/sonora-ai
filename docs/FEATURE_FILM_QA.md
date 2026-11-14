# Collaudo su Valkaama

*Valkaama*, regia di Tim Baumann, è un lungometraggio distribuito con licenza CC BY-SA 3.0. La prova usa l'AVI ufficiale SD con musica di Michael Georgi. La durata del contenitore è 5.593,600 s e la traccia effettivamente decodificata dura **5.585,688 s** (93 min 5,688 s). La traccia MP3 stereo della copia è stata convertita esplicitamente in mono a 48 kHz mediante FFmpeg. L'asset di progetto contiene **268.113.024 frame**. Film, tracce e cache rimangono locali. [Edizioni e licenza Valkaama](https://www.valkaama.com/index.php?l=en&page=valkaama)

| File | SHA-256 |
|---|---|
| AVI ufficiale | `9481bb61e4613ff30a4da9a645b0f76cb3b5496b7673e46f2d918ea97302caee` |
| FLAC mono importato | `3db34c8cda082555da179c265c1b1c4a04ea54a97cabd3e355c8018e6796d7b3` |

## Controlli eseguiti

- Import integrale su Mac e Docker Linux ARM64. Chromium ha aperto l'intera timeline nel container, applicato EQ, compressore e limiter live e riprodotto PCM dopo un seek a 93 min 1,25 s. Sul progetto completo questa prova iniziale usa la traccia originale.
- Separazione DBS-TIGER DnR su MPS nativo. Inferenza su 1.861 finestre in 3.753,792 s su Apple M2 Max. Dialoghi, Musica, Effetti e Residuo conservano tutti 268.113.024 frame mono a 48 kHz. Chromium ha riprodotto i tre stem integrali dal container, con limiter live, mute/solo, loop e seek a metà film e a 93 min 1,25 s. La stessa prova su un estratto dei primi 95,995 s ha dato esito positivo.
- Render ed export PCM24 in Docker sulla traccia originale integrale. Il master conserva 268.113.024 frame mono a 48 kHz e misura **−1,19888 dBTP** con ceiling −1 dBTP.
- Inpainting offline in Docker su regioni degli stem effettivi prodotti da DBS-TIGER MPS. La regione bersaglio è stata mascherata prima dell'inferenza. I candidati rifiutati restano esclusi. In ogni estratto sono stati verificati **96.000 frame esterni identici**. Il worker ha pubblicato la patch come proposta. L'API ha bloccato mix ed export con approvazione assente o revocata.

| Stem | Regione | RMSE candidato | RMSE silenzio | RMSE lineare |
|---|---|---:|---:|---:|
| Dialoghi | 81,050 s · 30 ms, seed 17 | 0,010002 | 0,013302 | 0,014060 |
| Effetti | 80,050 s · 45 ms, seed 23 | 0,004152 | 0,004580 | 0,005835 |

Le stesse patch sono state applicate e approvate sugli stem integrali in Docker. Il confronto binario ha verificato che i soli frame diversi sono i 1.440 di Dialoghi e i 2.160 di Effetti nelle rispettive maschere. L’RMSE misurato sui file restaurati integrali è 0,010002 per Dialoghi e 0,004152 per Effetti.

Il mix finale in Docker usa i tre stem integrali, le due patch approvate, EQ e compressione su Dialoghi e master e limiter true peak sul master. Il WAV float32 misura **−1,19922 dBTP**, con ceiling −1 dBTP e 3,54 dB di riduzione massima del limiter. Il master esportato in PCM 24 bit misura **−1,19922 dBTP** dopo quantizzazione e −1,2 dBTP nella misura FFmpeg. Il master e i tre stem esportati conservano 268.113.024 frame mono a 48 kHz. Gli SHA-256 dei quattro WAV, del manifest JSON e del report HTML corrispondono alla ricevuta di esportazione. L’export non riporta avvisi.

Nel primo test Chromium sulle versioni restaurate, le scansioni simultanee delle forme d’onda hanno ritardato l’avvio del PCM. Le viste superiori a un minuto ora richiedono una forma d’onda alla volta. Due ripetizioni Playwright sul container aggiornato hanno verificato che il monitor avanza mentre una forma d’onda è ancora in attesa, che riceve campioni da almeno tre stem e che il seek vicino ai titoli funziona.

Le misure sulle regioni selezionate descrivono il confronto con il segnale prima del mascheramento. Le prove esplorative hanno evidenziato anche regioni dove il silenzio o l'interpolazione lineare hanno errore minore. La qualità dipende dal contesto e ogni patch richiede ascolto e approvazione. [Dettagli inpainting](INPAINTING.md)

## Riproduzione della prova

```sh
ffmpeg -hide_banner -nostdin -i Valkaama.avi -map 0:a:0 -ac 1 -ar 48000 -c:a flac valkaama-48k-mono.flac
```

Importa il FLAC nello studio e usa DBS-TIGER DnR in modalità MPS nativa. Dopo la separazione, seleziona gli stem Dialoghi ed Effetti, imposta gli intervalli del prospetto, genera le patch High e prosegui con render ed export dopo l'approvazione. Il test browser può usare un progetto separato con `SONORA_LIVE_TEST_PROJECT=Valkaama` e le posizioni di avvio e seek in campioni. [Istruzioni Playwright](LIVE_MIX.md)
