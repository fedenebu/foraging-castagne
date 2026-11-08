/**
 * Mappa Strategica per Andare a Castagne — Campo dei Fiori & Sacro Monte di Varese
 * Interfaccia semplice e mobile-first con:
 * - 3 fasce di colore (Gialla, Arancione, Rossa)
 * - Salvataggio posti segreti con coordinate (localStorage)
 * - Salvagente offline se nel bosco sparisce il segnale 4G
 */

const SAVED_SPOTS_KEY = "castagne_saved_spots_v1";

const state = {
  near_m: 45,
  max_slope: 32,
  showSteep: false,
  showTrails: true,
  isSatellite: false,
  activeBands: {
    yellow: true,
    orange: true,
    red: true,
  },
  villages: [],
  parkings: [],
  spotMarker: null,
  lastInspectedSpot: null,
  gpsMarker: null,
  gpsWatchId: null,
  lastGpsCoords: null,
  savedSpots: [],
  savedMarkers: [],
};

const OVERVIEW_CAMERA = {
  center: [8.7765, 45.8735],
  zoom: 12.6,
  pitch: 0,
  bearing: 0,
};

let map = null;
let toastTimer = null;

async function initApp() {
  loadSavedSpotsFromStorage();
  bindUI();

  const res = await fetch("/api/map-data");
  const data = await res.json();
  state.villages = data.villages || [];

  // Estrai i parcheggi anche lato client per il salvagente offline
  if (data.landmarks && data.landmarks.features) {
    state.parkings = data.landmarks.features
      .filter((f) => f.properties && f.properties.category === "parking")
      .map((f) => ({
        name: f.properties.name || "Parcheggio",
        lon: f.geometry.coordinates[0],
        lat: f.geometry.coordinates[1],
      }));
  }

  renderVillagePills(state.villages);
  initMap(data);
}

function showToast(msg) {
  const el = document.getElementById("toastMsg");
  if (!el) return;
  el.textContent = msg;
  el.hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.hidden = true;
  }, 2400);
}

function findNearestVillageLocal(lon, lat) {
  if (!state.villages.length) return { name: "Campo dei Fiori" };
  let best = state.villages[0];
  let bestD = 1e9;
  state.villages.forEach((v) => {
    const d = Math.pow(lon - v.lon, 2) + Math.pow(lat - v.lat, 2);
    if (d < bestD) {
      bestD = d;
      best = v;
    }
  });
  return best;
}

function findNearestParkingLocal(lon, lat) {
  if (!state.parkings.length) {
    return { name: "Parcheggio locale", lon, lat, dist_m: 250 };
  }
  let best = state.parkings[0];
  let bestD2 = 1e9;
  state.parkings.forEach((p) => {
    const d2 = Math.pow((lon - p.lon) * 77500, 2) + Math.pow((lat - p.lat) * 111132, 2);
    if (d2 < bestD2) {
      bestD2 = d2;
      best = p;
    }
  });
  return {
    name: best.name,
    lon: best.lon,
    lat: best.lat,
    dist_m: Math.round(Math.sqrt(bestD2)),
  };
}

/**
 * Gestione Posti Salvati (localStorage + Marker sulla mappa)
 */
function loadSavedSpotsFromStorage() {
  try {
    const raw = localStorage.getItem(SAVED_SPOTS_KEY);
    state.savedSpots = raw ? JSON.parse(raw) : [];
  } catch (e) {
    state.savedSpots = [];
  }
  updateSavedBadgeAndList();
}

function persistSavedSpots() {
  try {
    localStorage.setItem(SAVED_SPOTS_KEY, JSON.stringify(state.savedSpots));
  } catch (e) {
    // ignore storage errors
  }
  updateSavedBadgeAndList();
  renderSavedMarkersOnMap();
}

