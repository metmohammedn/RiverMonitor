# River Monitor

Interactive river flood monitoring dashboard built with Dash, Plotly, and Dash Leaflet.

## Features

- **Map-first layout** — EA-style 60/40 split with 4 map tile options (Esri Topo, Voyager, Dark, OSM), flood zone overlays, rain radar, and user layer upload (GeoJSON/shapefile)
- **Station monitoring** — 2,800+ river gauges with flood classification (Major/Moderate/Minor/Normal), search by station/river/location
- **Wind & gust ensemble forecasts** — ECMWF IFS (51 members), GFS (31), ICON (40) with exceedance probability, model agreement scoring, and per-model spread charts
- **Weather windows** — safe periods identified from combined wind + gust + rain thresholds, with green bands on charts and OPEN/CLOSED summary
- **Precipitation forecasts** — multi-model rainfall with user-configurable thresholds
- **Tide forecasts** — Open-Meteo sea level data with HAT (Highest Astronomical Tide) reference lines
- **Weather observations** — recent wind/gust/rain analysis data overlaid on forecast charts
- **Forecast Demo** — real obs + forecast overlay from March 2026 QLD/NSW flood event with custom thresholds, warning panels, and CSV asset threshold upload
- **Flood Scenarios** — PDF viewer for Flood Scenarios Outlook documents (auto-discovered)
- **Interactive HTML export** — downloadable reports with charts, stats, and flood warnings
- **Google Analytics 4** — env-var driven, full interaction tracking (disabled when `GA_MEASUREMENT_ID` is empty)
- **Docker ready** — Dockerfile + docker-compose.yml with Redis sidecar

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
python app.py
# → http://localhost:8050
```

## Docker

```bash
docker compose up
```

## Configuration

All settings via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `false` | Flask debug mode |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8050` | Bind port |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis cache (optional) |
| `DATA_SOURCE` | `sqlite` | `sqlite` (archived) or `bom-api` (future live) |
| `GA_MEASUREMENT_ID` | `` | Google Analytics 4 ID (empty = disabled) |
| `OPENMETEO_MARINE_URL` | Open-Meteo default | Tide forecast endpoint |
| `OPENMETEO_ENSEMBLE_URL` | Open-Meteo default | Wind ensemble endpoint |

## Architecture

```
river-standalone/
├── app.py                    # Dash factory, GA4, health endpoint
├── config.py                 # Environment-driven configuration
├── src/
│   ├── pages/river.py        # EA-style map layout + all callbacks
│   ├── components/
│   │   └── river_charts.py   # River, tide, wind, gust, precip, overlay charts
│   ├── services/
│   │   ├── river_service.py      # SQLite queries, flood classification
│   │   ├── tide_service.py       # Tidal station detection + forecasts
│   │   ├── wind_service.py       # Ensemble fetch, exceedance, weather windows
│   │   ├── meteostat_service.py  # Weather observations (Open-Meteo analysis)
│   │   ├── export_service.py     # Interactive HTML report generation
│   │   └── flood_scenario_service.py  # PDF discovery + serving
│   ├── data/
│   │   ├── api_client.py    # Open-Meteo API (tide, ensemble, precipitation)
│   │   └── cache.py         # Redis cache manager
│   └── utils/constants.py   # All constants, thresholds, colors
├── data/
│   ├── water_obsv2.db            # Archived river observations
│   ├── rain_river_station_list.csv  # Station metadata
│   ├── FloodZones_for_BOM.geojson   # Flood zone polygons
│   ├── flood_scenarios/          # PDF documents
│   └── demo/                     # Forecast demo data + example CSV
├── assets/
│   ├── styles/               # Dark theme CSS
│   └── scripts/              # GA4 events + upload handler JS
├── Dockerfile
└── docker-compose.yml
```

## Data Sources

| Source | Used For | Auth |
|--------|----------|------|
| Open-Meteo Forecast API | Precipitation forecasts, weather observations | Free, no key |
| Open-Meteo Ensemble API | Wind/gust ensemble forecasts (ECMWF, GFS, ICON) | Free, no key |
| Open-Meteo Marine API | Tide forecasts (sea level height MSL) | Free, no key |
| RainViewer API | Real-time rain radar tiles | Free, no key |
| SQLite (archived) | River gauge observations (April 2022) | Local file |

## License

Internal use only. Data sourced from Bureau of Meteorology and Open-Meteo.
