---
noteId: "3f3d6e5055b811f1820ac302dffd812a"
tags: []

---

# Spiegazione del codice del progetto Smart District MILP-MPC

## 1. Idea generale del progetto

Il progetto implementa un sistema di gestione energetica per uno smart district/microgrid. Il controllore decide, ora per ora, come usare rete elettrica, fotovoltaico, batteria, sistema a idrogeno, generatore non rinnovabile, HVAC e ricarica PEV.

La logica usata è una **Model Predictive Control** con orizzonte di previsione di 24 ore. A ogni ora il codice:

1. legge lo stato corrente del sistema;
2. costruisce le previsioni per le prossime 24 ore;
3. costruisce e risolve un problema MILP in Pyomo;
4. applica solo la prima azione ottima;
5. aggiorna gli stati e ripete il processo all'ora successiva.

Il problema è **MILP** perché contiene variabili continue, come potenze e stati di carica, e variabili binarie, come accensione/spegnimento o modalità operative. Le variabili binarie servono a evitare comportamenti fisicamente impossibili, per esempio importare ed esportare energia nello stesso istante, caricare e scaricare la batteria contemporaneamente, oppure usare insieme heating e cooling HVAC.

L'obiettivo economico minimizza:

```text
costo energia importata
+costo combustibile DG
-ricavo energia esportata
+penalità per eventuali slack
```

Le slack sono variabili di rilassamento usate per evitare che il problema diventi infeasible in scenari molto difficili. Se vengono usate, sono penalizzate moltissimo, quindi il solver le usa solo quando è necessario.

---

## 2. `config.py`

Questo file contiene tutti i parametri numerici e le definizioni degli scenari. L'obiettivo è evitare numeri sparsi nel codice: se bisogna cambiare un parametro fisico o economico, si modifica qui.

### `MicrogridParams`

È una `dataclass` congelata, cioè un contenitore ordinato e non modificabile direttamente dei parametri del sistema.

Contiene:

- parametri MPC: `T = 24`, `dt = 1.0`;
- percorsi: cartella dataset e cartella output;
- limiti di rete: massima importazione ed esportazione;
- potenza nominale PV e carico uffici;
- parametri BESS: potenza, capacità, rendimenti, limiti SoC;
- parametri HSS: fuel cell, elettrolizzatore, serbatoio idrogeno, limiti SoH;
- parametri DG: potenza nominale, minimo tecnico, rendimento e costo combustibile;
- parametri HVAC: potenza, resistenza/capacità termica, rendimenti, comfort;
- parametri PEV: potenza di ricarica, capacità, target, disponibilità;
- tariffe F1/F2/F3;
- penalità delle slack;
- ordine di fallback dei solver.

Il parametro `P_ely_min = 6.5` è lasciato configurabile perché nel materiale del corso può esserci ambiguità con il valore `65`. Il codice usa `6.5` come minimo tecnico pratico, ma la scelta è centralizzata e facile da cambiare.

### `Scenario`

Descrive un caso di simulazione:

- nome dello scenario;
- indice orario di partenza;
- numero di ore simulate;
- costo del combustibile;
- stagione.

### `default_params(**overrides)`

Restituisce i parametri di default. Gli `overrides` permettono di creare una variante senza riscrivere tutto. Per esempio:

```python
params = default_params(c_f=0.45)
```

Questo è utile perché gli scenari differiscono soprattutto per il costo del combustibile.

### `default_scenarios(n_steps=48)`

Definisce i quattro scenari richiesti:

- estate, combustibile economico;
- estate, combustibile costoso;
- inverno, combustibile economico;
- inverno, combustibile costoso.

Le date sono fissate a gennaio 15 e luglio 15 in un calendario sintetico 2022. Questa scelta rende i risultati riproducibili.

### `to_namespace(params)`

Converte la dataclass in `SimpleNamespace`. È una funzione di utilità nel caso si preferisca accedere ai parametri come oggetti modificabili.

---

## 3. `utils.py`

Questo file contiene funzioni generiche riutilizzate dagli altri moduli.

### `ensure_dir(path)`

Crea una directory se non esiste e restituisce il percorso. Serve per evitare errori quando il codice salva CSV, immagini o file diagnostici.

### `get_horizon_slice(array, k, T)`

Estrae una finestra di lunghezza `T` a partire dall'indice `k`.

La funzione usa il modulo `%`, quindi se `k + T` supera la fine dell'anno, la finestra riparte dall'inizio. Questo è importante perché i dataset hanno 8760 ore e l'MPC deve poter funzionare anche vicino alla fine dell'anno.

