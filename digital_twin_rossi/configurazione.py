from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Optional, Union
import random

class TipoProdotto(str, Enum):
    FL_01 = "FL-01" 
    PN_03 = "PN-03" 
    IN_07 = "IN-07" 
    RD_01 = "RD-01" 

class TipoMacchinario(str, Enum):
    TRONCATRICE = "Troncatrice"
    TRAPANO = "Trapano"
    TORNIO = "Tornio"
    FRESA = "Fresa"
    RETTIFICA = "Rettifica"
    FORNO = "Forno"
    BANCO_ASSEMBLAGGIO = "Banco Assemblaggio"
    BANCO_COLLAUDO = "Banco Collaudo"
    BANCO_CONTROLLO = "Banco Controllo"

class TipoOperatore(str, Enum):
    GENERICO = "Operatore Generico"
    SPECIALIZZATO = "Tecnico Specializzato"

class PoliticaSchedulazione(Enum):
    FIFO = auto()
    SPT = auto()
    EDD = auto()

@dataclass
class ConfigurazioneSimulazione:
    """
    Classe data-container per la configurazione dei parametri di simulazione.
    
    Definisce i vincoli di capacità, i tempi di ciclo e i parametri economici del modello.
    Convenzioni unità di misura: tempo in minuti, valori monetari in Euro (€).
    """
    tempi_lavorazione: Dict[TipoMacchinario, Dict[TipoProdotto, float]]
    capacita: Dict[Union[TipoMacchinario, TipoOperatore], int]
    probabilita_rifacimento: float
    richiede_specialista: bool
    prezzi_prodotti: Optional[Dict[str, float]] = None
    penale_al_minuto: float = 0.0
    costo_orario_macchinari: Optional[Dict[TipoMacchinario, float]] = None
    costo_orario_operatori: Optional[Dict[TipoOperatore, float]] = None
    limiti_produzione_giornaliera: Optional[Dict[str, int]] = None
    limite_produzione_totale_giornaliera: Optional[int] = None
    fattore_variabilita_processo: float = 0.10
    tempo_setup_minuti: float = 0.0
    probabilita_guasto: float = 0.0
    minuti_riparazione_min: int = 60
    minuti_riparazione_max: int = 180
    minuti_buffer_sicurezza_assemblaggio: int = 300
    fattore_urgenza_min: float = 3.0
    fattore_urgenza_max: float = 6.0
    orario_inizio_turno: int = 8
    orario_fine_turno: int = 17
    
    distinta_base: Optional[Dict[str, Dict[str, int]]] = None
    livelli_scorta_minima: Optional[Dict[str, int]] = None
    lotto_riordino_standard: Optional[Dict[str, int]] = None

    def __post_init__(self):
        if not 0.0 <= self.probabilita_rifacimento <= 1.0:
            raise ValueError(f"Probabilità rifacimento non valida: {self.probabilita_rifacimento}")