function saveNewSpot(lon, lat, defaultVillage) {
  const vName = defaultVillage || findNearestVillageLocal(lon, lat).name;
  const count = state.savedSpots.length + 1;
  const customNote = window.prompt(
    `Vuoi dare un nome a questo posto a ${vName}? (Lascia pure così o scrivi una nota)`,
    `Castagne ${vName} #${count}`
  );
  if (customNote === null) return; // Utente ha premuto Annulla

  const now = new Date();
  const dateStr = now.toLocaleDateString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  const item = {
    id: `spot_${Date.now()}`,
    title: customNote.trim() || `Castagne ${vName} #${count}`,
    village: vName,
    lon: Number(lon.toFixed(6)),
    lat: Number(lat.toFixed(6)),
    date: dateStr,
  };

  state.savedSpots.unshift(item);
  persistSavedSpots();
  showToast(`Salvato: ${item.title}`);
}

function renderSavedMarkersOnMap() {
  if (!map) return;
  state.savedMarkers.forEach((m) => m.remove());
  state.savedMarkers = [];

  state.savedSpots.forEach((s) => {
    const el = document.createElement("div");
    el.className = "saved-spot-pin";
    el.title = `${s.title} (${s.lat}, ${s.lon})`;
    el.innerHTML = `
      <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
        <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
      </svg>
    `;
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openSpotInfo(s.lon, s.lat);
    });

    const marker = new maplibregl.Marker({ element: el })
      .setLngLat([s.lon, s.lat])
      .addTo(map);
    state.savedMarkers.push(marker);
  });
}

function updateSavedBadgeAndList() {
  const badge = document.getElementById("savedCountBadge");
  if (badge) badge.textContent = String(state.savedSpots.length);

  const container = document.getElementById("savedListContainer");
  const footer = document.getElementById("savedDrawerFooter");
  if (!container) return;

  if (state.savedSpots.length === 0) {
    container.innerHTML = `
      <p style="font-size: 0.80rem; color: #57534e; padding: 12px 4px;">
        Non hai ancora salvato nessun posto. Quando trovi tante castagne, premi <strong>"Segna posto"</strong> a destra o <strong>"Salva posto"</strong> nella scheda del punto!
      </p>
    `;
    if (footer) footer.hidden = true;
    return;
  }

  if (footer) footer.hidden = false;
  container.innerHTML = "";

  state.savedSpots.forEach((s) => {
    const row = document.createElement("div");
    row.className = "saved-item-card";
    row.innerHTML = `
      <div class="saved-item-info">
        <span class="saved-item-title">${s.title}</span>
        <span class="saved-item-coords">${s.lat.toFixed(5)}, ${s.lon.toFixed(5)}</span>
        <span class="saved-item-date">${s.village} · ${s.date}</span>
      </div>
      <div class="saved-item-actions">
        <button type="button" class="btn-mini btn-copy-one" title="Copia coordinate">Copia</button>
        <a href="https://www.google.com/maps/search/?api=1&query=${s.lat},${s.lon}" target="_blank" rel="noopener" class="btn-mini">Maps</a>
        <button type="button" class="btn-mini btn-mini-del" title="Elimina">✕</button>
      </div>
    `;

    row.querySelector(".saved-item-info").addEventListener("click", () => {
      document.getElementById("savedDrawer").hidden = true;
      if (map) {
        map.flyTo({ center: [s.lon, s.lat], zoom: 15.2, duration: 700 });
      }
      openSpotInfo(s.lon, s.lat);
    });

    row.querySelector(".btn-copy-one").addEventListener("click", () => {
      navigator.clipboard.writeText(`${s.lat}, ${s.lon}`);
      showToast(`Coordinate copiate: ${s.lat}, ${s.lon}`);
    });

    row.querySelector(".btn-mini-del").addEventListener("click", () => {
      state.savedSpots = state.savedSpots.filter((x) => x.id !== s.id);
      persistSavedSpots();
    });

    container.appendChild(row);
  });
}

