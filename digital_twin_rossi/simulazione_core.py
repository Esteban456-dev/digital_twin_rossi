import simpy
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Generator

from configurazione import (
    TipoMacchinario, TipoOperatore, TipoProdotto, PoliticaSchedulazione,
    ConfigurazioneSimulazione
)

MINUTI_GIORNALIERI = 1440

class GestoreTempo:
    """
    Servizio per la gestione della dimensione temporale della simulazione.
    Converte il tempo discreto della simulazione (minuti) in datetime reali.
    """
    def __init__(self, data_inizio: datetime):
        self.data_inizio = data_inizio

    def ottieni_data_corrente(self, minuti_simulazione: float) -> datetime:
        return self.data_inizio + timedelta(minutes=minuti_simulazione)

    def is_fine_settimana(self, minuti_simulazione: float) -> bool:
        dt = self.ottieni_data_corrente(minuti_simulazione)
        # 5 = Sabato, 6 = Domenica
        return dt.weekday() >= 5

    def ottieni_ora(self, minuti_simulazione: float) -> int:
        dt = self.ottieni_data_corrente(minuti_simulazione)
        return dt.hour

    def calcola_data_consegna(self, minuti_trascorsi: float) -> str:
        """
        Restituisce la data e ora reale simulata formattata come stringa.
        """
        dt = self.ottieni_data_corrente(minuti_trascorsi)
        days_names = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
        day_name = days_names[dt.weekday()]
        return f"{day_name} {dt.strftime('%d/%m/%Y %H:%M')}"

    def calcola_giorni_lavorativi(self, minuti_trascorsi: float, durata_turno_minuti: float) -> float:
        """
        Calcola i giorni lavorativi netti basandosi sulla durata effettiva del turno.
        """
        if durata_turno_minuti <= 0:
            return 0.0
        return minuti_trascorsi / durata_turno_minuti

class GestoreTurni:
    """
    Modulo responsabile della definizione dei calendari operativi e della disponibilità temporale delle risorse.
    Attualmente implementa un modello a ciclo continuo (24/7) semplificato per l'analisi teorica.
    """
    def __init__(self, ambiente: simpy.Environment, gestore_tempo: Optional[GestoreTempo] = None):
        self.ambiente = ambiente
        self.gestore_tempo = gestore_tempo
        
    def attendi_turno_lavorativo(self, configurazione):
        """
        Genera eventi di timeout se il sistema è fuori dall'orario lavorativo o nel weekend.
        Blocca il processo chiamante fino alla riapertura dell'impianto.
        """
        while True:
            if self.gestore_tempo:
                dt_corrente = self.gestore_tempo.ottieni_data_corrente(self.ambiente.now)
                giorno_settimana = dt_corrente.weekday() # 0=Lun, 5=Sab, 6=Dom
                
                if giorno_settimana >= 5: # Sabato o Domenica
                    giorni_al_lunedi = 7 - giorno_settimana
                    
                    minuti_a_mezzanotte = ((24 - dt_corrente.hour - 1) * 60) + (60 - dt_corrente.minute)
                    
                    giorni_interi_da_saltare = giorni_al_lunedi - 1
                    
                    minuti_apertura_lunedi = configurazione.orario_inizio_turno * 60
                    
                    tempo_attesa_weekend = minuti_a_mezzanotte + (giorni_interi_da_saltare * 24 * 60) + minuti_apertura_lunedi

                    if tempo_attesa_weekend <= 0.1:
                        tempo_attesa_weekend = 1.0 # Minimo 1 minuto di attesa per sbloccare il loop
                    
                    yield self.ambiente.timeout(tempo_attesa_weekend + 0.1)
                    continue 

            minuti_totali_simulazione = int(round(self.ambiente.now))
            minuti_giornalieri = minuti_totali_simulazione % MINUTI_GIORNALIERI
            
            minuti_inizio = int(configurazione.orario_inizio_turno * 60)
            minuti_fine = int(configurazione.orario_fine_turno * 60)
            
            if minuti_giornalieri >= minuti_fine:
                minuti_a_mezzanotte = MINUTI_GIORNALIERI - minuti_giornalieri
                tempo_attesa = minuti_a_mezzanotte + minuti_inizio
                
                if tempo_attesa <= 0: tempo_attesa = 1
                yield self.ambiente.timeout(tempo_attesa)

            elif minuti_giornalieri < minuti_inizio:
                tempo_attesa = minuti_inizio - minuti_giornalieri
                
                if tempo_attesa <= 0: tempo_attesa = 1
                yield self.ambiente.timeout(tempo_attesa)
            else:
                break

    def avanza_tempo_lavorativo(self, durata_minuti, configurazione):
        """
        Consuma 'durata_minuti' rispettando gli orari di lavoro.
        Se il tempo richiesto supera la fine del turno, attende la riapertura.
        """
        while durata_minuti > 1e-6: # Tolleranza float
            yield from self.attendi_turno_lavorativo(configurazione)

            minuti_giornalieri = self.ambiente.now % MINUTI_GIORNALIERI
            minuti_fine_turno = configurazione.orario_fine_turno * 60
            
            tempo_residuo_turno = minuti_fine_turno - minuti_giornalieri
            
            if tempo_residuo_turno <= 1e-6:
                yield from self.attendi_turno_lavorativo(configurazione)
                continue

            dt = min(durata_minuti, tempo_residuo_turno)
            
            yield self.ambiente.timeout(dt)
            durata_minuti -= dt

