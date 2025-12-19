import matplotlib.pyplot as plt
import csv
import os
from typing import List, Dict, Any

from configurazione import ConfigurazioneSimulazione, TipoProdotto, TipoMacchinario
from simulazione_core import OrdineDiLavoro, Macchinario, Operatore, StrategiaProcessoBase

class AnalizzatorePrestazioni:
    """
    Modulo di analisi delle performance produttive basato sullo standard OEE.
    Fornisce metriche aggregate di Disponibilità, Prestazione e Qualità.
    """

    def __init__(self):
        """Inizializza l'analizzatore."""
        pass
    
    def calcola_metriche_prestazionali(self, 
                    ordini_completati: List[OrdineDiLavoro], 
                    macchinari: Dict[str, Macchinario], 
                    operatori: Dict[str, Operatore],
                    strategie: Dict[str, StrategiaProcessoBase],
                    configurazione: ConfigurazioneSimulazione,
                    tempo_corrente: float) -> Dict[str, float]:
        """
        Calcola l'indice OEE e i KPI di dettaglio.
        
        Formula OEE = Disponibilità * Prestazione * Qualità
        - Disponibilità: Tempo in cui la macchina ha lavorato rispetto al tempo totale disponibile.
        - Prestazione: Velocità reale rispetto alla velocità teorica standard.
        - Qualità: Percentuale di prodotti buoni al primo colpo.
        """
        
        if not ordini_completati:
            return {
                "OEE_Score": 0.0,
                "Availability": 0.0,
                "Performance": 0.0,
                "Quality": 0.0
            }

        if ordini_completati:
            max_completion_time = max(o.tempo_completamento for o in ordini_completati if o.tempo_completamento)
            orizzonte_effettivo = max_completion_time if max_completion_time > 0 else tempo_corrente
        else:
            orizzonte_effettivo = tempo_corrente
            
        max_tempo_macchina_attiva = 0.0
        if macchinari:
            max_tempo_macchina_attiva = max([m.tempo_lavorazione + m.tempo_setup for m in macchinari.values()], default=0.0)
            
        if max_tempo_macchina_attiva > orizzonte_effettivo:
            orizzonte_effettivo = max_tempo_macchina_attiva
            
        if tempo_corrente > orizzonte_effettivo:
            orizzonte_effettivo = tempo_corrente

        
        totale_pezzi = len(ordini_completati)
        pezzi_difettosi = 0
        
        for ordine in ordini_completati:
            fasi = ordine.cronologia_fasi
            
            if ordine.prodotto.id in [TipoProdotto.PN_03, TipoProdotto.IN_07]:
                if fasi.count(TipoMacchinario.RETTIFICA) > 1:
                    pezzi_difettosi += 1
            elif TipoMacchinario.RETTIFICA in fasi:
                pezzi_difettosi += 1
                
        quality = (totale_pezzi - pezzi_difettosi) / totale_pezzi if totale_pezzi > 0 else 0.0

        minuti_giorno = 1440 # 24 * 60
        inizio_turno_min = int(configurazione.orario_inizio_turno * 60)
        fine_turno_min = int(configurazione.orario_fine_turno * 60)
        durata_turno = fine_turno_min - inizio_turno_min
        
        giorni_interi = int(orizzonte_effettivo / minuti_giorno)
        minuti_residui = orizzonte_effettivo % minuti_giorno
        
        giorni_lavorativi = 0
        for g in range(giorni_interi):
            day_of_week = g % 7
            if day_of_week < 5:
                giorni_lavorativi += 1
                
        tempo_operativo_teorico_minuti = giorni_lavorativi * durata_turno
        
        day_of_week_residuo = giorni_interi % 7
        if day_of_week_residuo < 5: 
            if minuti_residui > fine_turno_min:
                tempo_operativo_teorico_minuti += durata_turno
            elif minuti_residui > inizio_turno_min:
                tempo_operativo_teorico_minuti += (minuti_residui - inizio_turno_min)
        
        if tempo_operativo_teorico_minuti <= 0:
            availability = 0.0
        else:
            tempo_produttivo_totale = sum([m.tempo_lavorazione + m.tempo_setup for m in macchinari.values()])            
            capacita_totale_teorica = tempo_operativo_teorico_minuti * len(macchinari)
            availability = tempo_produttivo_totale / capacita_totale_teorica if capacita_totale_teorica > 0 else 0.0

        
        tempo_standard_totale = 0.0
        for ordine in ordini_completati:
            strategia = strategie.get(ordine.prodotto.id)
            if strategia:
                tempo_standard_totale += strategia.stima_tempo_ciclo(configurazione)
        
        tempo_reale_totale = sum(m.tempo_lavorazione for m in macchinari.values())

        if tempo_reale_totale > 0:
            performance = tempo_standard_totale / tempo_reale_totale
            if performance > 1.0:
                performance = 1.0
        else:
            performance = 0.0

        oee = availability * performance * quality

        metriche = {
            "OEE_Score": oee * 100, # Percentuale
            "Availability": availability * 100, # Percentuale
            "Performance": performance * 100, # Percentuale
            "Quality": quality * 100 # Percentuale
        }
        
        for nome_m, macchina in macchinari.items():
            if tempo_operativo_teorico_minuti > 0:
                util_prod = (macchina.tempo_lavorazione / (tempo_operativo_teorico_minuti * macchina.risorsa_simpy.capacity)) * 100
                util_setup = (macchina.tempo_setup / (tempo_operativo_teorico_minuti * macchina.risorsa_simpy.capacity)) * 100
                util_totale = util_prod + util_setup
                
                if util_totale > 100.1:
                    print(f"[WARN] ATTENZIONE: Risorsa {nome_m.value.upper()} ha fatto {util_totale - 100.0:.1f}% di straordinario")

                metriche[f"Utilizzo_Lavorazione_{nome_m.value}"] = util_prod
                metriche[f"Utilizzo_Setup_{nome_m.value}"] = util_setup
                metriche[f"Utilizzo_{nome_m.value}"] = util_totale
            else:
                metriche[f"Utilizzo_Lavorazione_{nome_m.value}"] = 0.0
                metriche[f"Utilizzo_Setup_{nome_m.value}"] = 0.0
                metriche[f"Utilizzo_{nome_m.value}"] = 0.0
            
        for nome_op, operatore in operatori.items():
            if tempo_operativo_teorico_minuti > 0:
                util_netto = (operatore.tempo_occupato_totale / (tempo_operativo_teorico_minuti * operatore.risorsa_simpy.capacity)) * 100
                
                if util_netto > 100.1:
                    print(f"[WARN] ATTENZIONE: Risorsa {nome_op.value.upper()} ha fatto {util_netto - 100.0:.1f}% di straordinario")
                
                metriche[f"Utilizzo_{nome_op.value}"] = util_netto
            else:
                metriche[f"Utilizzo_{nome_op.value}"] = 0.0

        return metriche