function renderVillagePills(villages) {
  const bar = document.getElementById("villagesBar");
  villages.forEach((v) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "village-pill";
    btn.dataset.village = v.id;
    btn.textContent = v.name;
    btn.addEventListener("click", () => {
      document.querySelectorAll(".village-pill").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("currentVillageStatus").textContent = `${v.name} — ${v.desc}`;
      if (map) {
        map.flyTo({
          center: [v.lon, v.lat],
          zoom: v.zoom || 14.3,
          duration: 850,
        });
      }
    });
    bar.appendChild(btn);
  });

  const allBtn = bar.querySelector('[data-village="all"]');
  if (allBtn) {
    allBtn.addEventListener("click", () => {
      document.querySelectorAll(".village-pill").forEach((b) => b.classList.remove("active"));
      allBtn.classList.add("active");
      document.getElementById("currentVillageStatus").textContent = "Campo dei Fiori & Sacro Monte (VA)";
      if (map) {
        map.flyTo({
          center: OVERVIEW_CAMERA.center,
          zoom: OVERVIEW_CAMERA.zoom,
          duration: 850,
        });
      }
    });
  }
}

function initMap(data) {
  const styleSpec = {
    version: 8,
    sources: {
      "outdoor-light": {
        type: "raster",
        tiles: [
          "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
          "https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
        ],
        tileSize: 256,
        attribution: "&copy; OpenStreetMap &copy; CARTO",
      },
      "satellite-imagery": {
        type: "raster",
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: 256,
        attribution: "&copy; Esri",
      },
    },
    layers: [
      {
        id: "outdoor-light-layer",
        type: "raster",
        source: "outdoor-light",
        layout: { visibility: "visible" },
      },
      {
        id: "satellite-layer",
        type: "raster",
        source: "satellite-imagery",
        layout: { visibility: "none" },
      },
    ],
  };

  map = new maplibregl.Map({
    container: "map",
    style: styleSpec,
    center: OVERVIEW_CAMERA.center,
    zoom: OVERVIEW_CAMERA.zoom,
    maxPitch: 45,
    attributionControl: false,
  });

  map.addControl(new maplibregl.NavigationControl({ showCompass: true, showZoom: true }), "top-left");
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "metric" }), "bottom-left");

  map.on("load", () => {
    addMapLayers(data);
    updateBandStylesOnGPU();
    renderSavedMarkersOnMap();
  });

  map.on("moveend", () => {
    const c = map.getCenter();
    if (map.getZoom() >= 13.4 && state.villages.length > 0) {
      const best = findNearestVillageLocal(c.lng, c.lat);
      document.getElementById("currentVillageStatus").textContent = `Zona di ${best.name}`;
    }
  });
}

