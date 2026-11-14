# Separazione locale

| Modello (ID) | Codice | Pesi | Profilo | Backends provati su Apple Silicon |
| --- | --- | --- | --- | --- |
| DBS-TIGER DnR v2 (`dbs-tiger-dnr`) | Apache-2.0, [revisione ff526463](https://github.com/JusperLee/Dynamic-Band-Splitting/tree/ff526463a58ee0278e7bd05c4b8bce112b743e34) e avvisi MIT incorporati | Apache-2.0, [SafeTensors 22da7d4c](https://huggingface.co/JusperLee/DBS-TIGER-DnR/tree/22da7d4cd3ea63f9365181008bff1c0d2ab6fb2b), 4 111 836 byte | Mono 44,1 kHz. Uscite musica, effetti, dialoghi. | CPU, MPS |
| Bandit V2 multilingue (`bandit-v2`) | Apache-2.0, [revisione d5563d90](https://github.com/kwatcharasupat/bandit-v2/tree/d5563d9031e95fdaa3e5a73d5020b9a0df61adb6) | CC BY-SA 4.0, [checkpoint multilingue Zenodo v1](https://zenodo.org/records/12701995), 446 680 129 byte | MUS64, mono 48 kHz. Uscite identificate come `speech`, `music`, `sfx`. | CPU, MPS |

`configs/models/registry.json` conserva hash completi, configurazioni, revisione del codice e riferimenti delle licenze. I pesi restano separati dal codice. Per Bandit il confronto iniziale con l'MD5 pubblicato da Zenodo ha fissato lo SHA-256 usato dal downloader. Il caricamento usa esplicitamente `weights_only=True` e richiede una corrispondenza rigorosa di chiavi e forme per entrambi i checkpoint. L'adattatore contiene soltanto il codice d'inferenza selezionato dagli autori a revisioni fisse.

```sh
scripts/sonora models list
scripts/sonora models install dbs-tiger-dnr
scripts/sonora models verify dbs-tiger-dnr
scripts/sonora models install bandit-v2
scripts/sonora models verify bandit-v2
scripts/sonora benchmark --model dbs-tiger-dnr --backend mps --input "/percorso/al/file.wav"
```

`installed` indica un file locale della dimensione attesa. Il comando di verifica controlla lo SHA-256. Il worker ripete quel controllo prima di caricare un checkpoint. I download verificano TLS, dimensione e hash e integrano il bundle CA Certifi con il contesto TLS di Python. Un file incompleto resta temporaneo e viene eliminato. Dopo l'installazione l'inferenza gira offline. Puoi scegliere una cache esterna con `SONORA_MODEL_DIR`.

## Timeline, canali e Metal

- La timeline del progetto è autorevole. Gli adattatori leggono i file a blocchi, elaborano finestre limitate e usano libsoxr in modalità streaming HQ dove la frequenza differisce. Il ricampionatore compensa il proprio ritardo accumulando i campioni e scaricando la coda alla fine. L'uscita viene ritagliata o estesa di pochi campioni a zero per compensare l'arrotondamento della doppia conversione. Ogni WAV float32 o RF64 ha lo stesso numero di campioni della sorgente PCM canonica.
- DBS-TIGER usa finestre da 6 s e passo da 3 s, con media uniforme, zero-padding e ritaglio finale. Su CPU una sola finestra fra 3 s esclusi e 6 s inclusi conserva la durata effettiva secondo la ricetta dell'autore. Su MPS ogni finestra ha forma fissa di 6 s. La durata del contesto di inferenza può influire sul risultato. Gli adattamenti Metal usano indici di scatter-reduce a 32 bit, pooling adattivo calcolato per intervalli nei casi non divisibili, e proiezione lineare prima del broadcast per evitare un kernel Metal con stride nullo. I bin FFT restano nell'intervallo intero consentito.
- Bandit V2 usa finestre Hann da 8 s, passo da 1 s, lato corto riflesso quanto disponibile e poi esteso a zero. La somma pesata è normalizzata sulla copertura locale. Mantiene la geometria e il taper della ricetta degli autori e usa una finestra per volta, con forma fissa e buffer del modello convertiti a float32. Fornire un estratto breve riduce la durata utile ma richiede comunque le finestre di contesto.
- Per lo stereo, entrambi i modelli elaborano L e R in sequenza e li riportano nell'ordine originale. Bilanciamento e correlazione misurati sono allegati per il mix originale e ogni uscita, compreso il residuo. La risposta indipendente dei canali può alterare la posizione o la stabilità delle sorgenti. Il confronto con un modello stereo congiunto è da eseguire.
- Il residuo è la differenza tra originale canonico e somma delle tre stime pre-restauro alla frequenza del progetto. La ricostruzione con il residuo verifica allineamento e conservazione numerica. I tre stem possono ancora contenere contaminazioni, come mostra il benchmark.
- L'inferenza usa il backend richiesto. Se MPS è disponibile, il catalogo lo espone. SONORA AI lascia disattivato il fallback globale su CPU nella configurazione normale. Se il processo eredita `PYTORCH_ENABLE_MPS_FALLBACK=1`, l'impostazione compare negli avvisi di provenienza. La memoria riportata da MPS è la memoria del driver a fine separazione. RSS massimo è il massimo storico del processo. Le misure non coprono tutti gli usi possibili di memoria unificata.

## Prova riproducibile con i checkpoint reali

Usa lo stesso comando per una combinazione diversa di checkpoint e backend cambiando le variabili.

```sh
SONORA_TEST_MODEL_DIR="/percorso/alla/cache" SONORA_TEST_MODEL=dbs-tiger-dnr SONORA_TEST_BACKEND=mps \
  .venv/bin/python -m unittest discover -s tests -p test_models.py -k test_real_checkpoint -v
```

I test ordinari coprono checkpoint assente o corrotto, annullamento, overlap-add e integrità della timeline con una funzione di trasporto deterministica. Il test reale è saltato con motivazione quando cache, checkpoint o backend sono indisponibili.

## Benchmark con riferimenti cinematografici

Prova eseguita su Apple M2 Max con 32 GiB e macOS 27.2.1, con PyTorch/Torchaudio 2.8.0, backend MPS e pesi indicati nella tabella. Il campione è l'intervallo 80–88 s di `film_04` del dataset CineAudioDB, ricostruito per somma dei riferimenti `dialogue`, `music` e `sfx` a 48 kHz stereo. È un adattamento audio di un'animazione della Blender Foundation / Blender Institute, licenza CC BY 3.0 secondo il dataset. Tracce e derivati del test sono stati tenuti in area temporanea. [Dataset e attribuzioni, revisione 63581980](https://huggingface.co/datasets/disco-eth/cineaudiodb/tree/63581980aeee6ac700deef4a5d0e14a4a437aea2), [NOTICE degli autori](https://huggingface.co/datasets/disco-eth/cineaudiodb/blob/63581980aeee6ac700deef4a5d0e14a4a437aea2/NOTICE.md).

| Misura (dB se indicato) | DBS-TIGER | Bandit V2 |
| --- | ---: | ---: |
| SI-SDR dialoghi | −2,37 dB | +1,81 dB |
| SI-SDR musica | −1,33 dB | +5,05 dB |
| SI-SDR effetti | −1,67 dB | +1,78 dB |
| Guadagno proiettato dialoghi | −11,05 dB | −6,12 dB |
| Guadagno proiettato musica | −8,50 dB | −2,78 dB |
| Guadagno proiettato effetti | −1,28 dB | −2,19 dB |
| Musica rilevata negli effetti | −2,25 dB | −9,03 dB |
| Effetti rilevati nella musica | −11,22 dB | −13,54 dB |
| Caricamento checkpoint, incluso SHA-256 | 0,70 s | 1,33 s |
| Inferenza, ricostruzione e scrittura | 9,82 s | 73,42 s |
| RTF (secondi di elaborazione / secondi audio) | 1,23 | 9,18 |
| Memoria allocata dal driver MPS a fine inferenza | 6,19 GB | 3,05 GB |

Il SI-SDR è il rapporto fra energia della proiezione sulla traccia vera ed energia della differenza, dopo rimozione della media, in dB. Il guadagno proiettato è ottenuto dalla scala di quella proiezione. La contaminazione è la potenza della componente proiettata, mediante regressione congiunta sui tre riferimenti, divisa per la potenza della componente corretta proiettata nello stesso stem. Valori più negativi indicano meno contaminazione misurata secondo questa definizione. La regressione può sottostimare contributi non lineari o ritardati.

Bandit ha avuto meno contaminazione musica/effetti e SI-SDR più alto in questo singolo estratto, impiegando più tempo. Il risultato è descrittivo di questa miscela additiva e non predice la qualità dei due modelli su altri film o su master non additivi. Per scegliere su materiale reale servono estratti ulteriori e ascolti comparativi.

Per ripetere la prova, scarica soltanto `data/film_04/{dialogue,music,sfx}.flac` dalla revisione del dataset indicata sopra in una cartella esterna al repository. SHA-256 in quell'ordine:

```text
65d2db9ddcab8eb43597839751906f3d689fc8d242db5c3f63bf0850321ab9c2  dialogue.flac
de9bcf2876327352a08502ae4284e56c54ecd681cb602d96f81e847354eb63d1  music.flac
0296369fc7c16d9799524fd7ddfd9bc2357e5b373a7d428605f04787a50fc203  sfx.flac
```

```sh
.venv/bin/python -m packages.model_adapters.benchmark \
  --references "/percorso/agli/stem" --model-dir "/percorso/alla/cache" \
  --backend mps --start 3840000 --end 4224000
```
