"""ArtworkDB parser and writer for iPod.

The ArtworkDB stores metadata about album artwork images that are
stored in .ithmb files. The structure follows the same mh** pattern
as iTunesDB:

- mhfd: File header
- mhsd: Section header (type 1 = image list, type 2 = album list)  
- mhli: List header for images
- mhii: Image item header (links to ithmb file locations)
- mhni: Child image info (specific format/size)
- mhod: Data object (various metadata)

For iPod 5.5g, artwork is stored in RGB565 format in .ithmb files.
"""

import struct
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from ..artwork import ARTWORK_FORMATS, get_artwork_size


@dataclass
class ArtworkImage:
    """Represents a single artwork image entry."""

    dbid: int  # Links to track dbid in iTunesDB
    image_data: dict[int, tuple[int, int]]  # format_id -> (ithmb_file_index, offset)
    source_size: int = 0  # Original image size
    rating: int = 0


@dataclass
class ArtworkDB:
    """Represents the ArtworkDB database."""

    images: list[ArtworkImage] = field(default_factory=list)
    next_ithmb_offset: dict[int, int] = field(default_factory=dict)  # format_id -> next offset

    def get_image_by_dbid(self, dbid: int) -> ArtworkImage | None:
        """Find artwork by track dbid."""
        for img in self.images:
            if img.dbid == dbid:
                return img
        return None


def parse_artworkdb(path: Path) -> ArtworkDB:
    """Parse an ArtworkDB file.

    Args:
        path: Path to ArtworkDB file

    Returns:
        Parsed ArtworkDB object
    """
    # For now, we just return an empty DB and rebuild it
    # Full parsing would be needed for incremental updates
    return ArtworkDB()


def save_artworkdb(db: ArtworkDB, artwork_dir: Path) -> None:
    """Save the ArtworkDB and .ithmb files.

    Args:
        db: ArtworkDB to save
        artwork_dir: Path to iPod_Control/Artwork directory
    """
    artwork_dir.mkdir(parents=True, exist_ok=True)

    # Build the database file
    db_data = _build_artworkdb(db)

    # Write ArtworkDB
    db_path = artwork_dir / "ArtworkDB"
    with open(db_path, "wb") as f:
        f.write(db_data)


def _build_artworkdb(db: ArtworkDB) -> bytes:
    """Build the ArtworkDB binary data."""
    output = BytesIO()

    # Build image list section (mhsd type 1)
    image_list_data = _build_image_list(db)

    # Build file header (mhfd)
    mhfd = _build_mhfd(len(db.images), image_list_data)

    output.write(mhfd)
    output.write(image_list_data)

    return output.getvalue()


def _build_mhfd(image_count: int, section_data: bytes) -> bytes:
    """Build the mhfd (file header)."""
    header_size = 132
    total_size = header_size + len(section_data)

    mhfd = BytesIO()
    mhfd.write(b"mhfd")  # Signature
    mhfd.write(struct.pack("<I", header_size))  # Header size
    mhfd.write(struct.pack("<I", total_size))  # Total size
    mhfd.write(struct.pack("<I", 2))  # Unknown (version?)
    mhfd.write(struct.pack("<I", 1))  # Number of sections
    mhfd.write(struct.pack("<I", 0))  # Unknown
    mhfd.write(struct.pack("<I", 0))  # Unknown
    mhfd.write(struct.pack("<I", 0))  # Unknown
    mhfd.write(struct.pack("<I", 2))  # Unknown (always 2)
    mhfd.write(struct.pack("<I", 0))  # Unknown
    mhfd.write(struct.pack("<I", 0))  # Unknown
    mhfd.write(struct.pack("<I", 0))  # Unknown
    mhfd.write(struct.pack("<I", 0))  # Unknown
    mhfd.write(struct.pack("<I", 0))  # Unknown

    # Padding to header size
    padding = header_size - mhfd.tell()
    if padding > 0:
        mhfd.write(b"\x00" * padding)

    return mhfd.getvalue()