class RisorsaProduttiva:
    """
    Classe astratta che modella una generica risorsa a capacità finita (Macchina o Operatore).
    Gestisce la coda di richieste (FIFO) e le metriche di utilizzo.
    """
    def __init__(self, ambiente: simpy.Environment, nome: str, capacita: int = 1):
        if capacita < 1:
            raise ValueError(f"La capacità della risorsa {nome} deve essere positiva, rilevato {capacita}")
        self.ambiente = ambiente
        self.nome = nome
        self.risorsa_simpy = simpy.PriorityResource(ambiente, capacity=capacita)
        
        # Contatori specifici per OEE e analisi tempi
        self.tempo_occupato_totale = 0.0 
        self.tempo_lavorazione = 0.0     
        self.tempo_setup = 0.0           
        self.tempo_guasto = 0.0          
        
        self.log_eventi = [] 
        
    def richiedi_accesso(self, priorita: int = 0):
        """Genera una richiesta di acquisizione della risorsa con un determinato livello di priorità."""
        return self.risorsa_simpy.request(priority=priorita)

    def registra_tempo_utilizzo(self, durata: float, tipo: str = 'lavorazione'):
        """Aggiorna i contatori del tempo operativo effettivo."""
        self.tempo_occupato_totale += durata
        
        if tipo == 'lavorazione':
            self.tempo_lavorazione += durata
        elif tipo == 'setup':
            self.tempo_setup += durata
        elif tipo == 'guasto':
            self.tempo_guasto += durata

    def calcola_tasso_utilizzo(self, orizzonte_temporale: float) -> float:
        """
        Calcola il tasso di saturazione NETTA della risorsa.
        Considera solo il tempo in cui la macchina è impegnata in attività produttive (Lavorazione + Setup).
        I guasti NON contribuiscono all'utilizzo produttivo.
        """
        if orizzonte_temporale == 0:
            return 0.0
            
        capacita_totale = self.risorsa_simpy.capacity
        if capacita_totale == 0:
            return 0.0
            
        disponibilita_teorica = orizzonte_temporale * capacita_totale
        
        # Utilizzo Produttivo = (Lavorazione + Setup) / Disponibilità
        tempo_produttivo = self.tempo_lavorazione + self.tempo_setup
        
        return (tempo_produttivo / disponibilita_teorica) * 100

class Macchinario(RisorsaProduttiva):
    """Rappresentazione digitale di un asset fisico (macchina utensile)."""
    def __init__(self, ambiente, nome, capacita=1):
        super().__init__(ambiente, nome, capacita)

class Operatore(RisorsaProduttiva):
    """Rappresentazione digitale di una risorsa umana."""
    def __init__(self, ambiente, nome, competenze, tipo_turno="standard", capacita=1):
        super().__init__(ambiente, nome, capacita=capacita)
        self.competenze = competenze
        self.tipo_turno = tipo_turno 

@dataclass
class Prodotto:
    """Entità che rappresenta l'articolo oggetto del processo produttivo."""
    id: str
    nome: str

@dataclass
class OrdineDiLavoro:
    """
    Entità che traccia il flusso di un lotto di produzione attraverso il sistema.
    Include timestamp per la tracciabilità temporale.
    """
    id: str
    prodotto: Prodotto
    tempo_creazione: float
    scadenza: float
    tempo_completamento: Optional[float] = None
    cronologia_fasi: List[str] = field(default_factory=list)
    log_lavorazioni: List[dict] = field(default_factory=list)
    consumato: bool = False
    componenti_consumati: List['OrdineDiLavoro'] = field(default_factory=list)

    @property
    def tempo_attraversamento(self) -> Optional[float]:
        """Calcola il Lead Time effettivo."""
        if self.tempo_completamento:
            return self.tempo_completamento - self.tempo_creazione
        return None

    def traccia_fase(self, descrizione_fase: str):
        """Aggiunge un evento alla cronologia di produzione."""
        self.cronologia_fasi.append(descrizione_fase)

