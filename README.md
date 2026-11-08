# Mappa Castagne — Campo dei Fiori & Sacro Monte di Varese

Web app interattiva pensata per chi nel fine settimana vuole andare a raccogliere **castagne** (*Castanea sativa*) sul **Massiccio del Campo dei Fiori e Sacro Monte di Varese**, anche direttamente dal **telefono mentre cammina nel bosco**.

---

## Il Vantaggio Strategico: Le 3 Fasce di Colore dai Sentieri

Chi va a castagne la domenica si ferma quasi sempre nei primi metri a bordo sentiero. L'applicazione incrocia i **boschi di castagno reali** (da OpenStreetMap), la **rete dei sentieri** (1.045 tracciati) e la **pendenza del terreno** (da modello altimetrico DEM a 13 metri), tagliando via automaticamente i dirupi pericolosi e dividendo il castagneto camminabile in **3 fasce di colore**:

- **Fascia GIALLA (es. 0–45 m dal sentiero)** — *Vicino al sentiero*: zona comodissima ma già battuta da tutti i passanti.
- **Fascia ARANCIONE (es. 45–110 m dal sentiero)** — *Zona Strategica Consigliata*: il punto d'oro fuori vista dal sentiero ma comodo e sicuro per rientrare col sacchetto pieno.
- **Fascia ROSSA (es. 110–220 m dal sentiero)** — *Bosco Profondo*: zona più interna e meno battuta in assoluto, sempre su terreno con pendenza sicura.

---

## Funzionalità Principali (Pensate per l'Uso su Telefono)

1. **Mappa Chiara e Sentieri Evidenti**: mappa luminosa ad alto contrasto (leggibile anche sotto la luce del sole) con sentieri CAI e tracce boschive bordati e tratteggiati per distinguerli subito, più vista **Satellite** con un tocco.
2. **Scelta Rapida dei Paesini**: barra scorrevole con i paesini del massiccio (**Brinzio**, **Orino**, **Castello Cabiaglio**, **Rasa di Varese**, **Sacro Monte**, **Velate**, **Luvinate & Barasso**, **Comerio & Caldana**) ed etichette grandi sulla mappa.
3. **Controlli Semplici a Portata di Pollice**:
   - **Slider "Quando inizia la zona buona (Arancione)?"**: decidi tu a quanti metri dal sentiero far partire la fascia strategica (`25 m` – `85 m`) e i colori si aggiornano in tempo reale (0 ms).
   - **3 Bottoni per il Terreno**: **Solo Pianori** ($\le 22\%$), **Normale** ($\le 32\%$), **Anche Ripido** ($\le 42\%$), più spunta opzionale per mostrare i dirupi da evitare.
4. **Pulsante GPS "Dove sono"**: ti segue in tempo reale mentre cammini sul sentiero per farti vedere quando hai di fianco una macchia Arancione o Rossa pianeggiante in cui entrare.
5. **Tocco su un Punto & Parcheggi (`P`)**: toccando qualsiasi punto del bosco ti dice subito in che paesino sei, a quanti metri sei dal sentiero, com'è il terreno e ti apre **Google Maps** per raggiungere il parcheggio più vicino.

---

## Requisiti e Avvio in Locale

### 1. Installazione dipendenze
```bash
pip install -r requirements.txt
```

### 2. Avvio dell'applicazione
```bash
python app.py
```

Apri il browser (su PC o smartphone collegato alla stessa rete) all'indirizzo:
```text
http://127.0.0.1:8000
```

### 3. Rigenerazione Dati OpenStreetMap / DEM (Opzionale)
I dati del Campo dei Fiori sono già inclusi e pronti nella cartella `data/`. Per riscaricarli da zero tramite Overpass API e AWS Terrarium DEM:
```bash
python scripts/fetch_and_process_gis.py --refresh
```
