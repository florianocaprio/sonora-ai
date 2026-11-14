# Limiter true peak del master

Il limiter è disponibile durante **Remix**. Si attiva esplicitamente in `master.limiter.enabled` e usa `master.ceiling_dbtp`, con valore predefinito −1 dBTP quando attivo. Il bypass del master disattiva il limiter insieme ai processori. Il monitor live ha un percorso e una latenza propri. Per ascoltare il risultato del limiter usa il master renderizzato.

| Campo | Default | Intervallo |
| --- | --- | --- |
| `enabled` | `false` | booleano |
| `lookahead_ms` | 5 | 1–20 ms |
| `release_ms` | 80 | 10–1.000 ms, costante di tempo del recupero esponenziale |
| `master.ceiling_dbtp` | −1 con limiter attivo | −30–0 dBTP |

Il DSP agisce dopo somma, trim, EQ, compressione e fader del master. Su ogni blocco rileva i massimi assoluti con interpolazione FIR polifase 8×, finestra Kaiser e contesto di 64 campioni ai bordi. Include i picchi campionati e usa l'inviluppo massimo tra i canali. Una media causale del guadagno richiesto dal massimo futuro dà un attacco anticipato. Il rilascio è esponenziale e conserva il proprio stato tra i blocchi. Lo stesso guadagno si applica a entrambi i canali, mantenendo l'allineamento, la lunghezza e l'ordine L/R. Il rilevatore usa un margine operativo di 0,20 dB sotto il ceiling. [ITU-R BS.1770-5, allegato 2](https://www.itu.int/rec/R-REC-BS.1770-5-202311-I)

Il renderer misura il file float riaperto con l'interpolatore nativo e, se disponibile, con `input_tp` di FFmpeg `loudnorm`. Il valore di verifica è il maggiore dei due. Se supera il ceiling, il renderer applica al file una correzione uniforme pari al superamento più 0,05 dB e ripete entrambe le misure. Se il superamento persiste, il master non viene pubblicato. Il manifest registra picco nativo, picco di riferimento, correzione di verifica, attenuazione massima e parametri. L'esportazione a un'altra frequenza può produrre nuovi picchi e ha una propria misura sul file finale. [FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm)

Il buffering è limitato a blocchi e contesto. A limiter attivo il rendering richiede un file temporaneo float delle dimensioni del master, oltre al file finale. La seconda scrittura completa è necessaria quando la verifica richiede una correzione. L'annullamento rimuove gli intermedi e conserva l'eventuale master preesistente.

## Verifica ripetibile

`scripts/test.sh --pattern test_limiter.py` esegue i controlli del limiter. La fixture numerica sintetizza le sinusoidi 15–19 della tabella 1 di EBU Tech 3341 a 48 kHz e verifica la tolleranza −0,4/+0,2 dBTP del misuratore. Verifica inoltre overshoot fra campioni, riproducibilità del bypass, identità del passaggio inattivo su segnale moderato, linkage stereo e allineamento tra blocchi, ricostruzione 16× indipendente, round-trip PCM24 a pari frequenza, silenzio e annullamento. FFmpeg abilita un secondo confronto indipendente sul master. [EBU Tech 3341, tabella 1](https://tech.ebu.ch/docs/tech/tech3341.pdf)

La validazione copre questi vettori e i file indicati nel rapporto di verifica. La sintesi interna evita di redistribuire il pacchetto audio EBU. Rimangono fuori dal collaudo la conformità completa EBU Mode, i layout multicanale e i picchi introdotti da encoder con perdita.