function addMapLayers(data) {
  map.addSource("chestnut-rings", {
    type: "geojson",
    data: data.chestnut_rings,
  });

  map.addLayer({
    id: "chestnut-steep-layer",
    type: "fill",
    source: "chestnut-rings",
    layout: { visibility: "none" },
    paint: {
      "fill-color": "#64748b",
      "fill-opacity": 0.42,
    },
  });

  map.addLayer({
    id: "chestnut-bands-fill",
    type: "fill",
    source: "chestnut-rings",
    paint: {
      "fill-color": "#f97316",
      "fill-opacity": 0.58,
    },
  });

  map.addLayer({
    id: "chestnut-bands-outline",
    type: "line",
    source: "chestnut-rings",
    paint: {
      "line-color": "rgba(120, 53, 15, 0.25)",
      "line-width": 0.8,
    },
  });

  // SENTIERI BEN VISIBILI
  map.addSource("trails-source", {
    type: "geojson",
    data: data.trails,
  });

  map.addLayer({
    id: "trails-casing-layer",
    type: "line",
    source: "trails-source",
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": "#ffffff",
      "line-width": ["interpolate", ["linear"], ["zoom"], 11, 3.0, 14, 5.2, 16, 7.5],
      "line-opacity": 0.92,
    },
  });

  map.addLayer({
    id: "trails-secondary-layer",
    type: "line",
    source: "trails-source",
    filter: ["==", ["get", "tier"], "secondary"],
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": "#44403c",
      "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.4, 14, 2.4, 16, 3.6],
      "line-dasharray": [2, 1.8],
    },
  });

  map.addLayer({
    id: "trails-primary-layer",
    type: "line",
    source: "trails-source",
    filter: ["==", ["get", "tier"], "primary"],
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": "#991b1b",
      "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.8, 14, 3.2, 16, 4.8],
    },
  });

  map.addLayer({
    id: "trails-labels-layer",
    type: "symbol",
    source: "trails-source",
    minzoom: 13.3,
    filter: ["==", ["get", "tier"], "primary"],
    layout: {
      "symbol-placement": "line",
      "text-field": ["get", "name"],
      "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
      "text-size": 11,
      "symbol-spacing": 320,
    },
    paint: {
      "text-color": "#7f1d1d",
      "text-halo-color": "#ffffff",
      "text-halo-width": 2.2,
    },
  });

  // PARCHEGGI (P)
  map.addSource("landmarks-source", {
    type: "geojson",
    data: data.landmarks,
  });

  map.addLayer({
    id: "parking-points-layer",
    type: "circle",
    source: "landmarks-source",
    filter: ["==", ["get", "category"], "parking"],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 5, 14, 8, 16, 10],
      "circle-color": "#2563eb",
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2,
    },
  });

  map.addLayer({
    id: "parking-labels-layer",
    type: "symbol",
    source: "landmarks-source",
    filter: ["==", ["get", "category"], "parking"],
    minzoom: 12.2,
    layout: {
      "text-field": "P",
      "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
      "text-size": 10,
      "text-allow-overlap": true,
    },
    paint: {
      "text-color": "#ffffff",
    },
  });

  // PAESINI PRINCIPALI
  const villagesGeoJSON = {
    type: "FeatureCollection",
    features: state.villages.map((v) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [v.lon, v.lat] },
      properties: { name: v.name, id: v.id },
    })),
  };

  map.addSource("villages-source", {
    type: "geojson",
    data: villagesGeoJSON,
  });

  map.addLayer({
    id: "villages-dots-layer",
    type: "circle",
    source: "villages-source",
    paint: {
      "circle-radius": 5,
      "circle-color": "#78350f",
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2,
    },
  });

  map.addLayer({
    id: "villages-labels-layer",
    type: "symbol",
    source: "villages-source",
    layout: {
      "text-field": ["get", "name"],
      "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
      "text-size": ["interpolate", ["linear"], ["zoom"], 11, 12.5, 14, 15],
      "text-offset": [0, 0.85],
      "text-anchor": "top",
      "text-allow-overlap": true,
    },
    paint: {
      "text-color": "#1c1917",
      "text-halo-color": "#ffffff",
      "text-halo-width": 2.8,
    },
  });

  map.on("click", (e) => {
    openSpotInfo(e.lngLat.lng, e.lngLat.lat);
  });
}

function updateBandStylesOnGPU() {
  const nearM = state.near_m;
  const midM = Math.round(nearM * 2.4);
  const farM = Math.round(nearM * 4.8);
  const maxSlope = state.max_slope;

  document.getElementById("lblMetersYellow").textContent = `0–${nearM} m`;
  document.getElementById("lblMetersOrange").textContent = `${nearM}–${midM} m`;
  document.getElementById("lblMetersRed").textContent = `${midM}–${farM} m`;
  document.getElementById("valNearDist").textContent = `Dopo ${nearM} metri dal sentiero`;
  document.getElementById("sheetSummaryText").textContent = `Zona buona da ${nearM}m dal sentiero · Pend. max ${maxSlope}%`;

  if (!map || !map.getLayer("chestnut-bands-fill")) return;

  const distConditions = [];
  if (state.activeBands.yellow) {
    distConditions.push(["<=", ["get", "dist_max_m"], nearM]);
  }
  if (state.activeBands.orange) {
    distConditions.push([
      "all",
      [">", ["get", "dist_max_m"], nearM],
      ["<=", ["get", "dist_max_m"], midM],
    ]);
  }
  if (state.activeBands.red) {
    distConditions.push([
      "all",
      [">", ["get", "dist_max_m"], midM],
      ["<=", ["get", "dist_max_m"], farM],
    ]);
  }

  if (distConditions.length === 0) {
    map.setFilter("chestnut-bands-fill", ["==", ["get", "dist_max_m"], -1]);
    map.setFilter("chestnut-bands-outline", ["==", ["get", "dist_max_m"], -1]);
  } else {
    const combinedFilter = [
      "all",
      ["<=", ["get", "slope_max_pct"], maxSlope],
      ["any", ...distConditions],
    ];
    map.setFilter("chestnut-bands-fill", combinedFilter);
    map.setFilter("chestnut-bands-outline", combinedFilter);
  }

  map.setPaintProperty("chestnut-bands-fill", "fill-color", [
    "step",
    ["get", "dist_max_m"],
    "#facc15",
    nearM + 1,
    "#f97316",
    midM + 1,
    "#dc2626",
  ]);

  if (map.getLayer("chestnut-steep-layer")) {
    map.setLayoutProperty(
      "chestnut-steep-layer",
      "visibility",
      state.showSteep ? "visible" : "none"
    );
    map.setFilter("chestnut-steep-layer", [">", ["get", "slope_max_pct"], maxSlope]);
  }
}

