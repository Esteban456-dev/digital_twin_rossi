import logging
import random
import simpy
import copy
from datetime import datetime

from configurazione import (
    ConfigurazioneSimulazione, 
    TipoProdotto, PoliticaSchedulazione, TipoMacchinario, TipoOperatore,
    genera_quantita_lotto_stocastico, genera_configurazione_stocastica
)
from simulazione_core import (
    MotoreSimulazione, GestoreTempo, GestoreTurni, SistemaProduttivo, GestoreEconomico, 
    OrdineDiLavoro, Prodotto
)
from infrastructure.reporting_service import AnalizzatorePrestazioni

class GestoreScenario:
    """
    Controller principale per l'orchestrazione degli scenari di simulazione.
    Coordina l'inizializzazione del motore, la configurazione del sistema produttivo e la raccolta dei KPI.
    """
    def __init__(self, strategie, configurazione, nome_scenario="Base", durata_giorni=5, seed=None, politica_schedulazione=PoliticaSchedulazione.FIFO):
        self.motore = MotoreSimulazione(durata_giorni, seme_casuale=seed)
        
        self.gestore_tempo = GestoreTempo(datetime(2024, 1, 1))
        self.gestore_turni = GestoreTurni(self.motore.ambiente, self.gestore_tempo)
        self.seme_casuale = seed
        self.nome_scenario = nome_scenario
        
        self.configurazione = copy.deepcopy(configurazione)
        
        if self.nome_scenario == "A":
            self.configurazione.capacita[TipoMacchinario.FRESA] = 2
        elif self.nome_scenario == "B":
            self.configurazione.capacita[TipoOperatore.SPECIALIZZATO] = 2
            self.configurazione.richiede_specialista = False
            
        self.sistema_produttivo = SistemaProduttivo(self.motore.ambiente, self.gestore_turni, strategie, self.configurazione, self.motore.rng, politica=politica_schedulazione, nome_scenario=self.nome_scenario)
        self.gestore_economico = GestoreEconomico(self.configurazione)
        self.analizzatore_prestazioni = AnalizzatorePrestazioni()
        self.quantita_target = None 
        self.ordini_completati = [] 

    def genera_domanda_stocastica(self, id_prodotto, intervallo_min, intervallo_max):
        """
        Generatore di arrivi casuali per simulare la domanda di mercato.
        Usa una distribuzione uniforme per l'intervallo tra gli arrivi.
        """
        ambiente = self.motore.ambiente
        while True:
            if self.quantita_target:
                completati_rd01 = len([wo for wo in self.ordini_completati if wo.prodotto.id == TipoProdotto.RD_01])
                if completati_rd01 >= self.quantita_target:
                    break
            
            yield ambiente.timeout(self.motore.rng.uniform(intervallo_min, intervallo_max))
            
            id_ordine = f"WO-{int(ambiente.now*100)}-{self.motore.rng.randint(1000,999)}"
            prodotto = Prodotto(id_prodotto, f"Prodotto {id_prodotto}")
            
            scadenza = ambiente.now + self.motore.rng.uniform(100, 300) 
            
            ordine = OrdineDiLavoro(id_ordine, prodotto, tempo_creazione=ambiente.now, scadenza=scadenza)
            
            ambiente.process(self._monitoraggio_processo(ordine))

    def _monitoraggio_processo(self, ordine):
        """Wrapper per il tracciamento del completamento degli ordini."""
        yield from self.sistema_produttivo.elabora_ordine(ordine)
        self.ordini_completati.append(ordine)

    def esegui_simulazione_standard(self):
        """Avvia una simulazione standard basata su generazione continua della domanda."""
        self.motore.ambiente.process(self.genera_domanda_stocastica(TipoProdotto.FL_01, 5, 15))
        self.motore.ambiente.process(self.genera_domanda_stocastica(TipoProdotto.PN_03, 5, 15))
        self.motore.ambiente.process(self.genera_domanda_stocastica(TipoProdotto.IN_07, 10, 20))
        self.motore.ambiente.process(self.genera_domanda_stocastica(TipoProdotto.RD_01, 15, 25))
        
        self.motore.avvia_simulazione()
        return self.elabora_report_finale()

    def _check_material_balance(self, quantita_pianificate):
        """
        Verifica preventivamente che il piano di produzione sia bilanciato.
        Controlla che per ogni prodotto assemblato ci siano sufficienti componenti pianificati,
        prevenendo deadlock per mancanza materiali.
        """
        distinta_base = self.configurazione.distinta_base or {}
        
        fabbisogno_componenti = {}

        for prodotto, qty_ordine in quantita_pianificate.items():
            if prodotto in distinta_base:
                componenti_richiesti = distinta_base[prodotto]
                for componente, qty_per_unit in componenti_richiesti.items():
                    fabbisogno_componenti[componente] = fabbisogno_componenti.get(componente, 0) + (qty_ordine * qty_per_unit)

        for componente, fabbisogno in fabbisogno_componenti.items():
            qty_pianificata = quantita_pianificate.get(componente, 0)
            
            stock_iniziale = 0
            if hasattr(self, 'sistema_produttivo') and self.sistema_produttivo:
                 magazzino = self.sistema_produttivo.magazzino_intermedio.get(componente)
                 if magazzino and hasattr(magazzino, 'items'):
                     stock_iniziale = len(magazzino.items)
            
            disponibilita_totale = qty_pianificata + stock_iniziale
            
            if disponibilita_totale < fabbisogno:
                raise ValueError(
                    f"CRITICAL PLANNING ERROR: Material Shortage Detected for '{componente}'. "
                    f"Required: {fabbisogno}, Planned+Stock: {disponibilita_totale} (Missing: {fabbisogno - disponibilita_totale}). "
                    f"Simulation aborted to prevent deadlock."
                )

    def esegui_lotto_stocastico(self, quantita_override=None, configurazione_override=None):
        """
        Esegue uno Stress Test del sistema produttivo utilizzando un lotto di ordini generato stocasticamente.
        Simula un picco di domanda improvviso per valutare la resilienza del sistema.
        """
        
        if quantita_override:
            quantita = quantita_override
        else:
            quantita = genera_quantita_lotto_stocastico()
            print(f"   [INPUT] Generazione stocastica dei volumi di produzione: {quantita}")
        
        if configurazione_override:
            config_casuale = configurazione_override
            print(f"   [SYSTEM] Generazione stocastica parametri (Tempi/Capacità) basata su Seed: {self.seme_casuale}")
        else:
            config_casuale = genera_configurazione_stocastica()
            print("   [CONFIG] Parametri del sistema configurati casualmente.")
        
        self.configurazione = config_casuale 
        self._check_material_balance(quantita)
        
        self.motore = MotoreSimulazione(durata_giorni=365, seme_casuale=self.seme_casuale)
        self.gestore_tempo = GestoreTempo(datetime(2024, 1, 1))
        self.gestore_turni = GestoreTurni(self.motore.ambiente, self.gestore_tempo)
        
        self.sistema_produttivo = SistemaProduttivo(self.motore.ambiente, self.gestore_turni, 
                                            self.sistema_produttivo.strategie, 
                                            config_casuale,
                                            self.motore.rng,
                                            politica=self.sistema_produttivo.politica, 
                                            nome_scenario="Stress Test Stocastico")
        self.ordini_completati = []

        totale_ordini = sum(quantita.values())
        print("   [SETUP] Inserimento degli ordini nel sistema produttivo (Batch Release)...")
        
        fattore_coda_stimato = 30
        tempo_svuotamento_coda = totale_ordini * fattore_coda_stimato
                
        for tipo_p, qty in quantita.items():
            for _ in range(qty):
                id_ordine = f"WO-BATCH-{self.motore.rng.randint(10000,99999)}"
                prodotto = Prodotto(tipo_p, f"Prodotto {tipo_p}")
                
                strategia = self.sistema_produttivo.strategie[tipo_p]
                tempo_std = strategia.stima_tempo_ciclo(config_casuale)
                
                if tipo_p == TipoProdotto.RD_01:
                    tempo_std += config_casuale.minuti_buffer_sicurezza_assemblaggio 
                
                min_urg = config_casuale.fattore_urgenza_min
                max_urg = config_casuale.fattore_urgenza_max
                fattore_urgenza = self.motore.rng.uniform(min_urg, max_urg)
                
                offset_batch = self.motore.rng.uniform(0, tempo_svuotamento_coda)
                
                scadenza = self.motore.ambiente.now + (tempo_std * fattore_urgenza) + offset_batch
                
                ordine = OrdineDiLavoro(id_ordine, prodotto, tempo_creazione=self.motore.ambiente.now, scadenza=scadenza)
                
                self.motore.ambiente.process(self._monitoraggio_processo(ordine))
        
        print(f"   [RUN] Avvio del motore di simulazione per {totale_ordini} ordini pianificati...")

        ambiente = self.motore.ambiente
        while True:
            try:
                ambiente.step()
            except simpy.core.EmptySchedule:
                break
            if len(self.ordini_completati) >= totale_ordini:
                break
            if ambiente.now > 365 * 24 * 60: 
                break

        # Aggiornamento contesto economico post-simulazione
        self.configurazione = config_casuale
        self.gestore_economico = GestoreEconomico(self.configurazione)

        # Elaborazione Reportistica
        risultati_dettagliati = self.elabora_report_finale()
        
        risultati_dettagliati.update({
            "Scenario": "Stress Test Stocastico",
            "Batch_Composition": quantita,
            "Total_Orders": totale_ordini,
            "Total_Time_Minutes": ambiente.now,
            "Total_Time_Days": ambiente.now / (24 * 60)
        })

        return risultati_dettagliati

    def elabora_report_finale(self):
        """Aggrega i dati grezzi della simulazione in metriche di business."""
        completati = [wo for wo in self.ordini_completati if wo.tempo_completamento is not None]
        
        rd01 = [wo for wo in completati if wo.prodotto.id == TipoProdotto.RD_01]
        throughput = len(rd01)
        tempi_attraversamento = [wo.tempo_attraversamento for wo in rd01 if wo.tempo_attraversamento]
        avg_lt = sum(tempi_attraversamento)/len(tempi_attraversamento) if tempi_attraversamento else 0
        
        ricavo = sum(self.gestore_economico.calcola_ricavo_effettivo(wo.prodotto.id, wo.tempo_completamento, wo.scadenza) for wo in completati)
        
        risultati = {
            "Scenario": self.nome_scenario,
            "Throughput_RD01": throughput,
            "Avg_LeadTime_RD01": avg_lt,
            "Total_Revenue": ricavo,
            "Detailed_Orders": completati
        }
        
        # Calcolo OEE
        metriche_oee = self.analizzatore_prestazioni.calcola_metriche_prestazionali(
            ordini_completati=completati,
            macchinari=self.sistema_produttivo.macchinari,
            operatori=self.sistema_produttivo.operatori,
            strategie=self.sistema_produttivo.strategie,
            configurazione=self.configurazione,
            tempo_corrente=self.motore.ambiente.now
        )
        
        risultati.update(metriche_oee)

        # Calcolo Totale Minuti di Setup
        totale_setup = sum([m.tempo_setup for m in self.sistema_produttivo.macchinari.values()])
        risultati["Total_Setup_Minutes"] = totale_setup
        
        return risultati

    def calcola_tempo_produzione_lotto(self):
        return self.motore.ambiente.now
