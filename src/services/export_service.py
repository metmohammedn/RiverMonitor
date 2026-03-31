"""
River Monitor — Export service.
Generates interactive HTML reports for river station data.
"""
from datetime import datetime
from typing import Dict, Optional

import plotly.io as pio


def generate_river_interactive_html(
    figures: Dict[str, "go.Figure"],
    station_name: str,
    sensor_id: str,
    summary_stats: Optional[Dict[str, str]] = None,
    warning: Optional[Dict[str, str]] = None,
) -> str:
    """
    Generate a standalone interactive HTML report for a River Monitoring station.

    Args:
        figures:        dict mapping section title -> Plotly Figure
        station_name:   river gauge station name
        sensor_id:      BoM sensor identifier
        summary_stats:  optional dict of label -> value for metric cards
        warning:        optional flood warning dict with title, severity, headline, etc.

    Returns:
        Complete HTML string ready for download.
    """
    now_str = datetime.now().strftime("%H:%M %d %b %Y")

    # Build each chart as an HTML <div>
    chart_sections = []
    for title, fig in figures.items():
        chart_html = pio.to_html(
            fig,
            full_html=False,
            include_plotlyjs=False,
            config={"displaylogo": False, "responsive": True},
        )
        chart_sections.append(f"""
        <div class="chart-section">
            <h2>{title}</h2>
            {chart_html}
        </div>
        """)

    charts_html = "\n".join(chart_sections)

    # Summary stats cards
    stats_html = ""
    if summary_stats:
        cards = []
        for label, value in summary_stats.items():
            cards.append(f"""
            <div class="stat-card">
                <div class="stat-label">{label}</div>
                <div class="stat-value">{value}</div>
            </div>
            """)
        stats_html = f'<div class="stats-row">{"".join(cards)}</div>'

    # Warning panel HTML
    warning_html = ""
    if warning and warning.get("title"):
        sev = warning.get("severity", "minor")
        sev_bg = {"major": "#DC143C", "moderate": "#FF8C00", "minor": "#FFD700"}.get(sev, "#FFD700")
        sev_text = {"major": "white", "moderate": "white", "minor": "#333"}.get(sev, "#333")
        fcst_sev = warning.get("forecast_severity", "minor")
        fcst_border = {"major": "#DC143C", "moderate": "#FF8C00", "minor": "#FFD700"}.get(fcst_sev, "#FFD700")
        fcst_bg_col = {"major": "#2a1015", "moderate": "#2a1f0d", "minor": "#2a2a0d"}.get(fcst_sev, "#1a1a2e")

        warning_html = f"""
        <div class="chart-section" style="padding:0;overflow:hidden;">
            <div style="background:{sev_bg};color:{sev_text};padding:14px 20px;font-weight:700;font-size:15px;">
                {warning.get('title', '')}
            </div>
            <div style="padding:16px 20px;line-height:1.65;font-size:14px;color:#e2e8f0;">
                <p style="font-size:12px;color:#94a3b8;margin-bottom:6px;">
                    <strong>Warning #{warning.get('number', '')}</strong>
                    &mdash; {warning.get('id', '')}
                    &mdash; Issued {warning.get('issued_at', '')}
                </p>
                <p style="font-weight:700;font-size:13px;text-transform:uppercase;white-space:pre-line;margin-bottom:12px;">
                    {warning.get('headline', '')}
                </p>
                <p style="margin-bottom:10px;">{warning.get('overview_text', '')}</p>
                <p style="font-weight:600;margin-bottom:10px;">{warning.get('status_text', '')}</p>
                <div style="background:{fcst_bg_col};border-left:4px solid {fcst_border};padding:10px 14px;margin:10px 0;border-radius:0 4px 4px 0;">
                    <strong>Forecast:</strong> {warning.get('forecast_text', '')}
                </div>
            </div>
            <div style="padding:10px 20px;background:#0d1320;font-size:12px;color:#64748b;border-top:1px solid #1e293b;">
                Source: Bureau of Meteorology &mdash; {warning.get('id', '')} &mdash; For emergency assistance call SES 132 500
            </div>
        </div>
        """

    river_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>River Station Report &mdash; {station_name}</title>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        :root {{
            --bg-primary: #0d1320;
            --bg-card: #111827;
            --border: #1e293b;
            --text: #f1f5f9;
            --text-dim: #94a3b8;
            --accent: #3b82f6;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg-primary);
            color: var(--text);
            line-height: 1.6;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 24px;
        }}
        .report-header {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px 32px;
            margin-bottom: 20px;
        }}
        .report-header h1 {{
            font-size: 22px;
            font-weight: 700;
            color: var(--accent);
            margin-bottom: 8px;
        }}
        .header-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 24px;
            margin-top: 12px;
        }}
        .meta-item {{
            font-size: 13px;
            color: var(--text-dim);
        }}
        .meta-item strong {{
            color: var(--text);
        }}
        .stats-row {{
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
            margin-bottom: 20px;
        }}
        .stat-card {{
            flex: 1;
            min-width: 140px;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 14px 18px;
        }}
        .stat-label {{ font-size: 11px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; }}
        .stat-value {{ font-size: 18px; font-weight: 700; color: var(--text); margin-top: 4px; }}
        .chart-section {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        .chart-section h2 {{
            font-size: 15px;
            font-weight: 600;
            color: var(--text);
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
        }}
        .report-footer {{
            text-align: center;
            padding: 20px;
            font-size: 11px;
            color: var(--text-dim);
            border-top: 1px solid var(--border);
            margin-top: 12px;
        }}
        @media print {{
            body {{ background: #fff; color: #000; }}
            .chart-section, .report-header, .stat-card {{
                background: #fff; border-color: #ddd;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="report-header">
            <h1>River Station Report &mdash; {station_name}</h1>
            <div class="header-meta">
                <div class="meta-item">Generated: <strong>{now_str}</strong></div>
                <div class="meta-item">Sensor ID: <strong>{sensor_id}</strong></div>
                <div class="meta-item">Source: <strong>BoM River Gauges (Archived)</strong></div>
            </div>
        </div>

        {stats_html}
        {charts_html}
        {warning_html}

        <div class="report-footer">
            River Monitor &mdash; Data: Bureau of Meteorology River Gauges
            &mdash; Interactive report generated {now_str}
            <br>All charts are fully interactive: zoom, pan, and hover for details.
        </div>
    </div>
</body>
</html>"""

    return river_html
