import logging
import traceback
import random
import sys
import os

from typing import List, Dict, Tuple, Any

from configurazione import (
    ConfigurazioneSimulazione, 
    TipoProdotto, PoliticaSchedulazione, 
    TipoMacchinario, TipoOperatore,
    genera_configurazione_stocastica,
    genera_quantita_lotto_stocastico
)
from simulazione_core import (
    StrategiaProcessoBase, StrategiaFL01, StrategiaPN03, StrategiaIN07, StrategiaRD01,
    GestoreEconomico, OrdineDiLavoro
)
from infrastructure.reporting_service import (
    esporta_dati, stampa_report_manageriale
)
from domain.services.scenario_service import GestoreScenario



logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')

def calcola_kpi_economici(
    ordini: List[OrdineDiLavoro], 
    gestore_economico: GestoreEconomico, 
    strategie: Dict[TipoProdotto, StrategiaProcessoBase]
) -> Tuple[float, float, int, float]:
    """
    Calcola i KPI economici aggregati per un insieme di ordini completati.
    """
    totale_ricavo = 0.0
    totale_costo_produzione = 0.0
    ordini_ritardo = 0
    
    for ordine in ordini:
        if getattr(ordine, 'consumato', False):
            continue

        # Ricavo Netto (al netto di penali)
        ricavo = gestore_economico.calcola_ricavo_effettivo(ordine.prodotto.id, ordine.tempo_completamento, ordine.scadenza)
        totale_ricavo += ricavo
        
        # Costo Industriale Variabile
        strategia_ordine = strategie.get(ordine.prodotto.id)
        margine_teorico = gestore_economico.calcola_margine_contribuzione(ordine, strategia_ordine)
        prezzo_base = gestore_economico.prezzi.get(ordine.prodotto.id, 0.0)
        costo = prezzo_base - margine_teorico
        totale_costo_produzione += costo
        
        # Livello di Servizio (Service Level - On-Time Delivery)
        if ordine.tempo_completamento and ordine.tempo_completamento > ordine.scadenza:
            ordini_ritardo += 1
            
    totale_profitto = totale_ricavo - totale_costo_produzione
    
    return totale_ricavo, totale_costo_produzione, ordini_ritardo, totale_profitto


