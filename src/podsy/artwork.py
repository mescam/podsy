"""Album artwork handling for iPod.

This module handles extracting artwork from audio files and converting
them to the iPod's RGB565 format for storage in ArtworkDB.

iPod 5.5g (Video) uses RGB565 Little Endian format with specific
correlation IDs and dimensions.
"""

import io
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from PIL import Image  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Sequence

# iPod 5.5g (Video) artwork format specifications
# Format ID (correlation_id) -> (width, height, image_size)
# These are the correct values for iPod Video 5G/5.5G
ARTWORK_FORMATS: dict[int, tuple[int, int, int]] = {
    1024: (320, 240, 153600),  # Full screen / Now Playing (320x240x2)
    1055: (200, 200, 80000),   # Large thumbnail (200x200x2) - used in Cover Flow
    1056: (100, 100, 20000),   # Small thumbnail (100x100x2) - used in lists
}

# Default formats to generate for each track
DEFAULT_FORMATS = [1024, 1055, 1056]


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


def convert_to_rgb565_le(image_data: bytes, width: int, height: int) -> bytes:
    """Convert image data to iPod RGB565 Little Endian format.

    iPod 5.5g uses RGB565 Little Endian (byte-swapped) format:
    - 5 bits red (bits 15-11), 6 bits green (bits 10-5), 5 bits blue (bits 4-0)
    - Stored as 16-bit little-endian values

    Args:
        image_data: Raw image data (JPEG, PNG, etc.)
        width: Target width
        height: Target height

    Returns:
        RGB565 LE formatted image data
    """
    # Load and resize image
    img = Image.open(io.BytesIO(image_data))

    # Convert to RGB if necessary (handles RGBA, P mode, etc.)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Resize with high quality resampling, maintaining aspect ratio
    # and center-cropping to fill the target dimensions
    img = _resize_and_crop(img, width, height)

    # Convert to RGB565 Little Endian
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

            # Pack as RGB565: RRRRRGGGGGGBBBBB
            rgb565 = (r5 << 11) | (g6 << 5) | b5

            # Store as little-endian (low byte first)
            output[idx] = rgb565 & 0xFF
            output[idx + 1] = (rgb565 >> 8) & 0xFF
            idx += 2

    return bytes(output)


def _resize_and_crop(img: Image.Image, width: int, height: int) -> Image.Image:
    """Resize image to fill target dimensions, cropping if necessary.

    This maintains aspect ratio and center-crops to fill the target.

    Args:
        img: PIL Image
        width: Target width
        height: Target height

    Returns:
        Resized and cropped image
    """
    src_width, src_height = img.size
    src_ratio = src_width / src_height
    dst_ratio = width / height

    if src_ratio > dst_ratio:
        # Source is wider - resize by height and crop width
        new_height = height
        new_width = int(src_width * height / src_height)
    else:
        # Source is taller - resize by width and crop height
        new_width = width
        new_height = int(src_height * width / src_width)

    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Center crop
    left = (new_width - width) // 2
    top = (new_height - height) // 2
    right = left + width
    bottom = top + height

    return img.crop((left, top, right, bottom))


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

        width, height, _ = ARTWORK_FORMATS[fmt_id]
        result[fmt_id] = convert_to_rgb565_le(image_data, width, height)

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

    _, _, size = ARTWORK_FORMATS[format_id]
    return size
