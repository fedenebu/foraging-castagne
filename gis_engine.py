"""
Motore Spaziale Semplificato — Raccolta Castagne (Campo dei Fiori & Sacro Monte di Varese)
Pre-calcola gli anelli di distanza dai sentieri e le fasce di pendenza nei castagneti
in modo che lo slider sul telefono aggiorni i colori (Giallo / Arancione / Rosso) in 0 ms!
"""

import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import box, mapping
from shapely.ops import unary_union

DATA_DIR = Path(__file__).resolve().parent / "data"

VILLAGES = [
    {"id": "brinzio", "name": "Brinzio", "lon": 8.7885, "lat": 45.8881, "zoom": 14.4, "desc": "Selve castanili storiche a nord del massiccio"},
    {"id": "orino", "name": "Orino", "lon": 8.7495, "lat": 45.8825, "zoom": 14.4, "desc": "Castagneti secolari verso la Rocca e Pian delle Noci"},
    {"id": "cabiaglio", "name": "Castello Cabiaglio", "lon": 8.7565, "lat": 45.8920, "zoom": 14.4, "desc": "Grandi selve castanili dolci sul versante nord-ovest"},
    {"id": "rasa", "name": "Rasa di Varese", "lon": 8.8135, "lat": 45.8760, "zoom": 14.4, "desc": "Conca boschiva ricca di castagni e sorgenti dell'Olona"},
    {"id": "sacromonte", "name": "Sacro Monte", "lon": 8.7936, "lat": 45.8608, "zoom": 14.4, "desc": "Versanti boschivi attorno a Santa Maria del Monte"},
    {"id": "velate", "name": "Velate", "lon": 8.7870, "lat": 45.8535, "zoom": 14.5, "desc": "Boschi di castagno pedemontani comodi e soleggiati"},
    {"id": "luvinate", "name": "Luvinate & Barasso", "lon": 8.7715, "lat": 45.8515, "zoom": 14.3, "desc": "Pendici sud del Campo dei Fiori sopra i borghi"},
    {"id": "comerio", "name": "Comerio & Caldana", "lon": 8.7440, "lat": 45.8565, "zoom": 14.3, "desc": "Castagneti del versante sud-occidentale"},
]

DIST_STEPS = [15, 25, 35, 45, 55, 65, 75, 90, 105, 120, 140, 160, 185, 210, 240, 280, 330]
SLOPE_STEPS = [18, 25, 32, 40, 50, 99]


def _merge_cells_to_smooth_polygon(
    mask_2d: np.ndarray,
    west: float,
    south: float,
    dlon: float,
    dlat: float,
) -> Any:
    ny, nx = mask_2d.shape
    row_boxes = []
    pad_lon = dlon * 0.05
    pad_lat = dlat * 0.05

    for iy in range(ny):
        row = mask_2d[iy]
        if not np.any(row):
            continue
        lat0 = south + iy * dlat - pad_lat
        lat1 = south + (iy + 1) * dlat + pad_lat

        padded = np.concatenate(([False], row, [False]))
        starts = np.where(padded[1:] & ~padded[:-1])[0]
        ends = np.where(~padded[1:] & padded[:-1])[0]

        for s, e in zip(starts, ends):
            lon0 = west + s * dlon - pad_lon
            lon1 = west + e * dlon + pad_lon
            row_boxes.append(box(lon0, lat0, lon1, lat1))

    if not row_boxes:
        return None

    merged = unary_union(row_boxes)
    smoothed = merged.buffer(dlon * 0.30, quad_segs=2).buffer(-dlon * 0.18, quad_segs=2)
    if smoothed.is_empty:
        smoothed = merged
    return smoothed.simplify(dlon * 0.12, preserve_topology=True)