class MotoreSimulazione:
    """
    Motore della simulazione a eventi discreti.
    Orchestra l'avanzamento temporale e l'esecuzione dei processi.
    """
    def __init__(self, durata_giorni: int = 7, seme_casuale: Optional[int] = None):
        self.ambiente = simpy.Environment()
        self.durata_giorni = durata_giorni
        self.durata_minuti = durata_giorni * MINUTI_GIORNALIERI
        self.logger = logging.getLogger("MotoreSimulazione")
        
        if seme_casuale is not None:
            self.rng = random.Random(seme_casuale)
        else:
            self.rng = random.Random()

    def avvia_simulazione(self):
        """Esegue il loop di simulazione fino all'orizzonte temporale definito."""
        self.logger.info(f"Inizializzazione run di simulazione: orizzonte {self.durata_giorni} giorni ({self.durata_minuti} min)")
        self.ambiente.run(until=self.durata_minuti)
        self.logger.info("Run di simulazione terminato.")

    @property
    def tempo_corrente(self) -> float:
        return self.ambiente.now

class StrategiaProcessoBase:
    """
    Classe base astratta per la definizione dei Cicli di Lavorazione.
    Implementa il pattern Strategy per disaccoppiare la logica di processo dal prodotto.
    """
    def esegui_processo(self, ordine: OrdineDiLavoro, sistema_produttivo: 'SistemaProduttivo'):
        raise NotImplementedError("Metodo astratto: deve essere implementato dalle sottoclassi.")

    def stima_tempo_ciclo(self, configurazione: ConfigurazioneSimulazione) -> float:
        return 0.0

    def _gestisci_rilavorazione(self, sistema_produttivo: 'SistemaProduttivo', ordine: OrdineDiLavoro):
        """
        Gestisce la logica stocastica di Rilavorazione per non conformità di qualità.
        """
        tempi = sistema_produttivo.configurazione.tempi_lavorazione
        if sistema_produttivo.rng.random() < sistema_produttivo.configurazione.probabilita_rifacimento:
            yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.RETTIFICA, tempi[TipoMacchinario.RETTIFICA][ordine.prodotto.id], TipoOperatore.GENERICO)
            yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.BANCO_CONTROLLO, tempi[TipoMacchinario.BANCO_CONTROLLO][ordine.prodotto.id], TipoOperatore.GENERICO)

class StrategiaFL01(StrategiaProcessoBase):
    """Routing Sheet per il prodotto FL-01 (Flangia)."""
    def esegui_processo(self, ordine, sistema_produttivo):
        tempi = sistema_produttivo.configurazione.tempi_lavorazione
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.TRONCATRICE, tempi[TipoMacchinario.TRONCATRICE][TipoProdotto.FL_01], TipoOperatore.GENERICO)
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.TRAPANO, tempi[TipoMacchinario.TRAPANO][TipoProdotto.FL_01], TipoOperatore.GENERICO)
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.BANCO_CONTROLLO, tempi[TipoMacchinario.BANCO_CONTROLLO][TipoProdotto.FL_01], TipoOperatore.GENERICO)
        
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.BANCO_CONTROLLO, tempi[TipoMacchinario.BANCO_CONTROLLO][TipoProdotto.FL_01], TipoOperatore.GENERICO)
        
        if TipoProdotto.FL_01 in sistema_produttivo.buffer_scorte:
            store = sistema_produttivo.buffer_scorte[TipoProdotto.FL_01]
            yield store.put(ordine)
            livello = len(store.items)
            sistema_produttivo.logger.info(f"MAGAZZINO: Deposita {ordine.id} (Totale FL-01: {livello})")
        
        if TipoProdotto.FL_01 in sistema_produttivo.magazzino_intermedio:
             yield sistema_produttivo.magazzino_intermedio[TipoProdotto.FL_01].put(ordine)

        ordine.tempo_completamento = sistema_produttivo.ambiente.now
        sistema_produttivo.logger.info(f"WO completato: {ordine.id} @ t={sistema_produttivo.ambiente.now}")

    def stima_tempo_ciclo(self, configurazione):
        tempi = configurazione.tempi_lavorazione
        return tempi[TipoMacchinario.TRONCATRICE][TipoProdotto.FL_01] + tempi[TipoMacchinario.TRAPANO][TipoProdotto.FL_01] + tempi[TipoMacchinario.BANCO_CONTROLLO][TipoProdotto.FL_01]

