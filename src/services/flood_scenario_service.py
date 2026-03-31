"""
Flood Scenarios — PDF discovery and Flask route registration.
Auto-discovers PDF files from a directory and serves them via Flask.
"""
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from flask import jsonify, send_from_directory
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

# State code mapping from BoM product ID prefixes
_STATE_PREFIXES = {
    "IDD": "NT",
    "IDN": "NSW",
    "IDQ": "QLD",
    "IDS": "SA",
    "IDT": "TAS",
    "IDV": "VIC",
    "IDW": "WA",
}


def discover_flood_pdfs(scenarios_dir: Path) -> List[Dict]:
    """
    Scan the directory for PDF files and parse metadata from filenames.

    Expected filename format: IDQ20910-20260309.030200.pdf
    """
    if not scenarios_dir.exists():
        logger.warning("Flood scenarios directory not found: %s", scenarios_dir)
        return []

    pdfs = []
    for f in sorted(scenarios_dir.glob("*.pdf")):
        filename = f.name
        size_kb = f.stat().st_size // 1024

        # Parse product ID and state
        product_id = filename.split("-")[0] if "-" in filename else filename.replace(".pdf", "")
        state = "Unknown"
        for prefix, state_name in _STATE_PREFIXES.items():
            if product_id.startswith(prefix):
                state = state_name
                break

        # Parse issue date from filename (e.g. 20260309.030200)
        issue_date = ""
        date_match = re.search(r"-(\d{8})\.(\d{6})", filename)
        if date_match:
            try:
                dt = datetime.strptime(
                    f"{date_match.group(1)}{date_match.group(2)}",
                    "%Y%m%d%H%M%S",
                )
                issue_date = dt.strftime("%d %b %Y %H:%M")
            except ValueError:
                issue_date = date_match.group(1)

        pdfs.append({
            "filename": filename,
            "product_id": product_id,
            "state": state,
            "issue_date": issue_date,
            "size_kb": size_kb,
        })

    logger.info("Discovered %d flood scenario PDFs", len(pdfs))
    return pdfs


def register_flood_routes(server, scenarios_dir: Path):
    """Register Flask routes for serving flood scenario PDFs."""

    @server.route("/api/flood-scenarios")
    def list_flood_scenarios():
        pdfs = discover_flood_pdfs(scenarios_dir)
        return jsonify(pdfs)

    @server.route("/api/flood-scenarios/<filename>")
    def serve_flood_scenario(filename):
        # Validate filename to prevent path traversal
        safe_name = secure_filename(filename)
        if safe_name != filename:
            return jsonify({"error": "Invalid filename"}), 400

        file_path = scenarios_dir / safe_name
        if not file_path.exists():
            return jsonify({"error": "File not found"}), 404

        return send_from_directory(
            str(scenarios_dir),
            safe_name,
            mimetype="application/pdf",
        )