class GestoreConfigurazione:
    def __init__(self) -> None:
        self.configurazione_base = self._crea_configurazione_base()

    def _crea_configurazione_base(self) -> ConfigurazioneSimulazione:
        tempi = {
            TipoMacchinario.TRONCATRICE: {
                TipoProdotto.FL_01: 10,
                TipoProdotto.PN_03: 15,
                TipoProdotto.IN_07: 30
            },
            TipoMacchinario.TRAPANO: {
                TipoProdotto.FL_01: 10
            },
            TipoMacchinario.TORNIO: {
                TipoProdotto.PN_03: 30
            },
            TipoMacchinario.FRESA: {
                TipoProdotto.IN_07: 45
            },
            TipoMacchinario.RETTIFICA: {
                TipoProdotto.PN_03: 20,
                TipoProdotto.IN_07: 20
            },
            TipoMacchinario.FORNO: {
                TipoProdotto.IN_07: 12
            },
            TipoMacchinario.BANCO_ASSEMBLAGGIO: {
                TipoProdotto.RD_01: 60
            },
            TipoMacchinario.BANCO_COLLAUDO: {
                TipoProdotto.RD_01: 30
            },
            TipoMacchinario.BANCO_CONTROLLO: {
                TipoProdotto.FL_01: 10,
                TipoProdotto.PN_03: 10,
                TipoProdotto.IN_07: 10
            }
        }
        
        capacita = {
            TipoMacchinario.TRONCATRICE: 3,
            TipoMacchinario.TORNIO: 3,
            TipoMacchinario.FRESA: 2,
            TipoMacchinario.TRAPANO: 2,
            TipoMacchinario.RETTIFICA: 2,
            TipoMacchinario.FORNO: 1,
            TipoMacchinario.BANCO_ASSEMBLAGGIO: 2,
            TipoMacchinario.BANCO_COLLAUDO: 2,
            TipoMacchinario.BANCO_CONTROLLO: 2,
            TipoOperatore.GENERICO: 6,
            TipoOperatore.SPECIALIZZATO: 3
        }

        distinta_base = {
            TipoProdotto.RD_01: {
                TipoProdotto.FL_01: 1,
                TipoProdotto.PN_03: 2
            }
        }
        
        return ConfigurazioneSimulazione(
            tempi_lavorazione=tempi,
            capacita=capacita,
            probabilita_rifacimento=0.05,
            richiede_specialista=True,
            fattore_variabilita_processo=0.0,
            tempo_setup_minuti=15,
            probabilita_guasto=0.01,
            distinta_base=distinta_base,
            prezzi_prodotti={
                TipoProdotto.FL_01: 50.0, TipoProdotto.PN_03: 80.0, 
                TipoProdotto.IN_07: 100.0, TipoProdotto.RD_01: 500.0
            },
            costo_orario_macchinari={m: 20.0 for m in TipoMacchinario},
            costo_orario_operatori={
                TipoOperatore.GENERICO: 25.0,
                TipoOperatore.SPECIALIZZATO: 40.0
            }
        )

    def ottieni_configurazione(self) -> ConfigurazioneSimulazione:
        return self.configurazione_base

def genera_quantita_lotto_stocastico(rng=None) -> Dict[TipoProdotto, int]:
    _rng = rng if rng else random
    
    qty_rd01 = _rng.randint(50, 80)
    
    min_fl01 = qty_rd01 * 1
    min_pn03 = qty_rd01 * 2
    
    sku_mancanti = {
        TipoProdotto.FL_01: min_fl01 + _rng.randint(20, 50),
        TipoProdotto.PN_03: min_pn03 + _rng.randint(20, 50),        
        TipoProdotto.IN_07: _rng.randint(100, 160),         
        TipoProdotto.RD_01: qty_rd01
    }
    
    return sku_mancanti

def genera_configurazione_stocastica(rng=None) -> ConfigurazioneSimulazione:
    _rng = rng if rng else random
    
    costo_macchine = {m: _rng.uniform(15.0, 30.0) for m in TipoMacchinario}
    costo_operatori = {
        TipoOperatore.GENERICO: _rng.uniform(20.0, 30.0),
        TipoOperatore.SPECIALIZZATO: _rng.uniform(35.0, 50.0)
    }

    tempi_proc = {}
    for m in TipoMacchinario:
        tempi_proc[m] = {}
        for p in TipoProdotto:
            tempi_proc[m][p] = _rng.randint(10, 40)

    # Definizione capacita' stocastiche
    capacita = {}
    for m in TipoMacchinario:
        capacita[m] = _rng.randint(2, 4)
    
    capacita[TipoOperatore.GENERICO] = _rng.randint(6, 10)
    capacita[TipoOperatore.SPECIALIZZATO] = _rng.randint(3, 5)

    distinta = {TipoProdotto.RD_01: {TipoProdotto.FL_01: 1, TipoProdotto.PN_03: 2}}

    # Generazione casuale dei limiti giornalieri
    limiti_prod_giornalieri = {
        TipoProdotto.FL_01: _rng.randint(50, 100),
        TipoProdotto.PN_03: _rng.randint(50, 100),
        TipoProdotto.IN_07: _rng.randint(50, 100),
        TipoProdotto.RD_01: _rng.randint(50, 100)
    }
    
    limite_totale_giornaliero = _rng.randint(300, 600)

    return ConfigurazioneSimulazione(
        tempi_lavorazione=tempi_proc,
        capacita=capacita,
        probabilita_rifacimento=0.02,
        richiede_specialista=True,
        distinta_base=distinta,
        prezzi_prodotti={p: 150.0 for p in TipoProdotto},
        costo_orario_macchinari=costo_macchine,
        costo_orario_operatori=costo_operatori,
        penale_al_minuto=0.003,
        limiti_produzione_giornaliera=limiti_prod_giornalieri,
        limite_produzione_totale_giornaliera=limite_totale_giornaliero
    )