class StrategiaPN03(StrategiaProcessoBase):
    """Routing Sheet per il prodotto PN-03 (Perno)."""
    def esegui_processo(self, ordine, sistema_produttivo):
        tempi = sistema_produttivo.configurazione.tempi_lavorazione
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.TRONCATRICE, tempi[TipoMacchinario.TRONCATRICE][TipoProdotto.PN_03], TipoOperatore.GENERICO)
        
        richiede_specialista = sistema_produttivo.configurazione.richiede_specialista
        tipo_operatore = TipoOperatore.SPECIALIZZATO if richiede_specialista else TipoOperatore.GENERICO
        
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.TORNIO, tempi[TipoMacchinario.TORNIO][TipoProdotto.PN_03], tipo_operatore, vincolo_specialista=richiede_specialista)
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.RETTIFICA, tempi[TipoMacchinario.RETTIFICA][TipoProdotto.PN_03], TipoOperatore.GENERICO)
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.BANCO_CONTROLLO, tempi[TipoMacchinario.BANCO_CONTROLLO][TipoProdotto.PN_03], TipoOperatore.GENERICO)
        
        yield from self._gestisci_rilavorazione(sistema_produttivo, ordine)
        yield from self._gestisci_rilavorazione(sistema_produttivo, ordine)

        if TipoProdotto.PN_03 in sistema_produttivo.buffer_scorte:
            store = sistema_produttivo.buffer_scorte[TipoProdotto.PN_03]
            yield store.put(ordine)
            livello = len(store.items)
            sistema_produttivo.logger.info(f"MAGAZZINO: Deposita {ordine.id} (Totale PN-03: {livello})")
        
        ordine.tempo_completamento = sistema_produttivo.ambiente.now
        sistema_produttivo.logger.info(f"WO completato: {ordine.id} @ t={sistema_produttivo.ambiente.now}")

    def stima_tempo_ciclo(self, configurazione):
        tempi = configurazione.tempi_lavorazione
        return tempi[TipoMacchinario.TRONCATRICE][TipoProdotto.PN_03] + tempi[TipoMacchinario.TORNIO][TipoProdotto.PN_03] + tempi[TipoMacchinario.RETTIFICA][TipoProdotto.PN_03] + tempi[TipoMacchinario.BANCO_CONTROLLO][TipoProdotto.PN_03]

class StrategiaIN07(StrategiaProcessoBase):
    """Routing Sheet per il prodotto IN-07 (Ingranaggio)."""
    def esegui_processo(self, ordine, sistema_produttivo):
        tempi = sistema_produttivo.configurazione.tempi_lavorazione
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.TRONCATRICE, tempi[TipoMacchinario.TRONCATRICE][TipoProdotto.IN_07], TipoOperatore.GENERICO)
        
        richiede_specialista = sistema_produttivo.configurazione.richiede_specialista
        tipo_operatore = TipoOperatore.SPECIALIZZATO if richiede_specialista else TipoOperatore.GENERICO
        
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.FRESA, tempi[TipoMacchinario.FRESA][TipoProdotto.IN_07], tipo_operatore, vincolo_specialista=richiede_specialista)
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.RETTIFICA, tempi[TipoMacchinario.RETTIFICA][TipoProdotto.IN_07], TipoOperatore.GENERICO)
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.FORNO, tempi[TipoMacchinario.FORNO][TipoProdotto.IN_07], TipoOperatore.GENERICO)
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.BANCO_CONTROLLO, tempi[TipoMacchinario.BANCO_CONTROLLO][TipoProdotto.IN_07], TipoOperatore.GENERICO)
        
        yield from self._gestisci_rilavorazione(sistema_produttivo, ordine)
        yield from self._gestisci_rilavorazione(sistema_produttivo, ordine)

        if TipoProdotto.IN_07 in sistema_produttivo.buffer_scorte:
            store = sistema_produttivo.buffer_scorte[TipoProdotto.IN_07]
            yield store.put(ordine)
            livello = len(store.items)
            sistema_produttivo.logger.info(f"MAGAZZINO: Deposita {ordine.id} (Totale IN-07: {livello})")
        
        if TipoProdotto.IN_07 in sistema_produttivo.magazzino_intermedio:
             yield sistema_produttivo.magazzino_intermedio[TipoProdotto.IN_07].put(ordine)

        ordine.tempo_completamento = sistema_produttivo.ambiente.now
        sistema_produttivo.logger.info(f"WO completato: {ordine.id} @ t={sistema_produttivo.ambiente.now}")

    def stima_tempo_ciclo(self, configurazione):
        tempi = configurazione.tempi_lavorazione
        return tempi[TipoMacchinario.TRONCATRICE][TipoProdotto.IN_07] + tempi[TipoMacchinario.FRESA][TipoProdotto.IN_07] + tempi[TipoMacchinario.RETTIFICA][TipoProdotto.IN_07] + tempi[TipoMacchinario.FORNO][TipoProdotto.IN_07] + tempi[TipoMacchinario.BANCO_CONTROLLO][TipoProdotto.IN_07]