def esegui_benchmark(strategie: Dict[TipoProdotto, StrategiaProcessoBase], seed: int) -> List[Dict[str, Any]]:
    """
    Esegue il benchmark comparativo tra le diverse politiche di schedulazione.
    """

    print("\n" + "="*80)
    print("DIGITAL TWIN: SIMULAZIONE PROCESSO PRODUTTIVO (METALMECCANICA)")
    print("="*80)
    print("\n[CONFIGURAZIONE LOTTO]")
    print(f"   > Modalità Input    : GENERAZIONE CASUALE (Stocastica)")
    print(f"   > Seed Simulazione  : {seed}")
    print(f"   > Reparto           : Job Shop (Tornitura, Fresatura, Assemblaggio)")
    print("-" * 80)
    
    politiche = [PoliticaSchedulazione.FIFO, PoliticaSchedulazione.SPT, PoliticaSchedulazione.EDD]
    risultati_confronto = []

    rng_master = random.Random(seed) 
    configurazione_master = genera_configurazione_stocastica(rng=rng_master)
    quantita_master = genera_quantita_lotto_stocastico(rng=rng_master)
    
    print(f"\n{'-'*30} VERIFICA GENERAZIONE STOCASTICA DATI (SEED: {seed}) {'-'*30}")
    
    print("\n[TEMPI DI LAVORAZIONE GENERATI (Minuti per Pezzo)]")
    for macchina, tempi in configurazione_master.tempi_lavorazione.items():
        tempi_str = ", ".join([f"{prod.value}: {t:.1f}min" for prod, t in tempi.items() if t > 0])
        if tempi_str:
            print(f"   > {macchina.value:<25}: {tempi_str}")
            
    print("\n[VINCOLI E CAPACITÀ PRODUTTIVA]")
    print(f"   > Limite Global Factory   : {configurazione_master.limite_produzione_totale_giornaliera} pezzi/giorno")
    print(f"   > Limiti per Prodotto     : " + " | ".join([f"{k}: {v}" for k, v in configurazione_master.limiti_produzione_giornaliera.items()]))
    
    # Visualizzazione Capacità Risorse
    print(f"   > Configurazione Risorse  :")
    for risorsa, cap in configurazione_master.capacita.items():
        print(f"      - {risorsa.value:<22}: {cap} unità")

    print("\n   [VOLUMI DI PRODUZIONE GENERATI (Stocastici)]")
    totale_pezzi = 0
    descrizioni = {"FL-01": "Flangia", "PN-03": "Perno", "IN-07": "Ingranaggio", "RD-01": "Riduttore"}
    
    print("   | CODICE | DESCRIZIONE         | QUANTITÀ (Pz) |")
    print("   |--------|---------------------|---------------|")
    
    for p, q in sorted(quantita_master.items(), key=lambda x: x[0].value):
        codice = p.value
        desc = descrizioni.get(codice, "Componente")
        print(f"   | {codice:<6} | {desc:<19} | {q:<13} |")
        totale_pezzi += q
        
    print("   -----------------------------------------------")
    print(f"   TOTALE PEZZI NEL LOTTO: {totale_pezzi}")
    print("-" * 90)
    # -----------------------------

    for politica in politiche:
        print("\n" + "-"*80)
        print(f"AVVIO SCENARIO DI TEST: {politica.name}")
        print("-" * 80)
        print(f"[CONFIG] Caricamento parametri politica {politica.name}... ATTIVO.")
        
        servizio_scenario = GestoreScenario(
            strategie=strategie, 
            configurazione=configurazione_master, 
            nome_scenario=f'Scenario_{politica.name}', 
            seed=seed, 
            politica_schedulazione=politica
        )
        
        risultati = servizio_scenario.esegui_lotto_stocastico(
            quantita_override=quantita_master,
            configurazione_override=configurazione_master 
        )
        
        tempo_totale = servizio_scenario.calcola_tempo_produzione_lotto()
        data_consegna = servizio_scenario.gestore_tempo.calcola_data_consegna(tempo_totale)
        
        data_inizio = servizio_scenario.gestore_tempo.data_inizio
        dt_fine = servizio_scenario.gestore_tempo.ottieni_data_corrente(tempo_totale)
        lead_time_giorni_cal = (dt_fine - data_inizio).days
        lead_time_h = (dt_fine - data_inizio).seconds / 3600
        
        durata_turno_min = (configurazione_master.orario_fine_turno - configurazione_master.orario_inizio_turno) * 60
        giorni_lavorativi_eq = servizio_scenario.gestore_tempo.calcola_giorni_lavorativi(tempo_totale, durata_turno_min)

        print(f"   [OK] Simulazione completata.")
        print(f"      - Tempo Totale (Lordo): {tempo_totale:.1f} min")
        print(f"      - Lead Time Calendario: {lead_time_giorni_cal}gg {lead_time_h:.1f}h (Data: {data_consegna})")
        print(f"      - Working Days Equivalent (base {durata_turno_min/60:.1f}h): {giorni_lavorativi_eq:.1f} gg")
        
        totale_ricavo, totale_costo_produzione, ordini_ritardo, totale_profitto = calcola_kpi_economici(
            risultati["Detailed_Orders"], 
            servizio_scenario.gestore_economico, 
            strategie
        )
        
        somma_minuti_ritardo = 0.0
        for o in risultati["Detailed_Orders"]:
            if o.tempo_completamento and o.tempo_completamento > o.scadenza:
                somma_minuti_ritardo += (o.tempo_completamento - o.scadenza)
        
        ritardo_medio = somma_minuti_ritardo / ordini_ritardo if ordini_ritardo > 0 else 0.0
        
        max_utilizzo = 0.0
        nome_bottleneck = "N/A"
        for key, val in risultati.items():
            if key.startswith("Utilizzo_") and "Lavorazione" not in key and "Setup" not in key:
                if val > max_utilizzo:
                    max_utilizzo = val
                    nome_bottleneck = key.replace("Utilizzo_", "")
        
        dati_scenario = {
            "Politica": politica.name,
            "Tempo": risultati["Total_Time_Minutes"],
            "Fatturato": totale_ricavo,
            "Profitto": totale_profitto,
            "Ritardi": ordini_ritardo,
            "Ritardo_Medio": ritardo_medio,
            "Bottleneck": nome_bottleneck,
            "Utilizzo_Bottleneck": max_utilizzo,
            "Dettagli": risultati["Detailed_Orders"],
            "Scenario_Service": servizio_scenario
        }
        dati_scenario.update(risultati)
        
        risultati_confronto.append(dati_scenario)

    try:
        fifo_res = next(r for r in risultati_confronto if r['Politica'] == 'FIFO')
        spt_res = next(r for r in risultati_confronto if r['Politica'] == 'SPT')
        
        setup_fifo = fifo_res.get("Total_Setup_Minutes", 0)
        setup_spt = spt_res.get("Total_Setup_Minutes", 0)
        
        if setup_fifo > 0 and setup_spt > (setup_fifo * 1.5):
            print(f"\n[ANALISI] NOTA: SPT penalizzata da eccessivi cambi setup (+{((setup_spt-setup_fifo)/setup_fifo)*100:.1f}% rispetto a FIFO)")
            print(f"          Setup SPT: {setup_spt:.1f} min vs FIFO: {setup_fifo:.1f} min")
    except StopIteration:
        pass

    print("\n[FASE 2] Elaborazione Risultati Comparativi")
    print("----------------------------------------------------------------------")
    header = f"| {'Politica':<10} | {'Tempo (min)':<12} | {'Fatturato (€)':<14} | {'Profitto (€)':<14} | {'Ritardi':<8} | {'Rit. Medio':<10} | {'Collo di Bottiglia':<25} |"
    print("-" * len(header))
    print(header)
    print("-" * len(header))
    
    try:
        output_dir = 'output'
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, 'summary_table.txt')
        
        with open(file_path, 'w') as f:
            f.write("-" * len(header) + "\n")
            f.write(header + "\n")
            f.write("-" * len(header) + "\n")
            
            for res in risultati_confronto:
                util_val = res['Utilizzo_Bottleneck']
                if util_val > 100.05:
                    overtime = util_val - 100.0
                    bottleneck_str = f"{res['Bottleneck']} (100% +{overtime:.1f}%)"
                else:
                    bottleneck_str = f"{res['Bottleneck']} ({util_val:.1f}%)"

                row = f"| {res['Politica']:<10} | {res['Tempo']:<12.1f} | {res['Fatturato']:<14.2f} | {res['Profitto']:<14.2f} | {res['Ritardi']:<8} | {res['Ritardo_Medio']:<10.1f} | {bottleneck_str:<25} |"
                print(row)
                f.write(row + "\n")
            
            print("-" * len(header))
            f.write("-" * len(header) + "\n")
    except IOError as e:
        print(f"Errore durante la scrittura del file '{file_path}': {e}")
        
    return risultati_confronto