### `clip(values, lower, upper)`

Limita un array in un intervallo. Viene usato soprattutto per impedire che PV o profili normalizzati superino limiti fisici.

### `pyomo_value(obj, default=0.0)`

Estrae in modo sicuro un valore numerico da un oggetto Pyomo. Se qualcosa non è valorizzato, restituisce un default. Nel codice principale oggi si usa soprattutto `value()` direttamente, ma questa funzione resta utile per estensioni e debug.

### `require_length(name, values, expected)`

Controlla che un array abbia la lunghezza attesa. È usato prima di costruire il modello per evitare errori più difficili da leggere dentro Pyomo.

### `sanitize_filename(name)`

Trasforma una stringa in un nome file sicuro. Serve per generare output con nomi scenario senza caratteri problematici.

---

## 4. `data_loader.py`

Questo modulo carica i dataset `.mat`, costruisce i profili annuali e prepara i dati esogeni.

### `_load_mat_variable(path, variable)`

Carica un file MATLAB con `scipy.io.loadmat` ed estrae una variabile specifica.

Perché è utile:

- controlla che il file esista;
- controlla che la variabile richiesta sia presente;
- converte il risultato in `numpy.ndarray` di tipo `float`.

Questo evita errori silenziosi se un file o una variabile hanno nomi diversi da quelli attesi.

### `_column(matrix, index, name)`

Estrae una colonna da una matrice e la appiattisce.

Nei dataset del corso molte matrici hanno forma:

```text
[hour, forecast, actual]
```

Quindi:

- colonna 1 = forecast;
- colonna 2 = actual.

La funzione gestisce anche il caso di array monodimensionale e produce messaggi chiari se la colonna non esiste.

### `_scale_to_nominal(values, nominal, name)`

Scala un profilo in modo che il suo massimo diventi la potenza nominale desiderata.

Per il carico uffici si usa:

```text
P_ul_scaled = P_ul_raw / max(P_ul_raw) * 450
```

Questa scelta serve perché i dati originali potrebbero essere in unità o scala non direttamente compatibili con il microgrid modellato.

### `build_synthetic_2022_index(n_hours=8760)`

Crea un indice orario da 8760 ore, cioè un anno non bisestile. È usato per:

- assegnare tariffe F1/F2/F3;
- stabilire setpoint stagionali;
- costruire la disponibilità PEV;
- dare timestamp leggibili ai risultati.

### `build_import_price_profile(index_or_datetime, F1, F2, F3)`

Costruisce il prezzo di importazione dell'energia secondo fasce orarie.

Assunzione usata:

- F1: giorni feriali 08:00-19:00;
- F2: giorni feriali 07:00-08:00 e 19:00-23:00, sabato 07:00-23:00;
- F3: notti, domeniche, festività e resto.

Le festività sono approssimate con alcune date italiane 2022. Questa approssimazione è documentata perché il dataset non include un calendario ufficiale completo.

### `build_temperature_setpoint(index)`

Genera il setpoint termico annuale:

- 22 °C da aprile a settembre;
- 20 °C da ottobre a marzo.

Questo distingue il comportamento estivo e invernale dell'HVAC.

### `build_pev_availability(index, params)`

Crea il profilo binario di disponibilità del veicolo:

```text
UR_pev = 1 se il veicolo è collegato
UR_pev = 0 se non è collegato
```

Il default è collegato dalle 18:00 alle 08:00. È una scelta realistica: il veicolo è disponibile sera/notte e assente durante il giorno.

### `load_project_data(data_dir, use_forecast=True)`

È la funzione principale del modulo.

Carica:

- temperatura esterna;
- irradianza;
- carico uffici;
- PUN;
- profilo PV in per-unit.

Poi costruisce:

- `T_ex_forecast`, `T_ex_actual`;
- `P_ul_forecast`, `P_ul_actual`;
- `P_pv_forecast`, `P_pv_actual`;
- PV alternativa da irradianza;
- prezzo export `p_e`, convertito da €/MWh a €/kWh;
- tariffa import `c_l`;
- setpoint `T_sp`;
- disponibilità PEV `UR_pev`;
- indice temporale `index`.

Perché vengono conservati sia forecast sia actual:

- dentro l'ottimizzazione MPC si usano previsioni;
- nei risultati si possono riportare anche i valori actual come misura/simulazione.

La funzione valida anche le lunghezze e controlla che PV e carichi non siano negativi.

---

## 5. `model.py`