class StrategiaRD01(StrategiaProcessoBase):
    """Routing Sheet per il prodotto RD-01 (Riduttore), che richiede assemblaggio."""
    def esegui_processo(self, ordine, sistema_produttivo):
        tempi = sistema_produttivo.configurazione.tempi_lavorazione
        
        if hasattr(sistema_produttivo, 'magazzino_intermedio'):
            sistema_produttivo.logger.info(f"ASSEMBLAGGIO: Richiesta materiali al Magazzino Intermedio per {ordine.id}...")
            
            if TipoProdotto.FL_01 in sistema_produttivo.magazzino_intermedio:
                # Prelievo Flangia reale
                comp_fl = yield sistema_produttivo.magazzino_intermedio[TipoProdotto.FL_01].get()
                ordine.componenti_consumati.append(comp_fl)
            
            if TipoProdotto.IN_07 in sistema_produttivo.magazzino_intermedio:
                # Prelievo Ingranaggi reali (2 unità)
                comp_in_1 = yield sistema_produttivo.magazzino_intermedio[TipoProdotto.IN_07].get()
                ordine.componenti_consumati.append(comp_in_1)
                
                comp_in_2 = yield sistema_produttivo.magazzino_intermedio[TipoProdotto.IN_07].get()
                ordine.componenti_consumati.append(comp_in_2)
                
            sistema_produttivo.logger.info(f"ASSEMBLAGGIO: Materiali prelevati dal Magazzino Intermedio.")

        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.BANCO_ASSEMBLAGGIO, tempi[TipoMacchinario.BANCO_ASSEMBLAGGIO][TipoProdotto.RD_01], TipoOperatore.GENERICO)
        yield from sistema_produttivo.esegui_operazione(ordine, TipoMacchinario.BANCO_COLLAUDO, tempi[TipoMacchinario.BANCO_COLLAUDO][TipoProdotto.RD_01], TipoOperatore.GENERICO)
        
        ordine.tempo_completamento = sistema_produttivo.ambiente.now
        sistema_produttivo.logger.info(f"WO completato: {ordine.id} @ t={sistema_produttivo.ambiente.now}")

    def stima_tempo_ciclo(self, configurazione):
        tempi = configurazione.tempi_lavorazione
        return tempi[TipoMacchinario.BANCO_ASSEMBLAGGIO][TipoProdotto.RD_01] + tempi[TipoMacchinario.BANCO_COLLAUDO][TipoProdotto.RD_01]

