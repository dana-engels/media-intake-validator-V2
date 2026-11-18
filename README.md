# Media Intake Validator

A local backend prototype that inspects video files and checks them against
an example delivery policy. It saves each decision and the reasons for it in
SQLite so a media operator can look them up later.

## Run the demo

Use Python 3.10 or later and install FFmpeg with both `ffmpeg` and `ffprobe`
available on your terminal's PATH. Install Python dependencies from this
directory.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m flask --app app:create_app run --port 5056
```

In a second terminal, generate two short clips and submit them.

```sh
samples=$(mktemp -d)
ffmpeg -v error -f lavfi -i color=c=blue:s=160x96:r=24 -frames:v 12 \
  -c:v libx264 -pix_fmt yuv420p "$samples/ready.mp4"
ffmpeg -v error -f lavfi -i color=c=red:s=160x96:r=24 -frames:v 12 \
  -c:v prores_ks -pix_fmt yuv422p10le "$samples/review.mov"
curl -i -F "file=@$samples/ready.mp4" http://127.0.0.1:5056/assets/inspect
curl -i -F "file=@$samples/review.mov;filename=mislabeled.mp4" \
  http://127.0.0.1:5056/assets/inspect
```

Both calls return HTTP 201 because both save an intake decision. The first
returns `status: ready`. The second reports an MOV container and ProRes codec
from the file bytes, so it returns `status: needs_review` with two reasons.
Take either response's `Location` header and open that path with a GET request.
For example, the first record in a fresh database is at
`http://127.0.0.1:5056/assets/1`. Stop and restart Flask, then GET the same path
to see the original decision.

To try a failure, upload a plain-text file under a video filename. The API
returns HTTP 422 and creates no asset record.

## How it works

1. `POST /assets/inspect` accepts one uploaded file. The service uses a
   temporary path for inspection and stores the filename for display.
2. `ffprobe` reads the file metadata. The container describes how streams are
   packaged, while the codec describes how video in the stream is encoded.
   The local adapter recognizes a subset of MP4 brands and QuickTime MOV
   and checks that the file contains readable video packets.
3. The example `web-delivery-v1` policy checks for MP4 with H.264. A readable
   video that fails the policy is still a valid intake decision. Unreadable or
   unsupported files fail before the policy runs.
4. SQLite stores the observed metadata, its source, the rule version, the
   decision, and its reasons. `GET /assets/<id>` reads that stored result.
5. The original `POST /assets` endpoint still accepts declared metadata such
   as `{"filename":"clip.mp4","container":"mp4","video_codec":"h264"}`.
   Records identify their metadata source as `declared` or `inspected`.

The [architecture decision record](docs/adr/0001-inspect-file-metadata.md)
explains the choice to inspect bytes and retain the declared-metadata path.

## Prototype roadmap

- [x] Apply the example policy and persist decisions in SQLite.
- [x] Inspect real files, handle invalid uploads, and document a synthetic demo.
- [ ] Extend the policy to cover additional delivery requirements and sample formats.
- [ ] Evaluate job queues, duplicate submissions, and deployment isolation if
  the prototype grows beyond a local demonstration.

The upload endpoint accepts a subset of MP4 and MOV files with one video
stream. Requests are limited to 25 MiB and inspection to five seconds.
`ready` means the metadata satisfies this example policy. It is not a full
decode or integrity check. Run the demo locally with synthetic files.

## Verify

```sh
.venv/bin/python -m unittest -v
.venv/bin/python -m unittest -v probe_checks
.venv/bin/python -m pip install ruff
.venv/bin/ruff check .
```

The API unit tests can run without FFmpeg. The real-file tests generate
synthetic clips and exercise `ffprobe` through the upload endpoint.
