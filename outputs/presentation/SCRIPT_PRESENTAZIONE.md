# Script presentazione progetto Smart District MILP-MPC

Durata indicativa: 10-12 minuti.  
Le frasi sono scritte come copione parlato: potete leggerle direttamente oppure usarle come traccia.

---

## Slide introduttiva - Problema, obiettivo e contesto

Buongiorno, oggi presentiamo il nostro progetto di gestione energetica per uno smart district, cioè un piccolo distretto energetico composto da più sorgenti, accumuli e carichi.

Il problema di partenza è questo: in un sistema reale la domanda elettrica, la produzione fotovoltaica, i prezzi dell'energia e le condizioni ambientali cambiano continuamente. Quindi non basta decidere una strategia fissa una volta per tutte. Serve un controllore capace di prendere decisioni ora per ora, usando le informazioni disponibili e rispettando vincoli fisici ed economici.

Nel nostro caso il distretto include fotovoltaico, rete elettrica, batteria, sistema a idrogeno con elettrolizzatore e fuel cell, generatore distribuito non rinnovabile, carico uffici, HVAC per il comfort termico e ricarica di un veicolo elettrico. L'obiettivo è minimizzare il costo operativo, ma senza violare i vincoli fondamentali: bilancio di potenza, limiti degli accumuli, comfort indoor e target di ricarica del veicolo.

Per risolvere questo problema abbiamo usato un approccio di ottimizzazione chiamato Model Predictive Control, o MPC. L'idea è semplice: a ogni ora guardiamo avanti sulle prossime 24 ore, ottimizziamo il comportamento del sistema, applichiamo solo la prima decisione e poi ripetiamo tutto all'ora successiva con gli stati aggiornati.

Per implementare il modello matematico abbiamo usato Pyomo, una libreria Python per formulare problemi di ottimizzazione. Pyomo ci permette di descrivere variabili, vincoli e funzione obiettivo in modo leggibile, restando vicini alla formulazione matematica. In particolare, il nostro modello è un MILP, cioè un problema lineare misto-intero: contiene variabili continue, come potenze e stati di carica, e variabili binarie, usate per rappresentare modalità operative come import/export, carica/scarica della batteria o riscaldamento/raffrescamento.

---

## Slide 00 - Architettura della microgrid

In questa slide vediamo l'architettura del sistema modellato.

Al centro c'è il bus elettrico, che rappresenta il nodo comune in cui devono bilanciarsi produzione e consumo. Sul lato della generazione troviamo il fotovoltaico, la rete elettrica in importazione, il generatore distribuito e la fuel cell del sistema a idrogeno. Sul lato dei consumi troviamo il carico uffici, l'HVAC, la ricarica del veicolo elettrico, la batteria quando si carica e l'elettrolizzatore quando produce idrogeno.

Il punto importante è che tutti questi componenti non vengono gestiti separatamente. Il modello li coordina insieme: se il fotovoltaico è disponibile può alimentare i carichi o caricare gli accumuli; se il prezzo dell'energia è alto conviene ridurre l'importazione dalla rete; se il combustibile del generatore è economico può essere conveniente usarlo di più; se invece è costoso il controllore tende a evitarlo.

Il vincolo centrale è il bilancio di potenza: in ogni ora, l'energia che entra nel bus deve essere uguale all'energia che esce. A questo si aggiungono i vincoli dei singoli dispositivi, come potenza massima, rendimento, stato di carica minimo e massimo, e modalità operative compatibili.

---

## Slide 01 - Workflow MPC

Questa slide descrive il funzionamento del controllo predittivo.

Il ciclo parte dalla misura dello stato corrente: stato di carica della batteria, stato del serbatoio a idrogeno, temperatura interna e stato di carica del veicolo elettrico. Poi vengono costruite le previsioni per le successive 24 ore: temperatura esterna, produzione fotovoltaica, carico non controllabile, prezzi dell'energia, setpoint termico e disponibilità del veicolo.

A questo punto Pyomo costruisce il problema MILP e lo passa a un solver. Il solver restituisce la sequenza ottima di decisioni per tutte le 24 ore dell'orizzonte, ma nella simulazione applichiamo solo la prima ora. Questa è la logica receding horizon: dopo un'ora aggiorniamo gli stati e ricalcoliamo tutto.

Questo approccio è utile perché combina pianificazione e adattamento. Pianifica perché guarda avanti e considera cosa succederà nelle prossime ore; si adatta perché ogni ora corregge la strategia in base allo stato effettivo raggiunto.

---

## Slide metodologia - Formulazione Pyomo del modello

Nel codice il modello è costruito nel file `model.py` attraverso una funzione che genera un `ConcreteModel` Pyomo.

