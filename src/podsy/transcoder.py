"""FLAC to AAC transcoding via ffmpeg + fdkaac pipeline.

Decodes FLAC with ffmpeg (resampling to 44100Hz stereo), encodes to AAC
with libfdk-aac via fdkaac (VBR mode 5, ~256kbps). This avoids the
FFmpeg native AAC encoder which produces audible crackling.
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final

__all__: Final = [
    "TranscodingError",
    "find_ffmpeg",
    "find_fdkaac",
    "check_transcoding_available",
    "is_flac",
    "transcode_flac_to_aac",
]

logger = logging.getLogger(__name__)


class TranscodingError(Exception):
    """Raised when transcoding fails."""


def find_ffmpeg() -> str | None:
    """Locate ffmpeg in PATH."""
    return shutil.which("ffmpeg")


def find_fdkaac() -> str | None:
    """Locate fdkaac in PATH."""
    return shutil.which("fdkaac")


def check_transcoding_available() -> bool:
    """Check if both ffmpeg and fdkaac are available."""
    return find_ffmpeg() is not None and find_fdkaac() is not None


def is_flac(path: Path) -> bool:
    """Check if a file is a FLAC audio file based on extension."""
    return path.suffix.lower() == ".flac"


def transcode_flac_to_aac(source: Path, output_dir: Path | None = None) -> Path:
    """Transcode FLAC to iPod-compatible M4A via ffmpeg + fdkaac.

    Pipeline: ffmpeg decodes FLAC to 44100Hz stereo WAV → pipes to fdkaac
    which encodes to AAC-LC VBR ~256kbps.

    Args:
        source: Path to the source FLAC file.
        output_dir: Directory for output. If None, uses a temp file (caller
            must clean up).

    Returns:
        Path to the transcoded M4A file.

    Raises:
        TranscodingError: If dependencies are missing or transcoding fails.
    """
    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path is None:
        raise TranscodingError("ffmpeg not found in PATH")

    fdkaac_path = find_fdkaac()
    if fdkaac_path is None:
        raise TranscodingError("fdkaac not found in PATH")

    if not source.exists():
        raise TranscodingError(f"Source file does not exist: {source}")

    if not is_flac(source):
        raise TranscodingError(f"Not a FLAC file: {source}")

    if output_dir is None:
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
            output_path = Path(tmp.name)
        is_temporary = True
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{source.stem}.m4a"
        is_temporary = False

    logger.info("Transcoding %s -> %s", source, output_path)

    # Step 1: ffmpeg decodes FLAC → 44100Hz stereo WAV piped to stdout
    # Step 2: fdkaac reads WAV from stdin → AAC-LC VBR 5 (~256kbps) M4A
    ffmpeg_cmd = [
        ffmpeg_path,
        "-i", str(source),
        "-f", "wav",
        "-ar", "44100",
        "-ac", "2",
        "-nostdin",
        "pipe:1",
    ]

    fdkaac_cmd = [
        fdkaac_path,
        "-m", "5",       # VBR bitrate mode 5 (~256kbps, highest quality for AAC LC)
        "-w", "20000",   # Bandwidth 20kHz
        "-o", str(output_path),
        "-",
    ]

    try:
        ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as e:
        if is_temporary and output_path.exists():
            output_path.unlink()
        raise TranscodingError(f"Failed to start ffmpeg: {e}") from e

    try:
        fdkaac_proc = subprocess.Popen(
            fdkaac_cmd,
            stdin=ffmpeg_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as e:
        ffmpeg_proc.kill()
        ffmpeg_proc.wait()
        if is_temporary and output_path.exists():
            output_path.unlink()
        raise TranscodingError(f"Failed to start fdkaac: {e}") from e

    # Allow ffmpeg to receive SIGPIPE if fdkaac exits early
    if ffmpeg_proc.stdout:
        ffmpeg_proc.stdout.close()

    try:
        _, fdkaac_err = fdkaac_proc.communicate(timeout=300)
    except subprocess.TimeoutExpired as e:
        ffmpeg_proc.kill()
        fdkaac_proc.kill()
        ffmpeg_proc.wait()
        fdkaac_proc.wait()
        if is_temporary and output_path.exists():
            output_path.unlink()
        raise TranscodingError(f"Transcoding timed out: {source}") from e

    # Collect ffmpeg stderr before wait() reaps the process
    ffmpeg_err = b""
    if ffmpeg_proc.stderr:
        ffmpeg_err = ffmpeg_proc.stderr.read()
    ffmpeg_proc.wait(timeout=10)

    if ffmpeg_proc.returncode != 0:
        if is_temporary and output_path.exists():
            output_path.unlink()
        raise TranscodingError(
            f"ffmpeg failed (exit {ffmpeg_proc.returncode}): "
            f"{ffmpeg_err.decode(errors='replace')}"
        )

    if fdkaac_proc.returncode != 0:
        if is_temporary and output_path.exists():
            output_path.unlink()
        raise TranscodingError(
            f"fdkaac failed (exit {fdkaac_proc.returncode}): "
            f"{fdkaac_err.decode(errors='replace')}"
        )

    if not output_path.exists():
        raise TranscodingError(f"Output file not created: {output_path}")

    logger.info("Transcoding completed: %s", output_path)
    return output_path