Questo è il cuore matematico del progetto. Qui viene costruito il problema MILP in Pyomo.

### `_horizon_value(horizon_data, name, j)`

Estrae un valore scalare da un array dell'orizzonte. Serve perché Pyomo lavora meglio quando i parametri numerici dentro le regole sono float semplici.

### `_validate_horizon(parms, horizon_data)`

Controlla che tutti gli array dell'orizzonte abbiano lunghezza `T`. Se manca un dato, il codice fallisce prima di costruire il modello, con errore leggibile.

### `build_microgrid_model(parms, horizon_data, initial_state)`

Costruisce il `ConcreteModel()` Pyomo per un singolo passo MPC.

#### Set temporali

```python
model.J = RangeSet(0, T - 1)
model.K = RangeSet(0, T)
```

`J` rappresenta gli intervalli di controllo, quindi le decisioni orarie.  
`K` rappresenta gli stati, quindi include anche lo stato iniziale e lo stato finale dopo 24 ore.

#### Variabili continue

Il modello definisce potenze di rete, PV curtailment, BESS, HSS, DG, HVAC e PEV. Gli stati sono:

- `SoC_b`: stato di carica batteria;
- `SoH_h`: stato del serbatoio idrogeno;
- `T_in`: temperatura interna.

Le slack sono:

- `slack_temp_low`;
- `slack_temp_high`;
- `slack_pev`.

Servono per evitare infeasibilità, ma hanno costo altissimo.

#### Variabili binarie

Le binarie rappresentano modalità operative:

- import/export rete;
- carica/scarica BESS;
- fuel cell/elettrolizzatore;
- DG acceso/spento;
- raffrescamento/riscaldamento HVAC.

Si usano perché il modello deve restare lineare ma deve anche rappresentare logiche on/off.

#### Vincoli iniziali

```python
SoC_b[0] == stato misurato
SoH_h[0] == stato misurato
T_in[0] == stato misurato
```

Gli stati iniziali non sono decisioni: sono condizioni note all'inizio del passo MPC.

#### Vincoli rete

La rete può importare oppure esportare, non entrambi:

```text
P_i <= P_i_max * delta_i
P_e <= P_e_max * delta_e
delta_i + delta_e <= 1
```

Questo evita una soluzione non fisica in cui il modello compra e vende nello stesso momento.

#### PV curtailment

Il fotovoltaico è esogeno. Il modello può usarlo oppure tagliarlo:

```text
0 <= P_curt <= P_pv_forecast
P_pv_used = P_pv_forecast - P_curt
```

Il curtailment serve quando c'è troppa produzione rispetto alla domanda, ai limiti di export o alla capacità di accumulo.

#### Power balance

È il vincolo elettrico principale:

```text
supply = demand
```

Supply:

- rete import;
- PV usato;
- batteria in scarica;
- fuel cell;
- DG.

Demand:

- rete export;
- carico uffici;
- HVAC;
- batteria in carica;
- elettrolizzatore;
- PEV.

Questo vincolo garantisce che ogni kW sia contabilizzato.

#### Dinamica BESS

La batteria evolve secondo:

```text
SoC[k+1] = SoC[k] + dt/E_b * (eta_ch * P_ch - P_dsc/eta_dsc)
```

La carica aumenta lo stato, la scarica lo diminuisce. I rendimenti rendono il modello più realistico.

Le binarie impediscono carica e scarica simultanee.

#### Dinamica HSS

Il sistema a idrogeno usa un modello energetico equivalente:

```text
SoH[k+1] = SoH[k] + dt/E_h * (eta_ely * P_ely - P_fc/eta_fc)
```

L'elettrolizzatore consuma elettricità e aumenta l'idrogeno immagazzinato.  
La fuel cell produce elettricità e consuma idrogeno.

Anche qui ci sono minimi tecnici e vincoli binari per evitare fuel cell ed elettrolizzatore insieme.

#### Vincoli DG

Il generatore non rinnovabile ha un minimo tecnico:

```text
P_g_min * delta_g <= P_g <= P_g_nom * delta_g
```

Questo è corretto perché un generatore acceso non può produrre arbitrariamente poco; se è spento, `delta_g = 0` e quindi `P_g = 0`.

#### Dinamica HVAC

La temperatura interna segue:

```text
T_in[k+1] =
    alpha * T_in[k]
    - beta * R * (eta_c * P_c - eta_h * P_h)
    + beta * T_ex[k]
```