class GeneratoreGrafici:
    """
    Modulo per la visualizzazione dei dati per la rappresentazione grafica dei risultati della simulazione.
    """

    def crea_grafico_gantt(self, ordini_completati: List[OrdineDiLavoro], nome_file: str = 'grafico_produzione.png'):
        """
        Genera un diagramma di Gantt per visualizzare la schedulazione temporale degli ordini completati.
        """
        if not ordini_completati:
            print("Nessun dato disponibile per la visualizzazione grafica.")
            return

        colori = {
            TipoProdotto.FL_01: 'blue',
            TipoProdotto.PN_03: 'red',
            TipoProdotto.IN_07: 'green',
            TipoProdotto.RD_01: 'orange'
        }

        fig, ax = plt.subplots(figsize=(15, 10))

        y_labels = []
        
        ordini_ordinati = sorted(ordini_completati, key=lambda x: x.tempo_creazione)

        for i, ordine in enumerate(ordini_ordinati):
            if ordine.tempo_completamento:
                start = ordine.tempo_creazione
                if ordine.log_lavorazioni:
                    # Trovo il timestamp minimo di inizio lavorazione
                    start = min([op['inizio'] for op in ordine.log_lavorazioni if 'inizio' in op])
                
                duration = ordine.tempo_completamento - start
                
                ax.barh(i, duration, left=start, height=0.6, 
                        color=colori.get(ordine.prodotto.id, 'gray'), 
                        edgecolor='black', alpha=0.8)
                
                y_labels.append(ordine.id)

        ax.set_yticks(range(len(y_labels)))
        ax.set_yticklabels(y_labels, fontsize=8)
        ax.set_xlabel('Tempo di Simulazione (minuti)')
        ax.set_title(f'Diagramma di Gantt - Flusso Produttivo ({nome_file})')
        
        # Griglia migliorata
        ax.grid(True, axis='x', linestyle='--', alpha=0.3)

        # Marker giornalieri
        max_time = max([o.tempo_completamento for o in ordini_completati if o.tempo_completamento], default=0)
        giorni = int(max_time / 1440) + 1
        
        for g in range(1, giorni + 1):
            plt.axvline(x=g * 1440, color='black', linestyle='--', linewidth=1, alpha=0.7)
            plt.text(g * 1440, len(y_labels) + 0.5, f'Giorno {g}', rotation=0, 
                     horizontalalignment='center', verticalalignment='bottom', fontweight='bold')

        handles = [plt.Rectangle((0,0),1,1, color=c) for c in colori.values()]
        labels = [p.value for p in colori.keys()]
        plt.legend(handles, labels, title="Codice Prodotto")

        plt.tight_layout()
        try:
            plt.savefig(nome_file)
            print(f"   [OK] Grafico generato e salvato in: '{nome_file}'")
        except IOError as e:
            print(f"Errore durante il salvataggio del grafico '{nome_file}': {e}")
        finally:
            plt.close()

    def crea_grafico_macchine(self, macchinari: Dict[str, Macchinario], nome_file: str = 'gantt_macchine.png'):
        """
        Genera un diagramma di Gantt orientato alle risorse.
        Visualizza l'attività delle macchine distinguendo Lavorazione (Verde), Setup (Giallo) e Guasti (Rosso).
        """
        if not macchinari:
            return

        fig, ax = plt.subplots(figsize=(15, 8))
        
        y_labels = []
        yticks = []
        
        # Itero sulle macchine
        for i, (nome_macchina, macchina) in enumerate(macchinari.items()):
            yticks.append(i)
            y_labels.append(nome_macchina.value)
            
            eventi = getattr(macchina, 'log_eventi', [])
            
            for evento in eventi:
                start = evento['inizio']
                duration = evento['fine'] - start
                tipo = evento['tipo']
                
                color = 'green' 
                if tipo == 'guasto':
                    color = 'red'
                elif tipo == 'setup':
                    color = 'yellow'
                
                ax.barh(i, duration, left=start, height=0.6, color=color, edgecolor='black', alpha=0.8)

        ax.set_yticks(yticks)
        ax.set_yticklabels(y_labels)
        ax.set_xlabel('Tempo di Simulazione (minuti)')
        ax.set_title('Diagramma di Gantt - Utilizzo Risorse (Resource View)')
        ax.grid(True, axis='x', linestyle='--', alpha=0.3)
        
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='green', edgecolor='black', label='Lavorazione'),
            Patch(facecolor='red', edgecolor='black', label='Guasto/Riparazione'),
            Patch(facecolor='yellow', edgecolor='black', label='Setup')
        ]
        ax.legend(handles=legend_elements, loc='upper right')
        
        plt.tight_layout()
        try:
            plt.savefig(nome_file)
            print(f"   [OK] Grafico Risorse generato e salvato in: '{nome_file}'")
        except IOError as e:
            print(f"Errore salvataggio grafico risorse: {e}")
        finally:
            plt.close()

    def crea_grafico_gantt_zoom(self, ordini_completati: List[OrdineDiLavoro], nome_file: str = 'gantt_zoom.png', ultimi_n: int = 30):
        """
        Genera un diagramma di Gantt filtrato sugli ultimi N ordini per garantire leggibilità.
        """
        if not ordini_completati:
            return

        ordini_ordinati = sorted(ordini_completati, key=lambda x: x.tempo_completamento if x.tempo_completamento else 0)
        ordini_zoom = ordini_ordinati[-ultimi_n:]
        
        self.crea_grafico_gantt(ordini_zoom, nome_file)
        print(f"   [OK] Grafico Zoom (ultimi {ultimi_n} ordini) generato e salvato in: '{nome_file}'")

