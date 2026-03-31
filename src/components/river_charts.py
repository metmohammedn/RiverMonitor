"""
River Monitor — Chart components.
Water level time series, tide forecasts, and future obs+forecast overlay.
"""
import plotly.graph_objects as go
import pandas as pd

from src.utils.constants import (
    PLOTLY_LAYOUT_DEFAULTS,
    TIDE_TRACE_COLOR,
    TIDE_TRACE_LINE_WIDTH,
    TIDE_FILL_COLOR,
    TIDE_CHART_HEIGHT,
)


def _base_layout(**overrides) -> dict:
    """Merge custom overrides onto the global dark theme layout defaults."""
    layout = dict(PLOTLY_LAYOUT_DEFAULTS)
    layout.update(overrides)
    return layout


def empty_chart(message: str = "Select a station to view data") -> go.Figure:
    """Create an empty placeholder chart with a message."""
    fig = go.Figure()
    fig.update_layout(**_base_layout(
        height=450,
        annotations=[{
            "text": message,
            "xref": "paper", "yref": "paper",
            "x": 0.5, "y": 0.5,
            "showarrow": False,
            "font": {"size": 16, "color": "#64748b"},
        }],
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
    ))
    return fig


def create_river_station_chart(
    df: pd.DataFrame,
    station_name: str,
) -> go.Figure:
    """
    River station time series with flood threshold lines.
    """
    if df.empty or "RealValue" not in df.columns:
        return empty_chart("No river data available")

    # Guard against all-NaN
    if df["RealValue"].dropna().empty:
        return empty_chart("No valid readings for this station")

    fig = go.Figure()

    # Main water level line
    fig.add_trace(go.Scatter(
        x=df["ObservationTimestamp"],
        y=df["RealValue"],
        mode="lines+markers",
        name="Water Level",
        line=dict(color="#3b82f6", width=3),
        marker=dict(size=4, color="#3b82f6"),
        hovertemplate="<b>%{x}</b><br>Level: %{y:.2f} m<extra></extra>",
    ))

    y_max = df["RealValue"].max() + 1

    # Threshold lines
    for thresh, color, label in [
        ("Minor", "#22c55e", "Minor Flood"),
        ("Moderate", "#f59e0b", "Moderate Flood"),
        ("Major", "#ef4444", "Major Flood"),
    ]:
        if thresh in df.columns and df[thresh].notna().any():
            val = df[thresh].iloc[0]
            if val > 0:
                fig.add_trace(go.Scatter(
                    x=[df["ObservationTimestamp"].min(), df["ObservationTimestamp"].max()],
                    y=[val, val],
                    mode="lines",
                    name=f"{label} ({val:.2f}m)",
                    line=dict(color=color, width=2, dash="dash"),
                    hoverinfo="skip",
                ))
                y_max = max(y_max, val + 0.5)

    fig.update_layout(**_base_layout(
        title=f"{station_name} — Last {len(df)} Observations",
        xaxis_title="Date and Time",
        yaxis_title="Height (m)",
        yaxis=dict(range=[0, y_max]),
        height=450,
        margin=dict(l=50, r=30, t=60, b=100),
        legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="left", x=0),
    ))
    return fig