/**
 * Salvagente Offline: se nel bosco sparisce il 4G, calcola i dati del punto
 * direttamente dal browser usando i poligoni già presenti sulla mappa.
 */
function computeOfflineSpotFallback(lon, lat) {
  const village = findNearestVillageLocal(lon, lat);
  const parking = findNearestParkingLocal(lon, lat);
  const pt = map.project([lon, lat]);
  const features = map.queryRenderedFeatures(pt, {
    layers: ["chestnut-bands-fill", "chestnut-steep-layer"],
  });

  const nearM = state.near_m;
  const midM = Math.round(nearM * 2.4);

  if (features && features.length > 0) {
    const p = features[0].properties;
    const distM = p.dist_m || p.dist_max_m || 50;
    const slopePct = p.slope_pct || 20;
    let band = "orange";
    let bandLabel = "Zona Arancione — Fascia Strategica";
    let advice = `Ottimo posto! Sei a circa ${distM} m dentro il bosco su terreno sicuro.`;

    if (slopePct > state.max_slope) {
      band = "steep";
      bandLabel = "Zona Troppo Ripida";
      advice = "Terreno ripido per raccogliere comodi.";
    } else if (distM <= nearM) {
      band = "yellow";
      bandLabel = "Zona Gialla — Vicino al Sentiero";
      advice = `Sei a circa ${distM} m dal sentiero: zona comoda ma già battuta.`;
    } else if (distM > midM) {
      band = "red";
      bandLabel = "Zona Rossa — Bosco Profondo";
      advice = `Zona isolata (circa ${distM} m dal sentiero) e terreno sicuro.`;
    }

    return {
      lon: Number(lon.toFixed(6)),
      lat: Number(lat.toFixed(6)),
      village_name: village.name,
      elev_m: 600,
      slope_pct: slopePct,
      terrain_desc: slopePct <= 18 ? "Pianeggiante / Comodo" : "Pendio camminabile",
      dist_trail_m: distM,
      nearest_trail: "Sentiero nel bosco",
      band,
      band_label: bandLabel,
      advice,
      parking,
    };
  }

  return {
    lon: Number(lon.toFixed(6)),
    lat: Number(lat.toFixed(6)),
    village_name: village.name,
    elev_m: 580,
    slope_pct: 15,
    terrain_desc: "Area esterna al castagneto",
    dist_trail_m: 80,
    nearest_trail: "Sentiero locale",
    band: "outside",
    band_label: "Fuori dal Castagneto",
    advice: "Spostati sulle zone colorate in Giallo, Arancione o Rosso.",
    parking,
  };
}