def _build_image_list(db: ArtworkDB) -> bytes:
    """Build the image list section (mhsd type 1 + mhli + mhii items)."""
    # Build all mhii entries
    mhii_data = BytesIO()
    for img in db.images:
        mhii_data.write(_build_mhii(img))

    mhii_bytes = mhii_data.getvalue()

    # Build mhli (list header)
    mhli = _build_mhli(len(db.images), mhii_bytes)

    # Build mhsd (section header)
    mhsd = _build_mhsd(1, mhli)

    return mhsd


def _build_mhsd(section_type: int, content: bytes) -> bytes:
    """Build an mhsd (section header)."""
    header_size = 96
    total_size = header_size + len(content)

    mhsd = BytesIO()
    mhsd.write(b"mhsd")  # Signature
    mhsd.write(struct.pack("<I", header_size))  # Header size
    mhsd.write(struct.pack("<I", total_size))  # Total size
    mhsd.write(struct.pack("<I", section_type))  # Section type (1=images)
    mhsd.write(struct.pack("<I", 0))  # Unknown
    mhsd.write(struct.pack("<I", 0))  # Unknown
    mhsd.write(struct.pack("<I", 0))  # Unknown
    mhsd.write(struct.pack("<I", 0))  # Unknown

    # Padding to header size
    padding = header_size - mhsd.tell()
    if padding > 0:
        mhsd.write(b"\x00" * padding)

    mhsd.write(content)
    return mhsd.getvalue()


def _build_mhli(image_count: int, content: bytes) -> bytes:
    """Build an mhli (image list header)."""
    header_size = 92

    mhli = BytesIO()
    mhli.write(b"mhli")  # Signature
    mhli.write(struct.pack("<I", header_size))  # Header size
    mhli.write(struct.pack("<I", image_count))  # Number of images
    mhli.write(struct.pack("<I", 0))  # Unknown
    mhli.write(struct.pack("<I", 0))  # Unknown
    mhli.write(struct.pack("<I", 0))  # Unknown
    mhli.write(struct.pack("<I", 0))  # Unknown

    # Padding to header size
    padding = header_size - mhli.tell()
    if padding > 0:
        mhli.write(b"\x00" * padding)

    mhli.write(content)
    return mhli.getvalue()


def _build_mhii(img: ArtworkImage) -> bytes:
    """Build an mhii (image item header) with child mhni entries."""
    # Build mhni children for each format
    mhni_data = BytesIO()
    for format_id, (ithmb_idx, offset) in img.image_data.items():
        mhni_data.write(_build_mhni(format_id, ithmb_idx, offset))

    mhni_bytes = mhni_data.getvalue()
    child_count = len(img.image_data)

    header_size = 152
    total_size = header_size + len(mhni_bytes)

    mhii = BytesIO()
    mhii.write(b"mhii")  # Signature
    mhii.write(struct.pack("<I", header_size))  # Header size
    mhii.write(struct.pack("<I", total_size))  # Total size
    mhii.write(struct.pack("<I", child_count))  # Number of children
    mhii.write(struct.pack("<I", 0))  # Image ID (auto-assigned)
    mhii.write(struct.pack("<Q", img.dbid))  # dbid - links to track
    mhii.write(struct.pack("<I", img.source_size))  # Source image size
    mhii.write(struct.pack("<I", 0))  # Unknown
    mhii.write(struct.pack("<I", img.rating))  # Rating
    mhii.write(struct.pack("<I", 0))  # Unknown
    mhii.write(struct.pack("<I", 0))  # Unknown
    mhii.write(struct.pack("<I", 0))  # Original date
    mhii.write(struct.pack("<I", 0))  # Digitized date
    mhii.write(struct.pack("<I", 0))  # Unknown

    # Padding to header size
    padding = header_size - mhii.tell()
    if padding > 0:
        mhii.write(b"\x00" * padding)

    mhii.write(mhni_bytes)
    return mhii.getvalue()


