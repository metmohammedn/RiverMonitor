"""
River Monitor — EA-style map-first layout.
Standalone page with flood-classified station markers, search, layer toggles,
station detail below map, and flood scenarios PDF viewer.
"""
import base64
import io
import json
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime

import pandas as pd
import dash
from dash import html, dcc, callback, Input, Output, State, no_update, ctx, ALL
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import dash_leaflet as dl
from flask import request, jsonify

from src.utils.constants import FLOOD_CLASSIFICATION_COLORS

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/",
    name="River Monitor",
    title="River Monitor",
)

_INPUT_STYLE = {
    "input": {"backgroundColor": "#0d1320", "border": "1px solid #1e293b"},
}
_COMBOBOX_PORTAL = {"withinPortal": True, "zIndex": 1000}

# Flood classification colors and marker radii
_FLOOD_COLORS = {
    "Major": "#ef4444",
    "Moderate": "#f59e0b",
    "Minor": "#22c55e",
    "Normal": "#3b82f6",
    "Unknown": "#6b7280",
}
_FLOOD_RADII = {"Major": 12, "Moderate": 10, "Minor": 8, "Normal": 5, "Unknown": 4}

# Flood zone polygon style by severity
_FLOOD_ZONE_COLORS = {
    "Red": {"color": "#ef4444", "fillColor": "#ef4444", "fillOpacity": 0.25, "weight": 2},
    "Amber": {"color": "#f59e0b", "fillColor": "#f59e0b", "fillOpacity": 0.20, "weight": 1.5},
    "Green": {"color": "#22c55e", "fillColor": "#22c55e", "fillOpacity": 0.15, "weight": 1},
}
_FLOOD_ZONE_DEFAULT_STYLE = {"color": "#64748b", "fillColor": "#64748b", "fillOpacity": 0.1, "weight": 1}

# Path to flood zones GeoJSON file
_FLOOD_ZONES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "FloodZones_for_BOM.geojson"
)


def _load_flood_zones_geojson():
    """Load and return the FloodZones GeoJSON data, or None if unavailable."""
    try:
        path = os.path.normpath(_FLOOD_ZONES_PATH)
        if not os.path.exists(path):
            logger.warning("FloodZones GeoJSON not found at %s", path)
            return None
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load FloodZones GeoJSON: %s", e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# RAINVIEWER RADAR TILES
# ─────────────────────────────────────────────────────────────────────────────
_rainviewer_cache = {"url": None, "fetched_at": 0}


def _get_rainviewer_tile_url():
    """Fetch the latest radar tile URL from RainViewer API (cached 5 min)."""
    import time as _time
    now = _time.time()
    if _rainviewer_cache["url"] and (now - _rainviewer_cache["fetched_at"]) < 300:
        return _rainviewer_cache["url"]

    try:
        import httpx
        resp = httpx.get("https://api.rainviewer.com/public/weather-maps.json", timeout=5)
        data = resp.json()
        # Get the latest radar frame
        radar_frames = data.get("radar", {}).get("past", [])
        if radar_frames:
            latest = radar_frames[-1]
            path = latest["path"]
            url = f"https://tilecache.rainviewer.com{path}/256/{{z}}/{{x}}/{{y}}/6/1_1.png"
            _rainviewer_cache["url"] = url
            _rainviewer_cache["fetched_at"] = now
            return url
    except Exception as e:
        logger.warning("Failed to fetch RainViewer radar data: %s", e)

    return _rainviewer_cache.get("url")


# ─────────────────────────────────────────────────────────────────────────────
# USER LAYER UPLOAD — session-only in-memory storage
# ─────────────────────────────────────────────────────────────────────────────
_user_layers: dict = {}

_ALLOWED_EXTENSIONS = {".geojson", ".json", ".zip"}
_MAX_FILE_SIZE_MB = 50


def _parse_uploaded_file(file_storage):
    """Parse an uploaded file (GeoJSON or zipped shapefile) into a GeoJSON dict."""
    filename = file_storage.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in _ALLOWED_EXTENSIONS:
        return None, f"Unsupported file type: {ext}"

    if ext in (".geojson", ".json"):
        try:
            data = json.load(file_storage)
            if data.get("type") != "FeatureCollection" or not data.get("features"):
                return None, "GeoJSON must be a FeatureCollection with at least one feature"
            return data, None
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return None, f"Invalid JSON: {e}"

    # .zip — extract and read with geopandas/fiona
    if ext == ".zip":
        tmp_dir = tempfile.mkdtemp(prefix="river_upload_")
        try:
            import zipfile as _zipfile

            zip_path = os.path.join(tmp_dir, filename)
            file_storage.save(zip_path)
            if not _zipfile.is_zipfile(zip_path):
                return None, "Uploaded .zip is not a valid ZIP archive"

            import geopandas as gpd

            gdf = gpd.read_file(f"zip://{zip_path}")
            if gdf.empty:
                return None, "No features found in shapefile"
            # Reproject to WGS84 if needed
            if gdf.crs and not gdf.crs.equals("EPSG:4326"):
                gdf = gdf.to_crs(epsg=4326)
            geojson_str = gdf.to_json()
            return json.loads(geojson_str), None
        except Exception as e:
            return None, f"Failed to read shapefile: {e}"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return None, "Unsupported file type"


def init_river_routes(server):
    """Register server-side upload endpoints on the Flask server."""

    @server.route("/api/river/upload-layer", methods=["POST"])
    def river_upload_layer():
        files = request.files.getlist("files")
        if not files:
            return jsonify({"error": "No files provided"}), 400

        loaded = []
        for f in files:
            geojson, err = _parse_uploaded_file(f)
            if err:
                logger.warning("Layer upload rejected (%s): %s", f.filename, err)
                continue
            layer_id = uuid.uuid4().hex[:8]
            feature_count = len(geojson.get("features", []))
            _user_layers[layer_id] = {
                "name": f.filename,
                "geojson": geojson,
                "feature_count": feature_count,
            }
            loaded.append({
                "layer_id": layer_id,
                "name": f.filename,
                "feature_count": feature_count,
            })
            logger.info(
                "User layer uploaded: %s → %s (%d features)",
                f.filename, layer_id, feature_count,
            )

        if not loaded:
            return jsonify({"error": "No valid GeoJSON or shapefile found"}), 400

        return jsonify({"loaded": loaded}), 200

    @server.route("/api/river/clear-layers", methods=["POST"])
    def river_clear_layers():
        _user_layers.clear()
        logger.info("User layers cleared")
        return jsonify({"cleared": True}), 200


# ─────────────────────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────────────────────

