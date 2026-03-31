"""
River Monitor — Configuration.
Environment-driven config for standalone deployment.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration."""

    # App
    APP_NAME = "River Monitor"
    DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 8050))

    # Data directory
    DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent / "data"))

    # Redis cache (optional — app runs without it)
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Open-Meteo API key (commercial subscription — leave blank for free tier)
    OPENMETEO_API_KEY = os.getenv("OPENMETEO_API_KEY", "")

    # Open-Meteo API endpoints (customer URLs when API key is set)
    OPENMETEO_FORECAST_URL = os.getenv(
        "OPENMETEO_FORECAST_URL",
        "https://customer-api.open-meteo.com/v1/forecast" if os.getenv("OPENMETEO_API_KEY") else "https://api.open-meteo.com/v1/forecast"
    )
    OPENMETEO_MARINE_URL = os.getenv(
        "OPENMETEO_MARINE_URL",
        "https://customer-marine-api.open-meteo.com/v1/marine" if os.getenv("OPENMETEO_API_KEY") else "https://marine-api.open-meteo.com/v1/marine"
    )
    OPENMETEO_ENSEMBLE_URL = os.getenv(
        "OPENMETEO_ENSEMBLE_URL",
        "https://customer-ensemble-api.open-meteo.com/v1/ensemble" if os.getenv("OPENMETEO_API_KEY") else "https://ensemble-api.open-meteo.com/v1/ensemble"
    )

    # API tuning
    API_TIMEOUT = int(os.getenv("API_TIMEOUT", 30))
    API_MAX_CONNECTIONS = int(os.getenv("API_MAX_CONNECTIONS", 10))

    # Data source selector (future: "bom-api" for live BoM Water API)
    DATA_SOURCE = os.getenv("DATA_SOURCE", "sqlite")

    # Flood Scenarios PDF directory
    FLOOD_SCENARIOS_DIR = Path(
        os.getenv("FLOOD_SCENARIOS_DIR", Path(__file__).parent / "data" / "flood_scenarios")
    )

    # Google Analytics 4 (leave blank to disable tracking)
    GA_MEASUREMENT_ID = os.getenv("GA_MEASUREMENT_ID", "")


def get_config() -> Config:
    """Return the application configuration."""
    return Config()
