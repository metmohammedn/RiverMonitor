"""
River monitoring service — flood classification, station queries, threshold lookups.
"""
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.utils.constants import FLOOD_CLASSIFICATION_COLORS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Database path
# ─────────────────────────────────────────────────────────────────────────────

def _get_db_path() -> Path:
    """Get path to the river observations SQLite database."""
    from config import get_config
    config = get_config()
    return config.DATA_DIR / "water_obsv2.db"


def _get_connection():
    """Get SQLite connection to river database."""
    db_path = _get_db_path()
    if not db_path.exists():
        logger.warning("River database not found: %s", db_path)
        return None
    return sqlite3.connect(str(db_path))


# ─────────────────────────────────────────────────────────────────────────────
# Station metadata
# ─────────────────────────────────────────────────────────────────────────────

_station_meta_cache = None


def load_station_metadata() -> pd.DataFrame:
    """Load river station metadata (coordinates, sensor type) from CSV."""
    global _station_meta_cache
    if _station_meta_cache is not None:
        return _station_meta_cache

    from config import get_config
    config = get_config()
    csv_path = config.DATA_DIR / "rain_river_station_list.csv"

    if not csv_path.exists():
        logger.warning("Station metadata not found: %s", csv_path)
        return pd.DataFrame()

    try:
        meta = pd.read_csv(csv_path)
        # Filter to water-related sensors only
        water_sensors = meta[
            meta["SENSOR_TYPE"].isin(["water level gauge", "tide gauge", "reservoir"])
        ].copy()
        # Deduplicate by SENSORID
        water_sensors = water_sensors.drop_duplicates(subset=["SENSORID"])
        _station_meta_cache = water_sensors
        logger.info("Loaded %d river station metadata entries", len(water_sensors))
        return water_sensors
    except Exception as e:
        logger.error("Failed to load station metadata: %s", e)
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Flood classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_flood_level(row) -> str:
    """
    Classify a station reading by flood thresholds.
    Returns: 'Major', 'Moderate', 'Minor', 'Normal', or 'Unknown'.
    """
    if pd.isna(row.get("Minor")):
        return "Unknown"
    value = row.get("RealValue", 0)
    if pd.notna(row.get("Major")) and value >= row["Major"]:
        return "Major"
    elif pd.notna(row.get("Moderate")) and value >= row["Moderate"]:
        return "Moderate"
    elif pd.notna(row.get("Minor")) and value >= row["Minor"]:
        return "Minor"
    else:
        return "Normal"


FLOOD_LEVEL_NUM = {"Major": 3, "Moderate": 2, "Minor": 1, "Normal": 0, "Unknown": 0}


# ─────────────────────────────────────────────────────────────────────────────
# Data queries
# ─────────────────────────────────────────────────────────────────────────────

