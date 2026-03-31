"""
River Monitor — Constants.
River/flood/tide-specific constants for the standalone app.
"""

# =============================================================================
# FLOOD CLASSIFICATION
# =============================================================================

FLOOD_CLASSIFICATION_COLORS = {
    "Major": {"color": "#dc2626", "radius": 12, "opacity": 0.8},
    "Moderate": {"color": "#f97316", "radius": 10, "opacity": 0.8},
    "Minor": {"color": "#22c55e", "radius": 8, "opacity": 0.8},
    "Normal": {"color": "#3b82f6", "radius": 5, "opacity": 0.5},
    "Unknown": {"color": "#9ca3af", "radius": 4, "opacity": 0.4},
}

QUALITY_LABELS = {
    10: "Good",
    20: "Suspect",
    30: "Bad",
}

RIVER_SENSOR_TYPES = ["water level gauge", "tide gauge", "reservoir"]

# =============================================================================
# TIDE FORECAST (Open-Meteo Marine API)
# =============================================================================

TIDAL_SENSOR_TYPES = ["tide gauge"]
TIDAL_NAME_KEYWORDS = ["tide", "tidal"]
TIDE_MARINE_VARIABLE = "sea_level_height_msl"
TIDE_PAST_HOURS = 72           # 3 days past context
TIDE_FORECAST_HOURS = 168      # 7 days forward
TIDE_CACHE_TTL_SECONDS = 1800  # 30 min
TIDE_TRACE_COLOR = "#14b8a6"
TIDE_TRACE_LINE_WIDTH = 2.5
TIDE_FILL_COLOR = "rgba(20, 184, 166, 0.12)"
TIDE_CHART_HEIGHT = 380

# Highest Astronomical Tide (HAT) reference values (metres above MSL)
# Source: BoM / Australian Hydrographic Office tidal planes
# Stations not in this lookup will use max(forecast) as estimated HAT
TIDE_HAT_VALUES = {
    # Queensland
    "040647-0": 1.32,   # Brisbane Bar
    "033305-0": 3.30,   # Outer Harbour (Mackay)
    "531044-0": 1.58,   # Cairns Harbour
    "531050-0": 1.58,   # Cairns Harbour Alert
    "527004-0": 1.80,   # Weipa
    "527005-0": 1.72,   # Thursday Island
    "531013-0": 1.50,   # Cooktown
    "531016-0": 1.45,   # Port Douglas
    "531014-0": 1.50,   # Mossman
    "529003-0": 2.10,   # Karumba
    "532002-0": 2.10,   # Clump Point
    "529040-0": 2.50,   # Burketown
    "529020-0": 1.90,   # Mornington Island
    "531089-0": 1.50,   # Palm Cove
    # NSW
    "206003-0": 1.10,   # Sydney Harbour
    "210004-0": 1.00,   # Port Kembla
    "213010-0": 1.10,   # Newcastle
    # Victoria
    "305025-0": 0.60,   # Melbourne (Williamstown)
    "305030-0": 0.90,   # Stony Point
    # South Australia
    "A2390522": 1.55,   # Port Adelaide Outer Harbour
    # Western Australia
    "F05020-0": 0.70,   # Fremantle
    "F00080-0": 4.90,   # Broome
    "F02270-0": 3.50,   # Port Hedland
    "F01590-0": 1.90,   # Exmouth
    "F02830-0": 1.20,   # Geraldton
    # Northern Territory
    "G81400-0": 4.10,   # Darwin
    "G81500-0": 4.00,   # Darwin East Arm
}

# =============================================================================
# FLOOD ZONE GEOJSON STYLES
# =============================================================================

FLOOD_ZONE_STYLES = {
    "Red": {"fillColor": "#DC143C", "color": "#8B0000", "fillOpacity": 0.35},
    "Amber": {"fillColor": "#FF8C00", "color": "#CC7000", "fillOpacity": 0.25},
    "Green": {"fillColor": "#228B22", "color": "#006400", "fillOpacity": 0.25},
    "None": {"fillColor": "#6495ED", "color": "#4169E1", "fillOpacity": 0.15},
}

