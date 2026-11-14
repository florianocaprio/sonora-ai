# SONORA AI

Leggi [brief](docs/MASTER_PROMPT.md), [requisiti](docs/REQUIREMENTS.md) e [stato](docs/WORK_STATE.md) prima di intervenire. Lavora con modifiche piccole, coordinate e verificabili. Usa un ramo dedicato quando possibile. Se incontri conflitti Git, descrivili prima di risolverli.

- Servizi cloud, credenziali e dati audio dell'utente restano fuori dal runtime e dal repository. Mantieni il servizio su loopback.
- Mantieni gli originali immutabili e i dati runtime esterni. Usa intervalli in campioni interi e il rendering autorevole per il confronto.
- Dichiara l'impatto di modifiche a migrazioni, OpenAPI e tipi. Rigenera gli artefatti con i comandi documentati.
- Descrivi i test effettivamente eseguiti, distinguendo fixture, inferenza CPU e MPS. Comandi: `pnpm install`, `pnpm run typecheck`, `pnpm --filter @workspace/api-server run test`.
