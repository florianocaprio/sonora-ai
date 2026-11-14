# Monitor multitraccia live

Nel progetto, carica l'audio e separalo. Premi **Ascolta mix live** nella console DSP. Il trasporto comune controlla riproduzione, pausa, stop, seek e loop della regione selezionata. Fader, trim, inversione di polarità, pan/balance, mute, solo, automazioni e fader del master agiscono durante l'ascolto. I meter mostrano il picco campionato al termine della somma e per canale, prima del volume monitor. L'eventuale clipping del monitor è visibile nel meter.

**Ascolta master** passa alla versione renderizzata alla posizione indicata dal clock del monitor. L'export e il master audio risultano dal renderer del worker. EQ, compressore e limiter operano nel render. Il monitor live usa un DSP più semplice, il risultato cambia con i processori attivi e con le transizioni. I timing del mixer, la legge stereo e le automazioni sono documentati in [AUDIO_ENGINE.md](AUDIO_ENGINE.md).

## Clock e memoria

Un solo AudioWorklet produce entrambe le uscite da campioni PCM allineati. La posizione deriva da un accumulatore fra campioni di progetto e frame del contesto audio Web, con interpolazione lineare per l'ascolto quando le frequenze differiscono. Il tooltip del trasporto riporta frequenza di progetto, frequenza del contesto e conteggio delle interruzioni. I campioni originali del renderer e dell'export conservano il proprio rate. **Loop** ritorna all'inizio della regione sul thread audio e la coda mantiene un blocco di ritorno quando si avvicina la fine della regione. [Specifica Web Audio, AudioWorklet](https://www.w3.org/TR/webaudio-1.1/#AudioWorklet)

L'API locale serve intervalli di PCM float32 little-endian interlacciato. Ogni blocco contiene al massimo 131.072 frame e tutte le tracce richieste. La coda mantiene al massimo tre blocchi completi o in trasferimento, pari a circa 4,4 MiB di campioni per quattro stem stereo a 48 kHz. Al seek o al cambio sorgenti, le richieste obsolete sono annullate e il processore ignora messaggi di generazioni precedenti. Se un blocco arriva tardi, il monitor entra in buffering: quanta parte della timeline è stata riprodotta è registrata dal clock condiviso e tutte le tracce ripartono dalla medesima posizione. Il primo caricamento e il prefill dopo seek sono distinti dal conteggio delle interruzioni successive.

I controlli della console agiscono sulle sorgenti già selezionate. Servono uno o più asset approvati mono/stereo con la stessa durata e frequenza di progetto e senza offset. Le versioni parziali possono essere ascoltate con il trasporto del singolo asset. Il monitor stereo applica pan a potenza costante al mono e attenuazione del canale opposto alle sorgenti stereo. Le modifiche manuali passano per uno smoothing di 3 ms. All'uscita dallo studio, il browser chiude il contesto audio e interrompe il caricamento.

## Verifica

Il test Playwright attiva il monitor, osserva i blocchi ricevuti dall'API e controlla la risposta del meter a mute e solo. In un OfflineAudioContext di Chromium somma due segnali stereo campione per campione, con progetto a 48 kHz e uscita a 44,1 kHz. Misura annullamento del canale sinistro, ampiezza e tolleranza temporale sul destro. Il test include l'invio di un blocco con generazione obsoleta.

```sh
SONORA_E2E_URL=http://127.0.0.1:8765 pnpm exec playwright test tests/e2e/live.spec.ts
SONORA_LIVE_TEST_MODEL=dbs-tiger-dnr SONORA_LIVE_TEST_BACKEND=cpu \
  pnpm exec playwright test tests/e2e/live.spec.ts
```

Su un progetto già separato, passa il nome esatto con `SONORA_LIVE_TEST_PROJECT` e un punto sonoro con `SONORA_LIVE_TEST_START_SAMPLE`. Per verificare anche un salto verso i titoli, imposta `SONORA_LIVE_TEST_END_SAMPLE`. I risultati numerici del test riguardano Chromium. La latenza del dispositivo, il comportamento del sistema al cambio uscita e la qualità del ricampionamento in ascolto dipendono dal browser e vanno misurati separatamente su Safari o altre configurazioni.