Il raffrescamento abbassa la temperatura; il riscaldamento la alza.  
Le binarie impediscono heating e cooling simultanei.

I vincoli comfort sono:

```text
T_sp - Delta_T <= T_in <= T_sp + Delta_T
```

con slack per mantenere il problema risolvibile anche in condizioni estreme.

#### Vincoli PEV

Il PEV può caricare solo se disponibile:

```text
P_pev <= UR_pev * P_pev_nom
```

Il modello richiede abbastanza energia per raggiungere il target SoC. È stato aggiunto un dettaglio importante: se il veicolo è collegato ora, il modello deve programmare la carica prima della prossima disconnessione. Questo evita il problema tipico del receding horizon in cui l'ottimizzatore rimanda sempre la carica al futuro e poi, applicando solo il primo comando, non carica mai.

#### Funzione obiettivo

Minimizza:

```text
import cost - export revenue + DG fuel cost + slack penalties + tiny regularization
```

Non si aggiunge un costo separato per HVAC, PEV, batteria o elettrolizzatore perché quei consumi sono già inclusi nel bilancio elettrico e quindi pagati tramite importazione o produzione.

### `_candidate_solvers(solver_name, fallbacks)`

Restituisce l'elenco dei solver da provare. Se l'utente specifica un solver, usa solo quello; altrimenti usa l'ordine di fallback.

### `_solver_is_available(name)`

Verifica se Pyomo riesce a usare un solver. Serve per passare automaticamente a HiGHS, CBC o GLPK se Gurobi non è installato.

### `solve_model(model, solver_name=None)`

Risoluzione del MILP.

Prova in ordine:

1. Gurobi;
2. HiGHS via `appsi_highs`;
3. HiGHS classico;
4. CBC;
5. GLPK.

Accetta soluzioni `optimal` o `feasible`. Se il modello è infeasible, salva un file `.lp` in `outputs/` per il debug.

### `extract_first_action(model)`

Estrae solo il controllo del primo intervallo `j = 0` e gli stati successivi `k = 1`.

Questa funzione è fondamentale per MPC: anche se ottimizziamo 24 ore, applichiamo solo la prima decisione.

---

## 6. `mpc.py`

Questo file implementa la simulazione receding horizon.

### `_select_pv_profile(parms, data, forecast=True)`

Sceglie il profilo PV da usare:

- da `res_1_year_pu.mat`, default;
- da irradianza, se configurato.

Permette di cambiare sorgente PV senza modificare il resto del codice.

### `_build_horizon_data(parms, data, k)`

Costruisce il dizionario `horizon_data` per l'ottimizzazione all'ora `k`.

Contiene slice di lunghezza `T` per:

- temperatura esterna forecast;
- PV forecast;
- load forecast;
- prezzi;
- setpoint;
- disponibilità PEV.

Calcola anche `PEV_deadline_step`, cioè la prima ora futura in cui il veicolo non sarà più collegato. Questo dato è usato nel modello per evitare il rinvio infinito della ricarica.

### `run_mpc(parms, data, start_index, n_steps, scenario_name)`

Esegue la simulazione MPC completa.

All'inizio imposta:

- SoC batteria iniziale;
- SoH idrogeno iniziale;
- temperatura interna iniziale uguale al setpoint;
- SoC PEV iniziale;
- target PEV.

Poi per ogni ora:

1. costruisce `horizon_data`;
2. costruisce il modello Pyomo;
3. risolve il MILP;
4. estrae la prima azione;
5. calcola costo e residuo di bilancio;
6. salva una riga nel DataFrame;
7. aggiorna gli stati per l'ora successiva.

La funzione restituisce un `DataFrame` con tutte le variabili utili per analisi, CSV e grafici.

---

## 7. `results.py`

Questo file produce risultati numerici, CSV e grafici.

### `summarize_results(df, parms)`

Calcola indicatori di sintesi:

- costo totale;
- energia importata;
- energia esportata;
- energia DG;
- SoC finale BESS;
- SoH finale HSS;
- SoC finale PEV;
- soddisfazione target PEV;
- violazioni comfort;
- massimo residuo del bilancio di potenza.

Serve per avere una tabella compatta confrontabile tra scenari.

### `save_results(df, summary, output_dir, scenario_name)`

Salva:

- `results_<scenario>.csv`;
- `summary_<scenario>.csv`.

### `_time_axis(df)`

Crea un asse temporale semplice da 0 a `len(df)-1`. Si usa nei grafici per rappresentare le ore simulate.

### `save_plots(df, summary, output_dir, scenario_name)`

