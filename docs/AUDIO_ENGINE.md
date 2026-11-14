# Motore audio e DSP

## Acquisizione e timeline

libsndfile riconosce il contenuto di WAV, WAVE esteso, RF64, AIFF, FLAC e MP3 anche con suffissi atipici. FFmpeg e ffprobe decodificano AAC/M4A con selezione della prima traccia audio, demuxer consentiti esplicitamente e protocollo locale. Su macOS Core Audio può decodificare AAC quando il codec è presente nella build. Nella macchina di prova l'importazione AAC è stata verificata con FFmpeg 9.0.2. I layout supportati sono mono e stereo, in ordine C o L/R. Un file multicanale richiede una conversione esplicita.

La timeline di lavoro è in campioni interi alla frequenza di progetto. L'asset canonico è PCM float32. Il decoder determina i campioni sorgente disponibili, applicando le informazioni di priming e padding che riconosce. I metadati non inferiscono una profondità PCM da un bitrate compresso. Il ricampionamento razionale usa un FIR simmetrico SciPy, contesto ai bordi di ogni blocco, fase ancorata al campione zero e durata arrotondata per eccesso al campione di uscita. Il bordo esterno è a zero. Un passaggio alla stessa frequenza conserva i valori float32. Il formato passa a RF64 quando necessario per la dimensione WAV. Le scritture avvengono su un file temporaneo nello stesso filesystem e la pubblicazione usa rinomina atomica. [libsndfile](https://libsndfile.github.io/libsndfile/) · [python-soundfile](https://python-soundfile.readthedocs.io/en/latest/) · [resample_poly](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.resample_poly.html)

## Diagnostica

L'analisi non modifica il segnale. Ogni regione è semichiusa `[start_sample, end_sample)`. I tre profili specializzati modificano la soglia relativa degli impulsi, la soglia di quasi-silenzio e l'energia tonale minima. Dialoghi privilegia la continuità. Musica ed effetti hanno soglie più conservative per preservare attacchi e ambienti. La sensibilità da 0 a 1 abbassa proporzionalmente le soglie di impulso, ronzio e offset DC. I risultati sono segnali da rivedere con l'ascolto.

| Profondità | Finestra temporale | Passo della misura spettrale |
| --- | --- | --- |
| Rapida | 500 ms | 2 s |
| Standard | 250 ms | 1 s |
| Approfondita | 125 ms | 0,5 s |

- **Integrità e livelli.** Conteggio NaN/Inf e campioni a fondo scala, picco campionato, RMS, crest factor, media DC per canale. Tre o più campioni esattamente uguali in prossimità del fondo scala sono marcati come possibile flat-top.
- **Stereo e bilanciamento.** Correlazione di Pearson e differenza d'energia destra/sinistra. Silenzio, canale senza energia o varianza zero possono rendere una misura indefinita.
- **Impulsi isolati.** Interpolazione dei due adiacenti usata come riferimento locale, soglia assoluta e multiplo robusto della deviazione mediana. Il rilevatore richiede continuità fra i campioni ai lati del candidato.
- **Possibili micro-gap.** Breve sequenza sotto la soglia di profilo, circondata da segnale misurabile. Una durata breve o energia bassa possono appartenere al contenuto.
- **Possibile ronzio.** FFT sul contenuto rimosso della media, finestra di Hann di massimo mezzo secondo, bins prossimi a 50/60 Hz e confronto con l'energia totale. Un tono sostenuto musicale può generare una segnalazione.
- **Indicazioni spettrali.** Frequenza entro la quale cade il 95% dell'energia spettrale media normalizzata. Il decimo percentile dell'RMS delle finestre non nulle è un indicatore di fondo. Queste quantità non separano rumore e contenuto.
- **Confidenza.** Il valore `confidence_kind = heuristic_score` descrive una convenzione del rilevatore. Un marker può essere confermato o escluso dall'operatore. La risposta mantiene al massimo 512 eventi e dichiara le ulteriori segnalazioni.

La waveform restituisce picchi aggregati su intervalli richiesti. Lo spettrogramma restituisce fino a 512 colonne di una regione con frequenze lineari, finestra di Hann, massimo sui canali e pavimento da −120 dBFS. L'analisi usa finestre locali e contesto per gli eventi a cavallo dei confini. La durata del file non estende il buffer dei campioni.

## Restauro

Il piano è una lista ordinata di operazioni in JSON con `type`, intervallo, `wet` da 0 a 1, `bypass` e parametri. Basic propone correzioni conservative per i difetti segnalati. Medium propone anche una lieve campana parametrica distinta per dialoghi, musica ed effetti. High può proporre l'interpolazione di micro-gap. Una proposta di ronzio su musica ed effetti viene inserita solo dopo conferma del marker. Le proposte si possono modificare prima della creazione di una versione da ascoltare e approvare. [Audio EQ Cookbook](https://www.w3.org/TR/audio-eq-cookbook/)