def create_tide_chart(
    df: pd.DataFrame,
    station_name: str,
    sensor_id: str = None,
) -> go.Figure:
    """
    Tide forecast area chart with MSL reference, 'Now' marker, and HAT line.

    Parameters
    ----------
    df : DataFrame indexed by datetime with 'sea_level_height_msl' column.
    station_name : display name of the tidal station.
    """
    if df.empty or "sea_level_height_msl" not in df.columns:
        return empty_chart("No tide forecast data available")

    fig = go.Figure()

    # Main tide area trace
    fig.add_trace(go.Scatter(
        x=df.index,
        y=df["sea_level_height_msl"],
        mode="lines",
        name="Sea Level (MSL)",
        line=dict(color=TIDE_TRACE_COLOR, width=TIDE_TRACE_LINE_WIDTH),
        fill="tozeroy",
        fillcolor=TIDE_FILL_COLOR,
        hovertemplate="<b>%{x}</b><br>Sea Level: %{y:.2f} m<extra></extra>",
    ))

    # MSL reference line at y=0
    fig.add_hline(
        y=0,
        line_dash="dot",
        line_color="#64748b",
        line_width=1,
        annotation_text="MSL",
        annotation_position="bottom right",
        annotation_font_color="#64748b",
        annotation_font_size=10,
    )

    # "Now" vertical marker
    now = pd.Timestamp.now(tz="UTC")
    if df.index.tz is None:
        now = now.tz_localize(None)

    y_min = df["sea_level_height_msl"].min()
    y_max = df["sea_level_height_msl"].max()
    y_range_pad = (y_max - y_min) * 0.1 if y_max > y_min else 0.2

    fig.add_trace(go.Scatter(
        x=[now, now],
        y=[y_min - y_range_pad, y_max + y_range_pad],
        mode="lines",
        name="Now",
        line=dict(color="#ef4444", width=1.5, dash="dash"),
        hoverinfo="skip",
        showlegend=True,
    ))

    # HAT (Highest Astronomical Tide) reference line
    from src.utils.constants import TIDE_HAT_VALUES
    hat_value = None
    hat_label = "HAT"
    if sensor_id and sensor_id in TIDE_HAT_VALUES:
        hat_value = TIDE_HAT_VALUES[sensor_id]
        hat_label = f"HAT ({hat_value:.2f}m)"
    elif not df["sea_level_height_msl"].dropna().empty:
        # Estimate from forecast data if not in lookup
        hat_value = float(df["sea_level_height_msl"].max())
        hat_label = f"Est. HAT ({hat_value:.2f}m)"

    if hat_value is not None:
        fig.add_hline(
            y=hat_value,
            line_dash="dot", line_color="#f59e0b", line_width=1.5,
        )
        fig.add_annotation(
            xref="paper", yref="y", x=0.01, y=hat_value,
            text=hat_label, showarrow=False,
            font=dict(color="#f59e0b", size=10), xanchor="left", yshift=10,
        )

    fig.update_layout(**_base_layout(
        title=f"Tide Forecast — {station_name}",
        xaxis_title="Date and Time (UTC)",
        yaxis_title="Sea Level Height (m MSL)",
        height=TIDE_CHART_HEIGHT,
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="left", x=0),
        margin=dict(l=50, r=30, t=60, b=90),
    ))
    return fig