def layout():
    return dmc.Stack(
        gap="md",
        style={"padding": "16px"},
        children=[
            # POC banner
            dmc.Alert(
                title="Proof of Concept",
                color="yellow", variant="light",
                icon=DashIconify(icon="tabler:info-circle"),
                children=(
                    "River data is from archived records (April 2022). "
                    "Production version will connect to live gauge feeds."
                ),
            ),
            # Search bar + summary metrics row
            dmc.Group(
                gap="md",
                align="flex-end",
                wrap="wrap",
                children=[
                    dmc.TextInput(
                        id="river-search",
                        placeholder="Search station, river, or location...",
                        leftSection=DashIconify(icon="tabler:search"),
                        w={"base": "100%", "sm": 350},
                        styles=_INPUT_STYLE,
                    ),
                ],
            ),
            # Summary metrics
            dmc.SimpleGrid(
                cols={"base": 2, "sm": 4, "lg": 5},
                spacing="md",
                children=[
                    _flood_metric("Major Flood", "0", "red", "tabler:alert-octagon", "river-major-count"),
                    _flood_metric("Moderate Flood", "0", "orange", "tabler:alert-triangle", "river-moderate-count"),
                    _flood_metric("Minor Flood", "0", "green", "tabler:alert-circle", "river-minor-count"),
                    _flood_metric("Normal", "0", "blue", "tabler:check", "river-normal-count"),
                    _flood_metric("Total Gauges", "0", "gray", "tabler:database", "river-total-count"),
                ],
            ),
            # View selector — 5 modes
            dmc.SegmentedControl(
                id="river-view-mode",
                data=[
                    {"label": "Map Overview", "value": "map"},
                    {"label": "Station Details", "value": "details"},
                    {"label": "Above Threshold", "value": "threshold"},
                    {"label": "Flood Scenarios", "value": "scenarios"},
                    {"label": "Forecast Demo", "value": "forecast-demo"},
                ],
                value="map", color="orange", fullWidth=True,
            ),
            # ─── MAP + DETAIL GRID (60/40 split on desktop) ─────────────
            html.Div(
                id="river-map-grid-wrapper",
                children=dmc.Grid(
                    gutter="md",
                    children=[
                        dmc.GridCol(
                            span={"base": 12, "md": 7},
                            children=[
                                dmc.Paper(
                    shadow="sm", p="md", radius="md",
                    style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                    children=[
                        dmc.Group(
                            justify="space-between",
                            mb="sm",
                            wrap="wrap",
                            children=[
                                dmc.Text("River Gauge Network", size="lg", fw=600, c="white"),
                                dmc.Group(gap="sm", wrap="wrap", children=[
                                    # Map style selector
                                    dmc.Select(
                                        id="river-map-tile-select",
                                        label="Map Style",
                                        data=[
                                            {"label": "Esri Topo", "value": "esri-topo"},
                                            {"label": "Voyager", "value": "voyager"},
                                            {"label": "Dark", "value": "dark"},
                                            {"label": "OpenStreetMap", "value": "osm"},
                                        ],
                                        value="esri-topo",
                                        w=160,
                                        size="xs",
                                        leftSection=DashIconify(icon="tabler:map", width=14),
                                        styles=_INPUT_STYLE,
                                        comboboxProps=_COMBOBOX_PORTAL,
                                    ),
                                    # Upload layer controls
                                    dmc.Button(
                                        "Upload Layer",
                                        id="river-upload-layer-btn",
                                        leftSection=DashIconify(icon="tabler:upload", width=16),
                                        variant="outline", color="cyan", size="xs",
                                    ),
                                    dmc.Button(
                                        "Clear Layer",
                                        id="river-clear-layer-btn",
                                        leftSection=DashIconify(icon="tabler:x", width=14),
                                        variant="subtle", color="red", size="xs",
                                        style={"display": "none"},
                                    ),
                                    dmc.Badge(
                                        "", id="river-upload-status",
                                        color="cyan", variant="outline", size="sm",
                                        style={"display": "none"},
                                    ),
                                    dmc.Switch(
                                        id="river-flood-zones-toggle",
                                        label="Flood Zones",
                                        checked=False,
                                        color="orange",
                                        size="sm",
                                        styles={"label": {"color": "#94a3b8", "cursor": "pointer"}},
                                    ),
                                    dmc.Switch(
                                        id="river-radar-toggle",
                                        label="Rain Radar",
                                        checked=False,
                                        color="blue",
                                        size="sm",
                                        styles={"label": {"color": "#94a3b8", "cursor": "pointer"}},
                                    ),
                                ]),
                            ],
                        ),
                        # Stores for upload bridge
                        dcc.Store(id="river-upload-result", data=None),
                        dcc.Store(id="river-clear-result", data=None),
                        # Store for station data (search filtering)
                        dcc.Store(id="river-stations-data", data=None),
                        html.Div(
                            id="river-map-container",
                            style={"height": "clamp(400px, 60vh, 700px)", "borderRadius": "8px", "overflow": "hidden"},
                        ),
                    ],
                ),
                            ],
                        ),
                        dmc.GridCol(
                            span={"base": 12, "md": 5},
                            className="river-detail-scroll-col",
                            children=[
                                dmc.Paper(
                                    id="river-map-station-panel",
                                    shadow="sm", p="md", radius="md",
                                    style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                                    children=[
                    dmc.Select(
                        id="river-map-station-select",
                        label="Select Station",
                        data=[], searchable=True, w={"base": "100%", "sm": 500},
                        leftSection=DashIconify(icon="tabler:map-pin"),
                        styles=_INPUT_STYLE,
                        comboboxProps=_COMBOBOX_PORTAL,
                    ),
                    # Info panel
                    html.Div(id="river-station-info", style={"marginTop": "12px"}),
                    # Chart
                    html.Div(id="river-map-station-chart-container", style={"marginTop": "12px"}),
                    # Tide forecast section (hidden by default)
                    html.Div(
                        id="river-map-tide-section",
                        style={"display": "none", "marginTop": "12px"},
                        children=dmc.Paper(
                            shadow="sm", p="md", radius="md",
                            style={"backgroundColor": "#0d1320", "border": "1px solid #1e293b"},
                            children=dcc.Loading(
                                type="circle", color="#14b8a6",
                                children=dcc.Graph(
                                    id="river-map-tide-chart",
                                    config={"displaylogo": False},
                                    style={"height": "380px"},
                                ),
                            ),
                        ),
                    ),
                    # Precipitation forecast section
                    html.Div(
                        id="river-map-precip-section",
                        style={"display": "none", "marginTop": "12px"},
                        children=dmc.Paper(
                            shadow="sm", p="md", radius="md",
                            style={"backgroundColor": "#0d1320", "border": "1px solid #1e293b"},
                            children=dcc.Loading(
                                type="circle", color="#3b82f6",
                                children=dcc.Graph(
                                    id="river-map-precip-chart",
                                    config={"displaylogo": False},
                                    style={"height": "350px"},
                                ),
                            ),
                        ),
                    ),
                    # Downloads + About
                    dmc.Group(gap="md", mt="md", children=[
                        dmc.Button(
                            "Download HTML Report",
                            id="river-map-html-btn",
                            leftSection=DashIconify(icon="tabler:file-code"),
                            variant="light", color="blue", size="sm",
                        ),
                    ]),
                    dcc.Download(id="river-map-download"),
                    # About this data collapsible
                    dmc.Accordion(
                        mt="sm",
                        children=[
                            dmc.AccordionItem(
                                value="about",
                                children=[
                                    dmc.AccordionControl(
                                        dmc.Text("About this data", size="sm", c="dimmed"),
                                    ),
                                    dmc.AccordionPanel(
                                        dmc.Text(
                                            "River height observations are real-time operational data from automated "
                                            "telemetry systems and manual readings. Heights are expressed in Local Gauge "
                                            "Height (LGH) unless otherwise noted. Some tidal stations use Australian "
                                            "Height Datum (AHD). Peak values shown are based on recorded observations "
                                            "at the time of viewing and may be refined post-event. Data is provided "
                                            "for flood warning purposes and may not be available during non-flood periods.",
                                            size="xs", c="dimmed",
                                        ),
                                    ),
                                ],
                            ),
                        ],
                    ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ),
            # ─── STATION DETAILS TAB ──────────────────────────────────
            html.Div(
                id="river-details-panel",
                style={"display": "none"},
                children=dmc.Stack(gap="md", children=[
                    dmc.Paper(
                        shadow="sm", p="md", radius="md",
                        style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                        children=dmc.Stack(gap="md", children=[
                            dmc.Group(gap="md", wrap="wrap", children=[
                                dmc.Select(
                                    id="river-station-select",
                                    label="Select Station",
                                    data=[], searchable=True, w={"base": "100%", "sm": 400},
                                    leftSection=DashIconify(icon="tabler:map-pin"),
                                    styles=_INPUT_STYLE,
                                    comboboxProps=_COMBOBOX_PORTAL,
                                ),
                                dmc.NumberInput(
                                    id="river-days-back",
                                    label="Days of History",
                                    value=7, min=1, max=30, w={"base": "100%", "xs": 130},
                                    styles=_INPUT_STYLE,
                                ),
                            ]),
                            # Weather threshold controls
                            dmc.Text("Weather Thresholds", size="sm", fw=600, c="dimmed"),
                            dmc.Group(gap="md", wrap="wrap", children=[
                                dmc.NumberInput(
                                    id="river-details-rain-threshold",
                                    label="Rain (mm/hr)",
                                    value=10,
                                    min=0, max=100, step=1, decimalScale=1,
                                    w={"base": "100%", "xs": 130},
                                    leftSection=DashIconify(icon="tabler:cloud-rain", width=14),
                                    styles=_INPUT_STYLE,
                                ),
                                dmc.NumberInput(
                                    id="river-details-wind-threshold",
                                    label="Wind (km/h)",
                                    value=100,
                                    min=0, max=200, step=5,
                                    w={"base": "100%", "xs": 130},
                                    leftSection=DashIconify(icon="tabler:wind", width=14),
                                    styles=_INPUT_STYLE,
                                ),
                                dmc.NumberInput(
                                    id="river-details-gust-threshold",
                                    label="Gust (km/h)",
                                    value=130,
                                    min=0, max=300, step=5,
                                    w={"base": "100%", "xs": 130},
                                    leftSection=DashIconify(icon="tabler:wind", width=14),
                                    styles=_INPUT_STYLE,
                                ),
                            ]),
                            dmc.Switch(
                                id="river-details-show-obs",
                                label="Show Observations",
                                checked=True,
                                color="cyan",
                                size="sm",
                                styles={"label": {"color": "#94a3b8", "cursor": "pointer"}},
                            ),
                            html.Div(id="river-details-obs-info", style={"display": "inline"}),
                        ]),
                    ),
                    html.Div(id="river-station-metrics"),
                    dmc.Paper(
                        shadow="sm", p="md", radius="md",
                        style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                        children=dcc.Loading(type="circle", color="#f59e0b", children=
                            dcc.Graph(id="river-station-chart",
                                      config={"displaylogo": False},
                                      style={"height": "450px"})),
                    ),
                    # Tide forecast section
                    html.Div(
                        id="river-tide-section",
                        style={"display": "none"},
                        children=dmc.Paper(
                            shadow="sm", p="md", radius="md",
                            style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                            children=dcc.Loading(
                                type="circle", color="#14b8a6",
                                children=dcc.Graph(
                                    id="river-tide-chart",
                                    config={"displaylogo": False},
                                    style={"height": "380px"},
                                ),
                            ),
                        ),
                    ),
                    # Precipitation forecast section (Details tab)
                    html.Div(
                        id="river-details-precip-section",
                        style={"display": "none"},
                        children=dmc.Paper(
                            shadow="sm", p="md", radius="md",
                            style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                            children=dcc.Loading(
                                type="circle", color="#3b82f6",
                                children=dcc.Graph(
                                    id="river-details-precip-chart",
                                    config={"displaylogo": False},
                                    style={"height": "350px"},
                                ),
                            ),
                        ),
                    ),
                    # Wind/Gust forecast section (Details tab)
                    html.Div(
                        id="river-details-wind-section",
                        style={"display": "none"},
                        children=dmc.Stack(gap="md", children=[
                            # Weather window summary
                            html.Div(id="river-details-ww-summary"),
                            # Wind exceedance chart
                            dmc.Paper(
                                shadow="sm", p="md", radius="md",
                                style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                                children=dcc.Loading(
                                    type="circle", color="#d62728",
                                    children=dcc.Graph(
                                        id="river-details-wind-exceedance-chart",
                                        config={"displaylogo": False},
                                        style={"height": "380px"},
                                    ),
                                ),
                            ),
                            # Per-model ensemble spreads (collapsible)
                            dmc.Accordion(
                                id="river-wind-ensemble-accordion",
                                chevronPosition="left",
                                children=[],
                            ),
                            # Gust chart
                            dmc.Paper(
                                shadow="sm", p="md", radius="md",
                                style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                                children=dcc.Loading(
                                    type="circle", color="#f59e0b",
                                    children=dcc.Graph(
                                        id="river-details-gust-chart",
                                        config={"displaylogo": False},
                                        style={"height": "380px"},
                                    ),
                                ),
                            ),
                        ]),
                    ),
                    # Downloads
                    dmc.Paper(
                        shadow="sm", p="sm", radius="md",
                        style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                        children=dmc.Group(gap="md", children=[
                            dmc.Text("Downloads", size="sm", fw=600, c="dimmed"),
                            dmc.Button(
                                "Interactive HTML",
                                id="river-html-btn",
                                leftSection=DashIconify(icon="tabler:file-code"),
                                variant="light", color="blue", size="sm",
                            ),
                        ]),
                    ),
                    dcc.Download(id="river-download"),
                ]),
            ),
            # ─── ABOVE THRESHOLD TAB ─────────────────────────────────
            html.Div(
                id="river-threshold-panel",
                style={"display": "none"},
                children=html.Div(id="river-threshold-cards"),
            ),
            # ─── FLOOD SCENARIOS TAB ─────────────────────────────────
            html.Div(
                id="river-scenarios-panel",
                style={"display": "none"},
                children=html.Div(id="river-scenarios-content"),
            ),
            # ─── FORECAST DEMO TAB ──────────────────────────────────
            html.Div(
                id="river-forecast-demo-panel",
                style={"display": "none"},
                children=dmc.Stack(gap="md", children=[
                    dmc.Alert(
                        title="Forecast Demo — March 2026 Flood Event",
                        color="blue", variant="light",
                        icon=DashIconify(icon="tabler:chart-line"),
                        children=(
                            "This demo uses real observation and forecast data from the March 2026 "
                            "Queensland/NSW flood event. In production, this view will be powered by "
                            "live BoM Water API feeds."
                        ),
                    ),
                    dmc.Paper(
                        shadow="sm", p="md", radius="md",
                        style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                        children=dmc.Group(gap="md", wrap="wrap", align="flex-end", children=[
                            dmc.Select(
                                id="river-forecast-demo-station",
                                label="Select Demo Station",
                                data=[],
                                searchable=True,
                                w={"base": "100%", "sm": 400},
                                leftSection=DashIconify(icon="tabler:map-pin"),
                                styles=_INPUT_STYLE,
                                comboboxProps=_COMBOBOX_PORTAL,
                            ),
                            dmc.TextInput(
                                id="river-forecast-demo-custom-label",
                                label="Custom Threshold Label",
                                value="Asset Risk Level",
                                w={"base": "100%", "xs": 200},
                                leftSection=DashIconify(icon="tabler:tag", width=14),
                                styles=_INPUT_STYLE,
                            ),
                            dmc.NumberInput(
                                id="river-forecast-demo-custom-level",
                                label="Level (m)",
                                value=None,
                                placeholder="e.g. 10.5",
                                min=0, max=30, step=0.1,
                                decimalScale=2,
                                w={"base": "100%", "xs": 140},
                                leftSection=DashIconify(icon="tabler:ruler-measure", width=14),
                                styles=_INPUT_STYLE,
                            ),
                        ]),
                    ),
                    # CSV asset threshold upload
                    dmc.Paper(
                        shadow="sm", p="md", radius="md",
                        style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                        children=dmc.Group(gap="md", align="center", wrap="wrap", children=[
                            dcc.Upload(
                                id="river-forecast-demo-csv-upload",
                                children=dmc.Button(
                                    "Upload Asset Threshold List",
                                    leftSection=DashIconify(icon="tabler:file-upload", width=16),
                                    variant="outline", color="teal", size="xs",
                                ),
                                accept=".csv",
                                multiple=False,
                            ),
                            html.Div(id="river-forecast-demo-csv-status"),
                            dcc.Store(id="river-forecast-demo-csv-data", data=None),
                            dmc.Text(
                                "CSV format: station, threshold_m",
                                size="xs", c="dimmed", fs="italic",
                            ),
                        ]),
                    ),
                    html.Div(id="river-forecast-demo-info"),
                    dmc.Paper(
                        shadow="sm", p="md", radius="md",
                        style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                        children=dcc.Loading(
                            type="circle", color="#1E90FF",
                            children=dcc.Graph(
                                id="river-forecast-demo-chart",
                                config={"displaylogo": False},
                                style={"height": "500px"},
                            ),
                        ),
                    ),
                    html.Div(id="river-forecast-demo-warning"),
                    # Download
                    dmc.Paper(
                        shadow="sm", p="sm", radius="md",
                        style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                        children=dmc.Group(gap="md", children=[
                            dmc.Text("Downloads", size="sm", fw=600, c="dimmed"),
                            dmc.Button(
                                "Interactive HTML",
                                id="river-forecast-demo-html-btn",
                                leftSection=DashIconify(icon="tabler:file-code"),
                                variant="light", color="blue", size="sm",
                            ),
                        ]),
                    ),
                    dcc.Download(id="river-forecast-demo-download"),
                ]),
            ),
        ],
    )


def _flood_metric(title, value, color, icon, id):
    return dmc.Paper(
        shadow="sm", p="md", radius="md",
        style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
        children=dmc.Group(
            justify="space-between",
            children=[
                dmc.Stack(gap=2, children=[
                    dmc.Text(title, size="xs", c="dimmed", tt="uppercase", fw=600),
                    dmc.Text(value, size="xl", fw=700, c="white", id=id),
                ]),
                dmc.ThemeIcon(
                    DashIconify(icon=icon, width=20),
                    variant="light", color=color, size="lg", radius="md",
                ),
            ],
        ),
    )


def _detail_metric(title, value, color):
    return dmc.Paper(
        shadow="sm", p="sm", radius="md",
        style={"backgroundColor": "#111827", "border": f"1px solid {color}30"},
        children=dmc.Stack(gap=2, children=[
            dmc.Text(title, size="xs", c="dimmed", tt="uppercase", fw=600),
            dmc.Text(value, size="lg", fw=700, c=color),
        ]),
    )


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────────────────────────────────────

# Toggle view panels
@callback(
    Output("river-map-grid-wrapper", "style"),
    Output("river-details-panel", "style"),
    Output("river-threshold-panel", "style"),
    Output("river-scenarios-panel", "style"),
    Output("river-forecast-demo-panel", "style"),
    Input("river-view-mode", "value"),
)
def toggle_river_view(view_mode):
    show = {"display": "block"}
    hide = {"display": "none"}
    if view_mode == "map":
        return show, hide, hide, hide, hide
    elif view_mode == "details":
        return hide, show, hide, hide, hide
    elif view_mode == "threshold":
        return hide, hide, show, hide, hide
    elif view_mode == "scenarios":
        return hide, hide, hide, show, hide
    elif view_mode == "forecast-demo":
        return hide, hide, hide, hide, show
    return show, hide, hide, hide, hide


# Load river data + summary + station options + threshold cards (fires once on load)
@callback(
    Output("river-major-count", "children"),
    Output("river-moderate-count", "children"),
    Output("river-minor-count", "children"),
    Output("river-normal-count", "children"),
    Output("river-total-count", "children"),
    Output("river-map-station-select", "data"),
    Output("river-station-select", "data"),
    Output("river-threshold-cards", "children"),
    Output("river-stations-data", "data"),
    Input("river-view-mode", "value"),
    prevent_initial_call=False,
)
def load_river_data(_view):
    from src.services.river_service import (
        get_latest_river_levels, get_flood_summary,
        get_station_options, get_above_threshold_stations,
    )

    df_latest = get_latest_river_levels()
    summary = get_flood_summary(df_latest)
    options = get_station_options(df_latest)

    # Identify tidal stations for dropdown labels
    from src.services.tide_service import get_tidal_sensor_ids
    tidal_ids = get_tidal_sensor_ids()

    if tidal_ids:
        for opt in options:
            if opt.get("value") in tidal_ids:
                opt["label"] = f"🌊 {opt['label']}"

    # Above threshold cards
    df_above = get_above_threshold_stations(df_latest)
    threshold_cards = _build_threshold_cards(df_above)

    # Station data for search filtering
    stations_data = []
    if not df_latest.empty:
        for _, row in df_latest.iterrows():
            stations_data.append({
                "sensor": row.get("sensor", ""),
                "name": row.get("StationName", row.get("station", "")),
                "basin": row.get("BasinName", ""),
            })

    return (
        str(summary["Major"]),
        str(summary["Moderate"]),
        str(summary["Minor"]),
        str(summary["Normal"]),
        str(summary["Total"]),
        options, options,
        threshold_cards,
        stations_data,
    )


# Render map — separate callback so tile/toggle changes don't re-query data.
# Returns no_update on view-mode changes to preserve viewport.
@callback(
    Output("river-map-container", "children"),
    Input("river-flood-zones-toggle", "checked"),
    Input("river-radar-toggle", "checked"),
    Input("river-map-tile-select", "value"),
    Input("river-upload-result", "data"),
    Input("river-clear-result", "data"),
    prevent_initial_call=False,
)
def render_river_map(show_flood_zones, show_radar, tile_style, _upload_result, _clear_result):
    from src.services.river_service import (
        get_latest_river_levels, merge_with_coordinates,
    )
    from src.services.tide_service import get_tidal_sensor_ids

    df_latest = get_latest_river_levels()
    df_map = merge_with_coordinates(df_latest)
    tidal_ids = get_tidal_sensor_ids()

    river_map = _build_river_map(
        df_map,
        show_flood_zones=show_flood_zones,
        show_radar=show_radar,
        tile_style=tile_style or "esri-topo",
        tidal_ids=tidal_ids,
    )
    return river_map


# Search filter — filter station dropdown based on search text
@callback(
    Output("river-map-station-select", "value"),
    Input("river-search", "value"),
    State("river-stations-data", "data"),
    prevent_initial_call=True,
)
def search_station(search_text, stations_data):
    if not search_text or not stations_data:
        return no_update

    search_lower = search_text.lower()
    for station in stations_data:
        name = (station.get("name") or "").lower()
        sensor = (station.get("sensor") or "").lower()
        basin = (station.get("basin") or "").lower()
        if search_lower in name or search_lower in sensor or search_lower in basin:
            return station["sensor"]

    return no_update


# Click a river station marker on the map → update both station dropdowns
@callback(
    Output("river-map-station-select", "value", allow_duplicate=True),
    Output("river-station-select", "value"),
    Input({"type": "river-station-marker", "sensor": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_river_station_from_map(n_clicks_list):
    if not ctx.triggered_id or not any(n for n in n_clicks_list if n):
        return no_update, no_update
    clicked_sensor = ctx.triggered_id["sensor"]
    return clicked_sensor, clicked_sensor


# Map station detail — info panel + chart
@callback(
    Output("river-station-info", "children"),
    Output("river-map-station-chart-container", "children"),
    Output("river-map-tide-section", "style"),
    Output("river-map-tide-chart", "figure"),
    Input("river-map-station-select", "value"),
    prevent_initial_call=True,
)
def render_map_station_detail(sensor_id):
    from src.services.river_service import get_last_n_records, classify_flood_level
    from src.components.river_charts import create_river_station_chart, create_tide_chart, empty_chart
    from src.services.tide_service import is_tidal_station, fetch_tide_forecast

    if not sensor_id:
        return html.Div(), html.Div(), {"display": "none"}, empty_chart("")

    df = get_last_n_records(sensor_id, n=50)
    if df.empty:
        return (
            dmc.Text("No data available for this station", c="dimmed", size="sm"),
            html.Div(),
            {"display": "none"},
            empty_chart(""),
        )

    station_name = df.iloc[-1].get("StationName", sensor_id)
    latest = df.iloc[-1]
    current_val = latest.get("RealValue", 0)
    classification = classify_flood_level(latest)
    cls_color = _FLOOD_COLORS.get(classification, "#6b7280")

    # Tendency
    if len(df) >= 4:
        recent = df["RealValue"].iloc[-4:].values
        avg_diff = sum(recent[i] - recent[i - 1] for i in range(1, len(recent))) / 3
        if avg_diff > 0.02:
            tendency = "Rising"
            tend_icon = "tabler:arrow-up"
            tend_color = "#ef4444"
        elif avg_diff < -0.02:
            tendency = "Falling"
            tend_icon = "tabler:arrow-down"
            tend_color = "#22c55e"
        else:
            tendency = "Steady"
            tend_icon = "tabler:arrow-right"
            tend_color = "#94a3b8"
    else:
        tendency = "Unknown"
        tend_icon = "tabler:minus"
        tend_color = "#94a3b8"

    # Last observation time
    last_time = latest.get("ObservationTimestamp", "")
    if hasattr(last_time, "strftime"):
        last_time_str = last_time.strftime("%d %b %Y %H:%M")
    else:
        last_time_str = str(last_time)

    # Info panel
    info = dmc.SimpleGrid(
        cols={"base": 2, "sm": 3, "lg": 6},
        spacing="sm",
        children=[
            _detail_metric("Station", station_name, "#f1f5f9"),
            _detail_metric("Current Level", f"{current_val:.2f} m", cls_color),
            _detail_metric("Flood Status", classification, cls_color),
            _detail_metric(
                "Tendency",
                tendency,
                tend_color,
            ),
            _detail_metric("Last Obs", last_time_str, "#94a3b8"),
            _detail_metric("Basin", latest.get("BasinName", "—"), "#94a3b8"),
        ],
    )

    # Chart
    fig = create_river_station_chart(df, station_name)
    chart = dcc.Graph(figure=fig, config={"displaylogo": False}, style={"height": "450px"})

    # Tide
    tide_style = {"display": "none"}
    tide_fig = empty_chart("")
    if is_tidal_station(sensor_id):
        tide_df = fetch_tide_forecast(sensor_id)
        if not tide_df.empty:
            from src.services.river_service import load_station_metadata
            meta = load_station_metadata()
            tide_name = sensor_id
            if not meta.empty:
                match = meta[meta["SENSORID"] == sensor_id]
                if not match.empty:
                    tide_name = match.iloc[0].get("SHORT_NAME", sensor_id)
            tide_fig = create_tide_chart(tide_df, tide_name, sensor_id=sensor_id)
            tide_style = {"display": "block", "marginTop": "12px"}

    return info, chart, tide_style, tide_fig


# ── Shared precipitation fetch helper ────────────────────────────────

def _fetch_precip_for_station(sensor_id):
    """Fetch multi-model precipitation forecast for a station. Returns (fig, style) or None."""
    from src.components.river_charts import create_precipitation_chart, empty_chart
    from src.services.river_service import load_station_metadata
    from src.data.api_client import get_api_client
    from src.utils.constants import PRECIP_MODELS, PRECIP_PAST_HOURS, PRECIP_FORECAST_HOURS

    if not sensor_id:
        return empty_chart(""), {"display": "none"}

    meta = load_station_metadata()
    if meta.empty:
        return empty_chart(""), {"display": "none"}

    match = meta[meta["SENSORID"] == sensor_id]
    if match.empty or pd.isna(match.iloc[0].get("LAT")) or pd.isna(match.iloc[0].get("LONG")):
        return empty_chart(""), {"display": "none"}

    lat = float(match.iloc[0]["LAT"])
    lon = float(match.iloc[0]["LONG"])
    station_name = match.iloc[0].get("SHORT_NAME", sensor_id)

    try:
        client = get_api_client()
    except RuntimeError:
        return empty_chart(""), {"display": "none"}

    model_data = {}
    grid_lat, grid_lon = lat, lon
    for model_name, config in PRECIP_MODELS.items():
        try:
            df, g_lat, g_lon = client.get_precipitation_forecast(
                lat, lon,
                model=config["api_model"],
                past_hours=PRECIP_PAST_HOURS,
                forecast_hours=PRECIP_FORECAST_HOURS,
            )
            if not df.empty:
                model_data[model_name] = {"df": df, "color": config["color"]}
                grid_lat, grid_lon = g_lat, g_lon  # use last returned grid coords
        except Exception as e:
            logger.warning("Precip fetch failed for %s/%s: %s", model_name, sensor_id, e)

    if not model_data:
        return empty_chart(""), {"display": "none"}

    fig = create_precipitation_chart(model_data, station_name, grid_lat, grid_lon)
    return fig, {"display": "block", "marginTop": "12px"}


# Precipitation forecast (Map view — fires when station selected)
@callback(
    Output("river-map-precip-section", "style"),
    Output("river-map-precip-chart", "figure"),
    Input("river-map-station-select", "value"),
    prevent_initial_call=True,
)
def render_map_precipitation(sensor_id):
    fig, style = _fetch_precip_for_station(sensor_id)
    return style, fig


# Precipitation forecast (Details tab — fires when station selected or threshold changes)
@callback(
    Output("river-details-precip-section", "style"),
    Output("river-details-precip-chart", "figure"),
    Input("river-station-select", "value"),
    Input("river-details-rain-threshold", "value"),
    prevent_initial_call=True,
)
def render_details_precipitation(sensor_id, rain_threshold):
    fig, style = _fetch_precip_for_station(sensor_id)
    # Add rain threshold line if set
    try:
        threshold_val = float(rain_threshold) if rain_threshold not in (None, "", " ") else None
    except (TypeError, ValueError):
        threshold_val = None
    if threshold_val is not None and threshold_val > 0 and fig.data:
        fig.add_hline(
            y=threshold_val,
            line_dash="dash", line_color="#ef4444", line_width=2,
        )
        fig.add_annotation(
            xref="paper", yref="y", x=1.01, y=threshold_val,
            text=f"<b>Rain Threshold ({threshold_val}mm/hr)</b>",
            showarrow=False, font=dict(color="#ef4444", size=10), xanchor="left",
        )
        # Ensure y-axis shows the threshold
        fig.update_layout(
            yaxis=dict(rangemode="nonnegative", range=[0, max(threshold_val * 1.2, 1)]),
            margin=dict(r=160),
        )
    return style, fig


# Wind/Gust ensemble forecasts (Details tab)
@callback(
    Output("river-details-wind-section", "style"),
    Output("river-details-wind-exceedance-chart", "figure"),
    Output("river-wind-ensemble-accordion", "children"),
    Output("river-details-gust-chart", "figure"),
    Output("river-details-ww-summary", "children"),
    Output("river-details-obs-info", "children"),
    Input("river-station-select", "value"),
    Input("river-details-wind-threshold", "value"),
    Input("river-details-gust-threshold", "value"),
    Input("river-details-rain-threshold", "value"),
    Input("river-details-show-obs", "checked"),
    prevent_initial_call=True,
)
def render_details_wind(sensor_id, wind_threshold, gust_threshold, rain_threshold, show_obs):
    from src.components.river_charts import (
        create_wind_exceedance_chart, create_wind_ensemble_chart,
        create_gust_chart, add_weather_windows, empty_chart,
    )
    from src.services.wind_service import (
        fetch_all_wind_ensembles, calculate_wind_exceedance,
        calculate_ensemble_stats, get_gust_stats,
        calculate_model_agreement, calculate_weather_windows,
    )
    from src.utils.constants import WIND_ENSEMBLE_MODELS, WIND_ENSEMBLE_FILL_COLORS

    if not sensor_id:
        return {"display": "none"}, empty_chart(""), [], empty_chart(""), html.Div(), html.Div()

    # Get station coordinates
    from src.services.river_service import load_station_metadata
    meta = load_station_metadata()
    if meta.empty:
        return {"display": "none"}, empty_chart(""), [], empty_chart(""), html.Div(), html.Div()

    match = meta[meta["SENSORID"] == sensor_id]
    if match.empty or pd.isna(match.iloc[0].get("LAT")) or pd.isna(match.iloc[0].get("LONG")):
        return {"display": "none"}, empty_chart(""), [], empty_chart(""), html.Div(), html.Div()

    lat = float(match.iloc[0]["LAT"])
    lon = float(match.iloc[0]["LONG"])
    station_name = match.iloc[0].get("SHORT_NAME", sensor_id)

    # Parse thresholds safely
    try:
        w_thresh = float(wind_threshold) if wind_threshold not in (None, "", " ") else 100
    except (TypeError, ValueError):
        w_thresh = 100
    try:
        g_thresh = float(gust_threshold) if gust_threshold not in (None, "", " ") else 130
    except (TypeError, ValueError):
        g_thresh = 130
    try:
        r_thresh = float(rain_threshold) if rain_threshold not in (None, "", " ") else 10
    except (TypeError, ValueError):
        r_thresh = 10

    # Fetch all wind ensembles
    wind_data = fetch_all_wind_ensembles(lat, lon)
    if not any(r["df"].shape[0] > 0 for r in wind_data.values()):
        return {"display": "none"}, empty_chart(""), [], empty_chart(""), html.Div(), html.Div()

    # Get grid coordinates from first successful model
    grid_lat, grid_lon = lat, lon
    for r in wind_data.values():
        if not r["df"].empty:
            grid_lat = r.get("grid_lat", lat)
            grid_lon = r.get("grid_lon", lon)
            break

    # Exceedance chart
    exceedance_data = {}
    for model_name, result in wind_data.items():
        df = result.get("df", pd.DataFrame())
        if df.empty:
            continue
        exc = calculate_wind_exceedance(df, w_thresh)
        if not exc.empty:
            exceedance_data[model_name] = {
                "series": exc,
                "color": WIND_ENSEMBLE_MODELS[model_name]["color"],
            }

    agreement = calculate_model_agreement(wind_data)
    exc_fig = create_wind_exceedance_chart(
        exceedance_data, w_thresh, station_name, grid_lat, grid_lon, agreement,
    )

    # Fetch precipitation for weather windows
    precip_dfs = {}
    try:
        from src.data.api_client import get_api_client
        from src.utils.constants import PRECIP_MODELS
        client = get_api_client()
        for m_name, m_cfg in PRECIP_MODELS.items():
            try:
                p_df, _, _ = client.get_precipitation_forecast(lat, lon, model=m_cfg["api_model"])
                if not p_df.empty:
                    precip_dfs[m_name] = p_df
            except Exception:
                pass
    except Exception:
        pass

    # Weather windows
    ww_result = calculate_weather_windows(wind_data, precip_dfs, w_thresh, g_thresh, r_thresh)
    windows = ww_result.get("windows", [])

    # Per-model ensemble spread charts (accordion items)
    accordion_items = []
    for model_name, result in wind_data.items():
        df = result.get("df", pd.DataFrame())
        if df.empty:
            continue
        stats = calculate_ensemble_stats(df, "wind_speed_10m")
        if stats.empty:
            continue
        color = WIND_ENSEMBLE_MODELS[model_name]["color"]
        fill = WIND_ENSEMBLE_FILL_COLORS.get(model_name, "rgba(128,128,128,0.12)")
        members = WIND_ENSEMBLE_MODELS[model_name]["members"]
        ensemble_fig = create_wind_ensemble_chart(
            stats, w_thresh, model_name, color, fill, members, windows,
        )
        accordion_items.append(
            dmc.AccordionItem(
                value=model_name,
                children=[
                    dmc.AccordionControl(
                        dmc.Text(f"{model_name} — {members} Members", size="sm", c="white"),
                    ),
                    dmc.AccordionPanel(
                        dcc.Graph(figure=ensemble_fig, config={"displaylogo": False},
                                  style={"height": "350px"}),
                    ),
                ],
            )
        )

    # Gust chart
    gust_chart_data = {}
    for model_name, result in wind_data.items():
        df = result.get("df", pd.DataFrame())
        if df.empty:
            continue
        gust_stats = get_gust_stats(df)
        if gust_stats is not None and not gust_stats.empty:
            gust_chart_data[model_name] = {
                "stats_df": gust_stats,
                "color": WIND_ENSEMBLE_MODELS[model_name]["color"],
            }

    gust_fig = create_gust_chart(gust_chart_data, g_thresh, station_name, grid_lat, grid_lon, windows)

    # Meteostat observations overlay
    obs_info = html.Div()
    if show_obs:
        try:
            from src.services.meteostat_service import fetch_recent_observations
            from src.components.river_charts import add_observation_trace
            obs_result = fetch_recent_observations(lat, lon, days_back=7)
            if obs_result["available"]:
                obs_df = obs_result["df"]
                # Overlay wind obs on exceedance chart (as actual wind speed, not %)
                # Better to overlay on ensemble spread — add to each accordion chart
                for item in accordion_items:
                    # Can't easily modify accordion figures after creation,
                    # so overlay on the main exceedance and gust charts instead
                    pass
                add_observation_trace(exc_fig, obs_df, "wind_speed_kmh", "Wind Obs (Analysis)")
                add_observation_trace(gust_fig, obs_df, "wind_gust_kmh", "Gust Obs (Analysis)")

                g_lat = obs_result.get("grid_lat", lat)
                g_lon = obs_result.get("grid_lon", lon)
                lat_dir = "S" if g_lat < 0 else "N"
                lon_dir = "E" if g_lon >= 0 else "W"
                obs_info = dmc.Badge(
                    f"Obs: {abs(g_lat):.2f}{lat_dir} {abs(g_lon):.2f}{lon_dir}",
                    color="cyan", variant="outline", size="sm",
                )
        except Exception as e:
            logger.warning("Meteostat overlay failed: %s", e)

    # Weather window summary card
    ww_summary = _build_weather_window_summary(ww_result, w_thresh, g_thresh, r_thresh)

    return (
        {"display": "block"},
        exc_fig,
        accordion_items,
        gust_fig,
        ww_summary,
        obs_info,
    )


def _build_weather_window_summary(ww_result, wind_thresh, gust_thresh, rain_thresh):
    """Build a weather window summary card."""
    is_open = ww_result.get("is_open_now", False)
    windows = ww_result.get("windows", [])
    total_hours = ww_result.get("total_hours", 0)
    next_window = ww_result.get("next_window")

    badge_color = "green" if is_open else "orange"
    badge_text = "OPEN NOW" if is_open else "CLOSED"

    children = [
        dmc.Group(gap="sm", children=[
            DashIconify(icon="tabler:shield-check" if is_open else "tabler:shield-x", width=20,
                        color="#22c55e" if is_open else "#f59e0b"),
            dmc.Text("Weather Window", size="sm", fw=700, c="white"),
            dmc.Badge(badge_text, color=badge_color, variant="filled", size="sm"),
        ]),
        dmc.Text(
            f"Wind < {wind_thresh} km/h | Gust < {gust_thresh} km/h | Rain < {rain_thresh} mm/hr",
            size="xs", c="dimmed", mt=4,
        ),
    ]

    if windows:
        children.append(
            dmc.Text(
                f"{len(windows)} safe window{'s' if len(windows) != 1 else ''} | {total_hours} hours total",
                size="xs", c="#22c55e", mt=4,
            )
        )

    if next_window:
        start, end = next_window
        start_str = start.strftime("%a %d %b %H:%M") if hasattr(start, "strftime") else str(start)
        end_str = end.strftime("%a %d %b %H:%M") if hasattr(end, "strftime") else str(end)
        label = "Current:" if is_open else "Next:"
        children.append(
            dmc.Text(f"{label} {start_str} — {end_str}", size="xs", c="#22c55e", mt=2),
        )

    return dmc.Paper(
        shadow="sm", p="md", radius="md",
        style={"backgroundColor": "#111827", "border": f"1px solid {'#22c55e' if is_open else '#f59e0b'}30"},
        children=dmc.Stack(gap=4, children=children),
    )


# Station details chart + metrics (Details tab)
@callback(
    Output("river-station-metrics", "children"),
    Output("river-station-chart", "figure"),
    Input("river-station-select", "value"),
    Input("river-days-back", "value"),
    prevent_initial_call=True,
)
def render_station_details(sensor_id, days_back):
    from src.services.river_service import get_station_history, classify_flood_level
    from src.components.river_charts import create_river_station_chart, empty_chart

    if not sensor_id:
        return html.Div(), empty_chart("Select a station to view details")

    days = days_back or 7
    df = get_station_history(sensor_id, days=days)
    if df.empty:
        return html.Div(), empty_chart(f"No data available for {sensor_id}")

    station_name = df.iloc[-1].get("StationName", sensor_id)

    # Build metrics
    latest = df.iloc[-1]
    current_val = latest.get("RealValue", 0)
    quality_map = {10: "Good", 20: "Suspect", 30: "Bad"}
    quality = quality_map.get(int(latest.get("Quality", 0)), "Unknown")

    classification = classify_flood_level(latest)
    cls_color = _FLOOD_COLORS.get(classification, "#6b7280")

    metrics = dmc.SimpleGrid(
        cols={"base": 2, "lg": 4},
        spacing="md",
        children=[
            _detail_metric("Current Level", f"{current_val:.2f} m", cls_color),
            _detail_metric("Status", classification, cls_color),
            _detail_metric("Quality", quality, "#3b82f6" if quality == "Good" else "#f59e0b"),
            _detail_metric("Readings", str(len(df)), "#64748b"),
        ],
    )

    fig = create_river_station_chart(df, station_name)
    return metrics, fig


# Tide forecast chart (Details tab — separate callback for tidal stations)
@callback(
    Output("river-tide-section", "style"),
    Output("river-tide-chart", "figure"),
    Input("river-station-select", "value"),
    prevent_initial_call=True,
)
def render_tide_forecast(sensor_id):
    from src.services.tide_service import is_tidal_station, fetch_tide_forecast
    from src.components.river_charts import create_tide_chart, empty_chart

    if not sensor_id or not is_tidal_station(sensor_id):
        return {"display": "none"}, empty_chart("")

    df = fetch_tide_forecast(sensor_id)
    if df.empty:
        return {"display": "block"}, empty_chart("Tide forecast unavailable for this station")

    # Get station name for chart title
    from src.services.river_service import load_station_metadata
    meta = load_station_metadata()
    station_name = sensor_id
    if not meta.empty:
        match = meta[meta["SENSORID"] == sensor_id]
        if not match.empty:
            station_name = match.iloc[0].get("SHORT_NAME", sensor_id)

    fig = create_tide_chart(df, station_name, sensor_id=sensor_id)
    return {"display": "block"}, fig


# Download river HTML report (map view)
@callback(
    Output("river-map-download", "data"),
    Input("river-map-html-btn", "n_clicks"),
    State("river-map-station-select", "value"),
    prevent_initial_call=True,
)
def download_river_html_map(_n_clicks, sensor_id):
    return _generate_download(sensor_id, days=7)


# Download river HTML report (details view)
@callback(
    Output("river-download", "data"),
    Input("river-html-btn", "n_clicks"),
    State("river-station-select", "value"),
    State("river-days-back", "value"),
    prevent_initial_call=True,
)
def download_river_html(_n_clicks, sensor_id, days_back):
    return _generate_download(sensor_id, days=days_back or 7)


def _generate_download(sensor_id, days):
    """Generate and download an interactive HTML report."""
    if not sensor_id:
        return no_update

    from src.services.river_service import get_station_history, classify_flood_level
    from src.components.river_charts import create_river_station_chart
    from src.services.export_service import generate_river_interactive_html

    df = get_station_history(sensor_id, days=days)
    if df.empty:
        return no_update

    station_name = df.iloc[-1].get("StationName", sensor_id)
    fig = create_river_station_chart(df, station_name)
    figures = {"Water Level — Time Series": fig}

    latest = df.iloc[-1]
    current_val = latest.get("RealValue", 0)
    classification = classify_flood_level(latest)
    quality_map = {10: "Good", 20: "Suspect", 30: "Bad"}
    quality = quality_map.get(int(latest.get("Quality", 0)), "Unknown")

    summary = {
        "Current Level": f"{current_val:.2f} m",
        "Classification": classification,
        "Quality": quality,
        "Readings": str(len(df)),
    }

    for level in ("Minor", "Moderate", "Major"):
        val = latest.get(level)
        if pd.notna(val):
            summary[f"{level} Threshold"] = f"{val:.2f} m"

    html_content = generate_river_interactive_html(figures, station_name, sensor_id, summary)

    safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in station_name).strip()
    today = datetime.now().strftime("%Y%m%d")

    return dict(content=html_content, filename=f"{safe_name}_River_Report_{today}.html")


# Flood Scenarios callback
@callback(
    Output("river-scenarios-content", "children"),
    Input("river-view-mode", "value"),
    prevent_initial_call=True,
)
def render_flood_scenarios(view_mode):
    if view_mode != "scenarios":
        return no_update

    try:
        from src.services.flood_scenario_service import discover_flood_pdfs
        from config import get_config
        config = get_config()
        pdfs = discover_flood_pdfs(config.FLOOD_SCENARIOS_DIR)
    except Exception as e:
        logger.error("Failed to discover flood scenarios: %s", e)
        pdfs = []

    if not pdfs:
        return dmc.Alert(
            "No flood scenario documents available.",
            title="No Documents", color="gray", variant="light",
            icon=DashIconify(icon="tabler:file-off"),
        )

    state_colors = {"NSW": "blue", "QLD": "orange", "NT": "red", "SA": "green", "VIC": "violet", "WA": "cyan", "TAS": "teal"}

    cards = []
    for pdf in pdfs:
        color = state_colors.get(pdf["state"], "gray")
        cards.append(
            dmc.Paper(
                shadow="sm", p="md", radius="md",
                style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
                children=dmc.Stack(gap="xs", children=[
                    dmc.Group(gap="sm", children=[
                        dmc.Badge(pdf["state"], color=color, variant="filled", size="sm"),
                        dmc.Text(pdf["product_id"], size="sm", fw=600, c="white"),
                    ]),
                    dmc.Text(f"Issued: {pdf['issue_date']}", size="xs", c="dimmed"),
                    dmc.Text(f"Size: {pdf['size_kb']} KB", size="xs", c="dimmed"),
                    dmc.Group(gap="sm", children=[
                        html.A(
                            dmc.Button(
                                "View PDF",
                                leftSection=DashIconify(icon="tabler:eye", width=14),
                                variant="light", color="blue", size="xs",
                            ),
                            href=f"/api/flood-scenarios/{pdf['filename']}",
                            target="_blank",
                        ),
                        html.A(
                            dmc.Button(
                                "Download",
                                leftSection=DashIconify(icon="tabler:download", width=14),
                                variant="outline", color="gray", size="xs",
                            ),
                            href=f"/api/flood-scenarios/{pdf['filename']}",
                            download=pdf["filename"],
                        ),
                    ]),
                ]),
            )
        )

    return dmc.SimpleGrid(
        cols={"base": 1, "sm": 2, "lg": 3},
        spacing="md",
        children=cards,
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAP HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_river_map(df_map, show_flood_zones=False, show_radar=False, tile_style="voyager", tidal_ids=None):
    """Build dash-leaflet map with flood-classified markers and optional overlays."""
    if df_map.empty:
        return dmc.Text("No station data available for mapping", c="dimmed", size="sm")

    if tidal_ids is None:
        tidal_ids = set()

    markers = []
    for _, row in df_map.iterrows():
        lat = row.get("LAT")
        lon = row.get("LONG")
        if pd.isna(lat) or pd.isna(lon):
            continue

        cls = row.get("classification", "Unknown")
        color = _FLOOD_COLORS.get(cls, "#6b7280")
        radius = _FLOOD_RADII.get(cls, 5)
        name = row.get("StationName", row.get("station", ""))
        sensor = row.get("sensor", "")
        value = row.get("RealValue", 0)
        is_tidal = sensor in tidal_ids

        from src.utils.constants import TIDE_HAT_VALUES
        tooltip_text = f"{name} ({cls}) — {value:.2f}m"
        if is_tidal:
            has_actual_hat = sensor in TIDE_HAT_VALUES
            if has_actual_hat:
                hat_val = TIDE_HAT_VALUES[sensor]
                tooltip_text = f"🌊 {tooltip_text} — Tidal (HAT: {hat_val:.2f}m)"
                border_color = "#f59e0b"  # amber/gold = actual HAT
            else:
                tooltip_text = f"🌊 {tooltip_text} — Tidal (Est. HAT)"
                border_color = "#14b8a6"  # teal = estimated HAT
            border_weight = 3
        else:
            border_color = color
            border_weight = 2 if cls in ("Major", "Moderate") else 1

        markers.append(
            dl.CircleMarker(
                center=[float(lat), float(lon)],
                radius=radius + (2 if is_tidal else 0),
                children=dl.Tooltip(tooltip_text),
                pathOptions={
                    "color": border_color,
                    "fillColor": color,
                    "fillOpacity": 0.8 if cls in ("Major", "Moderate", "Minor") else 0.5,
                    "weight": border_weight,
                },
                id={"type": "river-station-marker", "sensor": sensor},
                n_clicks=0,
            )
        )

    from src.utils.constants import MAP_TILES
    tile_url = MAP_TILES.get(tile_style, MAP_TILES["voyager"])

    map_children = [
        dl.TileLayer(url=tile_url),
        dl.LayerGroup(children=markers),
    ]

    # Add RainViewer radar overlay if toggled on
    if show_radar:
        radar_url = _get_rainviewer_tile_url()
        if radar_url:
            map_children.append(
                dl.TileLayer(
                    url=radar_url,
                    opacity=0.6,
                    attribution="RainViewer",
                )
            )

    # Add flood zones overlay if toggled on
    has_flood_zones = False
    if show_flood_zones:
        flood_zones = _build_flood_zone_layers()
        if flood_zones:
            map_children.extend(flood_zones)
            has_flood_zones = True

    # Add user-uploaded layers
    has_user_layers = False
    user_layers = _build_user_layers()
    if user_layers:
        map_children.extend(user_layers)
        has_user_layers = True

    # Build legend if any overlays are active
    if has_flood_zones or has_user_layers:
        legend_items = []
        if has_flood_zones:
            legend_items.append(
                html.Div("Flood Zones", style={"fontWeight": "600", "marginBottom": "4px", "color": "#e2e8f0"}),
            )
            legend_items.append(
                html.Div(style={"display": "flex", "alignItems": "center", "gap": "6px", "marginBottom": "2px"}, children=[
                    html.Div(style={"width": "12px", "height": "12px", "backgroundColor": "#f59e0b", "borderRadius": "2px", "opacity": "0.6"}),
                    html.Span("Amber"),
                ]),
            )
            legend_items.append(
                html.Div(style={"display": "flex", "alignItems": "center", "gap": "6px", "marginBottom": "2px"}, children=[
                    html.Div(style={"width": "12px", "height": "12px", "backgroundColor": "#22c55e", "borderRadius": "2px", "opacity": "0.6"}),
                    html.Span("Green"),
                ]),
            )
        if has_user_layers:
            if has_flood_zones:
                legend_items.append(html.Hr(style={"border": "none", "borderTop": "1px solid #1e293b", "margin": "4px 0"}))
            legend_items.append(
                html.Div("User Layer", style={"fontWeight": "600", "marginBottom": "4px", "color": "#e2e8f0"}),
            )
            legend_items.append(
                html.Div(style={"display": "flex", "alignItems": "center", "gap": "6px"}, children=[
                    html.Div(style={"width": "12px", "height": "12px", "backgroundColor": "#06b6d4", "borderRadius": "2px", "opacity": "0.6"}),
                    html.Span("Uploaded"),
                ]),
            )
        map_children.append(
            html.Div(
                style={
                    "position": "absolute", "bottom": "10px", "left": "10px",
                    "backgroundColor": "rgba(13, 19, 32, 0.9)",
                    "border": "1px solid #1e293b", "borderRadius": "6px",
                    "padding": "8px 12px", "zIndex": "1000",
                    "fontSize": "11px", "color": "#94a3b8",
                },
                children=legend_items,
            )
        )

    return dl.Map(
        center=[-25.5, 134.0], zoom=4,
        children=map_children,
        style={"height": "100%", "borderRadius": "8px", "position": "relative"},
        attributionControl=False,
    )


def _build_flood_zone_layers():
    """Build dash-leaflet Polygon layers from FloodZones GeoJSON."""
    geojson_data = _load_flood_zones_geojson()
    if not geojson_data or not geojson_data.get("features"):
        return None

    polygons = []
    for feature in geojson_data["features"]:
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})

        if geom.get("type") != "Polygon":
            continue

        coords = geom.get("coordinates", [])
        if not coords or not coords[0]:
            continue

        positions = [[pt[1], pt[0]] for pt in coords[0]]

        severity = props.get("severity", "")
        style = _FLOOD_ZONE_COLORS.get(severity, _FLOOD_ZONE_DEFAULT_STYLE)

        name = props.get("name", "Flood Zone")
        display_name = name
        if "_#" in name:
            display_name = name.split("_#")[-1].strip()
        elif name.count("_") >= 2:
            parts = name.split("_", 2)
            display_name = parts[-1].strip() if len(parts) > 2 else name

        states = props.get("impacted_states", "")
        tooltip_text = f"{display_name}"
        if states:
            tooltip_text += f" | {states.title()}"
        tooltip_text += f" | Severity: {severity}"

        polygons.append(
            dl.Polygon(
                positions=positions,
                pathOptions=style,
                children=dl.Tooltip(tooltip_text),
            )
        )

    if not polygons:
        return None

    return [dl.LayerGroup(children=polygons)]


def _build_user_layers():
    """Build dash-leaflet layers from user-uploaded GeoJSON data."""
    if not _user_layers:
        return None

    elements = []
    for layer_info in _user_layers.values():
        geojson_data = layer_info.get("geojson")
        if not geojson_data or not geojson_data.get("features"):
            continue

        for feature in geojson_data["features"]:
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})
            geom_type = geom.get("type", "")
            coords = geom.get("coordinates", [])

            if not coords:
                continue

            tooltip_parts = []
            for k, v in props.items():
                if v is not None and str(v).strip():
                    tooltip_parts.append(f"{k}: {v}")
            tooltip_text = " | ".join(tooltip_parts) if tooltip_parts else layer_info.get("name", "User Layer")

            style_poly = {"color": "#06b6d4", "fillColor": "#06b6d4", "fillOpacity": 0.15, "weight": 2}
            style_line = {"color": "#06b6d4", "weight": 3, "opacity": 0.8}

            if geom_type == "Polygon":
                positions = [[pt[1], pt[0]] for pt in coords[0]]
                elements.append(dl.Polygon(
                    positions=positions, pathOptions=style_poly,
                    children=dl.Tooltip(tooltip_text),
                ))
            elif geom_type == "MultiPolygon":
                for ring_set in coords:
                    positions = [[pt[1], pt[0]] for pt in ring_set[0]]
                    elements.append(dl.Polygon(
                        positions=positions, pathOptions=style_poly,
                        children=dl.Tooltip(tooltip_text),
                    ))
            elif geom_type == "LineString":
                positions = [[pt[1], pt[0]] for pt in coords]
                elements.append(dl.Polyline(
                    positions=positions, pathOptions=style_line,
                    children=dl.Tooltip(tooltip_text),
                ))
            elif geom_type == "MultiLineString":
                for line in coords:
                    positions = [[pt[1], pt[0]] for pt in line]
                    elements.append(dl.Polyline(
                        positions=positions, pathOptions=style_line,
                        children=dl.Tooltip(tooltip_text),
                    ))
            elif geom_type == "Point":
                elements.append(dl.CircleMarker(
                    center=[coords[1], coords[0]], radius=6,
                    pathOptions={"color": "#06b6d4", "fillColor": "#06b6d4", "fillOpacity": 0.7, "weight": 2},
                    children=dl.Tooltip(tooltip_text),
                ))
            elif geom_type == "MultiPoint":
                for pt in coords:
                    elements.append(dl.CircleMarker(
                        center=[pt[1], pt[0]], radius=6,
                        pathOptions={"color": "#06b6d4", "fillColor": "#06b6d4", "fillOpacity": 0.7, "weight": 2},
                        children=dl.Tooltip(tooltip_text),
                    ))

    if not elements:
        return None

    return [dl.LayerGroup(children=elements)]


def _build_threshold_cards(df_above):
    """Build cards for stations above flood thresholds."""
    if df_above.empty:
        return dmc.Alert(
            "All stations within normal levels — no flood thresholds exceeded.",
            title="All Clear", color="green", variant="light",
            icon=DashIconify(icon="tabler:check"),
        )

    cards = []
    for _, row in df_above.iterrows():
        cls = row.get("classification", "Unknown")
        color = _FLOOD_COLORS.get(cls, "#6b7280")
        name = row.get("StationName", row.get("station", ""))
        value = row.get("RealValue", 0)
        basin = row.get("BasinName", "")
        sensor = row.get("sensor", "")

        threshold_text = ""
        if cls == "Major" and pd.notna(row.get("Major")):
            threshold_text = f"Major threshold: {row['Major']:.2f}m"
        elif cls == "Moderate" and pd.notna(row.get("Moderate")):
            threshold_text = f"Moderate threshold: {row['Moderate']:.2f}m"
        elif cls == "Minor" and pd.notna(row.get("Minor")):
            threshold_text = f"Minor threshold: {row['Minor']:.2f}m"

        children = [
            dmc.Group(gap="sm", children=[
                dmc.Badge(cls, color="red" if cls == "Major" else
                          ("orange" if cls == "Moderate" else "green"),
                          variant="filled", size="sm"),
                dmc.Text(name, size="sm", fw=600, c="white"),
            ]),
            dmc.Text(f"Current: {value:.2f}m", size="lg", fw=700, c=color),
        ]
        if threshold_text:
            children.append(dmc.Text(threshold_text, size="xs", c="dimmed"))
        if basin:
            children.append(dmc.Text(f"Basin: {basin}", size="xs", c="dimmed"))
        children.append(dmc.Text(f"Sensor: {sensor}", size="xs", c="dimmed"))

        cards.append(
            dmc.Paper(
                shadow="sm", p="md", radius="md",
                style={"backgroundColor": "#111827", "border": f"2px solid {color}"},
                children=dmc.Stack(gap="xs", children=children),
            )
        )

    return dmc.SimpleGrid(
        cols={"base": 1, "sm": 2, "lg": 3},
        spacing="md",
        children=cards,
    )


# ─────────────────────────────────────────────────────────────────────────────
# FORECAST DEMO
# ─────────────────────────────────────────────────────────────────────────────

def _build_warning_panel(warning):
    """Build a flood warning panel from a warning dict."""
    if not warning:
        return html.Div()

    severity = warning.get("severity", "minor")
    sev_colors = {
        "major": {"bg": "#DC143C", "text": "white"},
        "moderate": {"bg": "#FF8C00", "text": "white"},
        "minor": {"bg": "#FFD700", "text": "#333"},
    }
    sev_style = sev_colors.get(severity, sev_colors["minor"])

    fcst_severity = warning.get("forecast_severity", "minor")
    fcst_bg = {"major": "#2a1015", "moderate": "#2a1f0d", "minor": "#2a2a0d"}.get(fcst_severity, "#1a1a2e")
    fcst_border = {"major": "#DC143C", "moderate": "#FF8C00", "minor": "#FFD700"}.get(fcst_severity, "#FFD700")

    return dmc.Paper(
        shadow="sm", radius="md",
        style={"backgroundColor": "#111827", "border": "1px solid #1e293b", "overflow": "hidden"},
        children=[
            # Colored header
            html.Div(
                style={
                    "backgroundColor": sev_style["bg"], "color": sev_style["text"],
                    "padding": "14px 20px", "fontWeight": 700, "fontSize": "15px",
                },
                children=warning.get("title", "Flood Warning"),
            ),
            # Body
            html.Div(
                style={"padding": "16px 20px", "lineHeight": "1.65", "fontSize": "14px", "color": "#e2e8f0"},
                children=[
                    html.P(
                        style={"fontSize": "12px", "color": "#94a3b8", "marginBottom": "6px"},
                        children=[
                            html.Strong(f"Warning #{warning.get('number', '')}"),
                            f" — {warning.get('id', '')} — Issued {warning.get('issued_at', '')}",
                        ],
                    ),
                    html.P(
                        style={
                            "fontWeight": 700, "fontSize": "13px", "textTransform": "uppercase",
                            "color": "#e2e8f0", "whiteSpace": "pre-line", "marginBottom": "12px",
                        },
                        children=warning.get("headline", ""),
                    ),
                    html.P(warning.get("overview_text", ""), style={"marginBottom": "10px"}),
                    html.P(
                        style={"fontWeight": 600, "marginBottom": "10px"},
                        children=warning.get("status_text", ""),
                    ),
                    html.Div(
                        style={
                            "backgroundColor": fcst_bg,
                            "borderLeft": f"4px solid {fcst_border}",
                            "padding": "10px 14px", "margin": "10px 0",
                            "borderRadius": "0 4px 4px 0",
                        },
                        children=[
                            html.Strong("Forecast: "),
                            warning.get("forecast_text", ""),
                        ],
                    ),
                ],
            ),
            html.Div(
                style={
                    "padding": "10px 20px", "backgroundColor": "#0d1320",
                    "fontSize": "12px", "color": "#64748b",
                    "borderTop": "1px solid #1e293b",
                },
                children=f"Source: Bureau of Meteorology — {warning.get('id', '')} — For emergency assistance call SES 132 500",
            ),
        ],
    )


# Parse uploaded CSV asset threshold list
@callback(
    Output("river-forecast-demo-csv-data", "data"),
    Output("river-forecast-demo-csv-status", "children"),
    Input("river-forecast-demo-csv-upload", "contents"),
    State("river-forecast-demo-csv-upload", "filename"),
    prevent_initial_call=True,
)
def parse_asset_csv(contents, filename):
    if contents is None:
        return None, html.Div()

    try:
        # Decode base64 CSV content
        content_type, content_string = contents.split(",")
        decoded = base64.b64decode(content_string)
        df = pd.read_csv(io.StringIO(decoded.decode("utf-8")))

        # Validate columns
        if "station" not in df.columns or "threshold_m" not in df.columns:
            return None, dmc.Badge(
                "CSV must have 'station' and 'threshold_m' columns",
                color="red", variant="outline", size="sm",
            )

        # Convert to dict keyed by station name (case-insensitive matching)
        thresholds = {}
        for _, row in df.iterrows():
            name = str(row["station"]).strip()
            try:
                level = float(row["threshold_m"])
                thresholds[name.lower()] = {"name": name, "level": level}
            except (ValueError, TypeError):
                continue

        if not thresholds:
            return None, dmc.Badge("No valid thresholds found", color="red", variant="outline", size="sm")

        status = dmc.Badge(
            f"{filename}: {len(thresholds)} thresholds loaded",
            color="teal", variant="filled", size="sm",
        )
        return thresholds, status

    except Exception as e:
        logger.warning("CSV parse failed: %s", e)
        return None, dmc.Badge(f"Error: {e}", color="red", variant="outline", size="sm")


@callback(
    Output("river-forecast-demo-station", "data"),
    Output("river-forecast-demo-station", "value"),
    Output("river-forecast-demo-info", "children"),
    Output("river-forecast-demo-chart", "figure"),
    Output("river-forecast-demo-warning", "children"),
    Input("river-forecast-demo-station", "value"),
    Input("river-view-mode", "value"),
    Input("river-forecast-demo-custom-level", "value"),
    Input("river-forecast-demo-custom-label", "value"),
    Input("river-forecast-demo-csv-data", "data"),
    prevent_initial_call=False,
)
def render_forecast_demo(station_key, view_mode, custom_level, custom_label, csv_data):
    from data.demo.forecast_demo_data import DEMO_SITES, DEMO_STATION_OPTIONS
    from src.components.river_charts import create_obs_forecast_overlay_chart, empty_chart

    options = DEMO_STATION_OPTIONS

    if not station_key or station_key not in DEMO_SITES:
        station_key = "warkon"

    if view_mode != "forecast-demo":
        return options, station_key, html.Div(), empty_chart(""), html.Div()

    site = DEMO_SITES[station_key]
    obs = site["observations"]
    last_obs = obs[-1]
    current_level = last_obs[1]

    thresholds = site["thresholds"]
    if current_level >= thresholds["major"]:
        flood_class, flood_color = "Major Flood", "red"
    elif current_level >= thresholds["moderate"]:
        flood_class, flood_color = "Moderate Flood", "orange"
    elif current_level >= thresholds["minor"]:
        flood_class, flood_color = "Minor Flood", "green"
    else:
        flood_class, flood_color = "Below Minor", "blue"

    if len(obs) >= 4:
        recent = [o[1] for o in obs[-4:]]
        avg_diff = sum(recent[i] - recent[i - 1] for i in range(1, len(recent))) / 3
        if avg_diff > 0.02:
            tendency, tend_color = "Rising", "red"
        elif avg_diff < -0.02:
            tendency, tend_color = "Falling", "green"
        else:
            tendency, tend_color = "Steady", "gray"
    else:
        tendency, tend_color = "Unknown", "gray"

    info = dmc.Paper(
        shadow="sm", p="md", radius="md",
        style={"backgroundColor": "#111827", "border": "1px solid #1e293b"},
        children=dmc.Group(gap="lg", wrap="wrap", children=[
            dmc.Stack(gap=2, children=[
                dmc.Text("SITE", size="xs", c="dimmed", fw=600),
                dmc.Text(site["name"], size="md", fw=700, c="white"),
            ]),
            dmc.Stack(gap=2, children=[
                dmc.Text("RIVER / BASIN", size="xs", c="dimmed", fw=600),
                dmc.Text(f"{site['river']} — {site['basin']}", size="md", c="white"),
            ]),
            dmc.Stack(gap=2, children=[
                dmc.Text("CURRENT LEVEL", size="xs", c="dimmed", fw=600),
                dmc.Text(f"{current_level:.2f} m {site['datum']}", size="md", fw=700, c="white"),
            ]),
            dmc.Stack(gap=2, children=[
                dmc.Text("TENDENCY", size="xs", c="dimmed", fw=600),
                dmc.Badge(tendency, color=tend_color, variant="light", size="lg"),
            ]),
            dmc.Stack(gap=2, children=[
                dmc.Text("FLOOD STATUS", size="xs", c="dimmed", fw=600),
                dmc.Badge(flood_class, color=flood_color, variant="filled", size="lg"),
            ]),
            dmc.Stack(gap=2, children=[
                dmc.Text("LAST OBS", size="xs", c="dimmed", fw=600),
                dmc.Text(last_obs[0], size="sm", c="#94a3b8"),
            ]),
        ]),
    )

    # Merge station's built-in custom thresholds with user-defined + CSV thresholds
    all_custom = list(site.get("custom_thresholds") or [])

    # CSV-uploaded asset threshold (matched by station name, case-insensitive)
    if csv_data and isinstance(csv_data, dict):
        station_name_lower = site["name"].lower()
        csv_match = csv_data.get(station_name_lower)
        if csv_match:
            all_custom.append({
                "level": csv_match["level"],
                "label": f"Asset Threshold ({csv_match['name']})",
                "color": "#FF69B4",  # hot pink — distinct from manual custom
                "dash": "dashdot",
            })

    # Manual user-defined threshold
    try:
        user_level = float(custom_level) if custom_level not in (None, "", " ") else None
    except (TypeError, ValueError):
        user_level = None
    if user_level is not None and user_level > 0:
        label = custom_label or "Custom Level"
        all_custom.append({
            "level": user_level,
            "label": label,
            "color": "#00CED1",
            "dash": "dashdot",
        })

    fig = create_obs_forecast_overlay_chart(
        observations=site["observations"],
        forecasts=site["forecasts"],
        thresholds=site["thresholds"],
        station_name=site["name"],
        river_name=site["river"],
        station_id=site["station"],
        datum=site["datum"],
        custom_thresholds=all_custom,
    )

    warning_panel = _build_warning_panel(site.get("warning"))

    return options, station_key, info, fig, warning_panel


# Download forecast demo as interactive HTML
@callback(
    Output("river-forecast-demo-download", "data"),
    Input("river-forecast-demo-html-btn", "n_clicks"),
    State("river-forecast-demo-station", "value"),
    State("river-forecast-demo-custom-level", "value"),
    State("river-forecast-demo-custom-label", "value"),
    State("river-forecast-demo-csv-data", "data"),
    prevent_initial_call=True,
)
def download_forecast_demo_html(_n_clicks, station_key, custom_level, custom_label, csv_data):
    from data.demo.forecast_demo_data import DEMO_SITES
    from src.components.river_charts import create_obs_forecast_overlay_chart
    from src.services.export_service import generate_river_interactive_html

    if not station_key or station_key not in DEMO_SITES:
        return no_update

    site = DEMO_SITES[station_key]

    # Build custom thresholds (same logic as render callback)
    all_custom = list(site.get("custom_thresholds") or [])

    # CSV asset threshold
    if csv_data and isinstance(csv_data, dict):
        csv_match = csv_data.get(site["name"].lower())
        if csv_match:
            all_custom.append({
                "level": csv_match["level"],
                "label": f"Asset Threshold ({csv_match['name']})",
                "color": "#FF69B4", "dash": "dashdot",
            })

    # Manual threshold
    try:
        user_level = float(custom_level) if custom_level not in (None, "", " ") else None
    except (TypeError, ValueError):
        user_level = None
    if user_level is not None and user_level > 0:
        label = custom_label or "Custom Level"
        all_custom.append({
            "level": user_level, "label": label,
            "color": "#00CED1", "dash": "dashdot",
        })

    fig = create_obs_forecast_overlay_chart(
        observations=site["observations"],
        forecasts=site["forecasts"],
        thresholds=site["thresholds"],
        station_name=site["name"],
        river_name=site["river"],
        station_id=site["station"],
        datum=site["datum"],
        custom_thresholds=all_custom,
    )

    figures = {"River Level — Observations + Forecast": fig}

    # Summary stats
    obs = site["observations"]
    last_obs = obs[-1]
    thresholds = site["thresholds"]
    current = last_obs[1]
    if current >= thresholds["major"]:
        cls = "Major Flood"
    elif current >= thresholds["moderate"]:
        cls = "Moderate Flood"
    elif current >= thresholds["minor"]:
        cls = "Minor Flood"
    else:
        cls = "Below Minor"

    summary = {
        "Station": f"{site['name']} ({site['station']})",
        "River": site["river"],
        "Basin": site["basin"],
        "Current Level": f"{current:.2f} m {site['datum']}",
        "Flood Status": cls,
        "Last Observation": last_obs[0],
    }
    # Add user threshold to summary if set
    if user_level is not None and user_level > 0:
        summary[custom_label or "Custom Level"] = f"{user_level:.2f} m"

    html_content = generate_river_interactive_html(
        figures, site["name"], site["station"], summary,
        warning=site.get("warning"),
    )

    safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in site["name"]).strip()
    return dict(content=html_content, filename=f"{safe_name}_Forecast_Demo.html")