def esporta_dati(risultato_scenario, strategie):
    """
    Esporta i risultati dettagliati della simulazione in formato CSV e genera il grafico di Gantt.
    
    Questa funzione serve a persistere i dati grezzi per successive analisi statistiche esterne
    e a fornire una rappresentazione visiva immediata della schedulazione (Gantt).
    """
    print(f"\n[REPORTING] Generazione dei file di dettaglio per lo scenario: {risultato_scenario['Politica']}...")
    
    dettagli_ordini = risultato_scenario["Dettagli"]
    servizio_scenario = risultato_scenario["Scenario_Service"]
    
    output_dir = 'output'
    os.makedirs(output_dir, exist_ok=True)
    
    file_path = os.path.join(output_dir, 'simulation_results.csv')
    
    try:
        with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
            nomi_colonne = ['ID_Ordine', 'Tipo_Prodotto', 'Tempo_Creazione', 'Tempo_Completamento', 'Tempo_Attraversamento', 'Ricavo', 'Costo_Produzione', 'Profitto']
            writer = csv.DictWriter(csvfile, fieldnames=nomi_colonne)

            writer.writeheader()
            for ordine in dettagli_ordini:
                ricavo_raw = servizio_scenario.gestore_economico.calcola_ricavo_effettivo(ordine.prodotto.id, ordine.tempo_completamento, ordine.scadenza)
                ricavo = round(ricavo_raw, 2)
                
                strategia_ordine = strategie.get(ordine.prodotto.id)
                margine_teorico = servizio_scenario.gestore_economico.calcola_margine_contribuzione(ordine, strategia_ordine)
                prezzo_base = servizio_scenario.gestore_economico.prezzi.get(ordine.prodotto.id, 0.0)
                
                costo_raw = prezzo_base - margine_teorico
                costo = round(costo_raw, 2)
                
                profitto = round(ricavo_raw - costo_raw, 2)

                writer.writerow({
                    'ID_Ordine': ordine.id,
                    'Tipo_Prodotto': ordine.prodotto.id,
                    'Tempo_Creazione': f"{ordine.tempo_creazione:.2f}",
                    'Tempo_Completamento': f"{ordine.tempo_completamento:.2f}" if ordine.tempo_completamento else "N/A",
                    'Tempo_Attraversamento': f"{ordine.tempo_attraversamento:.2f}" if ordine.tempo_attraversamento else "0",
                    'Ricavo': f"{ricavo:.2f}",
                    'Costo_Produzione': f"{costo:.2f}",
                    'Profitto': f"{profitto:.2f}"
                })
        print(f"   [OK] Esportazione dati CSV completata con successo in: '{file_path}'")
    except IOError as e:
        print(f"Errore durante l'esportazione CSV: {e}")

    print('   [GRAFICA] Elaborazione dei diagrammi di Gantt in corso...')
    generatore_grafici = GeneratoreGrafici()
    
    nome_file_gantt = f"gantt_scenario_{risultato_scenario['Politica'].lower()}_full.png"
    percorso_gantt = os.path.join(output_dir, nome_file_gantt)
    generatore_grafici.crea_grafico_gantt(dettagli_ordini, nome_file=percorso_gantt)
    
    nome_file_zoom = f"gantt_scenario_{risultato_scenario['Politica'].lower()}_zoom.png"
    percorso_zoom = os.path.join(output_dir, nome_file_zoom)
    generatore_grafici.crea_grafico_gantt_zoom(dettagli_ordini, nome_file=percorso_zoom, ultimi_n=30)
    
    macchinari = servizio_scenario.sistema_produttivo.macchinari
    nome_file_macchine = f"gantt_scenario_{risultato_scenario['Politica'].lower()}_macchine.png"
    percorso_macchine = os.path.join(output_dir, nome_file_macchine)
    generatore_grafici.crea_grafico_macchine(macchinari, nome_file=percorso_macchine)

