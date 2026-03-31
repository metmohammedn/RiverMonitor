"""
Tide forecast service — fetches sea-level height forecasts from the
Open-Meteo Marine API for tidal stations on the river monitoring page.

Data source: https://marine-api.open-meteo.com/v1/marine
Parameter:   sea_level_height_msl (includes tides, IBE, SSH)
Resolution:  ~8 km
Auth:        None required (free)
Updates:     Hourly model runs
"""
import logging
import threading
import time
from typing import Dict, Optional, Set, Tuple

import pandas as pd

from src.utils.constants import (
    TIDAL_SENSOR_TYPES,
    TIDAL_NAME_KEYWORDS,
    TIDE_CACHE_TTL_SECONDS,
    TIDE_PAST_HOURS,
    TIDE_FORECAST_HOURS,
)

logger = logging.getLogger(__name__)

# ── In-memory cache ──────────────────────────────────────────────────
_cache_lock = threading.Lock()
_tide_cache: Dict[Tuple[float, float], pd.DataFrame] = {}
_tide_cache_time: Dict[Tuple[float, float], float] = {}

# ── Tidal station set (lazily built) ─────────────────────────────────
_tidal_sensors: Optional[Set[str]] = None
_tidal_coords: Optional[Dict[str, Tuple[float, float]]] = None


# ── Station detection ────────────────────────────────────────────────

def _load_tidal_station_set() -> Tuple[Set[str], Dict[str, Tuple[float, float]]]:
    """
    Build the set of sensor IDs that are tidal stations and a mapping
    of sensor_id -> (lat, lon).

    Detection rules:
    1. SENSOR_TYPE is in TIDAL_SENSOR_TYPES (e.g. "tide gauge")
    2. SENSOR_TYPE == "water level gauge" AND (SHORT_NAME or NAME
       contains "tide" or "tidal", case-insensitive)
    """
    global _tidal_sensors, _tidal_coords
    if _tidal_sensors is not None:
        return _tidal_sensors, _tidal_coords

    from src.services.river_service import load_station_metadata

    meta = load_station_metadata()
    if meta.empty:
        _tidal_sensors = set()
        _tidal_coords = {}
        return _tidal_sensors, _tidal_coords

    # Rule 1: SENSOR_TYPE in tidal types
    mask_type = meta["SENSOR_TYPE"].isin(TIDAL_SENSOR_TYPES)

    # Rule 2: water level gauge with tide/tidal in name
    keyword_pattern = "|".join(TIDAL_NAME_KEYWORDS)
    mask_name = (
        (meta["SENSOR_TYPE"] == "water level gauge")
        & (
            meta["SHORT_NAME"].str.contains(keyword_pattern, case=False, na=False)
            | meta["NAME"].str.contains(keyword_pattern, case=False, na=False)
        )
    )

    tidal_df = meta[mask_type | mask_name].copy()

    sensor_set = set(tidal_df["SENSORID"].tolist())
    coords = {}
    for _, row in tidal_df.iterrows():
        sid = row["SENSORID"]
        lat = row.get("LAT")
        lon = row.get("LONG")
        if pd.notna(lat) and pd.notna(lon):
            coords[sid] = (float(lat), float(lon))

    _tidal_sensors = sensor_set
    _tidal_coords = coords

    logger.info(
        "Identified %d tidal stations (%d with coordinates)",
        len(sensor_set), len(coords),
    )
    return _tidal_sensors, _tidal_coords


def is_tidal_station(sensor_id: str) -> bool:
    """Check whether a sensor ID belongs to a tidal station."""
    sensors, _ = _load_tidal_station_set()
    return sensor_id in sensors


def get_tidal_station_coords(sensor_id: str) -> Optional[Tuple[float, float]]:
    """Get (lat, lon) for a tidal station, or None if not tidal."""
    _, coords = _load_tidal_station_set()
    return coords.get(sensor_id)


def get_tidal_sensor_ids() -> Set[str]:
    """Return the full set of tidal sensor IDs."""
    sensors, _ = _load_tidal_station_set()
    return sensors


# ── API / cache helpers ──────────────────────────────────────────────

def _get_client():
    try:
        from src.data.api_client import get_api_client
        return get_api_client()
    except RuntimeError:
        return None


# ── Public fetch function ────────────────────────────────────────────

def fetch_tide_forecast(
    sensor_id: str,
    past_hours: int = TIDE_PAST_HOURS,
    forecast_hours: int = TIDE_FORECAST_HOURS,
) -> pd.DataFrame:
    """
    Fetch tide (sea-level height MSL) forecast for a tidal station.

    Returns DataFrame indexed by datetime with 'sea_level_height_msl'
    column.  Empty DataFrame if station is not tidal or API fails.
    """
    coords = get_tidal_station_coords(sensor_id)
    if coords is None:
        return pd.DataFrame()

    lat, lon = coords
    cache_key = (round(lat, 4), round(lon, 4))

    # Check in-memory cache
    now = time.time()
    with _cache_lock:
        if cache_key in _tide_cache and cache_key in _tide_cache_time:
            age = now - _tide_cache_time[cache_key]
            if age < TIDE_CACHE_TTL_SECONDS:
                logger.debug(
                    "Tide cache hit for %s (age %.0fs)", sensor_id, age,
                )
                return _tide_cache[cache_key]

    # Fetch from API
    client = _get_client()
    if client is None:
        logger.warning("No API client available for tide fetch")
        return pd.DataFrame()

    try:
        df = client.get_tide_forecast(
            lat, lon,
            past_hours=past_hours,
            forecast_hours=forecast_hours,
        )
    except Exception as exc:
        logger.warning("Tide forecast fetch failed for '%s': %s", sensor_id, exc)
        df = pd.DataFrame()

    # Update cache
    with _cache_lock:
        _tide_cache[cache_key] = df
        _tide_cache_time[cache_key] = now

    if not df.empty:
        logger.info(
            "Tide forecast for '%s': %d rows from %s to %s",
            sensor_id, len(df),
            df.index.min().strftime("%Y-%m-%d %H:%M"),
            df.index.max().strftime("%Y-%m-%d %H:%M"),
        )

    return df
