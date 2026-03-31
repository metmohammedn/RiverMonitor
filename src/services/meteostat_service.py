"""
Weather observation service — fetches recent weather observations
(wind, gust, precipitation) from Open-Meteo's analysis/reanalysis data.

This provides model-assimilated "pseudo-observations" which are more reliable
than Meteostat for Australian locations with sparse station coverage.
"""
import logging
import threading
import time
from typing import Dict, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# In-memory cache
_cache_lock = threading.Lock()
_obs_cache: Dict[Tuple[float, float], dict] = {}
_obs_cache_time: Dict[Tuple[float, float], float] = {}
_OBS_CACHE_TTL = 3600  # 1 hour


def fetch_recent_observations(
    lat: float,
    lon: float,
    days_back: int = 7,
) -> dict:
    """
    Fetch recent hourly weather observations from Open-Meteo.

    Uses the standard forecast API with past_hours parameter, which returns
    model-assimilated analysis data for recent hours (effectively reanalysis
    quality for the past, blending into forecast for the future).

    Returns dict with:
        - "df": DataFrame with columns: wind_speed_kmh, wind_gust_kmh,
          precipitation_mm
        - "grid_lat", "grid_lon": actual model grid coordinates
        - "available": bool
    """
    cache_key = (round(lat, 2), round(lon, 2))

    # Check cache
    now_ts = time.time()
    with _cache_lock:
        if cache_key in _obs_cache and cache_key in _obs_cache_time:
            age = now_ts - _obs_cache_time[cache_key]
            if age < _OBS_CACHE_TTL:
                return _obs_cache[cache_key]

    result = {"df": pd.DataFrame(), "grid_lat": lat, "grid_lon": lon, "available": False}

    try:
        import httpx

        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "wind_speed_10m,wind_gusts_10m,precipitation",
            "past_hours": days_back * 24,
            "forecast_hours": 0,
            "timezone": "GMT",
        }
        resp = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
            timeout=15,
        )
        data = resp.json()

        grid_lat = data.get("latitude", lat)
        grid_lon = data.get("longitude", lon)

        if "hourly" not in data:
            result["grid_lat"] = grid_lat
            result["grid_lon"] = grid_lon
            with _cache_lock:
                _obs_cache[cache_key] = result
                _obs_cache_time[cache_key] = now_ts
            return result

        hourly = data["hourly"]
        df = pd.DataFrame({"time": pd.to_datetime(hourly["time"])})
        df = df.set_index("time")

        # Map Open-Meteo column names to our standard names
        col_map = {
            "wind_speed_10m": "wind_speed_kmh",
            "wind_gusts_10m": "wind_gust_kmh",
            "precipitation": "precipitation_mm",
        }
        for om_col, std_col in col_map.items():
            if om_col in hourly:
                df[std_col] = pd.to_numeric(
                    pd.Series(hourly[om_col], index=df.index), errors="coerce"
                )

        result = {
            "df": df,
            "grid_lat": grid_lat,
            "grid_lon": grid_lon,
            "available": not df.empty,
        }

        if not df.empty:
            logger.info(
                "Weather obs for (%.2f, %.2f): %d rows, grid=(%.2f, %.2f)",
                lat, lon, len(df), grid_lat, grid_lon,
            )

    except Exception as e:
        logger.warning("Weather obs fetch failed for (%.2f, %.2f): %s", lat, lon, e)

    # Cache
    with _cache_lock:
        _obs_cache[cache_key] = result
        _obs_cache_time[cache_key] = now_ts

    return result