Le variabili principali sono le potenze scambiate con la rete, la potenza fotovoltaica eventualmente tagliata, la carica e scarica della batteria, la fuel cell, l'elettrolizzatore, il generatore, HVAC e ricarica PEV. Gli stati dinamici sono invece lo stato di carica della batteria, lo stato dell'idrogeno e la temperatura interna.

Le variabili binarie servono a impedire comportamenti non fisici. Per esempio, il modello non può importare ed esportare energia nello stesso momento; la batteria non può caricarsi e scaricarsi contemporaneamente; il sistema HVAC non può riscaldare e raffrescare nello stesso intervallo; fuel cell ed elettrolizzatore non possono lavorare insieme.

La funzione obiettivo minimizza il costo dell'energia importata dalla rete, più il costo del combustibile del generatore, meno i ricavi dell'energia esportata. Abbiamo aggiunto anche penalità molto alte per eventuali violazioni del comfort o del target PEV. Queste variabili di slack servono a evitare infeasibility numeriche, ma essendo molto penalizzate il solver le usa solo se necessario.

---

## Slide dati e scenari

Per alimentare il modello abbiamo usato dati annuali con risoluzione oraria. Il codice carica temperatura esterna, irradianza, profilo fotovoltaico, carico uffici e PUN. A questi dati vengono aggiunti profili costruiti nel progetto, come le fasce tariffarie F1, F2 e F3, il setpoint termico stagionale e la disponibilità del veicolo elettrico.

Abbiamo simulato quattro scenari di 48 ore:

- Scenario A: estate con costo combustibile basso, pari a 0,15 euro per kWh.
- Scenario B: estate con costo combustibile alto, pari a 0,45 euro per kWh.
- Scenario C: inverno con costo combustibile basso.
- Scenario D: inverno con costo combustibile alto.

Questa scelta ci permette di isolare due effetti: il cambio di stagione, quindi carichi e temperatura diversi, e il cambio del prezzo del combustibile, che influenza direttamente l'utilizzo del generatore distribuito.

---

## Slide 02 - Confronto tra scenari

In questa slide confrontiamo i risultati principali dei quattro scenari.

Il primo elemento da osservare è il costo totale. Gli scenari con combustibile economico hanno costo più basso: circa 3695 euro in estate e 3009 euro in inverno. Quando il combustibile diventa costoso, il costo sale a circa 5519 euro in estate e 4709 euro in inverno.

Il secondo elemento è l'energia importata dalla rete. Quando il combustibile costa poco, il modello usa molto il generatore distribuito e importa meno: circa 4930 kWh nello scenario A e 3774 kWh nello scenario C. Quando invece il combustibile costa di più, il generatore diventa meno conveniente e l'importazione cresce: circa 10678 kWh nello scenario B e 9532 kWh nello scenario D.

Questo conferma che il modello sta prendendo decisioni coerenti dal punto di vista economico: sposta la fornitura verso la risorsa meno costosa, rispettando i vincoli operativi.

Un altro risultato importante è il PEV: in tutti gli scenari il target finale di stato di carica viene soddisfatto, arrivando a 0,80 p.u. Inoltre, le violazioni di comfort sono praticamente nulle.

---

## Slide 03 - Costo cumulativo

Questa figura mostra come evolve il costo cumulativo nel tempo.

Le curve permettono di vedere non solo il costo finale, ma anche quando il costo cresce più rapidamente. In generale, il costo aumenta nelle ore in cui il sistema deve importare più energia oppure usare risorse costose. Le differenze tra scenari diventano evidenti proprio perché il controllore reagisce in modo diverso al prezzo del combustibile e alle condizioni stagionali.

Il confronto più chiaro è tra scenari con lo stesso periodo ma diverso costo combustibile. In estate, lo scenario B resta sopra lo scenario A; in inverno, lo scenario D resta sopra lo scenario C. Questo significa che il parametro economico del generatore ha un impatto diretto sulla strategia operativa e sul costo finale.

---

## Slide 10 - Dispatch di energia per scenario

Queste slide mostrano il dispatch, cioè come vengono distribuite le potenze tra sorgenti e carichi.

Nella parte superiore vediamo le risorse che alimentano il sistema: rete, fotovoltaico utilizzato, scarica della batteria, fuel cell e generatore distribuito. Nella parte inferiore vediamo come l'energia viene assorbita: carico uffici, HVAC, carica batteria, elettrolizzatore, PEV ed eventuale export.

Il valore di questa visualizzazione è che rende leggibile la logica del controllore. Il modello non decide solo quanto comprare dalla rete, ma coordina più dispositivi contemporaneamente. Per esempio, può usare il generatore quando il combustibile è economico, può importare di più quando il generatore non conviene, può caricare il PEV durante le finestre in cui è disponibile e può mantenere il comfort termico usando HVAC.

