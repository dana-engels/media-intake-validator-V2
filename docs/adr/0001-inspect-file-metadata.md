# Inspect video metadata and record its source

The prototype originally accepted a caller's description of a video. For
uploads, we inspect the bytes with ffprobe and record an inspected metadata
source. We retain the declared metadata endpoint for clients that already
supply metadata and for comparisons during the demo.

We considered trusting the filename or accepting the caller's container and
codec alongside the upload. Both would let a renamed MOV appear to be an MP4.
The probe reports MP4 and MOV under one format family, so the adapter uses the
file's format brand to distinguish the supported containers and reads the
codec from the video stream. The policy stays separate from extraction. That
lets us test policy decisions without invoking the probe and verify the
adapter separately with generated videos.
