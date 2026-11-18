"""Read container and codec metadata from a locally staged video."""
import json
import subprocess

MP4_BRANDS = {"isom", "iso2", "iso3", "iso4", "iso5", "iso6", "mp41", "mp42", "avc1"}

class UnsupportedVideo(ValueError):
    """The probe could not identify a supported video format or codec."""


def inspect_video(path):
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-protocol_whitelist", "file",
            "-f", "mov", "-enable_drefs", "0", "-select_streams", "V",
            "-count_packets", "-show_entries", "format_tags=major_brand:stream=codec_name,nb_read_packets",
            "-of", "json", str(path),
        ],
        check=True, capture_output=True, text=True, timeout=5,
    )
    try:
        report = json.loads(completed.stdout)
        brand = report["format"]["tags"]["major_brand"].strip().lower()
        streams = report["streams"]
        if len(streams) != 1:
            raise UnsupportedVideo
        codec = streams[0]["codec_name"]
        packets = int(streams[0]["nb_read_packets"])
    except (ValueError, KeyError, TypeError, AttributeError):
        raise UnsupportedVideo from None
    if not codec or codec == "unknown" or packets < 1:
        raise UnsupportedVideo
    if brand in MP4_BRANDS:
        return "mp4", codec
    if brand == "qt":
        return "mov", codec
    raise UnsupportedVideo
