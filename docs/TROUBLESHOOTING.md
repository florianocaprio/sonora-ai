# Diagnostica su macOS

- **Porta occupata.** Chiudi un'istanza SONORA AI tramite `scripts/stop.sh` oppure imposta `SONORA_PORT=8766`. Usa la stessa configurazione per stop e start.
- **Priorità a Metal.** Esegui `scripts/sonora doctor` in una shell nativa ARM64. Se MPS manca, seleziona CPU. La disponibilità può variare tra shell interattiva e sessione con sandbox.
- **Checkpoint mancante o hash diverso.** Usa `scripts/sonora models install ID` e `scripts/sonora models verify ID`. Il catalogo presenta stato, dimensione e licenza.
- **AAC/M4A o misure mancanti.** Esegui `scripts/build-ffmpeg-macos.sh` oppure rendi ffmpeg e ffprobe disponibili nel PATH. `doctor` mostra i binari rilevati.
- **Spazio insufficiente.** Verifica che il volume dati e quello cache siano montati e scrivibili. Il materiale multitraccia float32 occupa più spazio dell'originale compresso.
- **File con più di due canali.** Il worker conserva il file ricevuto e segnala il limite. Usa una conversione esplicita a mono/stereo prima di avviare la pipeline.
- **Worker interrotto.** Riapri lo studio e scegli **Riprova** sul job interrotto. La ripartenza usa l'input immutabile e ricrea il job da inizio elaborazione.
- **PCM oltre il fondo scala.** Riduci il gain/master o scegli float32 quando il formato di consegna lo consente. Il ceiling del master produce un avviso misurato.
