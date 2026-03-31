"""
River Monitor — Standalone application.
Run with: python app.py
"""
import logging
import os
import sys

import dash
from dash import Dash, html, dcc
import dash_mantine_components as dmc

# Ensure src is importable
sys.path.insert(0, os.path.dirname(__file__))

from config import get_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> Dash:
    """Create and configure the River Monitor."""
    config = get_config()

    # Pre-import component libraries so Dash registers them before callbacks fire
    import dash_leaflet  # noqa: F401 — used by river map
    import dash_iconify  # noqa: F401 — used by river.py layout

    # Create Dash app with multi-page support
    app = Dash(
        __name__,
        use_pages=True,
        pages_folder=os.path.join(os.path.dirname(__file__), "src", "pages"),
        suppress_callback_exceptions=True,
        title=config.APP_NAME,
        update_title="Loading...",
        external_stylesheets=[
            "https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@300;400;500;600&display=swap",
        ],
    )

    server = app.server

    # ── Google Analytics 4 ──────────────────────────────────────────────
    ga_id = config.GA_MEASUREMENT_ID
    if ga_id:
        app.index_string = '''<!DOCTYPE html>
<html>
    <head>
        <!-- Google Analytics 4 -->
        <script async src="https://www.googletagmanager.com/gtag/js?id=''' + ga_id + '''"></script>
        <script>
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', "''' + ga_id + '''", {send_page_view: true});
        </script>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>'''
        logger.info("Google Analytics 4 enabled: %s", ga_id)
    else:
        logger.info("Google Analytics disabled (no GA_MEASUREMENT_ID set)")

    # ── Initialize services ──────────────────────────────────────────────

    # Redis cache (optional — app runs fine without it)
    try:
        from src.data.cache import init_cache
        init_cache(config.REDIS_URL)
        logger.info("Redis cache initialized")
    except Exception as e:
        logger.warning("Redis cache unavailable (app will run without caching): %s", e)

    # Open-Meteo API client (tide forecasts only)
    try:
        from src.data.api_client import init_api_client
        init_api_client(
            forecast_url=config.OPENMETEO_FORECAST_URL,
            marine_url=config.OPENMETEO_MARINE_URL,
            ensemble_url=config.OPENMETEO_ENSEMBLE_URL,
            api_key=config.OPENMETEO_API_KEY,
            timeout=config.API_TIMEOUT,
            max_connections=config.API_MAX_CONNECTIONS,
        )
        api_tier = "commercial" if config.OPENMETEO_API_KEY else "free"
        logger.info("API client initialized (%s tier)", api_tier)
    except Exception as e:
        logger.warning("API client initialization failed: %s", e)

    # ── Register Flask routes ────────────────────────────────────────────

    # River upload/clear layer endpoints
    from src.pages.river import init_river_routes
    init_river_routes(server)

    # Flood scenario PDF endpoints
    from src.services.flood_scenario_service import register_flood_routes
    register_flood_routes(server, config.FLOOD_SCENARIOS_DIR)

    # ── Dark theme (matches main dashboard) ──────────────────────────────
    dark_theme = dmc.DEFAULT_THEME.copy()
    dark_theme.update({
        "colorScheme": "dark",
        "primaryColor": "orange",
        "fontFamily": "DM Sans, sans-serif",
        "fontFamilyMonospace": "JetBrains Mono, monospace",
        "headings": {"fontFamily": "DM Sans, sans-serif"},
        "colors": {
            "dark": [
                "#C1C2C5", "#A6A7AB", "#909296", "#5c5f66",
                "#373A40", "#2C2E33", "#1e293b", "#111827",
                "#0d1320", "#080c14",
            ],
        },
    })

    # ── App layout ───────────────────────────────────────────────────────
    app.layout = dmc.MantineProvider(
        theme=dark_theme,
        forceColorScheme="dark",
        children=html.Div(
            style={
                "backgroundColor": "#080c14",
                "minHeight": "100vh",
            },
            children=[
                # Simple header bar
                dmc.Paper(
                    p="sm",
                    style={
                        "backgroundColor": "#0d1320",
                        "borderBottom": "1px solid #1e293b",
                    },
                    children=dmc.Group(
                        justify="space-between",
                        children=[
                            dmc.Group(
                                gap="sm",
                                children=[
                                    dmc.Text(
                                        "🌊 River Monitor",
                                        size="lg", fw=700, c="white",
                                    ),
                                    dmc.Badge(
                                        "ARCHIVED DATA",
                                        color="yellow", variant="dot", size="sm",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ),
                # Page content
                html.Div(
                    style={"padding": "0"},
                    children=dash.page_container,
                ),
            ],
        ),
    )

    # ── Health check endpoint (for Docker / ALB) ─────────────────────────
    @server.route("/health")
    def health():
        return {"status": "healthy"}

    return app


# ── Entry point ──────────────────────────────────────────────────────────
app = create_app()
server = app.server  # For gunicorn: gunicorn app:server

if __name__ == "__main__":
    config = get_config()
    app.run(debug=config.DEBUG, host=config.HOST, port=config.PORT)