class SistemaProduttivo:
    """
    Classe principale che modella l'intero sistema di produzione.
    Gestisce l'allocazione delle risorse, i flussi di materiale e i vincoli operativi.
    """
    def __init__(self, ambiente, gestore_turni, strategie, configurazione, rng, politica=PoliticaSchedulazione.FIFO, nome_scenario="Base"):
        self.ambiente = ambiente
        self.gestore_turni = gestore_turni
        self.strategie = strategie
        self.configurazione = configurazione
        self.rng = rng # Generatore Random Isolato
        self.politica = politica
        self.scenario = nome_scenario
        self.logger = logging.getLogger("SistemaProduttivo")
        
        self.macchinari = {}
        self.operatori = {}
        
        self.buffer_scorte = {}
        for prod in TipoProdotto:
            self.buffer_scorte[prod] = simpy.Store(ambiente)

        self.magazzino_intermedio = {
            TipoProdotto.FL_01: simpy.Store(ambiente),
            TipoProdotto.IN_07: simpy.Store(ambiente)
        }
        
        quantita_iniziali = {
            TipoProdotto.FL_01: 20,
            TipoProdotto.IN_07: 40
        }
        
        for tipo_prod, qta in quantita_iniziali.items():
            store = self.magazzino_intermedio[tipo_prod]
            for i in range(qta):
                dummy_prod = Prodotto(id=tipo_prod.value, nome=tipo_prod.name)
                dummy_order = OrdineDiLavoro(
                    id=f"STOCK-INIT-{tipo_prod.value}-{i}",
                    prodotto=dummy_prod,
                    tempo_creazione=0.0,
                    scadenza=0.0,
                    tempo_completamento=0.0
                )
                store.put(dummy_order)
        
        # Monitoraggio produzione giornaliera
        self.giorno_corrente = 0
        self.produzione_giornaliera_per_prodotto = {}
        self.produzione_giornaliera_totale = 0
        
        self._inizializza_asset()
        
        if self.configurazione.livelli_scorta_minima:
             self.ambiente.process(self.monitor_scorte())

    def monitor_scorte(self):
        """
        Monitora i livelli di scorta e innesca il riordino.
        """
        while True:
            yield self.ambiente.timeout(60)
            
            rop_levels = self.configurazione.livelli_scorta_minima or {}
            eoq_quantities = self.configurazione.lotto_riordino_standard or {}
            
            for prod_type, store in self.buffer_scorte.items():
                rop = rop_levels.get(prod_type)
                
                # Se non è definito un ROP, non gestisco in automatico
                if rop is None:
                    continue
                    
                current_level = len(store.items)
                
                if current_level < rop:
                    qty_to_order = eoq_quantities.get(prod_type, 10) # Default EOQ 10 se mancante
                    
                    self.logger.info(f"MONITOR SCORTE: Scorta bassa per {prod_type.value} ({current_level} < {rop}). Genero {qty_to_order} ordini.")
                    
                    # Generazione ordini di rifornimento
                    for i in range(int(qty_to_order)):
                        # Genero un ID univoco per il riordino
                        new_id = f"R-ORD-{prod_type.value}-{self.ambiente.now:.0f}-{i}"
                        
                        # Creo l'oggetto Prodotto (necessario per l'ordine)
                        prodotto_obj = Prodotto(id=prod_type.value, nome=prod_type.name)
                        
                        nuovo_ordine = OrdineDiLavoro(
                            id=new_id,
                            prodotto=prodotto_obj,
                            tempo_creazione=self.ambiente.now,
                            scadenza=self.ambiente.now + 2880
                        )
                        
                        self.ambiente.process(self.elabora_ordine(nuovo_ordine))

    def _inizializza_asset(self):
        """Istanzia le risorse produttive in base alla configurazione."""
        caps = self.configurazione.capacita
        
        for tipo_macchina in TipoMacchinario:
            capacita = caps.get(tipo_macchina, 1)
            self.macchinari[tipo_macchina] = Macchinario(self.ambiente, tipo_macchina, capacita)
            
        for tipo_operatore in TipoOperatore:
            capacita = caps.get(tipo_operatore, 1)
            self.operatori[tipo_operatore] = Operatore(self.ambiente, tipo_operatore, [], capacita=capacita)

    def esegui_operazione(self, ordine, nome_macchina, durata_min, tipo_operatore=None, vincolo_specialista=False):
        """
        Esegue un'operazione atomica di lavorazione.
        Gestisce l'acquisizione delle risorse e il ritardo temporale.
        """
        try:
            macchina = self.macchinari[nome_macchina]
        except KeyError:
            raise ValueError(f"Asset {nome_macchina} non presente nel layout")
        
        if nome_macchina not in self.configurazione.tempi_lavorazione:
             self.logger.warning(f"Configurazione tempi mancante per {nome_macchina}. Uso default.")
             pass
        
        priorita = 0
        
        yield from self.gestore_turni.attendi_turno_lavorativo(self.configurazione)

        if self.politica == PoliticaSchedulazione.SPT: 
            priorita = int(durata_min)
        elif self.politica == PoliticaSchedulazione.EDD:
            if ordine.scadenza:
                priorita = int(ordine.scadenza)
            else:
                priorita = 0
            
        with macchina.richiedi_accesso(priorita=priorita) as req_macchina:
            yield req_macchina
            
            ultimo_prodotto = getattr(macchina, 'ultimo_prodotto', None)
            if ultimo_prodotto is not None and ultimo_prodotto != ordine.prodotto.id:
                tempo_setup = self.configurazione.tempo_setup_minuti
                if tempo_setup > 0:
                    yield self.ambiente.timeout(tempo_setup)
                    macchina.registra_tempo_utilizzo(tempo_setup, tipo='setup')
                    macchina.log_eventi.append({
                        'tipo': 'setup',
                        'inizio': self.ambiente.now - tempo_setup,
                        'fine': self.ambiente.now,
                        'descrizione': 'Setup'
                    })
            macchina.ultimo_prodotto = ordine.prodotto.id
            
            yield from self.gestore_turni.attendi_turno_lavorativo(self.configurazione)

            # LOGICA GUASTI
            if self.rng.random() < self.configurazione.probabilita_guasto:
                min_rip = self.configurazione.minuti_riparazione_min
                max_rip = self.configurazione.minuti_riparazione_max
                tempo_riparazione = self.rng.randint(min_rip, max_rip) 
                print(f"!!! GUASTO MACCHINA: {nome_macchina} ferma per {tempo_riparazione} min @ t={self.ambiente.now:.1f} !!!")
                yield from self.gestore_turni.avanza_tempo_lavorativo(tempo_riparazione, self.configurazione)
                
                # Registro il tempo di guasto separatamente
                macchina.registra_tempo_utilizzo(tempo_riparazione, tipo='guasto')
                macchina.log_eventi.append({
                    'tipo': 'guasto',
                    'inizio': self.ambiente.now - tempo_riparazione,
                    'fine': self.ambiente.now,
                    'descrizione': 'Guasto'
                })

            if tipo_operatore:
                if vincolo_specialista and tipo_operatore != TipoOperatore.SPECIALIZZATO:
                    tipo_operatore = TipoOperatore.SPECIALIZZATO

                try:
                    operatore = self.operatori[tipo_operatore]
                except KeyError:
                    raise ValueError(f"Risorsa umana {tipo_operatore} non disponibile")
                
                with operatore.richiedi_accesso(priorita=priorita) as req_operatore:
                    yield req_operatore
                    
                    yield from self.gestore_turni.attendi_turno_lavorativo(self.configurazione)
                    
                    # Calcolo Tempo Stocastico
                    variabilita = self.configurazione.fattore_variabilita_processo
                    durata_effettiva = max(0.001, durata_min * self.rng.uniform(1.0 - variabilita, 1.0 + variabilita))
                    
                    # Esecuzione Lavorazione
                    yield self.ambiente.timeout(durata_effettiva)
                    
                    operatore.registra_tempo_utilizzo(durata_effettiva, tipo='lavorazione')
                    macchina.registra_tempo_utilizzo(durata_effettiva, tipo='lavorazione')
            else:
                variabilita = self.configurazione.fattore_variabilita_processo
                durata_effettiva = max(0.001, durata_min * self.rng.uniform(1.0 - variabilita, 1.0 + variabilita))
                
                yield self.ambiente.timeout(durata_effettiva)
                macchina.registra_tempo_utilizzo(durata_effettiva, tipo='lavorazione')
                
            macchina.log_eventi.append({
                'tipo': 'lavorazione',
                'inizio': self.ambiente.now - durata_effettiva,
                'fine': self.ambiente.now,
                'ordine': ordine.id,
                'descrizione': f"Lavorazione {ordine.id}"
            })
                
            ordine.traccia_fase(nome_macchina)
            ordine.log_lavorazioni.append({
                'fase': nome_macchina,
                'durata': durata_effettiva,
                'operatore': tipo_operatore,
                'inizio': self.ambiente.now - durata_effettiva,
                'fine': self.ambiente.now
            })
                
        self.logger.debug(f"Fase completata: {ordine.id} su {nome_macchina} @ t={self.ambiente.now}")

    def elabora_ordine(self, ordine):
        """
        Gestisce il ciclo di vita di un Ordine di Lavoro all'interno del sistema.
        Verifica i vincoli di capacità giornaliera prima di avviare il processo.
        """
        self.logger.info(f"WO Generato: {ordine.id} @ t={self.ambiente.now}")
        
        id_prodotto = ordine.prodotto.id
        
        has_limits = (self.configurazione.limiti_produzione_giornaliera is not None) or \
                     (self.configurazione.limite_produzione_totale_giornaliera is not None)

        if has_limits:
            while True:
                giorno_simulazione = int(self.ambiente.now / MINUTI_GIORNALIERI)
                if giorno_simulazione > self.giorno_corrente:
                    self.giorno_corrente = giorno_simulazione
                    self.produzione_giornaliera_per_prodotto = {} 
                    self.produzione_giornaliera_totale = 0
                    self.logger.info(f"Day {self.giorno_corrente}: Reset contatori produzione.")

                limiti_prodotti = self.configurazione.limiti_produzione_giornaliera or {}
                limite_prodotto = limiti_prodotti.get(id_prodotto, float('inf'))
                
                limite_totale = self.configurazione.limite_produzione_totale_giornaliera
                if limite_totale is None:
                    limite_totale = float('inf')
                
                prodotti_oggi = self.produzione_giornaliera_per_prodotto.get(id_prodotto, 0)
                
                # Controllo se ho raggiunto il limite per il singolo prodotto o il limite totale della fabbrica
                if prodotti_oggi >= limite_prodotto or self.produzione_giornaliera_totale >= limite_totale:
                    # Capacità esaurita per oggi. Calcolo quanto tempo manca alla riapertura domani mattina.
                    minuti_giornalieri = self.ambiente.now % MINUTI_GIORNALIERI
                    tempo_fine_giornata = MINUTI_GIORNALIERI - minuti_giornalieri # Minuti mancanti alla mezzanotte
                    tempo_apertura_domani = self.configurazione.orario_inizio_turno * 60 # Minuti dalla mezzanotte all'apertura
                    
                    tempo_attesa = tempo_fine_giornata + tempo_apertura_domani
                    
                    self.logger.info(f"Capacità giornaliera saturata per {ordine.id}. Attesa turno successivo ({tempo_attesa:.1f} min).")
                    # Metto in attesa il processo fino al prossimo turno disponibile
                    yield self.ambiente.timeout(tempo_attesa)
                else:
                    self.produzione_giornaliera_per_prodotto[id_prodotto] = prodotti_oggi + 1
                    self.produzione_giornaliera_totale += 1
                    break

        strategia = self.strategie.get(id_prodotto)
        if not strategia:
            raise ValueError(f"Routing Sheet non definita per {id_prodotto}")
            
        yield from strategia.esegui_processo(ordine, self)

