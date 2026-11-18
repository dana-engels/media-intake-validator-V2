"""Run the upload API with real FFmpeg tools and generated media."""
import shutil
import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from app import create_app


class RealProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for command in ("ffmpeg", "ffprobe"):
            if not shutil.which(command):
                raise RuntimeError(f"Install {command} and add it to PATH before running probe_checks.")
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.fixtures = Path(directory.name)
        for name, color, codec in (
            ("ready.mp4", "blue", "libx264"),
            ("review.mov", "red", "prores_ks"),
        ):
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                 "-i", f"color=c={color}:s=160x96:r=24", "-frames:v", "12",
                 "-c:v", codec, "-pix_fmt", "yuv420p" if codec == "libx264" else "yuv422p10le",
                 "-movflags", "+faststart",
                 str(cls.fixtures / name)],
                check=True, timeout=20,
            )

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "intake.sqlite3"
        self.client = create_app(self.database).test_client()

    def upload(self, filename, reported_name):
        with (self.fixtures / filename).open("rb") as video:
            return self.client.post("/assets/inspect", data={"file": (video, reported_name)})

    def test_real_files_are_classified_and_decisions_survive_restart(self):
        ready = self.upload("ready.mp4", "ready.mp4")
        self.assertEqual(ready.status_code, 201)
        self.assertEqual(ready.json["status"], "ready")
        self.assertEqual(ready.json["metadata_source"], "inspected")

        review = self.upload("review.mov", "mislabeled.mp4")
        self.assertEqual(review.status_code, 201)
        self.assertEqual(review.json["status"], "needs_review")
        self.assertEqual(review.json["container"], "mov")
        self.assertEqual(review.json["video_codec"], "prores")
        self.assertEqual(len(review.json["reasons"]), 2)

        restarted = create_app(self.database).test_client()
        for record in (ready, review):
            self.assertEqual(restarted.get(record.headers["Location"]).json, record.json)

    def test_plain_text_with_video_extension_is_rejected(self):
        (self.fixtures / "bad.mp4").write_text("This is plain text.", encoding="utf-8")
        response = self.upload("bad.mp4", "bad.mp4")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/assets/1").status_code, 404)

    def test_video_header_without_packet_data_is_rejected(self):
        data = (self.fixtures / "ready.mp4").read_bytes()
        empty_media = data[:data.index(b"mdat") - 4]
        response = self.client.post("/assets/inspect", data={"file": (BytesIO(empty_media), "truncated.mp4")})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/assets/1").status_code, 404)

    def test_unsupported_brand_is_rejected_even_with_readable_video_packets(self):
        data = bytearray((self.fixtures / "ready.mp4").read_bytes())
        self.assertEqual(data[4:8], b"ftyp")
        data[8:12] = b"zzzz"
        response = self.client.post("/assets/inspect", data={"file": (BytesIO(data), "unsupported.mp4")})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/assets/1").status_code, 404)


if __name__ == "__main__":
    unittest.main()