async function openSpotInfo(lon, lat) {
  if (lon < 8.70 || lon > 8.85 || lat < 45.83 || lat > 45.92) return;

  if (!state.spotMarker) {
    state.spotMarker = new maplibregl.Marker({ color: "#ea580c" })
      .setLngLat([lon, lat])
      .addTo(map);
  } else {
    state.spotMarker.setLngLat([lon, lat]);
  }

  let info = null;
  try {
    const qs = new URLSearchParams({
      lon: lon.toFixed(6),
      lat: lat.toFixed(6),
      near_m: state.near_m,
      max_slope: state.max_slope,
    });
    const res = await fetch(`/api/spot-info?${qs.toString()}`);
    if (res.ok) {
      info = await res.json();
    } else {
      info = computeOfflineSpotFallback(lon, lat);
    }
  } catch (err) {
    // Salvagente offline se nel bosco non c'è segnale 4G
    info = computeOfflineSpotFallback(lon, lat);
  }

  state.lastInspectedSpot = info;

  const sheet = document.getElementById("spotSheet");
  sheet.hidden = false;

  const dot = document.getElementById("spotColorDot");
  const colorMap = {
    yellow: "#facc15",
    orange: "#f97316",
    red: "#dc2626",
    steep: "#64748b",
    outside: "#a8a29e",
    deep: "#991b1b",
  };
  dot.style.background = colorMap[info.band] || "#f97316";

  document.getElementById("spotBandTitle").textContent = info.band_label;
  document.getElementById("spotVillageTitle").textContent = `Zona di ${info.village_name}`;
  document.getElementById("spotCoordsText").textContent = `${info.lat.toFixed(5)}, ${info.lon.toFixed(5)}`;
  document.getElementById("spotAdvice").textContent = info.advice;

  document.getElementById("spotDistValue").textContent = `A ${info.dist_trail_m} metri`;
  document.getElementById("spotTrailName").textContent = info.nearest_trail;
  document.getElementById("spotSlopeValue").textContent = `${info.terrain_desc} (${info.slope_pct}%)`;
  document.getElementById("spotElevValue").textContent = `Quota ${info.elev_m} m s.l.m.`;

  const p = info.parking;
  document.getElementById("parkingBtnText").textContent = `Parcheggio a ${p.dist_m}m (${p.name})`;
  document.getElementById("linkParkingMaps").href = `https://www.google.com/maps/dir/?api=1&destination=${p.lat},${p.lon}&travelmode=driving`;
  document.getElementById("linkPointMaps").href = `https://www.google.com/maps/search/?api=1&query=${info.lat},${info.lon}`;
}

function toggleLiveGPS() {
  const btn = document.getElementById("btnMyLocation");
  const label = document.getElementById("gpsBtnText");

  if (!navigator.geolocation) {
    alert("Il GPS non è disponibile su questo dispositivo.");
    return;
  }

  if (state.gpsWatchId !== null) {
    navigator.geolocation.clearWatch(state.gpsWatchId);
    state.gpsWatchId = null;
    btn.classList.remove("tracking");
    label.textContent = "Dove sono";
    return;
  }

  btn.classList.add("tracking");
  label.textContent = "GPS attivo";

  state.gpsWatchId = navigator.geolocation.watchPosition(
    (pos) => {
      const { longitude, latitude } = pos.coords;
      state.lastGpsCoords = { lon: longitude, lat: latitude };

      if (!state.gpsMarker) {
        const el = document.createElement("div");
        el.className = "gps-user-dot";
        state.gpsMarker = new maplibregl.Marker({ element: el })
          .setLngLat([longitude, latitude])
          .addTo(map);
      } else {
        state.gpsMarker.setLngLat([longitude, latitude]);
      }

      map.flyTo({
        center: [longitude, latitude],
        zoom: Math.max(map.getZoom(), 15),
        duration: 700,
      });

      openSpotInfo(longitude, latitude);
    },
    () => {
      btn.classList.remove("tracking");
      label.textContent = "Dove sono";
      state.gpsWatchId = null;
      alert("Attiva il permesso di posizione sul telefono per vedere dove ti trovi sul sentiero.");
    },
    { enableHighAccuracy: true, maximumAge: 5000 }
  );
}

