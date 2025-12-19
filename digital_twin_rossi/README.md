# Author: Alberto Caggiano

## Guida Rapida

### 1. Installazione
Assicurarsi di disporre di un ambiente Python 3.9+ e installare le dipendenze:

```bash
pip install -r requirements.txt
```

### 2. Esecuzione
Per avviare la simulazione comparativa degli scenari:

```bash
python main.py
```
Il software eseguirà sequenzialmente le politiche configurate, mostrando a video il report manageriale e salvando i dettagli su file.

## Struttura del Progetto

*   **`domain/`**: Contiene la logica di business e le definizioni del dominio (es. `services/scenario_service.py` per l'orchestrazione, `exceptions.py`).
*   **`infrastructure/`**: Gestisce l'output e la visualizzazione (es. `reporting_service.py` per la generazione dei grafici e dei report CSV).
*   **`output/`**: Directory di destinazione per tutti gli artefatti generati dalla simulazione (Report Tabellari, Grafici di Gantt, Summary).
*   **`simulazione_core.py`**: Il motore di simulazione, definisce le classi `Macchinario`, `OrdineDiLavoro` e le strategie di processo.
*   **`configurazione.py`**: File centralizzato per la parametrizzazione del modello (tempi, costi, probabilità guasti).

