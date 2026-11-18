import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path

from app import create_app


class IntakeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "test.sqlite3"
        self.client = create_app(self.database).test_client()

    def test_ready_asset_survives_restart(self):
        result = self.client.post("/assets", json={
            "filename": "trailer.mp4", "container": " MP4 ", "video_codec": "H264",
        })
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json["status"], "ready")
        self.assertEqual(result.json["ruleset"], "web-delivery-v1")
        self.assertEqual(result.json["reasons"], [])

        restarted = create_app(self.database).test_client()
        fetched = restarted.get(result.headers["Location"])
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json, result.json)
        self.assertEqual(fetched.json["metadata_source"], "declared")

    def test_valid_metadata_can_require_review(self):
        result = self.client.post("/assets", json={
            "filename": "trailer.mov", "container": "mov", "video_codec": "prores",
        })
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json["status"], "needs_review")
        self.assertEqual(len(result.json["reasons"]), 2)

    def test_uploaded_file_is_inspected_and_saved(self):
        client = create_app(self.database, probe=lambda _: ("mp4", "h264")).test_client()
        recorded = client.post("/assets/inspect", data={"file": (BytesIO(b"example"), "trailer.mp4")})
        self.assertEqual(recorded.status_code, 201)
        self.assertEqual(recorded.json["metadata_source"], "inspected")
        self.assertEqual(recorded.json["status"], "ready")
        restarted = create_app(self.database).test_client()
        self.assertEqual(restarted.get(recorded.headers["Location"]).json, recorded.json)

    def test_old_database_keeps_previous_decision_and_identifies_declared_source(self):
        legacy = Path(self.database).with_name("legacy.sqlite3")
        with closing(sqlite3.connect(legacy)) as connection, connection:
            connection.execute("""
                CREATE TABLE assets (
                    id INTEGER PRIMARY KEY, filename TEXT, container TEXT, video_codec TEXT,
                    ruleset TEXT, status TEXT, reasons TEXT
                )
            """)
            connection.execute("""
                INSERT INTO assets VALUES (
                    41, 'clip.mov', 'mov', 'prores', 'older-policy',
                    'ready', '[]'
                )
            """)
        fetched = create_app(legacy).test_client().get("/assets/41")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json["ruleset"], "older-policy")
        self.assertEqual(fetched.json["status"], "ready")
        self.assertEqual(fetched.json["metadata_source"], "declared")

    def test_inspection_failures_create_no_records_and_remove_temporary_files(self):
        for problem, expected in (
            (subprocess.CalledProcessError(1, "ffprobe"), 422),
            (FileNotFoundError("ffprobe"), 503),
            (subprocess.TimeoutExpired("ffprobe", 5), 504),
        ):
            with self.subTest(status=expected):
                observed_paths = []

                def failing_probe(path, observed_paths=observed_paths, problem=problem):
                    observed_paths.append(path)
                    self.assertEqual(path.read_bytes(), b"example")
                    raise problem

                failing = create_app(self.database, probe=failing_probe).test_client()
                response = failing.post("/assets/inspect", data={"file": (BytesIO(b"example"), "clip.mp4")})
                self.assertEqual(response.status_code, expected)
                self.assertIn("error", response.json)
                self.assertFalse(observed_paths[0].exists())
                self.assertEqual(failing.get("/assets/1").status_code, 404)

    def test_missing_and_oversized_uploads_are_rejected(self):
        app = create_app(self.database)
        app.config["MAX_UPLOAD_BYTES"] = 1024
        client = app.test_client()
        self.assertEqual(client.post("/assets/inspect", data={}).status_code, 400)
        response = client.post("/assets/inspect", data={"file": (BytesIO(b"x" * 1025), "clip.mp4")})
        self.assertEqual(response.status_code, 413)
        self.assertIn("error", response.json)
        self.assertEqual(client.get("/assets/1").status_code, 404)

    def test_file_inspection_is_limited_to_loopback(self):
        app = create_app(self.database, probe=lambda _: ("mp4", "h264"))
        remote = app.test_client()
        response = remote.post("/assets/inspect", data={"file": (BytesIO(b"example"), "clip.mp4")},
                               environ_overrides={"REMOTE_ADDR": "192.0.2.20"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(remote.get("/assets/1").status_code, 404)

    def test_invalid_text_and_out_of_range_id_return_client_errors(self):
        response = self.client.post("/assets", json={
            "filename": "\ud800", "container": "mp4", "video_codec": "h264",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/assets/1").status_code, 404)
        self.assertEqual(self.client.get("/assets/9223372036854775808").status_code, 404)

    def test_malformed_json_creates_no_asset(self):
        result = self.client.post("/assets", data="{", content_type="application/json")
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.get("/assets/1").status_code, 404)

    def test_blank_required_field_creates_no_asset(self):
        result = self.client.post("/assets", json={
            "filename": "trailer.mp4", "container": "mp4", "video_codec": " ",
        })
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.get("/assets/1").status_code, 404)


if __name__ == "__main__":
    unittest.main()