# =============================================================================
# UI THEME TOKENS
# =============================================================================

THEME_COLORS = {
    "bg_primary": "#080c14",
    "bg_secondary": "#0d1320",
    "bg_panel": "#111827",
    "bg_panel_hover": "#1a2332",
    "border": "#1e293b",
    "border_active": "#f59e0b",
    "text_primary": "#f1f5f9",
    "text_secondary": "#94a3b8",
    "text_muted": "#64748b",
    "accent": "#f59e0b",
    "accent_dim": "rgba(245,158,11,0.15)",
    "danger": "#ef4444",
    "success": "#22c55e",
    "info": "#3b82f6",
    "warning": "#f59e0b",
}

# Chart layout defaults (dark theme)
PLOTLY_LAYOUT_DEFAULTS = {
    "template": "plotly_dark",
    "paper_bgcolor": "#111827",
    "plot_bgcolor": "#0d1320",
    "font": {"family": "DM Sans, sans-serif", "color": "#f1f5f9", "size": 12},
    "margin": {"l": 50, "r": 30, "t": 40, "b": 80},
    "hovermode": "x unified",
    "legend": {
        "orientation": "h",
        "yanchor": "top",
        "y": -0.30,
        "xanchor": "left",
        "x": 0,
        "font": {"size": 10},
    },
}

# Map tile URLs
MAP_TILES = {
    "voyager": "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
    "dark": "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    "esri-topo": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    "osm": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
}

MAP_TILE_OPTIONS = [
    {"label": "Voyager", "value": "voyager"},
    {"label": "Dark", "value": "dark"},
    {"label": "Esri Topo", "value": "esri-topo"},
    {"label": "OpenStreetMap", "value": "osm"},
]

# Australia center for default map view
AUSTRALIA_CENTER = [-25.5, 134.0]
AUSTRALIA_ZOOM = 4

# =============================================================================
# PRECIPITATION FORECAST
# =============================================================================

PRECIP_MODELS = {
    "ECMWF IFS": {"api_model": "ecmwf_ifs025", "color": "#d62728"},
    "GFS": {"api_model": "gfs_seamless", "color": "#1f77b4"},
    "ICON": {"api_model": "icon_seamless", "color": "#2ca02c"},
}

PRECIP_FORECAST_HOURS = 168  # 7 days
PRECIP_PAST_HOURS = 24       # 1 day context

# =============================================================================
# WIND / GUST ENSEMBLE FORECASTS
# =============================================================================

WIND_ENSEMBLE_MODELS = {
    "ECMWF IFS": {"api_model": "ecmwf_ifs025", "members": 51, "color": "#d62728"},
    "GFS": {"api_model": "gfs025", "members": 31, "color": "#1f77b4"},
    "ICON": {"api_model": "icon_global", "members": 40, "color": "#2ca02c"},
}

WIND_ENSEMBLE_FILL_COLORS = {
    "ECMWF IFS": "rgba(214, 39, 40, 0.12)",
    "GFS": "rgba(31, 119, 180, 0.12)",
    "ICON": "rgba(44, 160, 44, 0.12)",
}

# Default thresholds (km/h — land/infrastructure context, not marine knots)
DEFAULT_WIND_THRESHOLD_KMH = 100
DEFAULT_GUST_THRESHOLD_KMH = 130

# Weather windows
DEFAULT_WEATHER_WINDOW_WIND_KMH = 100
DEFAULT_WEATHER_WINDOW_GUST_KMH = 130
DEFAULT_WEATHER_WINDOW_RAIN_MM = 10
WEATHER_WINDOW_COLOR = "rgba(34, 197, 94, 0.12)"

# Beaufort-scale reference lines for land context (km/h)
WIND_REF_GALE = 63       # Gale force (Beaufort 8)
WIND_REF_STORM = 89      # Storm force (Beaufort 10)
WIND_REF_HURRICANE = 118  # Hurricane force (Beaufort 12)
