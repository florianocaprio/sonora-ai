# Inpainting neurale per brevi lacune musicali

Il modello `diffusion-inpaint` usa i pesi EMA ufficiali di Diffusion-Based Audio Inpainting. La configurazione salvata nel checkpoint indica l'addestramento su pianoforte solo (MAESTRO), a 22.050 Hz mono. Lo studio espone la funzione nel profilo High dello stem **Musica**. Gli altri stem richiedono un modello con addestramento e validazione adatti. Su musica orchestrale o mista il risultato va valutato come candidato sperimentale. Il segnale prodotto è una nuova stima della lacuna. [Articolo Moliner–Välimäki](https://www.aes.org/e-lib/browse.cfm?elib=22383) · [Codice upstream](https://github.com/eloimoliner/audio-inpainting-diffusion/tree/28b0e92683d58d0ab12a73e675a4da387b00caa5)

Il checkpoint pesa 712.985.958 byte. Il download è esplicito. L'origine, la revisione, la licenza MIT dichiarata dall'autore e lo SHA-256 sono fissati nel [manifest](../configs/inpainting/diffusion-inpaint.json). Il digest viene verificato prima di caricare i pesi. Il caricamento usa `weights_only=True`, sostituti inerti per le classi OmegaConf dei metadati di training e corrispondenza rigorosa di forme e chiavi. Il codice di inferenza viene eseguito localmente. [Checkpoint ufficiale](https://huggingface.co/Eloimoliner/audio-inpainting-diffusion/tree/9d7358c7a6b157d925ee2255d122ab5ec93771fb)

## Impostazioni e limiti verificati

- Maschera temporale tra 20 e 250 ms, con almeno 250 ms di segnale disponibile su ogni lato. Il modello riceve una finestra centrata da 32.768 campioni a 22.050 Hz, con padding zero solo dove manca ulteriore contesto. Il checkpoint è stato addestrato con 184.184 campioni di contesto. La riduzione e i 10 passi Euler sono scelte di inferenza per rendere praticabile l'anteprima CPU.
- Campionamento EDM a precisione float32 con osservazioni imposte ad ogni passo. Ogni canale riceve lo stesso seed intero e viene elaborato indipendentemente. In stereo la stima generata può alterare la correlazione L/R dentro la regione.
- Il motore oscura i campioni selezionati prima del ricampionamento. Genera una nuova stima e la ricampiona alla frequenza di progetto, ammessa tra 8 e 192 kHz. Il raccordo a coseno dura al massimo 3 ms e ricade interamente all'interno della maschera. I campioni float32 esterni sono copiati senza modifiche e l'asset sorgente rimane intatto.
- Il candidato registra hash, modello, seed, algoritmo, backend, progressi per passo di diffusione, durata e RSS massimo storico del processo. Inpainting usa CPU con al massimo quattro thread PyTorch. A/B, differenza e revisione si fanno nello studio, prima di usare il candidato nel mix o nell'export.

## Verifica riproducibile

```sh
scripts/sonora models install diffusion-inpaint
scripts/sonora models verify diffusion-inpaint
SONORA_TEST_INPAINT_MODEL_DIR="$HOME/Library/Caches/SONORA AI/models" \
  scripts/test.sh --pattern test_inpainting.py
```

Test con patch simulata per verificare campioni esterni, incrocio del confine di un blocco, stereo e 8/44,1/48/192 kHz. Il test opzionale esegue l'inferenza vera su un segnale di pianoforte sintetizzato nel test, con lacuna di 80 ms da 0,82 a 0,90 s, a 48 kHz mono. Su Apple M2 Max, seed 42, una prova ha impiegato 34,05 s in inferenza, con RSS massimo del processo di 1.446.461.440 byte. RMSE sulla regione di 0,0520 contro 0,0669 della maschera muta. Tutti i 140.160 campioni esterni sono identici. Nell’immagine Docker Linux ARM64 il test con gli stessi pesi e seed ha impiegato 23,20 s in inferenza, con RSS massimo di 1.197.932.544 byte. L’RMSE coincide a sei cifre decimali e il test conferma la stessa preservazione dei campioni esterni. La prova misura una singola lacuna sintetica.

## Codice incluso

`packages/inpainting/_vendor/network.py` conserva la rete MIT del repository ufficiale alla revisione del manifest con import relativi e rimozione dei log e degli import inutilizzati. La trasformata deriva dall'implementazione CQT degli autori, revisione `370e3d0a01deb5e469ece9b6369d074f7ad2831c`, dichiarata MIT. SONORA include il componente sotto il nome interno `packages.inpainting._vendor.cqt`, con la sola normalizzazione degli spazi e rimozione della stampa del parametro Kaiser. Le parti derivate da NSGT di Thomas Grill conservano attribuzioni NUHAG e condizioni Artistic-2.0. Il sorgente di tali parti, comprese queste modifiche, può essere redistribuito secondo Artistic-2.0. [CQT sorgente](https://github.com/eloimoliner/CQT_pytorch/tree/370e3d0a01deb5e469ece9b6369d074f7ad2831c) · [NSGT sorgente](https://github.com/grrrr/nsgt) · [Licenze incluse](../packages/inpainting/_vendor/)