Genera i grafici tecnici di base:

- componenti di potenza;
- SoC BESS;
- SoH HSS;
- temperatura interna/esterna/setpoint;
- HVAC;
- PEV;
- rete e prezzi;
- costo cumulato.

Sono grafici utili per debug e analisi tecnica.

### `_style_presentation_axis(ax, title, xlabel, ylabel)`

Applica uno stile comune ai grafici da presentazione. Centralizzare lo stile rende le figure coerenti.

### `_cost_terms(df, parms)`

Calcola il breakdown economico:

- costo importazione;
- costo combustibile DG;
- ricavo export;
- totale netto.

### `_save_microgrid_architecture(output_dir)`

Genera una slide grafica che mostra l'architettura della microgrid: bus elettrico al centro, sorgenti e carichi intorno.

Serve per spiegare il sistema prima di mostrare formule o risultati.

### `_save_mpc_workflow(output_dir)`

Genera una slide che spiega il processo MPC:

1. misura dello stato;
2. forecast;
3. soluzione MILP;
4. applicazione della prima azione;
5. shift dell'orizzonte.

### `save_presentation_plots(df, summary, parms, output_dir, scenario_name)`

Genera grafici "slide-ready" per ogni scenario:

- dispatch supply/demand;
- stati e vincoli;
- analisi economica;
- KPI summary.

Questi grafici sono meno diagnostici e più comunicativi, pensati per la presentazione.

### `save_presentation_overview(summaries, all_results, output_dir)`

Genera grafici trasversali tra scenari:

- confronto scenari;
- confronto costi cumulati;
- README con indice delle figure.

---

## 8. `main.py`

Questo è il punto di ingresso del progetto.

### `_print_summary(summary)`

Stampa a terminale i principali risultati di uno scenario:

- costo totale;
- energia importata/esportata;
- energia DG;
- stati finali;
- comfort;
- target PEV.

### `main()`

Esegue tutta la pipeline:

1. crea la cartella output;
2. carica i dataset;
3. cicla sui quattro scenari;
4. aggiorna il costo combustibile;
5. lancia `run_mpc`;
6. calcola summary;
7. salva CSV;
8. genera plot tecnici;
9. genera plot da presentazione;
10. salva la summary complessiva;
11. genera i grafici di confronto tra scenari.

La riga:

```python
if __name__ == "__main__":
    main()
```

permette di eseguire il progetto con:

```bash
python main.py
```

---

## 9. `requirements.txt`

Contiene le dipendenze:

- `pyomo`: modellazione MILP;
- `numpy`: array e calcolo numerico;
- `pandas`: tabelle, DataFrame, date;
- `scipy`: lettura file `.mat`;
- `matplotlib`: grafici;
- `highspy`: solver HiGHS;
- `isort`: ordinamento import e integrazione VSCode.

---

## 10. `.vscode/settings.json`

Configura VSCode per usare il Python del virtual environment:

```text
.venv/bin/python
```

e per far usare a `isort` lo stesso interprete. Questo evita banner di errore dovuti a strumenti installati in un ambiente diverso.

---

## 11. Perché il codice è modulare

Il progetto è diviso in moduli per separare le responsabilità:

- `config.py`: parametri;
- `data_loader.py`: dati;
- `model.py`: matematica MILP;
- `mpc.py`: logica receding horizon;
- `results.py`: output e grafici;
- `main.py`: orchestrazione.

Questa separazione rende il progetto più facile da:

- spiegare;
- testare;
- modificare;
- estendere.

Per esempio, se si vuole cambiare solo il modello HVAC, si lavora in `model.py`. Se si vuole cambiare il giorno di simulazione, si lavora in `config.py`. Se si vogliono cambiare i grafici, si lavora in `results.py`.

---

## 12. Come spiegare il flusso durante una presentazione

Una spiegazione efficace può seguire questo ordine:

1. **Sistema fisico**: microgrid con PV, BESS, HSS, DG, HVAC, UPL, PEV e rete.
2. **Dati**: dataset annuali, forecast/actual, prezzi e carichi.
3. **Modello MILP**: variabili continue e binarie, vincolo di bilancio, dinamiche degli stati.
4. **MPC**: ottimizzo 24 ore, applico solo la prima azione, aggiorno stati.
5. **Scenari**: estate/inverno e combustibile economico/costoso.
6. **Risultati**: costi, energia importata, uso DG, comfort, target PEV.
7. **Grafici presentation**: architettura, workflow MPC, dispatch, stati e confronto scenari.