Negli scenari A e C, con combustibile basso, il generatore è usato in modo molto marcato: l'energia DG totale è circa 5760 kWh. Negli scenari B e D, con combustibile alto, l'uso del generatore si azzera praticamente, e il sistema compensa importando più energia dalla rete.

---

## Slide 11 - Stati e vincoli operativi

Questa slide verifica che le decisioni del modello rispettino gli stati e i vincoli.

Il primo grafico mostra lo stato di carica della batteria. Il SoC resta sempre entro i limiti ammessi, tra 0,10 e 0,90 p.u., e al termine degli scenari arriva a 0,10 p.u. Questo indica che il controllore sfrutta la batteria fino al limite minimo consentito quando è economicamente utile.

Il secondo grafico mostra lo stato del sistema a idrogeno. In questi risultati lo stato finale resta intorno a 0,50 p.u., quindi il sistema a idrogeno non viene scaricato in modo rilevante nel bilancio finale.

Il terzo grafico riguarda il comfort termico. La temperatura interna resta dentro la fascia di comfort definita dal setpoint più o meno 2 gradi. Questo è importante perché mostra che la minimizzazione del costo non avviene sacrificando il comfort degli utenti.

Infine, il grafico PEV mostra la ricarica del veicolo e il raggiungimento del target. Il veicolo parte da 0,30 p.u. e raggiunge 0,80 p.u., rispettando la finestra di disponibilità serale/notturna.

---

## Slide 12 - Risultato economico

Qui analizziamo la parte economica.

Il costo totale è composto principalmente da costo di importazione dalla rete e costo combustibile del generatore, mentre l'export produce un ricavo. Nel nostro caso l'export è molto limitato: nello scenario A vale circa 5,4 kWh, mentre negli altri scenari è praticamente nullo. Quindi il risultato economico è dominato dalla scelta tra importazione da rete e uso del generatore.

Quando il combustibile costa 0,15 euro per kWh, il generatore è conveniente e viene usato molto. Quando il combustibile costa 0,45 euro per kWh, il modello preferisce importare dalla rete e spegne quasi completamente il generatore.

Questa slide è utile per collegare la formulazione matematica alle decisioni osservate: il solver non segue regole manuali, ma minimizza una funzione obiettivo. Il cambiamento delle decisioni nasce direttamente dai costi e dai vincoli inseriti nel modello.

---

## Slide 13 - KPI di scenario

Questa slide riassume i KPI più importanti per ogni scenario.

Possiamo usarla come chiusura del singolo scenario: costo totale, energia importata, energia esportata, energia prodotta dal generatore, stato finale degli accumuli, violazione del comfort e soddisfacimento del target PEV.

I messaggi principali sono tre.

Primo: il modello rispetta i vincoli di comfort e ricarica. La violazione termica è nulla o numericamente trascurabile, e il target PEV è sempre soddisfatto.

Secondo: il prezzo del combustibile modifica fortemente il ruolo del generatore distribuito. Con combustibile basso il DG produce circa 5760 kWh; con combustibile alto viene evitato.

Terzo: l'MPC produce una strategia dinamica e coerente, perché non ottimizza una singola ora isolata, ma considera le prossime 24 ore e poi aggiorna continuamente la decisione.

---

## Conclusione

In conclusione, il progetto dimostra come un problema di gestione energetica di smart district possa essere formulato come MILP e risolto con Pyomo dentro una logica MPC.

Il vantaggio dell'approccio è che possiamo combinare molti elementi in un unico modello: prezzi, previsioni, accumuli, generatori, comfort, veicoli elettrici e vincoli fisici. Invece di usare regole fisse, il sistema sceglie automaticamente la strategia più conveniente per lo scenario corrente.

Dai risultati emerge che il controllore risponde correttamente agli incentivi economici: quando il combustibile è economico usa il generatore distribuito, mentre quando il combustibile è costoso preferisce la rete. Allo stesso tempo mantiene il comfort termico e garantisce la ricarica del veicolo.

Un possibile sviluppo futuro sarebbe estendere il modello includendo incertezza più realistica nelle previsioni, degrado degli accumuli o scenari di demand response. Però già nella versione attuale il progetto mostra bene il valore dell'ottimizzazione per coordinare sistemi energetici complessi.

---

## Versione breve per chiusura orale

Se dovessimo riassumere tutto in poche frasi: abbiamo modellato uno smart district come problema di ottimizzazione MILP, lo abbiamo implementato in Pyomo e lo abbiamo inserito in un controllo MPC a orizzonte mobile di 24 ore. Il sistema decide ora per ora come usare rete, fotovoltaico, batteria, idrogeno, generatore, HVAC e PEV. I risultati mostrano che il controllore minimizza i costi, cambia strategia quando cambia il prezzo del combustibile e rispetta i vincoli di comfort e ricarica.

