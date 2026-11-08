"""
Pipeline GIS per l'acquisizione e l'analisi spaziale Open Data
Area di studio: Massiccio del Campo dei Fiori & Sacro Monte di Varese (VA, Lombardia)
"""

import json
import math
import sys
import time
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from scipy.ndimage import gaussian_filter, uniform_filter
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, mapping
from shapely.ops import polygonize, unary_union
from shapely.prepared import prep

BBOX = {
    "south": 45.846,
    "west": 8.722,
    "north": 45.898,
    "east": 8.828,
}

CENTER_LAT = (BBOX["south"] + BBOX["north"]) / 2.0
CENTER_LON = (BBOX["west"] + BBOX["east"]) / 2.0

METERS_PER_DEG_LAT = 111132.92 - 559.82 * math.cos(2 * math.radians(CENTER_LAT))
METERS_PER_DEG_LON = 111412.84 * math.cos(math.radians(CENTER_LAT))

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "CampoDeiFioriForagingGIS/1.0 (OpenData Spatial Analysis; Varese)"
}


def lonlat_to_xy(lon: float, lat: float) -> tuple[float, float]:
    x = (lon - BBOX["west"]) * METERS_PER_DEG_LON
    y = (lat - BBOX["south"]) * METERS_PER_DEG_LAT
    return x, y


def xy_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = BBOX["west"] + x / METERS_PER_DEG_LON
    lat = BBOX["south"] + y / METERS_PER_DEG_LAT
    return lon, lat