def create_precipitation_chart(
    model_data: dict,
    station_name: str,
    grid_lat: float = None,
    grid_lon: float = None,
) -> go.Figure:
    """
    Multi-model precipitation forecast line chart.

    Parameters
    ----------
    model_data : dict mapping model_name -> {"df": DataFrame, "color": str}
                 Each DataFrame indexed by datetime with 'precipitation' column.
    station_name : display name.
    grid_lat, grid_lon : actual model grid coordinates (for subtitle).
    """
    if not model_data:
        return empty_chart("No precipitation data available")

    fig = go.Figure()

    for model_name, data in model_data.items():
        df = data["df"]
        color = data["color"]
        if df.empty or "precipitation" not in df.columns:
            continue

        fig.add_trace(go.Scatter(
            x=df.index,
            y=df["precipitation"],
            mode="lines",
            name=model_name,
            line=dict(color=color, width=2),
            hovertemplate=(
                "<b>" + model_name + "</b><br>"
                "%{x}<br>"
                "Precip: %{y:.1f} mm<extra></extra>"
            ),
        ))

    if not fig.data:
        return empty_chart("No precipitation data available")

    # "Now" vertical marker (shape + annotation avoids Timestamp arithmetic bug)
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    fig.add_shape(
        type="line", xref="x", yref="paper",
        x0=now, x1=now, y0=0, y1=1,
        line=dict(color="#ef4444", width=1.5, dash="dash"),
    )
    fig.add_annotation(
        x=now, y=0.97, yref="paper",
        text="Now", showarrow=False,
        font=dict(color="#ef4444", size=10),
    )

    # Build title with grid location as subtitle on a new line
    title_text = f"Precipitation Forecast — {station_name}"
    subtitle = ""
    if grid_lat is not None and grid_lon is not None:
        lat_dir = "S" if grid_lat < 0 else "N"
        lon_dir = "E" if grid_lon >= 0 else "W"
        subtitle = f"Nearest grid point: {abs(grid_lat):.2f}{lat_dir} {abs(grid_lon):.2f}{lon_dir}"

    title_dict = dict(text=title_text, font=dict(size=15))
    if subtitle:
        title_dict["text"] = f"{title_text}<br><span style='font-size:11px;color:#64748b'>{subtitle}</span>"

    fig.update_layout(**_base_layout(
        title=title_dict,
        xaxis_title="Date and Time",
        yaxis_title="Precipitation (mm/hr)",
        yaxis=dict(rangemode="nonnegative"),
        height=350,
        margin=dict(l=50, r=30, t=65, b=80),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    ))
    return fig


def add_observation_trace(
    fig: go.Figure,
    obs_df: pd.DataFrame,
    variable: str,
    name: str = "Observed",
    color: str = "#22d3ee",
) -> None:
    """Overlay observation data as a cyan trace with triangle markers."""
    if obs_df.empty or variable not in obs_df.columns:
        return
    series = obs_df[variable].dropna()
    if series.empty:
        return
    fig.add_trace(go.Scatter(
        x=series.index, y=series.values,
        mode="lines+markers", name=name,
        line=dict(color=color, width=1.5),
        marker=dict(color=color, size=5, symbol="triangle-up"),
        hovertemplate="<b>" + name + "</b><br>%{x}<br>%{y:.1f}<extra></extra>",
    ))


def add_weather_windows(fig: go.Figure, windows: list) -> None:
    """Add green vertical bands for safe weather windows."""
    from src.utils.constants import WEATHER_WINDOW_COLOR
    for i, (start, end) in enumerate(windows):
        fig.add_vrect(
            x0=start, x1=end,
            fillcolor=WEATHER_WINDOW_COLOR,
            line_width=0,
            annotation_text="Safe" if i == 0 else "",
            annotation_position="top left",
            annotation_font_color="#22c55e",
            annotation_font_size=10,
        )