def main() -> None:
    print("======================================================================")

    print("Benvenuto. Il software sta per avviare la simulazione digitale del processo.")
    
    SEED = random.randint(1, 100000)
    print(f"[SYSTEM] Seed di simulazione generato casualmente: {SEED}")

    strategie = {
        TipoProdotto.FL_01: StrategiaFL01(),
        TipoProdotto.PN_03: StrategiaPN03(),
        TipoProdotto.IN_07: StrategiaIN07(),
        TipoProdotto.RD_01: StrategiaRD01()
    }

    risultati_confronto = esegui_benchmark(strategie, SEED)
    
    miglior_scenario = None
    max_profitto = -float('inf')

    for scenario in risultati_confronto:
        print(f"\n{'='*60}")
        print(f">>> ANALISI SCENARIO: {scenario['Politica']}")
        print(f"{'='*60}")

        esporta_dati(scenario, strategie)
        stampa_report_manageriale(scenario, strategie)

        if scenario['Profitto'] > max_profitto:
            max_profitto = scenario['Profitto']
            miglior_scenario = scenario

    print(f"\n{'='*60}")
    print("RISULTATO FINALE SIMULAZIONE")
    print(f"{'='*60}")
    
    if miglior_scenario:
        tempo_minuti = miglior_scenario['Tempo']
        giorni = int(tempo_minuti // 1440)
        ore = int((tempo_minuti % 1440) // 60)
        minuti = int(tempo_minuti % 60)
        
        print(f">>> SCENARIO OTTIMALE: {miglior_scenario['Politica']}")
        print(f">>> TEMPO DI PRODUZIONE COMPLESSIVO:")
        print(f"    [{tempo_minuti:.1f}] Minuti")
        print(f"    (Pari a: {giorni} giorni, {ore} ore e {minuti} minuti)")
        print("-" * 60)
        print(f"    Profitto Totale    : € {miglior_scenario['Profitto']:,.2f}")
        print(f"    Collo di Bottiglia : {miglior_scenario['Bottleneck']} ({miglior_scenario['Utilizzo_Bottleneck']:.1f}%)")
    else:
        print("Nessuno scenario completato con successo.")
    
    print("\n======================================================================")
    print("   SIMULAZIONE TERMINATA CON SUCCESSO                                 ")
    print("======================================================================")
    print("I file di output (Report CSV, Grafici Gantt) sono disponibili nella cartella '/output'.")

if __name__ == '__main__':
    try:
        main()
    except UnicodeEncodeError as e:
        print(f"\nERRORE DI CODIFICA RILEVATO: {e}")
        print("Il tuo terminale non supporta alcuni caratteri Unicode usati nell'output.")
        print("SUGGERIMENTO: Imposta la variabile d'ambiente PYTHONIOENCODING=utf-8 prima di avviare lo script.")
        print("Esempio Powershell: $env:PYTHONIOENCODING='utf-8'; python main.py")
    except Exception as e:
        print(f"\nErrore durante l'esecuzione della simulazione: {e}")
        traceback.print_exc()
        sys.exit(1)