def get_latest_river_levels() -> pd.DataFrame:
    """
    Get the latest observation for each river sensor.
    Returns DataFrame with one row per sensor, with flood classification.
    """
    conn = _get_connection()
    if conn is None:
        return pd.DataFrame()

    try:
        query = """
        WITH latest_obs AS (
            SELECT sensor, MAX(ObservationTimestamp) as max_time
            FROM river
            GROUP BY sensor
        )
        SELECT r.*
        FROM river r
        INNER JOIN latest_obs l ON r.sensor = l.sensor
            AND r.ObservationTimestamp = l.max_time
        WHERE r.RealValue IS NOT NULL
            AND r.RealValue > -9999
        """
        df = pd.read_sql(query, conn, parse_dates=["ObservationTimestamp"])
        conn.close()

        if df.empty:
            return df

        # Convert types
        for col in ["RealValue", "Minor", "Moderate", "Major"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Classify flood levels
        df["classification"] = df.apply(classify_flood_level, axis=1)
        df["level_num"] = df["classification"].map(FLOOD_LEVEL_NUM)

        # Sort by severity
        df = df.sort_values(["level_num", "RealValue"], ascending=[False, False])

        # Deduplicate by sensor ID — keep the first row (highest severity)
        df = df.drop_duplicates(subset=["sensor"], keep="first")

        logger.info("Loaded latest river levels: %d sensors", len(df))
        return df

    except Exception as e:
        logger.error("Failed to get latest river levels: %s", e)
        if conn:
            conn.close()
        return pd.DataFrame()


def get_station_history(sensor_id: str, days: int = 7) -> pd.DataFrame:
    """
    Get river observation history for a specific sensor.
    Falls back to all records if date filter returns empty.
    """
    conn = _get_connection()
    if conn is None:
        return pd.DataFrame()

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = """
        SELECT * FROM river
        WHERE sensor = ?
        AND ObservationTimestamp >= ?
        AND RealValue IS NOT NULL
        AND RealValue > -9999
        ORDER BY ObservationTimestamp
        """
        df = pd.read_sql(query, conn, params=(sensor_id, cutoff.isoformat()),
                         parse_dates=["ObservationTimestamp"])

        # Fallback: get all records if date filter was too narrow
        if df.empty:
            query_all = """
            SELECT * FROM river
            WHERE sensor = ?
            AND RealValue IS NOT NULL
            AND RealValue > -9999
            ORDER BY ObservationTimestamp
            """
            df = pd.read_sql(query_all, conn, params=(sensor_id,),
                             parse_dates=["ObservationTimestamp"])

        conn.close()

        for col in ["RealValue", "Minor", "Moderate", "Major"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    except Exception as e:
        logger.error("Failed to get station history for %s: %s", sensor_id, e)
        if conn:
            conn.close()
        return pd.DataFrame()


def get_last_n_records(sensor_id: str, n: int = 50) -> pd.DataFrame:
    """Get the last N observations for a sensor."""
    conn = _get_connection()
    if conn is None:
        return pd.DataFrame()

    try:
        query = """
        SELECT * FROM river
        WHERE sensor = ?
        AND RealValue IS NOT NULL
        AND RealValue > -9999
        ORDER BY ObservationTimestamp DESC
        LIMIT ?
        """
        df = pd.read_sql(query, conn, params=(sensor_id, n),
                         parse_dates=["ObservationTimestamp"])
        conn.close()

        if not df.empty:
            df = df.sort_values("ObservationTimestamp")

        for col in ["RealValue", "Minor", "Moderate", "Major"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    except Exception as e:
        logger.error("Failed to get last %d records for %s: %s", n, sensor_id, e)
        if conn:
            conn.close()
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Summary helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_flood_summary(df_latest: pd.DataFrame) -> Dict[str, int]:
    """Get counts by flood classification."""
    if df_latest.empty or "classification" not in df_latest.columns:
        return {"Major": 0, "Moderate": 0, "Minor": 0, "Normal": 0, "Unknown": 0, "Total": 0}

    counts = df_latest["classification"].value_counts().to_dict()
    return {
        "Major": counts.get("Major", 0),
        "Moderate": counts.get("Moderate", 0),
        "Minor": counts.get("Minor", 0),
        "Normal": counts.get("Normal", 0),
        "Unknown": counts.get("Unknown", 0),
        "Total": len(df_latest),
    }


def get_above_threshold_stations(df_latest: pd.DataFrame) -> pd.DataFrame:
    """Get stations currently above any flood threshold."""
    if df_latest.empty or "level_num" not in df_latest.columns:
        return pd.DataFrame()
    return df_latest[df_latest["level_num"] > 0].copy()


def get_station_options(df_latest: pd.DataFrame) -> List[Dict[str, str]]:
    """
    Get station selector options sorted by severity.
    Format: "🔴 Major - Station Name (sensor) - 5.23m"
    Deduplicates by sensor ID.
    """
    if df_latest.empty:
        return []

    icons = {"Major": "🔴", "Moderate": "🟠", "Minor": "🟢", "Normal": "🔵", "Unknown": "⚪"}
    options = []
    seen_sensors = set()
    for _, row in df_latest.iterrows():
        sensor = row.get("sensor", "")
        if sensor in seen_sensors:
            continue
        seen_sensors.add(sensor)
        icon = icons.get(row.get("classification", "Unknown"), "⚪")
        name = row.get("StationName", row.get("station", "Unknown"))
        value = row.get("RealValue", 0)
        cls = row.get("classification", "")
        label = f"{icon} {cls} - {name} ({sensor}) - {value:.2f}m"
        options.append({"label": label, "value": sensor})

    return options


def merge_with_coordinates(df_stations: pd.DataFrame) -> pd.DataFrame:
    """Merge station data with lat/lon coordinates from metadata."""
    meta = load_station_metadata()
    if meta.empty or df_stations.empty:
        return df_stations

    merged = df_stations.merge(
        meta[["SENSORID", "LAT", "LONG"]],
        left_on="sensor", right_on="SENSORID", how="left",
    )
    # Drop rows without coordinates
    merged = merged[merged["LAT"].notna() & merged["LONG"].notna()].copy()
    return merged
