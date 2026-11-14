# Manuale rapido di SONORA AI

Con SONORA AI puoi separare l’audio di un film in dialoghi, musica ed effetti, riparare brevi lacune e regolare il mix prima di esportarlo.

## Apri lo studio

Se i container sono già attivi, apri [SONORA AI](http://127.0.0.1:8765) in Chrome o Chromium sullo stesso computer. Per un nuovo avvio, accendi Docker Desktop ed esegui dalla cartella del repository:

```sh
docker compose up --build -d --wait
```

## Importa e separa

1. In **Progetti** inserisci un nome e premi **Crea progetto**. Nello studio premi **Importa audio** e scegli un WAV, FLAC, AIFF, MP3 o AAC/M4A mono o stereo. Per la prima prova basta un breve estratto con voce e sottofondo. Per un film, estrai prima la traccia audio che vuoi elaborare.
2. Apri **Modelli**, scarica **DBS-TIGER DnR** e verifica il checksum. Torna al progetto, scegli il modello in **Separazione AI**, seleziona **CPU** se usi Docker e premi **Separa tracce**. Per ottenere stem allineati per il mix lascia **Solo regione** deselezionato. Durante la prima prova puoi ascoltare anche il solo originale dalla console DSP.

## Configura e avvia il restauro

1. Seleziona **Originale** o uno stem completo nella timeline. **Avvia restauro** è in alto nell’**Inspector**, sopra le schede. Se il profilo è ancora vuoto, il pulsante apre **Restauro** per configurarlo.
2. Scegli **Basic**, **Medium** o **High**. Usa **Proponi catena** oppure scegli un processore e premi **Aggiungi**. Ogni profilo ha una catena indipendente. Per ritrovare una catena dopo un cambio di traccia o un ricaricamento della pagina, salvala in **Preset personali** e ricaricala dal profilo corrispondente.
3. Premi **Avvia restauro**. Lo studio esegue gli interventi del profilo attivo dall’alto verso il basso. Usa le frecce per cambiare l’ordine e **Bypass** per saltare un intervento. Al termine, in **Versioni** ascolta il risultato e confrontalo con la sorgente. Premi **Approva** per renderlo selezionabile nella console DSP.

Per riparare una lacuna con **Inpainting neurale**, seleziona **Dialoghi**, **Effetti** o **Musica** nella timeline e delimita la regione. In **Restauro → High** scegli **Inpainting neurale** e premi **Aggiungi**. Puoi ritoccare **Inizio** e **Fine** in campioni. A 48 kHz, 30 ms corrispondono a 1.440 campioni.

Usa regioni di 20–80 ms per **Dialoghi** e 20–120 ms per **Effetti**. Per **Musica** installa in **Modelli** il checkpoint sperimentale **Diffusion inpainting · Pianoforte**, che accetta regioni di 20–250 ms su pianoforte solo. Lascia almeno 250 ms di segnale da ciascun lato e ascolta il risultato prima di approvarlo.

## Ascolta il mix ed esporta

1. In **Console DSP** scegli la versione approvata per ogni traccia. Premi **Ascolta mix live** e prova fader, pan, mute e solo. Apri **Processori** su un canale o sul master per regolare EQ e compressore durante l’ascolto.
2. Nei **Processori** del master attiva **Limiter true peak** e imposta il **Ceiling (dBTP)**. Premi **Render mix**, quindi **Ascolta master**. Il render verifica il true peak sul file. Le misure si trovano in **Misure ultimo master**.
3. Nel pannello **Report** scegli WAV float32, WAV PCM 24 bit o FLAC 24 bit e premi **Esporta master e stem**. Scarica il master, le tracce e il report dai link dell’esportazione.

## Se un comando è disabilitato

- **Separa tracce** richiede un originale e un modello installato.
- **Avvia restauro** richiede una traccia completa approvata e almeno un intervento attivo nel profilo scelto. Se la catena usa la ricostruzione, controlla anche la lunghezza e il contesto della lacuna.
- **Ascolta mix live** richiede almeno una sorgente completa approvata. Con più sorgenti, durata e frequenza devono coincidere.
- **Esporta master e stem** richiede un master renderizzato.

Per arrestare lo studio usa `docker compose down`. Progetti e modelli restano nei volumi Docker. [Guida ai container](CONTAINERS.md) · [Avvio nativo su macOS con MPS](../README.md#avvio-su-macos)
