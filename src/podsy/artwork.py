"""Album artwork handling for iPod.

This module handles extracting artwork from audio files and converting
them to the iPod's RGB565 format for storage in ArtworkDB.
"""

import io
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from PIL import Image  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Sequence

# iPod 5.5g artwork format specifications
# Format ID -> (width, height, pixel_format, correlation_id)
# The correlation_id links to the photo database format
ARTWORK_FORMATS = {
    1055: (56, 56, "rgb565", 1055),  # List view thumbnail
    1068: (140, 140, "rgb565", 1068),  # Now Playing small
    1027: (320, 320, "rgb565", 1027),  # Cover Flow / full screen
}

# Default formats to generate for each track
DEFAULT_FORMATS = [1055, 1068, 1027]


class ArtworkError(Exception):
    """Base exception for artwork errors."""


def extract_artwork(audio_path: Path) -> bytes | None:
    """Extract embedded artwork from an audio file.

    Args:
        audio_path: Path to the audio file

    Returns:
        Raw image data as bytes, or None if no artwork found
    """
    suffix = audio_path.suffix.lower()

    try:
        if suffix == ".mp3":
            return _extract_mp3_artwork(audio_path)
        elif suffix in (".m4a", ".m4p", ".mp4", ".aac"):
            return _extract_m4a_artwork(audio_path)
    except Exception:
        # If extraction fails, just return None
        pass

    return None


def _extract_mp3_artwork(audio_path: Path) -> bytes | None:
    """Extract artwork from MP3 file (APIC frame)."""
    try:
        tags = ID3(audio_path)
    except Exception:
        return None

    # Look for APIC frames (Attached Picture)
    for key in tags:
        if key.startswith("APIC"):
            apic = tags[key]
            return apic.data

    return None


def _extract_m4a_artwork(audio_path: Path) -> bytes | None:
    """Extract artwork from M4A/MP4 file (covr atom)."""
    try:
        mp4 = MP4(audio_path)
    except Exception:
        return None

    # Look for 'covr' (cover art) tag
    if mp4.tags and "covr" in mp4.tags:
        covers = mp4.tags["covr"]
        if covers:
            # Return the first cover
            return bytes(covers[0])

    return None


def convert_to_rgb565(image_data: bytes, width: int, height: int) -> bytes:
    """Convert image data to iPod RGB565 format.

    iPod uses RGB565 Little Endian format:
    - 5 bits red, 6 bits green, 5 bits blue
    - Stored as 16-bit little-endian values

    Args:
        image_data: Raw image data (JPEG, PNG, etc.)
        width: Target width
        height: Target height

    Returns:
        RGB565 formatted image data
    """
    # Load and resize image
    img = Image.open(io.BytesIO(image_data))

    # Convert to RGB if necessary (handles RGBA, P mode, etc.)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Resize with high quality resampling
    img = img.resize((width, height), Image.Resampling.LANCZOS)

    # Convert to RGB565
    output = bytearray(width * height * 2)

    pixels = img.load()
    idx = 0

    for y in range(height):
        for x in range(width):
            pixel = cast("Sequence[int]", pixels[x, y])  # type: ignore[index]
            r, g, b = pixel[0], pixel[1], pixel[2]

            # Convert 8-bit RGB to RGB565
            r5 = (r >> 3) & 0x1F  # 5 bits
            g6 = (g >> 2) & 0x3F  # 6 bits
            b5 = (b >> 3) & 0x1F  # 5 bits

            # Pack as RGB565 little-endian
            # Format: RRRRRGGGGGGBBBBB
            rgb565 = (r5 << 11) | (g6 << 5) | b5

            # Store as little-endian
            output[idx] = rgb565 & 0xFF
            output[idx + 1] = (rgb565 >> 8) & 0xFF
            idx += 2

    return bytes(output)


def convert_to_iyuv(image_data: bytes, width: int, height: int) -> bytes:
    """Convert image data to iPod IYUV format.

    Some iPod models use IYUV (YUV420 planar) format.
    This is Y plane, then U plane (quarter size), then V plane (quarter size).

    Args:
        image_data: Raw image data (JPEG, PNG, etc.)
        width: Target width
        height: Target height

    Returns:
        IYUV formatted image data
    """
    # Load and resize image
    img = Image.open(io.BytesIO(image_data))

    # Convert to RGB if necessary
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Resize with high quality resampling
    img = img.resize((width, height), Image.Resampling.LANCZOS)

    # Convert to YCbCr
    img_ycbcr = img.convert("YCbCr")

    # Extract planes
    y_plane = bytearray(width * height)
    u_plane = bytearray((width // 2) * (height // 2))
    v_plane = bytearray((width // 2) * (height // 2))

    pixels = img_ycbcr.load()

    # Y plane - full resolution
    idx = 0
    for row in range(height):
        for col in range(width):
            pixel = cast("Sequence[int]", pixels[col, row])  # type: ignore[index]
            y_plane[idx] = pixel[0]
            idx += 1

    # U and V planes - quarter resolution (2x2 averaging)
    idx = 0
    for row in range(0, height, 2):
        for col in range(0, width, 2):
            # Average 2x2 block
            cb_sum = 0
            cr_sum = 0
            for dy in range(2):
                for dx in range(2):
                    pixel = cast("Sequence[int]", pixels[col + dx, row + dy])  # type: ignore[index]
                    cb_sum += pixel[1]
                    cr_sum += pixel[2]

            u_plane[idx] = cb_sum // 4
            v_plane[idx] = cr_sum // 4
            idx += 1

    return bytes(y_plane) + bytes(u_plane) + bytes(v_plane)


def generate_artwork_formats(
    image_data: bytes,
    format_ids: list[int] | None = None,
) -> dict[int, bytes]:
    """Generate artwork in multiple iPod formats.

    Args:
        image_data: Raw image data from audio file
        format_ids: List of format IDs to generate (default: all)

    Returns:
        Dict mapping format_id to converted image data
    """
    if format_ids is None:
        format_ids = DEFAULT_FORMATS

    result = {}

    for fmt_id in format_ids:
        if fmt_id not in ARTWORK_FORMATS:
            continue

        width, height, pixel_format, _ = ARTWORK_FORMATS[fmt_id]

        if pixel_format == "rgb565":
            result[fmt_id] = convert_to_rgb565(image_data, width, height)
        elif pixel_format == "iyuv":
            result[fmt_id] = convert_to_iyuv(image_data, width, height)

    return result


def get_artwork_size(format_id: int) -> int:
    """Get the byte size of artwork for a given format.

    Args:
        format_id: The artwork format ID

    Returns:
        Size in bytes
    """
    if format_id not in ARTWORK_FORMATS:
        return 0

    width, height, pixel_format, _ = ARTWORK_FORMATS[format_id]

    if pixel_format == "rgb565":
        return width * height * 2
    elif pixel_format == "iyuv":
        return width * height + 2 * ((width // 2) * (height // 2))

    return 0