function bindUI() {
  // 1. Slider lontananza dal sentiero
  const sliderNear = document.getElementById("sliderNearDist");
  sliderNear.addEventListener("input", () => {
    state.near_m = Number(sliderNear.value);
    updateBandStylesOnGPU();
  });

  // 2. Scelta pendenza terreno
  document.querySelectorAll(".slope-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".slope-btn").forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-checked", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-checked", "true");
      state.max_slope = Number(btn.dataset.slope);
      updateBandStylesOnGPU();
    });
  });

  // 3. Checkbox mostra dirupi ripidi
  document.getElementById("chkShowSteep").addEventListener("change", (e) => {
    state.showSteep = e.target.checked;
    updateBandStylesOnGPU();
  });

  // 4. Tocco sui 3 riquadri colore
  document.querySelectorAll(".band-card").forEach((card) => {
    card.addEventListener("click", () => {
      const bandKey = card.dataset.band;
      state.activeBands[bandKey] = !state.activeBands[bandKey];
      card.classList.toggle("active", state.activeBands[bandKey]);
      updateBandStylesOnGPU();
    });
  });

  // 5. Bottone Sentieri On/Off
  document.getElementById("btnToggleTrails").addEventListener("click", (e) => {
    state.showTrails = !state.showTrails;
    e.currentTarget.classList.toggle("active", state.showTrails);
    const vis = state.showTrails ? "visible" : "none";
    ["trails-casing-layer", "trails-secondary-layer", "trails-primary-layer", "trails-labels-layer"].forEach((id) => {
      if (map && map.getLayer(id)) map.setLayoutProperty(id, "visibility", vis);
    });
  });

  // 6. Bottone Vista Satellite
  document.getElementById("btnToggleSat").addEventListener("click", (e) => {
    state.isSatellite = !state.isSatellite;
    e.currentTarget.classList.toggle("active", state.isSatellite);
    if (!map) return;
    map.setLayoutProperty("satellite-layer", "visibility", state.isSatellite ? "visible" : "none");
    map.setLayoutProperty("outdoor-light-layer", "visibility", state.isSatellite ? "none" : "visible");
  });

  // 7. Bottone riduci/espandi pannello in basso
  document.getElementById("btnToggleSheet").addEventListener("click", () => {
    const sheet = document.getElementById("bottomSheet");
    const isCollapsed = sheet.classList.toggle("collapsed");
    document.getElementById("btnToggleSheet").setAttribute("aria-expanded", String(!isCollapsed));
    document.getElementById("sheetToggleLabel").textContent = isCollapsed ? "Apri filtri" : "Riduci";
  });

  // 8. Chiudi scheda punto toccato
  document.getElementById("btnCloseSpot").addEventListener("click", () => {
    document.getElementById("spotSheet").hidden = true;
    if (state.spotMarker) {
      state.spotMarker.remove();
      state.spotMarker = null;
    }
  });

  // 9. Bottone GPS "Dove sono"
  document.getElementById("btnMyLocation").addEventListener("click", toggleLiveGPS);

  // 10. Pulsantino discreto "+ Segna posto" (salva posizione GPS attuale, punto toccato o centro mappa)
  document.getElementById("btnQuickSaveSpot").addEventListener("click", () => {
    if (state.lastGpsCoords) {
      saveNewSpot(state.lastGpsCoords.lon, state.lastGpsCoords.lat);
    } else if (state.lastInspectedSpot && !document.getElementById("spotSheet").hidden) {
      saveNewSpot(state.lastInspectedSpot.lon, state.lastInspectedSpot.lat, state.lastInspectedSpot.village_name);
    } else if (map) {
      const c = map.getCenter();
      saveNewSpot(c.lng, c.lat);
    }
  });

  // 11. Bottone "Salva posto" dentro la scheda del punto toccato
  document.getElementById("btnSaveFromSheet").addEventListener("click", () => {
    if (state.lastInspectedSpot) {
      saveNewSpot(
        state.lastInspectedSpot.lon,
        state.lastInspectedSpot.lat,
        state.lastInspectedSpot.village_name
      );
    }
  });

  // 12. Apertura/Chiusura Cassetto Posti Salvati
  document.getElementById("btnOpenSavedList").addEventListener("click", () => {
    const drawer = document.getElementById("savedDrawer");
    drawer.hidden = !drawer.hidden;
  });

  document.getElementById("btnCloseSavedDrawer").addEventListener("click", () => {
    document.getElementById("savedDrawer").hidden = true;
  });

  document.getElementById("btnCopyAllSaved").addEventListener("click", () => {
    if (!state.savedSpots.length) return;
    const text = state.savedSpots
      .map((s) => `${s.title} (${s.village} - ${s.date}): ${s.lat}, ${s.lon}`)
      .join("\n");
    navigator.clipboard.writeText(text);
    showToast("Tutte le coordinate copiate negli appunti!");
  });
}

document.addEventListener("DOMContentLoaded", initApp);