def create_wind_exceedance_chart(
    exceedance_data: dict,
    wind_threshold: float,
    station_name: str,
    grid_lat: float = None,
    grid_lon: float = None,
    agreement: dict = None,
) -> go.Figure:
    """
    Multi-model wind speed exceedance probability chart.
    exceedance_data: {model_name: {"series": pd.Series, "color": str}}
    """
    if not exceedance_data:
        return empty_chart("No wind data available")

    from src.utils.constants import WIND_ENSEMBLE_MODELS

    fig = go.Figure()

    # Risk zone bands
    fig.add_hrect(y0=0, y1=10, fillcolor="rgba(34, 197, 94, 0.06)", line_width=0)
    fig.add_hrect(y0=10, y1=30, fillcolor="rgba(234, 179, 8, 0.06)", line_width=0)
    fig.add_hrect(y0=30, y1=100, fillcolor="rgba(239, 68, 68, 0.06)", line_width=0)

    # Risk zone labels
    fig.add_annotation(xref="paper", yref="y", x=1.01, y=5, text="Low", showarrow=False,
                       font=dict(color="#22c55e", size=9), xanchor="left")
    fig.add_annotation(xref="paper", yref="y", x=1.01, y=20, text="Moderate", showarrow=False,
                       font=dict(color="#eab308", size=9), xanchor="left")
    fig.add_annotation(xref="paper", yref="y", x=1.01, y=65, text="High", showarrow=False,
                       font=dict(color="#ef4444", size=9), xanchor="left")

    for model_name, data in exceedance_data.items():
        series = data["series"]
        color = data["color"]
        dash_style = "solid" if model_name == "ECMWF IFS" else "dash"

        fig.add_trace(go.Scatter(
            x=series.index, y=series.values,
            mode="lines", name=model_name,
            line=dict(color=color, width=2.5 if model_name == "ECMWF IFS" else 1.5, dash=dash_style),
            hovertemplate="<b>" + model_name + "</b><br>%{x}<br>Probability: %{y:.0f}%<extra></extra>",
        ))

    # Title with grid location
    title = f"Wind Exceedance: > {wind_threshold} km/h — {station_name}"
    if grid_lat is not None and grid_lon is not None:
        lat_dir = "S" if grid_lat < 0 else "N"
        lon_dir = "E" if grid_lon >= 0 else "W"
        title += f"<br><span style='font-size:11px;color:#64748b'>Grid: {abs(grid_lat):.2f}{lat_dir} {abs(grid_lon):.2f}{lon_dir}</span>"

    # Agreement badge
    if agreement and agreement.get("score") is not None:
        title += f"<br><span style='font-size:11px;color:{agreement['color']}'>{agreement['level']} ({agreement['score']:.0f}%)</span>"

    fig.update_layout(**_base_layout(
        title=dict(text=title, font=dict(size=14)),
        yaxis_title="Exceedance Probability (%)",
        xaxis_title="Date and Time",
        yaxis=dict(range=[0, 100]),
        height=380,
        margin=dict(l=50, r=70, t=80, b=80),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="left", x=0),
    ))
    return fig


def create_wind_ensemble_chart(
    stats_df: pd.DataFrame,
    wind_threshold: float,
    model_name: str,
    color_main: str,
    color_fill: str,
    member_count: int,
    weather_windows: list = None,
) -> go.Figure:
    """Per-model ensemble spread: p10-p90 band + median + threshold."""
    if stats_df.empty:
        return empty_chart(f"No {model_name} wind data")

    fig = go.Figure()

    # P10-P90 band
    fig.add_trace(go.Scatter(
        x=stats_df.index, y=stats_df["p90"], mode="lines",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=stats_df.index, y=stats_df["p10"], mode="lines",
        line=dict(width=0), fill="tonexty", fillcolor=color_fill,
        name=f"10-90% range ({member_count} members)",
        hoverinfo="skip",
    ))

    # Median
    fig.add_trace(go.Scatter(
        x=stats_df.index, y=stats_df["median"], mode="lines",
        name="Median", line=dict(color=color_main, width=2.5),
        hovertemplate="<b>Median</b><br>%{x}<br>%{y:.1f} km/h<extra></extra>",
    ))

    # Threshold line
    fig.add_hline(y=wind_threshold, line_dash="dash", line_color="#ef4444", line_width=2)
    fig.add_annotation(
        xref="paper", yref="y", x=1.01, y=wind_threshold,
        text=f"<b>{wind_threshold} km/h</b>", showarrow=False,
        font=dict(color="#ef4444", size=10), xanchor="left",
    )

    # Weather windows
    if weather_windows:
        add_weather_windows(fig, weather_windows)

    fig.update_layout(**_base_layout(
        title=f"{model_name} Wind Ensemble — {member_count} Members",
        yaxis_title="Wind Speed (km/h)",
        xaxis_title="Date and Time",
        yaxis=dict(rangemode="nonnegative"),
        height=350,
        margin=dict(l=50, r=80, t=50, b=80),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="left", x=0),
    ))
    return fig