def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> tuple[int, int]:
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def aspect_to_cardinal(deg: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int(((deg + 22.5) % 360.0) // 45.0)
    return dirs[idx]


def assign_sector(lon: float, lat: float, elev: float) -> str:
    if lon < 8.758 and lat > 45.870:
        return "Dorsale Forte di Orino & Cabiaglio"
    if lon >= 8.758 and lon <= 8.802 and lat > 45.876:
        return "Versante Nord — Selve di Brinzio"
    if lon > 8.798 and lat > 45.868:
        return "Conca della Rasa & Sorgenti Olona"
    if lon > 8.782 and lat <= 45.868:
        return "Sacro Monte, Velate & Monte Tre Croci"
    if elev > 960:
        return "Crinale Campo dei Fiori & Punta Paradiso"
    return "Versante Sud — Luvinate, Barasso & Comerio"


def classify_habitat_cell(
    lon: float,
    lat: float,
    elev_m: float,
    slope_pct: float,
    aspect_deg: float,
    in_rel_west: bool,
    in_special_chestnut: bool,
    in_special_fagus: bool,
) -> str:
    """
    Classificazione ecologico-forestale del Parco Regionale Campo dei Fiori:
    - Rispetta i poligoni puntuali OSM (es. 'Selva Castanile del consorzio', 'genus=Fagus')
    - Modella i rimboschimenti di conifere (Pian delle Noci / Villaggio Cagnola / versante N Forte d'Orino)
    - Modella le fasce fitoclimatiche reali (Castanetum 340-850m, Fascia Mista 820-920m, Fagetum >910m)
    """
    if in_special_chestnut:
        return "castagneto"
    if in_special_fagus:
        return "faggeta"

    is_north_aspect = (aspect_deg >= 305 or aspect_deg <= 55)
    is_south_warm = (120 <= aspect_deg <= 250)

    # Nuclei di conifere (rimboschimenti storici Pian delle Noci / medio-alto versante N/NW)
    if in_rel_west and is_north_aspect and (760 <= elev_m <= 1040) and (8.742 <= lon <= 8.788):
        return "conifere"

    # Faggeta Montana Superiore (Fagus sylvatica)
    fagus_threshold = 935 if is_south_warm else (885 if is_north_aspect else 910)
    if elev_m >= fagus_threshold:
        return "faggeta"

    # Fascia Mista Prealpina (Castagno, Faggio, Acero, Frassino, Carpino nero)
    mixed_threshold = 850 if is_south_warm else (780 if is_north_aspect else 815)
    if elev_m >= mixed_threshold or (is_north_aspect and slope_pct > 36.0 and elev_m > 620):
        return "misto"

    # Castagneto / Boschi di Latifoglie a dominanza Castanea sativa (340m - 850m)
    return "castagneto"


def fetch_or_load_dem(zoom: int = 13, force_refresh: bool = False) -> dict:
    cache_path = DATA_DIR / "dem_campodeifiori.npz"
    if cache_path.exists() and not force_refresh:
        print(f"[DEM] Caricamento DEM da cache locale: {cache_path.name}")
        loaded = np.load(cache_path)
        return {k: loaded[k] for k in loaded.files}

    print(f"[DEM] Download tile altimetrici Terrarium (Zoom {zoom}) per Campo dei Fiori...")
    x_min, y_max = deg2num(BBOX["south"], BBOX["west"], zoom)
    x_max, y_min = deg2num(BBOX["north"], BBOX["east"], zoom)

    cols = (x_max - x_min + 1) * 256
    rows = (y_max - y_min + 1) * 256
    elev_mosaic = np.zeros((rows, cols), dtype=np.float32)

    session = requests.Session()
    session.headers.update(HEADERS)

    for ty in range(y_min, y_max + 1):
        for tx in range(x_min, x_max + 1):
            url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{zoom}/{tx}/{ty}.png"
            r = session.get(url, timeout=20)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGB")
            arr = np.asarray(img, dtype=np.float32)
            elev = (arr[:, :, 0] * 256.0 + arr[:, :, 1] + arr[:, :, 2] / 256.0) - 32768.0
            r0 = (ty - y_min) * 256
            c0 = (tx - x_min) * 256
            elev_mosaic[r0 : r0 + 256, c0 : c0 + 256] = elev

    px_x = np.arange(cols) / 256.0 + x_min
    px_y = np.arange(rows) / 256.0 + y_min

    lons = px_x / (2.0 ** zoom) * 360.0 - 180.0
    lats = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * px_y / (2.0 ** zoom)))))

    lon_mask = (lons >= BBOX["west"] - 0.002) & (lons <= BBOX["east"] + 0.002)
    lat_mask = (lats >= BBOX["south"] - 0.002) & (lats <= BBOX["north"] + 0.002)

    sub_elev = elev_mosaic[np.ix_(lat_mask, lon_mask)]
    sub_lons = lons[lon_mask]
    sub_lats = lats[lat_mask]

    smooth_elev = gaussian_filter(sub_elev, sigma=0.85)

    dx_m = abs(float(np.mean(np.diff(sub_lons)))) * METERS_PER_DEG_LON
    dy_m = abs(float(np.mean(np.diff(sub_lats)))) * METERS_PER_DEG_LAT

    dz_dy_raw, dz_dx = np.gradient(smooth_elev, dy_m, dx_m)
    dz_dy = -dz_dy_raw

    slope_rad = np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2))
    slope_deg = np.degrees(slope_rad)
    slope_pct = np.tan(slope_rad) * 100.0
    aspect_deg = (np.degrees(np.arctan2(dz_dx, dz_dy)) + 360.0) % 360.0

    regional_slope_pct = uniform_filter(slope_pct, size=11)
    terrace_bonus = np.clip((regional_slope_pct - slope_pct) / 14.0, 0.0, 1.0)

    dem_data = {
        "elev": smooth_elev.astype(np.float32),
        "slope_pct": slope_pct.astype(np.float32),
        "slope_deg": slope_deg.astype(np.float32),
        "aspect_deg": aspect_deg.astype(np.float32),
        "terrace_bonus": terrace_bonus.astype(np.float32),
        "lons": sub_lons.astype(np.float64),
        "lats": sub_lats.astype(np.float64),
        "dx_m": np.array(dx_m, dtype=np.float32),
        "dy_m": np.array(dy_m, dtype=np.float32),
    }
    np.savez_compressed(cache_path, **dem_data)
    print(f"[DEM] Salvato in cache {cache_path.name} ({smooth_elev.shape[1]}x{smooth_elev.shape[0]} px)")
    return dem_data