def stampa_report_manageriale(risultato_scenario, strategie):
    """
    Stampa a video un report manageriale sintetico.
    """
    dettagli_ordini = risultato_scenario["Dettagli"]
    servizio_scenario = risultato_scenario["Scenario_Service"]

    print("\n==================================================")
    print("               REPORT MANAGERIALE                 ")
    print("==================================================")
    
    print("\n--- PARAMETRI DI SIMULAZIONE ---")
    
    config = servizio_scenario.configurazione
    durata_turno_min = (config.orario_fine_turno - config.orario_inizio_turno) * 60
    durata_turno_min = durata_turno_min if durata_turno_min > 0 else 1440 
    
    print(f"Orizzonte Temporale: {risultato_scenario['Tempo']:.0f} min ({risultato_scenario['Tempo'] / durata_turno_min:.1f} giorni lavorativi)")
    print(f"Turno Operativo: {config.orario_inizio_turno:02d}:00 - {config.orario_fine_turno:02d}:00 ({durata_turno_min/60:.0f}h)")
    print("Variabilità Processo: +/- 10% (Stocastico)")
    
    print("\n--- ANALISI COSTI UNITARI MEDI ---")
    costi_per_prodotto = {}
    conteggi_per_prodotto = {}
    
    for ordine in dettagli_ordini:
        prod_id = ordine.prodotto.id
        
        strategia_ordine = strategie.get(prod_id)
        margine_teorico = servizio_scenario.gestore_economico.calcola_margine_contribuzione(ordine, strategia_ordine)
        prezzo_base = servizio_scenario.gestore_economico.prezzi.get(prod_id, 0.0)
        costo = prezzo_base - margine_teorico
        
        costi_per_prodotto[prod_id] = costi_per_prodotto.get(prod_id, 0.0) + costo
        conteggi_per_prodotto[prod_id] = conteggi_per_prodotto.get(prod_id, 0) + 1

    for prod_id, totale_costi in costi_per_prodotto.items():
        n_pezzi = conteggi_per_prodotto.get(prod_id, 1)
        costo_medio = totale_costi / n_pezzi
        print(f"Costo Unitario Medio {prod_id.value:<10}: {costo_medio:.2f} €")

    print("\n--- ALERT OPERATIVI (SOGLIA UTILIZZO > 85%) ---")
    alerts_found = False
    for key, val in risultato_scenario.items():
        if key.startswith("Utilizzo_") and key != "Utilizzo_Bottleneck":
            if "Lavorazione" in key or "Setup" in key:
                continue

            nome_risorsa = key.replace("Utilizzo_", "")
            if val > 85.0:
                print(f"!!! CRITICITA RILEVATA: RISORSA '{nome_risorsa.upper()}' SATURA (Utilizzo: {val:.1f}%) - NECESSARIA AZIONE CORRETTIVA !!!")
                alerts_found = True
    
    if not alerts_found:
        print("Nessuna criticità operativa rilevata (Tutte le risorse < 85% saturazione).")

    print('\n>>> Analisi di Simulazione Completata.')