| Operazione | Parametri | Elaborazione |
| --- | --- | --- |
| `dc_remove` | Wet e regione | Sottrae la media della regione per ogni canale. |
| `dehum` | `frequency_hz`, `q` | IIR notch al centro richiesto. |
| `declick` | `threshold` in ampiezza float | Sostituisce deviazioni isolate sopra soglia con la media dei due adiacenti. |
| `peq` | `frequency_hz`, `gain_db`, `q` | Una campana parametrica con banda regolabile. |
| `microgap` | `max_duration_ms` fino a 20 ms | Interpolazione lineare fra i campioni ai lati della regione. La provenienza compare come ricostruzione. |

Dehum ed EQ preriscaldano lo stato del filtro usando fino a un secondo di contesto. I raccordi di DC, dehum ed EQ si svolgono all'interno della regione, fino a 8 ms per bordo interno. La riparazione conserva bit per bit i valori float32 esterni alla regione. La differenza riproducibile è la versione restaurata meno la sorgente allineata. L'elaborazione a blocchi con al massimo due intermedi simultanei privilegia l'affidabilità e richiede un passaggio sul file per ogni operazione.

Il profilo High supporta inoltre una patch [di inpainting neurale](INPAINTING.md) su Musica con modello per pianoforte e regione 20–250 ms. Rimangono aperti flat-top, denoising neurale, de-essing, dereverb, sostituzione da sorgente alternativa ed estensione di banda. Le stime di wow/flutter, pumping, intelligibilità e contaminazione semantica richiedono ulteriori rilevatori e validazione sui materiali appropriati.

## Mixer ed esportazione

Il renderer somma in float64 e scrive il master in float32. Ogni traccia ammette trim in dB, fino a otto bande EQ, compressione collegata fra i canali, fader, polarità, mute, solo e pan/balance. Il bypass disattiva EQ e compressore. Il pan mono usa legge a potenza costante, con uscita stereo quando lo richiede almeno un canale incluso. Il bilanciamento stereo attenua il canale opposto. L'automazione passa per punti ordinati in campioni, con interpolazione lineare dei dB e di pan/balance. Le transizioni di mute richiedono fino a 5 ms, limitati dal punto successivo.

Il compressore usa il massimo delle ampiezze dei canali su blocchi di 32 campioni, soglia, ratio, knee quadratico, smoothing di attacco e rilascio e makeup. Il guadagno è interpolato nel blocco. I processori CPU non aggiungono ritardo alla timeline. È disponibile il massimo abbattimento in dB rilevato per canale e master. Il [mix live](LIVE_MIX.md) miscela PCM a blocchi con un clock AudioWorklet. Il file master renderizzato include i processori EQ e dinamica. I meter nel manifest misurano l'asset finito.

Il residuo entra nella somma solo se abilitato. Il master offre trim, EQ, compressione e un [limiter true peak](LIMITER.md) da attivare esplicitamente. Il renderer verifica il ceiling sul file master e l’export lo misura di nuovo dopo la conversione. La normalizzazione broadcast resta da integrare. [ITU-R BS.1770-5](https://www.itu.int/rec/R-REC-BS.1770-5-202311-I/en) · [EBU R 128](https://tech.ebu.ch/publications/r128)

FFmpeg `loudnorm` misura il segnale in ingresso al filtro. L'uscita normalizzata del filtro viene scartata. La scansione `ebur128` sugli ultimi quattro secondi fornisce momentary e short-term sull'ultima finestra completa. L'unità integrata è LUFS, il campo del range è LU, il true peak è dBTP. I file sotto 400 ms possono avere soltanto un true peak, il range e la misura short-term necessitano di almeno tre secondi. I valori indefiniti o i filtri indisponibili producono un campo JSON nullo. L'esportazione WAV float32, WAV PCM24 e FLAC 24 bit misura l'audio riaperto dal formato finale. Il passaggio a PCM24 fallisce se un campione eccede l'intervallo rappresentabile. Al momento la conversione PCM24 non applica dither. [FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm) · [FFmpeg ebur128](https://ffmpeg.org/ffmpeg-filters.html#ebur128)

## Verifica numerica

`python -m unittest discover -s tests -p test_audio.py -v` usa fixture sintetiche generate al volo. La verifica include round-trip PCM, frequenza e durata AAC entro un frame del codec, confronto con ricampionamento monolitico entro 3 × 10⁻⁷, micro-gap con errore entro 10⁻⁸ e campioni esterni invariati, lettura FLAC, separazione fra picco campionato e true peak, controllo del ceiling, meter EBU su tono, conservazione di bande sane e annullamento senza pubblicazione. Le verifiche AAC e loudness richiedono FFmpeg. Il test sul tono a 1 kHz usa la tolleranza di 0,2 LU, quello sul picco della sinusoide 0,12 dB.