def _build_mhni(format_id: int, ithmb_idx: int, offset: int) -> bytes:
    """Build an mhni (child image info) entry."""
    if format_id not in ARTWORK_FORMATS:
        return b""

    width, height, _, correlation_id = ARTWORK_FORMATS[format_id]
    image_size = get_artwork_size(format_id)

    header_size = 76

    # Build mhod for the ithmb file reference
    mhod = _build_ithmb_mhod(ithmb_idx)
    total_size = header_size + len(mhod)

    mhni = BytesIO()
    mhni.write(b"mhni")  # Signature
    mhni.write(struct.pack("<I", header_size))  # Header size
    mhni.write(struct.pack("<I", total_size))  # Total size
    mhni.write(struct.pack("<I", 1))  # Number of children (mhod)
    mhni.write(struct.pack("<I", correlation_id))  # Format/correlation ID
    mhni.write(struct.pack("<I", offset))  # Offset in ithmb file
    mhni.write(struct.pack("<I", image_size))  # Image data size
    mhni.write(struct.pack("<H", height))  # Vertical padding
    mhni.write(struct.pack("<H", width))  # Horizontal padding
    mhni.write(struct.pack("<H", height))  # Image height
    mhni.write(struct.pack("<H", width))  # Image width
    mhni.write(struct.pack("<I", 0))  # Unknown
    mhni.write(struct.pack("<I", 0))  # Unknown

    # Padding to header size
    padding = header_size - mhni.tell()
    if padding > 0:
        mhni.write(b"\x00" * padding)

    mhni.write(mhod)
    return mhni.getvalue()


def _build_ithmb_mhod(ithmb_idx: int) -> bytes:
    """Build an mhod for ithmb file reference."""
    # Filename like ":iPod_Control:Artwork:F1027_1.ithmb"
    filename = f":iPod_Control:Artwork:F{ithmb_idx}_1.ithmb"
    encoded = filename.encode("utf-16-le")

    header_size = 24
    total_size = header_size + len(encoded)

    mhod = BytesIO()
    mhod.write(b"mhod")  # Signature
    mhod.write(struct.pack("<I", header_size))  # Header size
    mhod.write(struct.pack("<I", total_size))  # Total size
    mhod.write(struct.pack("<I", 3))  # Type 3 = filename
    mhod.write(struct.pack("<I", 0))  # Unknown
    mhod.write(struct.pack("<I", len(encoded)))  # String length
    mhod.write(encoded)

    return mhod.getvalue()


def write_ithmb(
    artwork_dir: Path,
    format_id: int,
    image_data: bytes,
    offset: int,
) -> None:
    """Write image data to an ithmb file.

    Args:
        artwork_dir: Path to iPod_Control/Artwork directory
        format_id: The artwork format ID (used in filename)
        image_data: RGB565 formatted image data
        offset: Byte offset to write at
    """
    artwork_dir.mkdir(parents=True, exist_ok=True)
    ithmb_path = artwork_dir / f"F{format_id}_1.ithmb"

    # Open in r+b if exists, wb if new
    if ithmb_path.exists():
        with open(ithmb_path, "r+b") as f:
            f.seek(offset)
            f.write(image_data)
    else:
        # Create new file, may need padding if offset > 0
        with open(ithmb_path, "wb") as f:
            if offset > 0:
                f.write(b"\x00" * offset)
            f.write(image_data)


def add_artwork_to_db(
    db: ArtworkDB,
    artwork_dir: Path,
    dbid: int,
    artwork_formats: dict[int, bytes],
) -> ArtworkImage:
    """Add artwork for a track to the database.

    Args:
        db: ArtworkDB instance
        artwork_dir: Path to iPod_Control/Artwork directory
        dbid: Track's dbid for linking
        artwork_formats: Dict of format_id -> RGB565 image data

    Returns:
        The created ArtworkImage entry
    """
    # Check if artwork already exists for this dbid
    existing = db.get_image_by_dbid(dbid)
    if existing:
        return existing

    image_data: dict[int, tuple[int, int]] = {}
    total_size = 0

    for format_id, data in artwork_formats.items():
        # Get current offset for this format
        if format_id not in db.next_ithmb_offset:
            db.next_ithmb_offset[format_id] = 0

        offset = db.next_ithmb_offset[format_id]

        # Write to ithmb file
        write_ithmb(artwork_dir, format_id, data, offset)

        # Record location
        image_data[format_id] = (format_id, offset)
        total_size += len(data)

        # Update next offset
        db.next_ithmb_offset[format_id] = offset + len(data)

    # Create image entry
    img = ArtworkImage(
        dbid=dbid,
        image_data=image_data,
        source_size=total_size,
    )
    db.images.append(img)

    return img
