import csv
import os
import sys

def esegui_audit():
    file_path = os.path.join('output', 'simulation_results.csv')
    
    print(f"--- AVVIO VERIFICA COERENZA DATI: {file_path} ---")

    if not os.path.exists(file_path):
        print(f"ERRORE: Il file {file_path} non esiste.")
        return

    errori = 0
    totale_ordini = 0
    totale_profitto = 0.0
    somma_attraversamento = 0.0
    
    errori_dettaglio = []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for righe in reader:
                totale_ordini += 1
                try:
                    id_ordine = righe['ID_Ordine']
                    t_creazione = float(righe['Tempo_Creazione'])
                    
                    if righe['Tempo_Completamento'] == 'N/A':
                        continue 
                        
                    t_completamento = float(righe['Tempo_Completamento'])
                    t_attraversamento = float(righe['Tempo_Attraversamento'])
                    ricavo = float(righe['Ricavo'])
                    costo = float(righe['Costo_Produzione'])
                    profitto = float(righe['Profitto'])
                    
                    somma_attraversamento += t_attraversamento
                    totale_profitto += profitto

                    if t_completamento <= t_creazione:
                        errori += 1
                        errori_dettaglio.append(f"ORDINE {id_ordine}: Completato ({t_completamento}) prima/uguale creazione ({t_creazione})")
                        continue

                    diff_time = t_completamento - t_creazione
                    if abs(diff_time - t_attraversamento) > 0.1:
                        errori += 1
                        errori_dettaglio.append(f"ORDINE {id_ordine}: Attr. CSV ({t_attraversamento}) != Calc ({diff_time:.2f})")
                        continue

                    profitto_calc = ricavo - costo
                    if abs(profitto_calc - profitto) > 0.001:
                        errori += 1
                        errori_dettaglio.append(f"ORDINE {id_ordine}: Profitto CSV ({profitto}) != Calc ({profitto_calc:.3f}) [R={ricavo}-C={costo}]")
                        continue

                except ValueError as e:
                    print(f"Errore parsing riga {totale_ordini}: {e}")
                    continue

        media_attraversamento = somma_attraversamento / totale_ordini if totale_ordini > 0 else 0

        print(f"\n--- STATISTICHE SINTETICHE ---")
        print(f"Ordini Analizzati : {totale_ordini}")
        print(f"Profitto Totale   : {totale_profitto:.2f} €")
        print(f"Tempo Medio Attr. : {media_attraversamento:.2f} min")

        print(f"\n--- ESITO AUDIT ---")
        if errori == 0:
            print("AUDIT SUPERATO: I dati sono matematicamente coerenti.")
        else:
            print(f"AUDIT FALLITO: Trovate {errori} incongruenze.")
            print("Esempi errori:")
            for e in errori_dettaglio[:5]:
                print(f"   - {e}")

    except Exception as e:
        print(f"ERRORE CRITICO DURANTE L'AUDIT: {e}")

if __name__ == "__main__":
    esegui_audit()