class ChestnutForagingEngine:
    def __init__(self) -> None:
        t0 = time.perf_counter()
        self.trails_geojson = json.loads((DATA_DIR / "trails.geojson").read_text(encoding="utf-8"))
        self.landmarks_geojson = json.loads((DATA_DIR / "landmarks.geojson").read_text(encoding="utf-8"))
        grid_raw = json.loads((DATA_DIR / "spatial_grid.json").read_text(encoding="utf-8"))

        dem_npz = np.load(DATA_DIR / "dem_campodeifiori.npz")
        self.dem_full = {k: dem_npz[k] for k in dem_npz.files}

        self.bbox = grid_raw["bbox"]
        self.nx = int(grid_raw["nx"])
        self.ny = int(grid_raw["ny"])
        self.step_m = float(grid_raw["step_m"])
        self.dlon = float(grid_raw["dlon"])
        self.dlat = float(grid_raw["dlat"])
        self.cell_area_ha = (self.step_m * self.step_m) / 10000.0

        cells = grid_raw["cells"]
        self.cells_list = cells
        n = len(cells)
        self.n_cells = n

        self.ix = np.array([c["ix"] for c in cells], dtype=np.int32)
        self.iy = np.array([c["iy"] for c in cells], dtype=np.int32)
        self.lon = np.array([c["lon"] for c in cells], dtype=np.float64)
        self.lat = np.array([c["lat"] for c in cells], dtype=np.float64)
        self.elev_m = np.array([c["elev_m"] for c in cells], dtype=np.float32)
        self.slope_pct = np.array([c["slope_pct"] for c in cells], dtype=np.float32)
        self.dist_trail_m = np.array([c["dist_trail_m"] for c in cells], dtype=np.float32)
        self.forest_types = [c["forest_type"] for c in cells]
        self.nearest_trails = [c["nearest_trail"] for c in cells]

        # Solo boschi vocati a Castagne (castagneto + bosco misto fino a 880m)
        self.is_chestnut_wood = np.array(
            [
                (c["forest_type"] == "castagneto")
                or (c["forest_type"] == "misto" and c["elev_m"] <= 880)
                for c in cells
            ],
            dtype=bool,
        )

        # Estrai tutti i parcheggi
        self.parkings = []
        for feat in self.landmarks_geojson["features"]:
            if feat["properties"].get("category") == "parking":
                coords = feat["geometry"]["coordinates"]
                self.parkings.append({
                    "name": feat["properties"].get("name", "Parcheggio Escursionisti"),
                    "lon": coords[0],
                    "lat": coords[1],
                    "ele": feat["properties"].get("ele", 500),
                })

        # Carica o genera i poligoni pre-smussati per anelli di distanza e pendenza
        self.rings_geojson = self._load_or_build_rings()

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        print(
            f"[CHESTNUT ENGINE] Pronto in {elapsed_ms:.1f} ms "
            f"({len(self.rings_geojson['features'])} anelli poligonali)."
        )

    def _load_or_build_rings(self) -> dict:
        cache_file = DATA_DIR / "chestnut_rings.geojson"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        print("[CHESTNUT ENGINE] Costruzione anelli poligonali del castagneto (una tantum)...")
        features = []
        west = self.bbox["west"]
        south = self.bbox["south"]

        d_prev = 0.0
        for d_max in DIST_STEPS:
            d_mask = (self.dist_trail_m > d_prev) & (self.dist_trail_m <= d_max) & self.is_chestnut_wood
            d_mid = int(round((d_prev + d_max) / 2.0))
            s_prev = 0.0
            for s_max in SLOPE_STEPS:
                mask = d_mask & (self.slope_pct > s_prev) & (self.slope_pct <= s_max)
                s_mid = int(round((s_prev + min(s_max, 55)) / 2.0))
                s_prev = s_max
                if not np.any(mask):
                    continue

                grid_2d = np.zeros((self.ny, self.nx), dtype=bool)
                grid_2d[self.iy[mask], self.ix[mask]] = True
                poly = _merge_cells_to_smooth_polygon(grid_2d, west, south, self.dlon, self.dlat)
                if poly and not poly.is_empty:
                    area_ha = round(float(np.sum(mask)) * self.cell_area_ha, 2)
                    features.append({
                        "type": "Feature",
                        "geometry": mapping(poly),
                        "properties": {
                            "dist_m": d_mid,
                            "dist_max_m": int(d_max),
                            "slope_pct": s_mid,
                            "slope_max_pct": int(s_max),
                            "area_ha": area_ha,
                        },
                    })
            d_prev = d_max

        fc = {"type": "FeatureCollection", "features": features}
        cache_file.write_text(json.dumps(fc), encoding="utf-8")
        return fc

    def find_nearest_village(self, lon: float, lat: float) -> dict:
        best = VILLAGES[0]
        best_d2 = 1e9
        for v in VILLAGES:
            d2 = (lon - v["lon"]) ** 2 + (lat - v["lat"]) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best = v
        return best

    def find_nearest_parking(self, lon: float, lat: float) -> dict:
        if not self.parkings:
            return {"name": "Parcheggio locale", "lon": lon, "lat": lat, "dist_m": 200}
        best = self.parkings[0]
        best_d2 = 1e9
        for p in self.parkings:
            d2 = ((lon - p["lon"]) * 77500.0) ** 2 + ((lat - p["lat"]) * 111132.0) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best = p
        return {
            "name": best["name"],
            "lon": best["lon"],
            "lat": best["lat"],
            "dist_m": int(round(math.sqrt(best_d2))),
        }

    def inspect_spot(
        self,
        lon: float,
        lat: float,
        near_limit_m: float = 45.0,
        max_slope_pct: float = 32.0,
    ) -> dict[str, Any]:
        lons = self.dem_full["lons"]
        lats = self.dem_full["lats"]
        c = int(np.clip(np.argmin(np.abs(lons - lon)), 0, len(lons) - 1))
        r = int(np.clip(np.argmin(np.abs(lats - lat)), 0, len(lats) - 1))

        elev_m = int(round(float(self.dem_full["elev"][r, c])))
        slope_pct = round(float(self.dem_full["slope_pct"][r, c]), 0)

        d2 = (self.lon - lon) ** 2 + (self.lat - lat) ** 2
        nearest_idx = int(np.argmin(d2))
        deg_dist = math.sqrt(float(d2[nearest_idx]))
        in_wood = deg_dist < (self.dlon * 1.2)

        cell = self.cells_list[nearest_idx]
        dist_trail_m = int(round(float(cell["dist_trail_m"])))
        nearest_trail = cell["nearest_trail"]
        is_chestnut = bool(self.is_chestnut_wood[nearest_idx]) if in_wood else False

        village = self.find_nearest_village(lon, lat)
        parking = self.find_nearest_parking(lon, lat)

        near_m = float(near_limit_m)
        mid_m = round(near_m * 2.4)
        far_m = round(near_m * 4.8)

        if slope_pct <= 16:
            terrain_desc = "Pianeggiante / Molto comodo a piedi"
        elif slope_pct <= 26:
            terrain_desc = "Pendio dolce — Si cammina bene"
        elif slope_pct <= max_slope_pct:
            terrain_desc = "Pendio moderato — Scarpe da trekking"
        else:
            terrain_desc = "Terreno ripido e faticoso — Sconsigliato"

        if not in_wood or not is_chestnut:
            band = "outside"
            band_label = "Fuori dal Castagneto"
            advice = "Qui sei fuori dai boschi di castagno (prato, paese o vetta alta). Spostati sulle zone colorate."
        elif slope_pct > max_slope_pct:
            band = "steep"
            band_label = "Zona Troppo Ripida"
            advice = f"C'è bosco di castagno, ma il terreno qui è troppo ripido ({int(slope_pct)}%)."
        elif dist_trail_m <= near_m:
            band = "yellow"
            band_label = "Zona Gialla — Vicino al Sentiero"
            advice = f"Sei a {dist_trail_m} m dal sentiero: posto comodissimo, ma qui si fermano tutti e trovi meno castagne."
        elif dist_trail_m <= mid_m:
            band = "orange"
            band_label = "Zona Arancione — Fascia Strategica"
            advice = f"Ottimo posto! Sei a {dist_trail_m} m dentro il bosco: chi passeggia sul sentiero non arriva qui, ma rientri facilmente."
        elif dist_trail_m <= far_m:
            band = "red"
            band_label = "Zona Rossa — Bosco Profondo"
            advice = f"Zona molto isolata ({dist_trail_m} m dal sentiero) e terreno sicuro: qui non arriva quasi nessuno!"
        else:
            band = "deep"
            band_label = "Molto Lontano dai Sentieri"
            advice = f"Sei a {dist_trail_m} m dal sentiero più vicino: bosco molto profondo."

        return {
            "lon": round(lon, 6),
            "lat": round(lat, 6),
            "village_name": village["name"],
            "elev_m": elev_m,
            "slope_pct": int(slope_pct),
            "terrain_desc": terrain_desc,
            "dist_trail_m": dist_trail_m,
            "nearest_trail": nearest_trail,
            "band": band,
            "band_label": band_label,
            "advice": advice,
            "parking": parking,
        }
