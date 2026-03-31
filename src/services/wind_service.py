"""
Wind forecast service — ensemble wind/gust forecasts, exceedance probabilities,
weather windows. Ported from marine_service.py, adapted for km/h (land context).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.utils.constants import WIND_ENSEMBLE_MODELS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Single model fetch
# ─────────────────────────────────────────────────────────────────────────────

def fetch_wind_ensemble(lat: float, lon: float, model_key: str = "ECMWF IFS") -> Dict[str, Any]:
    """Fetch wind ensemble for a single model. Returns dict with df, grid_lat, grid_lon."""
    model_cfg = WIND_ENSEMBLE_MODELS.get(model_key)
    if not model_cfg:
        logger.warning("Unknown wind model: %s", model_key)
        return {"df": pd.DataFrame(), "grid_lat": lat, "grid_lon": lon}

    # Check cache first
    try:
        from src.data.cache import get_cache
        cache = get_cache()
        cache_key = f"river:wind:{lat:.4f}:{lon:.4f}:{model_cfg['api_model']}"
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug("Wind cache hit for %s at (%s, %s)", model_key, lat, lon)
            return cached
    except Exception:
        cache = None
        cache_key = None

    try:
        from src.data.api_client import get_api_client
        client = get_api_client()
        result = client.get_wind_ensemble_forecast(lat, lon, model=model_cfg["api_model"])
    except Exception as e:
        logger.warning("Wind fetch failed for %s: %s", model_key, e)
        return {"df": pd.DataFrame(), "grid_lat": lat, "grid_lon": lon}

    # Cache result
    if cache and cache_key and not result["df"].empty:
        cache.set(cache_key, result, ttl_seconds=3600)

    if not result["df"].empty:
        logger.info(
            "Wind ensemble %s: %d rows, %d columns",
            model_key, len(result["df"]), len(result["df"].columns),
        )

    return result


def fetch_all_wind_ensembles(lat: float, lon: float) -> Dict[str, Dict[str, Any]]:
    """Fetch all wind ensemble models. Returns {model_key: result_dict}."""
    results = {}
    for model_key in WIND_ENSEMBLE_MODELS:
        results[model_key] = fetch_wind_ensemble(lat, lon, model_key)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Ensemble statistics
# ─────────────────────────────────────────────────────────────────────────────

def calculate_ensemble_stats(df: pd.DataFrame, variable: str = "wind_speed_10m") -> pd.DataFrame:
    """Calculate median, p10, p90 from ensemble member columns."""
    member_cols = [c for c in df.columns if variable in c and "member" in c]
    if not member_cols:
        return pd.DataFrame()

    member_data = df[member_cols]
    stats = pd.DataFrame(index=df.index)
    stats["median"] = member_data.median(axis=1, skipna=True)
    stats["p10"] = member_data.quantile(0.10, axis=1)
    stats["p90"] = member_data.quantile(0.90, axis=1)
    return stats


def get_gust_stats(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Calculate max, median, p90 from gust ensemble member columns."""
    gust_cols = [c for c in df.columns if "wind_gusts_10m" in c and "member" in c]
    if not gust_cols:
        return None

    member_data = df[gust_cols]
    stats = pd.DataFrame(index=df.index)
    stats["max"] = member_data.max(axis=1, skipna=True)
    stats["median"] = member_data.median(axis=1, skipna=True)
    stats["p90"] = member_data.quantile(0.90, axis=1)
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Exceedance probability
# ─────────────────────────────────────────────────────────────────────────────

def calculate_wind_exceedance(df: pd.DataFrame, threshold_kmh: float) -> pd.Series:
    """
    Calculate % of ensemble members exceeding threshold at each timestep.
    Returns Series of probabilities (0-100).
    """
    wind_cols = [c for c in df.columns if "wind_speed_10m" in c and "member" in c]
    if not wind_cols:
        return pd.Series(dtype=float)

    exceedance = (df[wind_cols] > threshold_kmh).sum(axis=1) / len(wind_cols) * 100
    return exceedance


# ─────────────────────────────────────────────────────────────────────────────
# Model agreement
# ─────────────────────────────────────────────────────────────────────────────