def fetch_or_load_osm(force_refresh: bool = False) -> dict:
    cache_path = DATA_DIR / "raw_osm_campodeifiori.json"
    if cache_path.exists() and not force_refresh:
        print(f"[OSM] Caricamento dati vettoriali OSM da cache: {cache_path.name}")
        return json.loads(cache_path.read_text(encoding="utf-8"))

    bbox_str = f"{BBOX['south']},{BBOX['west']},{BBOX['north']},{BBOX['east']}"
    query = f"""
    [out:json][timeout:60];
    (
      way["landuse"="forest"]({bbox_str});
      way["natural"="wood"]({bbox_str});
      relation["landuse"="forest"]({bbox_str});
      relation["natural"="wood"]({bbox_str});
      way["highway"~"^(path|footway|track|bridleway|steps)$"]({bbox_str});
      node["natural"~"^(peak|saddle|spring)$"]({bbox_str});
      node["amenity"="parking"]({bbox_str});
      way["amenity"="parking"]({bbox_str});
      node["place"~"^(village|hamlet|locality)$"]({bbox_str});
    );
    out geom;
    """
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    for ep in endpoints:
        try:
            print(f"[OSM] Query Overpass API su {ep}...")
            resp = requests.post(ep, data={"data": query}, headers=HEADERS, timeout=65)
            if resp.status_code == 200:
                data = resp.json()
                elements = data.get("elements", [])
                print(f"[OSM] Ricevuti {len(elements)} elementi vettoriali.")
                cache_path.write_text(json.dumps(data), encoding="utf-8")
                return data
            else:
                print(f"[OSM] HTTP {resp.status_code} da {ep}")
        except Exception as exc:
            print(f"[OSM] Errore su {ep}: {exc}")
        time.sleep(2)
    raise RuntimeError("Impossibile scaricare i dati da Overpass API.")


def sample_dem_at(dem: dict, lon: float, lat: float) -> tuple[float, float, float, float]:
    lons = dem["lons"]
    lats = dem["lats"]
    c = int(np.clip(np.argmin(np.abs(lons - lon)), 0, len(lons) - 1))
    r = int(np.clip(np.argmin(np.abs(lats - lat)), 0, len(lats) - 1))
    return (
        float(dem["elev"][r, c]),
        float(dem["slope_pct"][r, c]),
        float(dem["aspect_deg"][r, c]),
        float(dem["terrace_bonus"][r, c]),
    )