def create_gust_chart(
    gust_data: dict,
    gust_threshold: float,
    station_name: str,
    grid_lat: float = None,
    grid_lon: float = None,
    weather_windows: list = None,
) -> go.Figure:
    """
    Multi-model gust comparison chart.
    gust_data: {model_name: {"stats_df": DataFrame with max/median/p90, "color": str}}
    """
    if not gust_data:
        return empty_chart("No gust data available")

    from src.utils.constants import WIND_REF_GALE, WIND_REF_STORM

    fig = go.Figure()

    for model_name, data in gust_data.items():
        stats = data["stats_df"]
        color = data["color"]
        if stats is None or stats.empty:
            continue

        # Max gust (dotted)
        fig.add_trace(go.Scatter(
            x=stats.index, y=stats["max"], mode="lines",
            name=f"{model_name} Max",
            line=dict(color=color, width=1.5, dash="dot"),
            hovertemplate="<b>" + model_name + " Max</b><br>%{x}<br>%{y:.1f} km/h<extra></extra>",
        ))

        # Median gust (solid)
        fig.add_trace(go.Scatter(
            x=stats.index, y=stats["median"], mode="lines",
            name=f"{model_name} Median",
            line=dict(color=color, width=2),
            hovertemplate="<b>" + model_name + " Median</b><br>%{x}<br>%{y:.1f} km/h<extra></extra>",
        ))

    # Threshold line
    fig.add_hline(y=gust_threshold, line_dash="dash", line_color="#ef4444", line_width=2)
    fig.add_annotation(
        xref="paper", yref="y", x=1.01, y=gust_threshold,
        text=f"<b>Threshold ({gust_threshold} km/h)</b>", showarrow=False,
        font=dict(color="#ef4444", size=10), xanchor="left",
    )

    # Beaufort reference lines
    fig.add_hline(y=WIND_REF_GALE, line_dash="dot", line_color="#64748b", line_width=1)
    fig.add_annotation(
        xref="paper", yref="y", x=0.01, y=WIND_REF_GALE,
        text=f"Gale ({WIND_REF_GALE} km/h)", showarrow=False,
        font=dict(color="#64748b", size=9), xanchor="left", yshift=10,
    )
    fig.add_hline(y=WIND_REF_STORM, line_dash="dot", line_color="#64748b", line_width=1)
    fig.add_annotation(
        xref="paper", yref="y", x=0.01, y=WIND_REF_STORM,
        text=f"Storm ({WIND_REF_STORM} km/h)", showarrow=False,
        font=dict(color="#64748b", size=9), xanchor="left", yshift=10,
    )

    # Weather windows
    if weather_windows:
        add_weather_windows(fig, weather_windows)

    # Title
    title = f"Wind Gusts — {station_name}"
    if grid_lat is not None and grid_lon is not None:
        lat_dir = "S" if grid_lat < 0 else "N"
        lon_dir = "E" if grid_lon >= 0 else "W"
        title += f"<br><span style='font-size:11px;color:#64748b'>Grid: {abs(grid_lat):.2f}{lat_dir} {abs(grid_lon):.2f}{lon_dir}</span>"

    fig.update_layout(**_base_layout(
        title=dict(text=title, font=dict(size=14)),
        yaxis_title="Wind Gust (km/h)",
        xaxis_title="Date and Time",
        yaxis=dict(rangemode="nonnegative"),
        height=380,
        margin=dict(l=50, r=110, t=70, b=80),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="left", x=0),
    ))
    return fig