def calculate_model_agreement(wind_data: Dict[str, Dict[str, Any]]) -> Dict:
    """
    Compare median wind forecasts across models.
    Returns score (0-100), level, color, interpretation.
    """
    medians = {}
    for model_key, result in wind_data.items():
        df = result.get("df", pd.DataFrame())
        if df.empty:
            continue
        stats = calculate_ensemble_stats(df, "wind_speed_10m")
        if not stats.empty:
            medians[model_key] = stats["median"]

    if len(medians) < 2:
        return {"score": None, "level": "Insufficient", "color": "gray", "num_models": len(medians)}

    # Align all medians to a common index
    combined = pd.DataFrame(medians)
    spread = combined.std(axis=1, skipna=True)
    avg_spread = spread.mean()

    score = max(0, 100 - (avg_spread / 20 * 100))
    if score >= 80:
        level, color = "High Confidence", "green"
    elif score >= 60:
        level, color = "Moderate Confidence", "blue"
    elif score >= 40:
        level, color = "Low Confidence", "orange"
    else:
        level, color = "Very Low Confidence", "red"

    return {
        "score": round(score, 1),
        "level": level,
        "color": color,
        "avg_spread": round(avg_spread, 1),
        "num_models": len(medians),
        "models": list(medians.keys()),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Weather windows
# ─────────────────────────────────────────────────────────────────────────────

def calculate_weather_windows(
    wind_data: Dict[str, Dict[str, Any]],
    precip_dfs: Dict[str, pd.DataFrame],
    wind_thresh_kmh: float = 100,
    gust_thresh_kmh: float = 130,
    rain_thresh_mm: float = 10,
) -> Dict:
    """
    Identify safe weather windows where ALL conditions are met:
    - Ensemble median wind speed < wind_thresh
    - Ensemble max gust < gust_thresh
    - Max precipitation across models < rain_thresh

    Uses ECMWF IFS as primary model for wind/gust.
    """
    # Get ECMWF wind data (primary model)
    ecmwf = wind_data.get("ECMWF IFS", {})
    df = ecmwf.get("df", pd.DataFrame())
    if df.empty:
        return {"windows": [], "total_hours": 0, "next_window": None, "is_open_now": False}

    # Wind condition: median < threshold
    wind_cols = [c for c in df.columns if "wind_speed_10m" in c and "member" in c]
    if not wind_cols:
        return {"windows": [], "total_hours": 0, "next_window": None, "is_open_now": False}
    median_wind = df[wind_cols].median(axis=1, skipna=True)
    wind_safe = median_wind < wind_thresh_kmh

    # Gust condition: max across members < threshold
    gust_cols = [c for c in df.columns if "wind_gusts_10m" in c and "member" in c]
    if gust_cols:
        max_gust = df[gust_cols].max(axis=1, skipna=True)
        gust_safe = max_gust < gust_thresh_kmh
    else:
        gust_safe = pd.Series(True, index=df.index)

    # Rain condition: max across all models < threshold
    if precip_dfs:
        # Combine all precip models, take max at each timestep
        precip_combined = pd.DataFrame(index=df.index)
        for model_name, precip_df in precip_dfs.items():
            if not precip_df.empty and "precipitation" in precip_df.columns:
                # Reindex to wind timestamps
                reindexed = precip_df["precipitation"].reindex(
                    df.index, method="nearest", tolerance=pd.Timedelta("2h")
                )
                precip_combined[model_name] = reindexed
        if not precip_combined.empty:
            max_precip = precip_combined.max(axis=1, skipna=True).fillna(0)
            rain_safe = max_precip < rain_thresh_mm
        else:
            rain_safe = pd.Series(True, index=df.index)
    else:
        rain_safe = pd.Series(True, index=df.index)

    # Combined safe mask
    safe_mask = wind_safe & gust_safe & rain_safe

    # Extract contiguous windows
    windows = _extract_contiguous_windows(safe_mask)

    # Calculate summary
    total_hours = sum(
        int((end - start).total_seconds() / 3600) for start, end in windows
    )

    now = pd.Timestamp.now(tz="UTC")
    if df.index.tz is None:
        now = now.tz_localize(None)

    is_open_now = False
    next_window = None
    for start, end in windows:
        if start <= now <= end:
            is_open_now = True
            next_window = (start, end)
            break
        elif start > now and next_window is None:
            next_window = (start, end)

    return {
        "windows": windows,
        "total_hours": total_hours,
        "next_window": next_window,
        "is_open_now": is_open_now,
    }


def _extract_contiguous_windows(mask: pd.Series) -> List[Tuple]:
    """Extract contiguous True runs as (start, end) timestamp tuples."""
    if mask.empty:
        return []

    windows = []
    in_window = False
    start = None

    for ts, safe in mask.items():
        if safe and not in_window:
            start = ts
            in_window = True
        elif not safe and in_window:
            windows.append((start, ts))
            in_window = False

    # Close final window if still open
    if in_window and start is not None:
        windows.append((start, mask.index[-1]))

    return windows
