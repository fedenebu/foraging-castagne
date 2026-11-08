"""
FastAPI Backend — Andare a Castagne (Campo dei Fiori & Sacro Monte di Varese)
Web app semplice e mobile-first per individuare le fasce di castagneto
(Gialla / Arancione / Rossa) in base alla distanza dai sentieri e alla pendenza.
"""

from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from gis_engine import VILLAGES, ChestnutForagingEngine

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Castagne Campo dei Fiori — Mappa Strategica dei Sentieri",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = ChestnutForagingEngine()


@app.get("/api/map-data")
def get_map_data():
    """Restituisce paesini, sentieri, parcheggi e fasce poligonali del castagneto."""
    return JSONResponse({
        "bbox": engine.bbox,
        "villages": VILLAGES,
        "trails": engine.trails_geojson,
        "landmarks": engine.landmarks_geojson,
        "chestnut_rings": engine.rings_geojson,
    })


@app.get("/api/spot-info")
def get_spot_info(
    lon: float = Query(..., ge=8.70, le=8.86),
    lat: float = Query(..., ge=45.83, le=45.92),
    near_m: float = Query(45.0, ge=15.0, le=120.0),
    max_slope: float = Query(32.0, ge=15.0, le=60.0),
):
    """Restituisce le informazioni semplici sul punto toccato sulla mappa."""
    info = engine.inspect_spot(
        lon=lon,
        lat=lat,
        near_limit_m=near_m,
        max_slope_pct=max_slope,
    )
    return JSONResponse(info)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