def build_vector_layers(osm_data: dict, dem: dict) -> tuple[list, list, list, dict]:
    bbox_poly = box(BBOX["west"], BBOX["south"], BBOX["east"], BBOX["north"])
    trails_features = []
    forests_features = []
    landmarks_features = []

    all_forest_polys = []
    west_rel_polys = []
    special_chestnut_polys = []
    special_fagus_polys = []
    exclusion_polys = []

    elements = osm_data.get("elements", [])

    for el in elements:
        el_type = el.get("type")
        tags = el.get("tags", {})

        # 1. Punti di riferimento
        if el_type == "node" and tags:
            lat = el.get("lat")
            lon = el.get("lon")
            if lat is None or lon is None:
                continue
            if not (BBOX["south"] <= lat <= BBOX["north"] and BBOX["west"] <= lon <= BBOX["east"]):
                continue

            elev_m, slope_pct, _, _ = sample_dem_at(dem, lon, lat)
            category = None
            name = tags.get("name")

            if tags.get("natural") == "peak" and name:
                category = "peak"
            elif tags.get("natural") == "saddle" and name:
                category = "saddle"
            elif tags.get("place") in ("village", "hamlet", "locality") and name:
                category = "locality"
                if tags.get("place") == "village":
                    exclusion_polys.append(Point(lon, lat).buffer(0.0020))
            elif tags.get("amenity") == "parking":
                category = "parking"
                name = name or "Parcheggio / Accesso Sentieri"

            if category:
                ele_val = int(round(elev_m))
                raw_ele = str(tags.get("ele", "")).strip()
                if raw_ele.replace(".", "", 1).isdigit():
                    ele_val = int(round(float(raw_ele)))

                landmarks_features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                    "properties": {
                        "id": f"node_{el['id']}",
                        "name": name,
                        "category": category,
                        "ele": ele_val,
                        "slope_pct": round(slope_pct, 1),
                    },
                })

        elif el_type == "way" and tags.get("amenity") == "parking":
            geom = el.get("geometry", [])
            if geom:
                lon = float(np.mean([p["lon"] for p in geom]))
                lat = float(np.mean([p["lat"] for p in geom]))
                if BBOX["south"] <= lat <= BBOX["north"] and BBOX["west"] <= lon <= BBOX["east"]:
                    elev_m, slope_pct, _, _ = sample_dem_at(dem, lon, lat)
                    landmarks_features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                        "properties": {
                            "id": f"way_park_{el['id']}",
                            "name": tags.get("name", "Area Parcheggio Escursionisti"),
                            "category": "parking",
                            "ele": int(round(elev_m)),
                            "slope_pct": round(slope_pct, 1),
                        },
                    })

        # 2. Sentieri
        elif el_type == "way" and "highway" in tags:
            hw = tags["highway"]
            geom = el.get("geometry", [])
            if len(geom) < 2:
                continue
            coords = [(round(pt["lon"], 6), round(pt["lat"], 6)) for pt in geom]
            line = LineString(coords).intersection(bbox_poly)
            if line.is_empty:
                continue

            pts_xy = [lonlat_to_xy(pt["lon"], pt["lat"]) for pt in geom]
            length_m = LineString(pts_xy).length
            if length_m < 15:
                continue

            mid_pt = geom[len(geom) // 2]
            elev_m, slope_pct, _, _ = sample_dem_at(dem, mid_pt["lon"], mid_pt["lat"])

            ref = tags.get("ref", "")
            name = tags.get("name", "")
            sac_scale = tags.get("sac_scale", "")

            is_primary = bool(ref or name or hw in ("track", "footway", "steps") or sac_scale == "hiking")
            tier = "primary" if is_primary else "secondary"

            display_name = name or (f"Sentiero CAI {ref}" if ref else (
                "Mulattiera / Strada Forestale" if hw == "track" else "Traccia Boschiva Secondaria"
            ))

            lines_to_add = [line] if line.geom_type == "LineString" else (
                list(line.geoms) if line.geom_type == "MultiLineString" else []
            )
            for sub_idx, sub_line in enumerate(lines_to_add):
                trails_features.append({
                    "type": "Feature",
                    "geometry": mapping(sub_line),
                    "properties": {
                        "id": f"trail_{el['id']}_{sub_idx}",
                        "name": display_name,
                        "ref": ref,
                        "highway": hw,
                        "tier": tier,
                        "sac_scale": sac_scale or "escursionistico",
                        "length_m": int(round(length_m)),
                        "elev_m": int(round(elev_m)),
                        "slope_pct": round(slope_pct, 1),
                    },
                })

        # 3. Poligoni boschivi (Way e Relation)
        elif (el_type in ("way", "relation")) and (
            tags.get("landuse") == "forest" or tags.get("natural") == "wood"
        ):
            if tags.get("access") == "private" or tags.get("sport"):
                # Escludiamo campi privati / airsoft recintati
                geom = el.get("geometry", [])
                if len(geom) >= 4:
                    coords = [(pt["lon"], pt["lat"]) for pt in geom]
                    if coords[0] != coords[-1]:
                        coords.append(coords[0])
                    try:
                        exclusion_polys.append(Polygon(coords).buffer(0))
                    except Exception:
                        pass
                continue

            poly_obj = None
            if el_type == "way":
                geom = el.get("geometry", [])
                if len(geom) >= 4:
                    coords = [(pt["lon"], pt["lat"]) for pt in geom]
                    if coords[0] != coords[-1]:
                        coords.append(coords[0])
                    try:
                        p = Polygon(coords)
                        if not p.is_valid:
                            p = p.buffer(0)
                        poly_obj = p.intersection(bbox_poly)
                    except Exception:
                        pass
            else:
                outer_lines = []
                inner_lines = []
                for m in el.get("members", []):
                    m_geom = m.get("geometry", [])
                    if len(m_geom) >= 2:
                        line_coords = [(pt["lon"], pt["lat"]) for pt in m_geom]
                        if m.get("role") == "inner":
                            inner_lines.append(LineString(line_coords))
                        else:
                            outer_lines.append(LineString(line_coords))
                if outer_lines:
                    try:
                        outer_polys = list(polygonize(unary_union(outer_lines)))
                        if outer_polys:
                            merged_outer = unary_union(outer_polys)
                            if inner_lines:
                                inner_polys = list(polygonize(unary_union(inner_lines)))
                                if inner_polys:
                                    merged_outer = merged_outer.difference(unary_union(inner_polys))
                            poly_obj = merged_outer.intersection(bbox_poly)
                    except Exception:
                        pass

            if poly_obj and not poly_obj.is_empty and poly_obj.area > 1e-7:
                all_forest_polys.append(poly_obj)
                if el.get("id") == 18417425:
                    west_rel_polys.append(poly_obj)
                if tags.get("produce") == "chestnuts" or "castan" in tags.get("name", "").lower():
                    special_chestnut_polys.append((poly_obj, tags.get("name", "Selva Castanile del Consorzio")))
                elif tags.get("genus") == "Fagus":
                    special_fagus_polys.append((poly_obj, tags.get("name", "Faggeta Censita OSM")))

    excl_mask = unary_union(exclusion_polys) if exclusion_polys else Polygon()
    u_all_forest = unary_union(all_forest_polys).difference(excl_mask)
    u_west_rel = unary_union(west_rel_polys).difference(excl_mask) if west_rel_polys else Polygon()
    u_special_chestnut = unary_union([p for p, _ in special_chestnut_polys]) if special_chestnut_polys else Polygon()
    u_special_fagus = unary_union([p for p, _ in special_fagus_polys]) if special_fagus_polys else Polygon()

    # Aggiungiamo prima le particelle forestali speciali censite su OSM (es. Selva Castanile del Consorzio)
    comp_idx = 0
    for sp, sname in special_chestnut_polys:
        area_ha = sp.area * METERS_PER_DEG_LON * METERS_PER_DEG_LAT / 10000.0
        rep = sp.representative_point()
        elev_m, slope_pct, aspect_deg, _ = sample_dem_at(dem, rep.x, rep.y)
        comp_idx += 1
        forests_features.append({
            "type": "Feature",
            "geometry": mapping(sp),
            "properties": {
                "id": f"forest_osm_special_{comp_idx}",
                "name": f"{sname} (Particella Censita OSM)",
                "forest_class": "castagneto",
                "forest_label": "Selva Castanile da Frutto Censita (Castanea sativa)",
                "sector": assign_sector(rep.x, rep.y, elev_m),
                "elev_m": int(round(elev_m)),
                "slope_pct": round(slope_pct, 1),
                "aspect": aspect_to_cardinal(aspect_deg),
                "area_ha": round(area_ha, 2),
                "verified_osm_stand": True,
            },
        })

    # Suddivisione della copertura boschiva in 48 compartimenti (8x6) classificati su base fitoclimatica e DEM
    lon_edges = np.linspace(BBOX["west"], BBOX["east"], 9)
    lat_edges = np.linspace(BBOX["south"], BBOX["north"], 7)

    for j in range(len(lat_edges) - 1):
        for i in range(len(lon_edges) - 1):
            tile_box = box(lon_edges[i], lat_edges[j], lon_edges[i + 1], lat_edges[j + 1])
            sub = u_all_forest.intersection(tile_box)
            if sub.is_empty:
                continue
            sub_polys = [sub] if sub.geom_type == "Polygon" else (
                list(sub.geoms) if sub.geom_type == "MultiPolygon" else []
            )
            for sp in sub_polys:
                area_ha = sp.area * METERS_PER_DEG_LON * METERS_PER_DEG_LAT / 10000.0
                if area_ha < 1.0:
                    continue
                sp_simp = sp.simplify(0.00008, preserve_topology=True)
                rep = sp_simp.representative_point()
                elev_m, slope_pct, aspect_deg, _ = sample_dem_at(dem, rep.x, rep.y)
                if elev_m < 340:
                    continue

                sector_name = assign_sector(rep.x, rep.y, elev_m)
                in_west = u_west_rel.contains(rep) if not u_west_rel.is_empty else False
                f_class = classify_habitat_cell(
                    rep.x, rep.y, elev_m, slope_pct, aspect_deg, in_west, False, False
                )

                labels_map = {
                    "castagneto": "Selva Castanile & Latifoglie (Castanea sativa)",
                    "faggeta": "Faggeta Montana Superiore (Fagus sylvatica)",
                    "misto": "Bosco Misto Prealpino (Castagno, Faggio, Acero)",
                    "conifere": "Rimboschimento di Conifere (Picea, Abies, Pinus)",
                }
                f_label = labels_map[f_class]

                comp_idx += 1
                forests_features.append({
                    "type": "Feature",
                    "geometry": mapping(sp_simp),
                    "properties": {
                        "id": f"forest_comp_{comp_idx}",
                        "name": f"{f_label.split(' (')[0]} — {sector_name.split(' — ')[-1]}",
                        "forest_class": f_class,
                        "forest_label": f_label,
                        "sector": sector_name,
                        "elev_m": int(round(elev_m)),
                        "slope_pct": round(slope_pct, 1),
                        "aspect": aspect_to_cardinal(aspect_deg),
                        "area_ha": round(area_ha, 1),
                        "verified_osm_stand": False,
                    },
                })

    forest_unions = {
        "all_forest": u_all_forest,
        "west_rel": u_west_rel,
        "special_chestnut": u_special_chestnut,
        "special_fagus": u_special_fagus,
    }
    print(
        f"[GIS] Costruiti {len(trails_features)} segmenti sentiero, "
        f"{len(forests_features)} compartimenti boschivi classificati, "
        f"{len(landmarks_features)} punti di riferimento."
    )
    return trails_features, forests_features, landmarks_features, forest_unions


def build_spatial_analysis_grid(
    dem: dict,
    trails_features: list,
    forest_unions: dict,
    step_m: float = 42.0,
) -> dict:
    width_m = (BBOX["east"] - BBOX["west"]) * METERS_PER_DEG_LON
    height_m = (BBOX["north"] - BBOX["south"]) * METERS_PER_DEG_LAT

    xs = np.arange(step_m / 2.0, width_m, step_m)
    ys = np.arange(step_m / 2.0, height_m, step_m)
    nx = len(xs)
    ny = len(ys)

    print(f"[GRID] Generazione griglia di analisi spaziale {nx}x{ny} ({nx * ny} celle a passo {step_m:.0f}m)...")

    primary_pts = []
    primary_names = []
    all_pts = []
    all_names = []

    for tf in trails_features:
        props = tf["properties"]
        t_name = props["name"]
        tier = props["tier"]
        coords = tf["geometry"]["coordinates"]
        line_xy = LineString([lonlat_to_xy(c[0], c[1]) for c in coords])
        length = line_xy.length
        n_samples = max(2, int(length // 8.0) + 1)
        for d in np.linspace(0, length, n_samples):
            pt = line_xy.interpolate(d)
            xy = (pt.x, pt.y)
            all_pts.append(xy)
            all_names.append(t_name)
            if tier == "primary":
                primary_pts.append(xy)
                primary_names.append(t_name)

    tree_all = cKDTree(np.array(all_pts))
    tree_primary = cKDTree(np.array(primary_pts)) if primary_pts else tree_all

    prep_all = prep(forest_unions["all_forest"])
    prep_west = prep(forest_unions["west_rel"]) if not forest_unions["west_rel"].is_empty else None
    prep_chestnut = prep(forest_unions["special_chestnut"]) if not forest_unions["special_chestnut"].is_empty else None
    prep_fagus = prep(forest_unions["special_fagus"]) if not forest_unions["special_fagus"].is_empty else None

    cells = []
    counts_by_type = {"castagneto": 0, "faggeta": 0, "misto": 0, "conifere": 0}

    for iy, y_m in enumerate(ys):
        lat = BBOX["south"] + y_m / METERS_PER_DEG_LAT
        for ix, x_m in enumerate(xs):
            lon = BBOX["west"] + x_m / METERS_PER_DEG_LON
            pt_wgs = Point(lon, lat)

            elev_m, slope_pct, aspect_deg, terrace_bonus = sample_dem_at(dem, lon, lat)
            if elev_m < 340:
                continue

            if not prep_all.contains(pt_wgs):
                continue

            in_west = prep_west.contains(pt_wgs) if prep_west else False
            in_spec_c = prep_chestnut.contains(pt_wgs) if prep_chestnut else False
            in_spec_f = prep_fagus.contains(pt_wgs) if prep_fagus else False

            f_type = classify_habitat_cell(
                lon, lat, elev_m, slope_pct, aspect_deg, in_west, in_spec_c, in_spec_f
            )

            counts_by_type[f_type] += 1
            dist_all, idx_all = tree_all.query([x_m, y_m])
            dist_pri, idx_pri = tree_primary.query([x_m, y_m])

            nearest_name = primary_names[int(idx_pri)] if dist_pri < dist_all + 50 else all_names[int(idx_all)]

            cells.append({
                "ix": ix,
                "iy": iy,
                "lon": round(lon, 6),
                "lat": round(lat, 6),
                "elev_m": int(round(elev_m)),
                "slope_pct": round(slope_pct, 1),
                "slope_deg": round(math.degrees(math.atan(slope_pct / 100.0)), 1),
                "aspect_deg": int(round(aspect_deg)),
                "aspect": aspect_to_cardinal(aspect_deg),
                "terrace_bonus": round(terrace_bonus, 3),
                "forest_type": f_type,
                "verified_stand": bool(in_spec_c or in_spec_f),
                "dist_trail_m": round(float(dist_all), 1),
                "dist_primary_m": round(float(dist_pri), 1),
                "nearest_trail": nearest_name,
                "sector": assign_sector(lon, lat, elev_m),
            })

    dlon = step_m / METERS_PER_DEG_LON
    dlat = step_m / METERS_PER_DEG_LAT

    grid_payload = {
        "bbox": BBOX,
        "nx": nx,
        "ny": ny,
        "step_m": step_m,
        "dlon": round(dlon, 7),
        "dlat": round(dlat, 7),
        "total_wooded_cells": len(cells),
        "total_wooded_area_ha": round(len(cells) * (step_m * step_m) / 10000.0, 1),
        "counts_by_type": counts_by_type,
        "cells": cells,
    }
    print(
        f"[GRID] Celle boschive attive: {len(cells)} ({grid_payload['total_wooded_area_ha']} ha) -> "
        f"Castagneto: {counts_by_type['castagneto']}, Faggeta: {counts_by_type['faggeta']}, "
        f"Misto: {counts_by_type['misto']}, Conifere: {counts_by_type['conifere']}"
    )
    return grid_payload


def build_slope_contour_grid(dem: dict, stride: int = 5) -> dict:
    elev = dem["elev"][::stride, ::stride]
    slope = dem["slope_pct"][::stride, ::stride]
    aspect = dem["aspect_deg"][::stride, ::stride]
    lons = dem["lons"][::stride]
    lats = dem["lats"][::stride]

    return {
        "rows": int(elev.shape[0]),
        "cols": int(elev.shape[1]),
        "lons": [round(float(x), 6) for x in lons],
        "lats": [round(float(y), 6) for y in lats],
        "elev_m": np.round(elev, 0).astype(int).tolist(),
        "slope_pct": np.round(slope, 1).tolist(),
        "aspect_deg": np.round(aspect, 0).astype(int).tolist(),
    }


def main():
    force = "--refresh" in sys.argv
    dem = fetch_or_load_dem(zoom=13, force_refresh=force)
    osm = fetch_or_load_osm(force_refresh=force)

    trails_features, forests_features, landmarks_features, forest_unions = build_vector_layers(osm, dem)
    grid_payload = build_spatial_analysis_grid(dem, trails_features, forest_unions, step_m=42.0)
    dem_compact = build_slope_contour_grid(dem, stride=5)

    (DATA_DIR / "trails.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": trails_features}),
        encoding="utf-8",
    )
    (DATA_DIR / "forests.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": forests_features}),
        encoding="utf-8",
    )
    (DATA_DIR / "landmarks.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": landmarks_features}),
        encoding="utf-8",
    )
    (DATA_DIR / "spatial_grid.json").write_text(
        json.dumps(grid_payload),
        encoding="utf-8",
    )
    (DATA_DIR / "dem_surface.json").write_text(
        json.dumps(dem_compact),
        encoding="utf-8",
    )
    print("[SUCCESS] Tutti i dataset GIS vettoriali e altimetrici sono stati generati in /data!")


if __name__ == "__main__":
    main()