class GestoreEconomico:
    """
    Modulo di contabilità industriale per il calcolo dei costi, ricavi e margini.
    """
    def __init__(self, configurazione):
        self.configurazione = configurazione
        self.prezzi = self.configurazione.prezzi_prodotti
        self.penale_al_minuto = self.configurazione.penale_al_minuto
        self.costo_macchinari = self.configurazione.costo_orario_macchinari or {}
        self.costo_operatori = self.configurazione.costo_orario_operatori or {}
        self.tempi_lavorazione = self.configurazione.tempi_lavorazione

    def calcola_ricavo_effettivo(self, id_prodotto, tempo_completamento, scadenza):
        """Calcola il ricavo netto applicando eventuali penali per ritardo."""
        if tempo_completamento is None:
            return 0.0
            
        prezzo_base = self.prezzi.get(id_prodotto, 0.0)
        
        ritardo = max(0, tempo_completamento - scadenza)
        penale = ritardo * self.penale_al_minuto
        
        return max(0.0, prezzo_base - penale)

    def calcola_margine_contribuzione(self, ordine, strategia=None):
        """
        Calcola il Margine di Contribuzione dell'ordine.
        Margine = Prezzo di Vendita - Costi Variabili Diretti (Manodopera + Macchina)
        """
        tipo_prodotto = ordine.prodotto.id
        prezzo_vendita = self.prezzi.get(tipo_prodotto, 0.0)
        
        costo_totale = 0.0
        
        if ordine.log_lavorazioni:
            for lavorazione in ordine.log_lavorazioni:
                tempo_ore = lavorazione['durata'] / 60.0
                costo_macchina = self.costo_macchinari.get(lavorazione['fase'], 0.0)
                costo_operatore = self.costo_operatori.get(lavorazione['operatore'], 0.0) if lavorazione['operatore'] else 0.0
                
                costo_fase = tempo_ore * (costo_macchina + costo_operatore)
                costo_totale += costo_fase
        else:
            for macchina in ordine.cronologia_fasi:
                tempi_macchina = self.tempi_lavorazione.get(macchina, {})
                if isinstance(tempi_macchina, dict):
                    tempo_minuti = tempi_macchina.get(tipo_prodotto, 0)
                else:
                    tempo_minuti = tempi_macchina
                    
                tempo_ore = tempo_minuti / 60.0
                
                costo_macchina = self.costo_macchinari.get(macchina, 0.0)
                
                tipo_operatore = TipoOperatore.GENERICO
                if macchina in [TipoMacchinario.RETTIFICA, TipoMacchinario.BANCO_COLLAUDO]:
                     tipo_operatore = TipoOperatore.SPECIALIZZATO
                
                costo_operatore = self.costo_operatori.get(tipo_operatore, 0.0)
                
                costo_fase = tempo_ore * (costo_macchina + costo_operatore)
                costo_totale += costo_fase
        
        if hasattr(ordine, 'componenti_consumati') and ordine.componenti_consumati:
            for componente in ordine.componenti_consumati:
                margine_comp = self.calcola_margine_contribuzione(componente)
                prezzo_comp = self.prezzi.get(componente.prodotto.id, 0.0)
                costo_produzione_comp = prezzo_comp - margine_comp
                
                costo_totale += costo_produzione_comp
            
        return prezzo_vendita - costo_totale
