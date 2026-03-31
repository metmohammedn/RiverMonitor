"""
Open-Meteo API client — tide forecasts only.
Slim version for the River Monitor standalone app.
"""
import asyncio
import logging
import time
from typing import Optional

import httpx
import pandas as pd

logger = logging.getLogger(__name__)


class OpenMeteoClient:
    """
    HTTP client for the Open-Meteo Marine API (tide forecasts).
    Features: connection pooling, automatic retries with backoff.
    """

    def __init__(
        self,
        forecast_url: str = "https://api.open-meteo.com/v1/forecast",
        marine_url: str = "https://marine-api.open-meteo.com/v1/marine",
        ensemble_url: str = "https://ensemble-api.open-meteo.com/v1/ensemble",
        api_key: str = "",
        timeout: int = 30,
        max_connections: int = 10,
        max_retries: int = 3,
    ):
        self._forecast_url = forecast_url
        self._marine_url = marine_url
        self._ensemble_url = ensemble_url
        self._api_key = api_key
        self._max_retries = max_retries

        self._client = httpx.Client(
            timeout=timeout,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_connections // 2,
                keepalive_expiry=60,
            ),
            transport=httpx.HTTPTransport(retries=max_retries),
        )

        self._async_client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_connections // 2,
                keepalive_expiry=60,
            ),
            transport=httpx.AsyncHTTPTransport(retries=max_retries),
        )

    def close(self):
        """Close the HTTP client and release connections."""
        self._client.close()

    async def aclose(self):
        """Close the async HTTP client."""
        await self._async_client.aclose()

    def _request(self, url: str, params: dict) -> dict:
        """Make a GET request with retry logic. Appends API key if configured."""
        if self._api_key:
            params = {**params, "apikey": self._api_key}
        for attempt in range(self._max_retries):
            try:
                response = self._client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "API HTTP error (attempt %d/%d): %s %s",
                    attempt + 1, self._max_retries, e.response.status_code, url,
                )
                if attempt == self._max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
            except httpx.RequestError as e:
                logger.warning(
                    "API request error (attempt %d/%d): %s",
                    attempt + 1, self._max_retries, e,
                )
                if attempt == self._max_retries - 1:
                    raise
                time.sleep(2 ** attempt)

    async def _async_request(self, url: str, params: dict) -> dict:
        """Make an async GET request with retry logic. Appends API key if configured."""
        if self._api_key:
            params = {**params, "apikey": self._api_key}
        for attempt in range(self._max_retries):
            try:
                response = await self._async_client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "Async API HTTP error (attempt %d/%d): %s %s",
                    attempt + 1, self._max_retries, e.response.status_code, url,
                )
                if attempt == self._max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
            except httpx.RequestError as e:
                logger.warning(
                    "Async API request error (attempt %d/%d): %s",
                    attempt + 1, self._max_retries, e,
                )
                if attempt == self._max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

    # ─────────────────────────────────────────────────────────────────────
    # Tide forecast
    # ─────────────────────────────────────────────────────────────────────

    def get_tide_forecast(
        self,
        lat: float,
        lon: float,
        past_hours: int = 72,
        forecast_hours: int = 168,
    ) -> pd.DataFrame:
        """
        Fetch sea-level height (MSL) from the Open-Meteo Marine API.

        Includes ocean tides, inverted barometer effect, and sea surface
        height anomaly.  Resolution ~8 km.

        Returns DataFrame indexed by datetime with 'sea_level_height_msl' column.
        """
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "sea_level_height_msl",
            "past_hours": past_hours,
            "forecast_hours": forecast_hours,
        }

        try:
            data = self._request(self._marine_url, params)
        except Exception:
            logger.error(
                "Tide forecast request failed for (%s, %s)", lat, lon,
            )
            return pd.DataFrame()

        if "hourly" not in data:
            return pd.DataFrame()

        hourly = data["hourly"]
        df = pd.DataFrame({"time": pd.to_datetime(hourly["time"])})
        df = df.set_index("time")

        for key, values in hourly.items():
            if key != "time":
                df[key] = pd.to_numeric(
                    pd.Series(values, index=df.index), errors="coerce"
                )

        return df

    # ─────────────────────────────────────────────────────────────────────
    # Wind ensemble forecast
    # ─────────────────────────────────────────────────────────────────────

    def get_wind_ensemble_forecast(
        self,
        lat: float,
        lon: float,
        model: str = "ecmwf_ifs025",
    ) -> dict:
        """
        Fetch wind speed + gust ensemble forecast from Open-Meteo Ensemble API.

        Returns dict with 'df' (DataFrame with member columns in km/h),
        'grid_lat', 'grid_lon'.
        """
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "wind_speed_10m,wind_gusts_10m",
            "models": model,
            "timezone": "GMT",
        }

        try:
            data = self._request(self._ensemble_url, params)
        except Exception:
            logger.error(
                "Wind ensemble failed for (%s, %s) model=%s", lat, lon, model,
            )
            return {"df": pd.DataFrame(), "grid_lat": lat, "grid_lon": lon}

        grid_lat = data.get("latitude", lat)
        grid_lon = data.get("longitude", lon)

        if "hourly" not in data:
            return {"df": pd.DataFrame(), "grid_lat": grid_lat, "grid_lon": grid_lon}

        hourly = data["hourly"]
        df = pd.DataFrame({"time": pd.to_datetime(hourly["time"])})
        df = df.set_index("time")

        for key, values in hourly.items():
            if key != "time":
                # Values are already in km/h — no conversion needed
                df[key] = pd.to_numeric(
                    pd.Series(values, index=df.index), errors="coerce"
                )

        return {"df": df, "grid_lat": grid_lat, "grid_lon": grid_lon}

    # ─────────────────────────────────────────────────────────────────────
    # Precipitation forecast (multi-model)
    # ─────────────────────────────────────────────────────────────────────

    def get_precipitation_forecast(
        self,
        lat: float,
        lon: float,
        model: str = "ecmwf_ifs025",
        past_hours: int = 24,
        forecast_hours: int = 168,
    ) -> tuple:
        """
        Fetch hourly precipitation from Open-Meteo Forecast API.

        Returns (DataFrame, grid_lat, grid_lon) where grid_lat/grid_lon are
        the actual coordinates Open-Meteo snapped to on its model grid.
        """
        forecast_url = self._forecast_url
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "precipitation",
            "past_hours": past_hours,
            "forecast_hours": forecast_hours,
            "models": model,
        }

        try:
            data = self._request(forecast_url, params)
        except Exception:
            logger.error(
                "Precipitation forecast failed for (%s, %s) model=%s",
                lat, lon, model,
            )
            return pd.DataFrame(), lat, lon

        # Extract the grid coordinates Open-Meteo actually used
        grid_lat = data.get("latitude", lat)
        grid_lon = data.get("longitude", lon)

        if "hourly" not in data:
            return pd.DataFrame(), grid_lat, grid_lon

        hourly = data["hourly"]
        df = pd.DataFrame({"time": pd.to_datetime(hourly["time"])})
        df = df.set_index("time")

        for key, values in hourly.items():
            if key != "time":
                df[key] = pd.to_numeric(
                    pd.Series(values, index=df.index), errors="coerce"
                )

        return df, grid_lat, grid_lon


# Module-level singleton (initialized in app factory)
_client: Optional[OpenMeteoClient] = None


def init_api_client(
    forecast_url: str = "https://api.open-meteo.com/v1/forecast",
    marine_url: str = "https://marine-api.open-meteo.com/v1/marine",
    ensemble_url: str = "https://ensemble-api.open-meteo.com/v1/ensemble",
    api_key: str = "",
    timeout: int = 30,
    max_connections: int = 10,
) -> OpenMeteoClient:
    """Initialize the global API client."""
    global _client
    _client = OpenMeteoClient(
        forecast_url=forecast_url,
        marine_url=marine_url,
        ensemble_url=ensemble_url,
        api_key=api_key,
        timeout=timeout,
        max_connections=max_connections,
    )
    return _client


def get_api_client() -> OpenMeteoClient:
    """Get the global API client."""
    if _client is None:
        raise RuntimeError("API client not initialized. Call init_api_client() first.")
    return _client