def create_obs_forecast_overlay_chart(
    observations: list,
    forecasts: list,
    thresholds: dict,
    station_name: str,
    river_name: str = "",
    station_id: str = "",
    datum: str = "LGH",
    custom_thresholds: list = None,
) -> go.Figure:
    """
    Obs + forecast overlay chart with flood threshold bands and peak annotation.

    Parameters
    ----------
    observations : list of [datetime_str, level] pairs
    forecasts : list of {"time": str, "level": float, "text": str} dicts (can be empty)
    thresholds : {"minor": float, "moderate": float, "major": float}
    custom_thresholds : optional list of {"level", "label", "color", "dash"} dicts
    """
    if not observations:
        return empty_chart("No observation data available")

    obs_times = [o[0] for o in observations]
    obs_levels = [o[1] for o in observations]

    # Determine ranges
    minor = thresholds.get("minor", 0)
    moderate = thresholds.get("moderate", 0)
    major = thresholds.get("major", 0)

    custom_levels = [ct["level"] for ct in (custom_thresholds or [])]
    all_levels = obs_levels + [f["level"] for f in forecasts] + [major + 1] + custom_levels
    y_min = max(0, min(obs_levels) - 0.5)
    y_max = max(all_levels) + 1

    # X-axis range: extend 2 days past last forecast (or last obs)
    from datetime import datetime, timedelta
    all_times = obs_times + [f["time"] for f in forecasts]
    last_time = datetime.fromisoformat(all_times[-1]) + timedelta(days=2)
    first_time = datetime.fromisoformat(all_times[0])

    # Flood class helper
    def get_flood_class(level):
        if level >= major:
            return ("Major Flood", "#DC143C")
        elif level >= moderate:
            return ("Moderate Flood", "#FF8C00")
        elif level >= minor:
            return ("Minor Flood", "#2e7d32")
        return ("Below Minor", "#1565c0")

    # Observation hover text
    obs_hover = []
    for t, lv in observations:
        cls_label, cls_color = get_flood_class(lv)
        obs_hover.append(
            f"<b>{t}</b><br>"
            f"Level: <b>{lv:.2f} m</b><br>"
            f"Status: <b>{cls_label}</b><br>"
            f"<i>Observed</i>"
        )

    fig = go.Figure()

    # Obs trace — blue solid line
    fig.add_trace(go.Scatter(
        x=obs_times, y=obs_levels,
        mode="lines",
        name="Observed Level",
        line=dict(color="#1E90FF", width=2.5),
        hoverinfo="text",
        hovertext=obs_hover,
        hoverlabel=dict(bgcolor="#111827", bordercolor="#1E90FF", font=dict(size=12)),
    ))

    # Forecast trace — red dashed + diamonds (connected from last obs)
    if forecasts:
        last_obs_time = obs_times[-1]
        last_obs_level = obs_levels[-1]

        fcst_times = [last_obs_time] + [f["time"] for f in forecasts]
        fcst_levels = [last_obs_level] + [f["level"] for f in forecasts]
        fcst_hover = [""]  # empty for connection point
        for f in forecasts:
            cls_label, cls_color = get_flood_class(f["level"])
            fcst_hover.append(
                f"<b>{f['time']}</b><br>"
                f"Forecast Level: <b>{f['level']:.2f} m</b><br>"
                f"Status: <b>{cls_label}</b><br>"
                f"<i>{river_name} {f['text']}</i>"
            )

        fig.add_trace(go.Scatter(
            x=fcst_times, y=fcst_levels,
            mode="lines+markers",
            name="Issued Forecast",
            line=dict(color="#FF6347", width=2.5, dash="dash"),
            marker=dict(color="#FF6347", size=10, symbol="diamond"),
            hoverinfo="text",
            hovertext=fcst_hover,
            hoverlabel=dict(bgcolor="#111827", bordercolor="#FF6347", font=dict(size=12)),
        ))

    # Shapes: flood threshold bands
    shapes = []

    # Minor → Moderate band (green)
    shapes.append(dict(
        type="rect", xref="paper", yref="y",
        x0=0, x1=1, y0=minor, y1=moderate,
        fillcolor="rgba(46, 125, 50, 0.08)", line=dict(width=0),
    ))
    # Moderate → Major band (orange)
    shapes.append(dict(
        type="rect", xref="paper", yref="y",
        x0=0, x1=1, y0=moderate, y1=major,
        fillcolor="rgba(255, 140, 0, 0.08)", line=dict(width=0),
    ))
    # Major → top band (red)
    shapes.append(dict(
        type="rect", xref="paper", yref="y",
        x0=0, x1=1, y0=major, y1=y_max,
        fillcolor="rgba(220, 20, 60, 0.06)", line=dict(width=0),
    ))

    # Threshold lines
    annotations = []
    threshold_defs = [
        (minor, f"Minor ({minor}m)", "#2e7d32"),
        (moderate, f"Moderate ({moderate}m)", "#FF8C00"),
        (major, f"Major ({major}m)", "#DC143C"),
    ]
    for level, label, color in threshold_defs:
        if level <= y_max:
            shapes.append(dict(
                type="line", xref="paper", yref="y",
                x0=0, x1=1, y0=level, y1=level,
                line=dict(color=color, width=2, dash="dash"),
            ))
            annotations.append(dict(
                xref="paper", yref="y", x=1.01, y=level,
                text=f"<b>{label}</b>", showarrow=False,
                font=dict(color=color, size=11), xanchor="left",
            ))

    # Custom threshold lines
    for ct in (custom_thresholds or []):
        if ct["level"] <= y_max:
            shapes.append(dict(
                type="line", xref="paper", yref="y",
                x0=0, x1=1, y0=ct["level"], y1=ct["level"],
                line=dict(color=ct["color"], width=1.5, dash=ct.get("dash", "dot")),
            ))
            annotations.append(dict(
                xref="paper", yref="y", x=1.01, y=ct["level"],
                text=f"<b>{ct['label']} ({ct['level']}m)</b>", showarrow=False,
                font=dict(color=ct["color"], size=10), xanchor="left",
            ))

    # "Latest Obs" vertical line
    last_obs = obs_times[-1]
    shapes.append(dict(
        type="line", xref="x", yref="paper",
        x0=last_obs, x1=last_obs, y0=0, y1=1,
        line=dict(color="#888", width=1.5, dash="dot"),
    ))
    annotations.append(dict(
        xref="x", yref="paper", x=last_obs, y=1.06,
        text="<b>Latest Obs</b>", showarrow=False,
        font=dict(color="#888", size=10),
    ))

    # Peak annotation — ONLY when river has truly peaked (not still rising)
    peak_idx = 0
    peak_val = obs_levels[0]
    for i, v in enumerate(obs_levels):
        if v > peak_val:
            peak_val = v
            peak_idx = i

    has_peaked = peak_idx < len(obs_levels) - 1
    if peak_val >= minor and has_peaked:
        annotations.append(dict(
            x=obs_times[peak_idx], y=peak_val,
            text=f"Peak: {peak_val:.2f}m",
            showarrow=True, arrowhead=2, arrowsize=0.8, arrowcolor="#e2e8f0",
            ax=40, ay=-30,
            font=dict(size=11, color="#e2e8f0"),
            bgcolor="rgba(17, 24, 39, 0.9)",
            bordercolor="#64748b", borderwidth=1, borderpad=4,
        ))

    # Title
    title_text = f"{station_name} ({river_name}) - Station {station_id}"

    fig.update_layout(**_base_layout(
        height=500,
        hovermode="closest",
        showlegend=False,
        title=dict(text=title_text, font=dict(size=16, color="#e2e8f0")),
        xaxis=dict(
            title="Date/Time (AEST)",
            type="date",
            gridcolor="#1e293b",
            tickformat="%d %b\n%H:%M",
            dtick=86400000,
            range=[first_time.isoformat(), last_time.isoformat()],
        ),
        yaxis=dict(
            title=f"River Level (m {datum})",
            gridcolor="#1e293b",
            range=[y_min, y_max],
        ),
        shapes=shapes,
        annotations=annotations,
        margin=dict(l=60, r=220, t=50, b=60),
    ))
    return fig
