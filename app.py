import json
import sqlite3
import subprocess
from contextlib import closing
from ipaddress import ip_address
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from flask import Flask, jsonify, request, url_for

from inspection import UnsupportedVideo, inspect_video

RULESET = "web-delivery-v1"
MAX_REQUEST_BYTES = 25 * 1024 * 1024
MAX_ASSET_ID = 2**63 - 1


def review_reasons(container, video_codec):
    reasons = []
    if container != "mp4":
        reasons.append("Delivery requires an MP4 container.")
    if video_codec != "h264":
        reasons.append("Delivery requires H.264 video.")
    return reasons


def create_app(database="intake.sqlite3", probe=inspect_video):
    app = Flask(__name__)
    app.config["MAX_UPLOAD_BYTES"] = MAX_REQUEST_BYTES

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                container TEXT NOT NULL,
                video_codec TEXT NOT NULL,
                ruleset TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('ready', 'needs_review')),
                reasons TEXT NOT NULL,
                metadata_source TEXT NOT NULL DEFAULT 'declared'
            )
        """)
        columns = connection.execute("PRAGMA table_info(assets)")
        if not any(column[1] == "metadata_source" for column in columns):
            connection.execute(
                "ALTER TABLE assets ADD COLUMN metadata_source TEXT NOT NULL DEFAULT 'declared'"
            )

    def save_asset(metadata, metadata_source):
        reasons = review_reasons(metadata["container"], metadata["video_codec"])
        status = "needs_review" if reasons else "ready"
        with closing(sqlite3.connect(database)) as connection, connection:
            cursor = connection.execute(
                """INSERT INTO assets (filename, container, video_codec, ruleset, status, reasons, metadata_source)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (metadata["filename"], metadata["container"], metadata["video_codec"],
                 RULESET, status, json.dumps(reasons), metadata_source),
            )
            asset_id = cursor.lastrowid

        response = jsonify(**metadata, id=asset_id, ruleset=RULESET, status=status,
                           reasons=reasons, metadata_source=metadata_source)
        response.status_code = 201
        response.headers["Location"] = url_for("get_asset", asset_id=asset_id)
        return response

    @app.post("/assets")
    def submit_asset():
        payload = request.get_json(silent=True)
        fields = ("filename", "container", "video_codec")
        if not isinstance(payload, dict):
            return jsonify(error="Expected a JSON object."), 400

        metadata = {}
        for field in fields:
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 255:
                return jsonify(error=f"{field} must be a nonempty string of up to 255 characters."), 400
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return jsonify(error=f"{field} must contain valid Unicode text."), 400
            metadata[field] = value.strip()

        for field in ("container", "video_codec"):
            metadata[field] = metadata[field].lower()

        return save_asset(metadata, "declared")

    @app.post("/assets/inspect")
    def submit_video():
        try:
            is_local = ip_address(request.remote_addr or "").is_loopback
        except ValueError:
            is_local = False
        if not is_local:
            return jsonify(error="Video uploads are only accepted over localhost."), 403

        request.max_content_length = app.config["MAX_UPLOAD_BYTES"]
        files = list(request.files.items(multi=True))
        if len(files) != 1 or files[0][0] != "file":
            return jsonify(error="Upload exactly one video in the file field."), 400
        upload = files[0][1]
        filename = PurePosixPath((upload.filename or "").replace("\\", "/")).name.strip()
        if not filename or len(filename) > 255:
            return jsonify(error="Provide a filename of up to 255 characters."), 400

        with TemporaryDirectory(prefix="media-intake-") as directory:
            path = Path(directory) / "video"
            upload.save(path)
            try:
                container, codec = probe(path)
            except subprocess.TimeoutExpired:
                return jsonify(error="Video inspection timed out."), 504
            except OSError:
                return jsonify(error="The video inspection tool is unavailable."), 503
            except (subprocess.CalledProcessError, UnsupportedVideo):
                return jsonify(error="Upload a readable MP4 or MOV with one video stream."), 422
        return save_asset(
            {"filename": filename, "container": container, "video_codec": codec},
            "inspected",
        )

    @app.errorhandler(413)
    def upload_too_large(_):
        return jsonify(error="Request exceeds the configured size limit."), 413

    @app.get("/assets/<int:asset_id>")
    def get_asset(asset_id):
        if asset_id > MAX_ASSET_ID:
            return jsonify(error="Asset not found."), 404
        with closing(sqlite3.connect(database)) as connection:
            connection.row_factory = sqlite3.Row
            asset = connection.execute(
                """SELECT id, filename, container, video_codec, ruleset, status, reasons, metadata_source
                   FROM assets WHERE id = ?""",
                (asset_id,),
            ).fetchone()

        if asset is None:
            return jsonify(error="Asset not found."), 404
        result = dict(asset)
        result["reasons"] = json.loads(result["reasons"])
        return jsonify(result)

    return app
