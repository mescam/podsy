"""ArtworkDB parser and writer for iPod.

The ArtworkDB stores metadata about album artwork images that are
stored in .ithmb files. The structure for iPod 5.5g (Video):

- mhfd: File header (132 bytes)
- mhsd type 1: Image list section
  - mhli: Image list header (92 bytes)
    - mhii: Image item (152 bytes) - one per artwork
      - mhod type 2: Container for thumbnail
        - mhni: Image name/reference (76 bytes)
          - mhod type 3: Filename string
- mhsd type 2: Album list section (mostly empty for music)
  - mhla: Album list header
- mhsd type 3: File list section
  - mhlf: File list header (92 bytes)
    - mhif: File info (124 bytes) - one per ithmb file

For iPod 5.5g, artwork is stored in RGB565 LE format in .ithmb files.
"""

import struct
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from ..artwork import ARTWORK_FORMATS, get_artwork_size


@dataclass
class ArtworkImage:
    """Represents a single artwork image entry."""

    id: int  # Unique ID for this artwork (starts at 100)
    dbid: int  # Links to track dbid in iTunesDB
    image_data: dict[int, tuple[int, int]]  # format_id -> (ithmb_file_index, offset)
    source_size: int = 0  # Original image size


@dataclass
class ArtworkDB:
    """Represents the ArtworkDB database."""

    images: list[ArtworkImage] = field(default_factory=list)
    next_ithmb_offset: dict[int, int] = field(default_factory=dict)  # format_id -> next offset
    next_image_id: int = 100  # Starting ID for mhii entries

    def get_image_by_dbid(self, dbid: int) -> ArtworkImage | None:
        """Find artwork by track dbid."""
        for img in self.images:
            if img.dbid == dbid:
                return img
        return None


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
    # Build sections
    image_list_section = _build_image_list_section(db)
    album_list_section = _build_album_list_section()
    file_list_section = _build_file_list_section(db)

    sections = image_list_section + album_list_section + file_list_section

    # Build file header (mhfd)
    mhfd = _build_mhfd(db, sections)

    return mhfd + sections


def _build_mhfd(db: ArtworkDB, sections: bytes) -> bytes:
    """Build the mhfd (file header).

    Based on libgpod's MhfdHeader structure:
    - header_id[4], header_len, total_len (12 bytes)
    - unknown1 (4 bytes)
    - unknown2 (4 bytes) - must be 2 for iTunes 4.9+
    - num_children (4 bytes)
    - unknown3 (4 bytes)
    - next_id (4 bytes)
    - unknown5 (8 bytes)
    - unknown6 (8 bytes)
    - unknown_flag1 (1 byte) - set to 2
    - unknown_flag2, unknown_flag3, unknown_flag4 (3 bytes)
    - unknown8-11 (16 bytes)
    - padding to 0x84 (132 bytes)
    """
    header_size = 0x84  # 132 bytes
    total_size = header_size + len(sections)

    mhfd = BytesIO()
    mhfd.write(b"mhfd")  # Signature
    mhfd.write(struct.pack("<I", header_size))  # Header size
    mhfd.write(struct.pack("<I", total_size))  # Total size
    mhfd.write(struct.pack("<I", 0))  # unknown1
    mhfd.write(struct.pack("<I", 2))  # unknown2 - MUST be 2 for iTunes 4.9+
    mhfd.write(struct.pack("<I", 3))  # num_children (3 sections)
    mhfd.write(struct.pack("<I", 0))  # unknown3
    mhfd.write(struct.pack("<I", db.next_image_id))  # next_id
    mhfd.write(struct.pack("<Q", 0))  # unknown5 (64-bit)
    mhfd.write(struct.pack("<Q", 0))  # unknown6 (64-bit)
    mhfd.write(struct.pack("<B", 2))  # unknown_flag1 - set to 2
    mhfd.write(struct.pack("<B", 0))  # unknown_flag2
    mhfd.write(struct.pack("<B", 0))  # unknown_flag3
    mhfd.write(struct.pack("<B", 0))  # unknown_flag4
    mhfd.write(struct.pack("<I", 0))  # unknown8
    mhfd.write(struct.pack("<I", 0))  # unknown9
    mhfd.write(struct.pack("<I", 0))  # unknown10
    mhfd.write(struct.pack("<I", 0))  # unknown11

    # Padding to header size
    padding = header_size - mhfd.tell()
    if padding > 0:
        mhfd.write(b"\x00" * padding)

    return mhfd.getvalue()


def _build_image_list_section(db: ArtworkDB) -> bytes:
    """Build the image list section (mhsd type 1)."""
    # Build mhli with all mhii entries
    mhli_content = BytesIO()
    for img in db.images:
        mhli_content.write(_build_mhii(img))

    mhli = _build_mhli(len(db.images), mhli_content.getvalue())
    return _build_mhsd(1, mhli)


def _build_album_list_section() -> bytes:
    """Build the album list section (mhsd type 2) - empty for music."""
    mhla = _build_mhla()
    return _build_mhsd(2, mhla)


def _build_file_list_section(db: ArtworkDB) -> bytes:
    """Build the file list section (mhsd type 3)."""
    # Get all unique format IDs used
    format_ids = set()
    for img in db.images:
        format_ids.update(img.image_data.keys())

    mhlf_content = BytesIO()
    for fmt_id in sorted(format_ids):
        mhlf_content.write(_build_mhif(fmt_id))

    mhlf = _build_mhlf(len(format_ids), mhlf_content.getvalue())
    return _build_mhsd(3, mhlf)


def _build_mhsd(section_type: int, content: bytes) -> bytes:
    """Build an mhsd (section header).

    Based on libgpod's ArtworkDB_MhsdHeader:
    - header_id[4], header_len, total_len (12 bytes)
    - index (16-bit) - section type
    - unknown014 (16-bit)
    - padding to 0x60 (96 bytes)
    """
    header_size = 0x60  # 96 bytes
    total_size = header_size + len(content)

    mhsd = BytesIO()
    mhsd.write(b"mhsd")  # Signature
    mhsd.write(struct.pack("<I", header_size))  # Header size
    mhsd.write(struct.pack("<I", total_size))  # Total size
    mhsd.write(struct.pack("<H", section_type))  # Section type (16-bit)
    mhsd.write(struct.pack("<H", 0))  # unknown014 (16-bit)

    # Padding to header size
    padding = header_size - mhsd.tell()
    if padding > 0:
        mhsd.write(b"\x00" * padding)

    mhsd.write(content)
    return mhsd.getvalue()


def _build_mhli(image_count: int, content: bytes) -> bytes:
    """Build an mhli (image list header)."""
    header_size = 0x5C  # 92 bytes

    mhli = BytesIO()
    mhli.write(b"mhli")  # Signature
    mhli.write(struct.pack("<I", header_size))  # Header size
    mhli.write(struct.pack("<I", image_count))  # Number of images

    # Padding to header size
    padding = header_size - mhli.tell()
    if padding > 0:
        mhli.write(b"\x00" * padding)

    mhli.write(content)
    return mhli.getvalue()


def _build_mhla() -> bytes:
    """Build an mhla (album list header) - empty."""
    header_size = 0x5C  # 92 bytes

    mhla = BytesIO()
    mhla.write(b"mhla")  # Signature
    mhla.write(struct.pack("<I", header_size))  # Header size
    mhla.write(struct.pack("<I", 0))  # Number of albums (empty)

    # Padding to header size
    padding = header_size - mhla.tell()
    if padding > 0:
        mhla.write(b"\x00" * padding)

    return mhla.getvalue()


def _build_mhlf(file_count: int, content: bytes) -> bytes:
    """Build an mhlf (file list header)."""
    header_size = 0x5C  # 92 bytes

    mhlf = BytesIO()
    mhlf.write(b"mhlf")  # Signature
    mhlf.write(struct.pack("<I", header_size))  # Header size
    mhlf.write(struct.pack("<I", file_count))  # Number of files

    # Padding to header size
    padding = header_size - mhlf.tell()
    if padding > 0:
        mhlf.write(b"\x00" * padding)

    mhlf.write(content)
    return mhlf.getvalue()


def _build_mhif(format_id: int) -> bytes:
    """Build an mhif (file info) entry."""
    header_size = 0x7C  # 124 bytes
    image_size = get_artwork_size(format_id)

    mhif = BytesIO()
    mhif.write(b"mhif")  # Signature
    mhif.write(struct.pack("<I", header_size))  # Header size
    mhif.write(struct.pack("<I", header_size))  # Total size (no children)
    mhif.write(struct.pack("<I", 0))  # Unknown
    mhif.write(struct.pack("<I", format_id))  # Correlation ID
    mhif.write(struct.pack("<I", image_size))  # Image size in bytes

    # Padding to header size
    padding = header_size - mhif.tell()
    if padding > 0:
        mhif.write(b"\x00" * padding)

    return mhif.getvalue()


def _build_mhii(img: ArtworkImage) -> bytes:
    """Build an mhii (image item header) with child mhod/mhni entries.

    Based on libgpod's MhiiHeader structure:
    - header_id[4], header_len, total_len, num_children (16 bytes)
    - image_id (4 bytes)
    - song_id (8 bytes) - this is the dbid linking to track
    - unknown4 (4 bytes)
    - rating (4 bytes)
    - unknown6 (4 bytes)
    - orig_date (4 bytes)
    - digitized_date (4 bytes)
    - orig_img_size (4 bytes)
    - padding to 0x98 (152 bytes)
    """
    # Build mhod type 2 containers with mhni children for each format
    children_data = BytesIO()
    for format_id, (_, offset) in img.image_data.items():
        children_data.write(_build_mhod_type2(format_id, offset))

    children_bytes = children_data.getvalue()
    child_count = len(img.image_data)

    header_size = 0x98  # 152 bytes
    total_size = header_size + len(children_bytes)

    mhii = BytesIO()
    mhii.write(b"mhii")  # Signature
    mhii.write(struct.pack("<I", header_size))  # Header size
    mhii.write(struct.pack("<I", total_size))  # Total size
    mhii.write(struct.pack("<I", child_count))  # Number of children
    mhii.write(struct.pack("<I", img.id))  # Image ID
    mhii.write(struct.pack("<Q", img.dbid))  # song_id (dbid) - links to track
    mhii.write(struct.pack("<I", 0))  # unknown4
    mhii.write(struct.pack("<I", 0))  # rating
    mhii.write(struct.pack("<I", 0))  # unknown6
    mhii.write(struct.pack("<I", 0))  # orig_date
    mhii.write(struct.pack("<I", 0))  # digitized_date
    mhii.write(struct.pack("<I", img.source_size))  # orig_img_size

    # Padding to header size
    padding = header_size - mhii.tell()
    if padding > 0:
        mhii.write(b"\x00" * padding)

    mhii.write(children_bytes)
    return mhii.getvalue()


def _build_mhod_type2(format_id: int, offset: int) -> bytes:
    """Build an mhod type 2 (container) with mhni child."""
    # Build mhni first
    mhni = _build_mhni(format_id, offset)

    header_size = 0x18  # 24 bytes
    total_size = header_size + len(mhni)

    mhod = BytesIO()
    mhod.write(b"mhod")  # Signature
    mhod.write(struct.pack("<I", header_size))  # Header size
    mhod.write(struct.pack("<I", total_size))  # Total size
    mhod.write(struct.pack("<H", 2))  # Type 2 = container
    mhod.write(struct.pack("<H", 0))  # Unknown
    mhod.write(struct.pack("<I", 0))  # Unknown

    mhod.write(mhni)
    return mhod.getvalue()


def _build_mhni(format_id: int, offset: int) -> bytes:
    """Build an mhni (image name/reference) entry."""
    if format_id not in ARTWORK_FORMATS:
        return b""

    width, height, image_size = ARTWORK_FORMATS[format_id]

    # Build mhod type 3 (filename)
    mhod_filename = _build_mhod_type3(format_id)

    header_size = 0x4C  # 76 bytes
    total_size = header_size + len(mhod_filename)

    mhni = BytesIO()
    mhni.write(b"mhni")  # Signature
    mhni.write(struct.pack("<I", header_size))  # Header size
    mhni.write(struct.pack("<I", total_size))  # Total size
    mhni.write(struct.pack("<I", 1))  # Number of children (mhod)
    mhni.write(struct.pack("<I", format_id))  # Correlation ID
    mhni.write(struct.pack("<I", offset))  # Offset in ithmb file
    mhni.write(struct.pack("<I", image_size))  # Image data size
    mhni.write(struct.pack("<H", height))  # Vertical padding (= height)
    mhni.write(struct.pack("<H", width))  # Horizontal padding (= width)
    mhni.write(struct.pack("<H", height))  # Image height
    mhni.write(struct.pack("<H", width))  # Image width
    mhni.write(struct.pack("<I", 0))  # Unknown
    mhni.write(struct.pack("<I", 0))  # Unknown

    # Padding to header size
    padding = header_size - mhni.tell()
    if padding > 0:
        mhni.write(b"\x00" * padding)

    mhni.write(mhod_filename)
    return mhni.getvalue()


def _build_mhod_type3(format_id: int) -> bytes:
    """Build an mhod type 3 (filename string).

    Based on libgpod's ArtworkDB_MhodHeaderString structure:
    - header_id[4], header_len, total_len (12 bytes)
    - type (16-bit), unknown13 (8-bit), padding_len (8-bit) (4 bytes)
    - unknown1, unknown2 (8 bytes) - not used in type 3
    - string_len (4 bytes)
    - encoding (8-bit), unknown5 (8-bit), unknown6 (16-bit), unknown4 (32-bit) (8 bytes)
    - string data
    Total header: 36 bytes before string
    """
    # Filename like ":iPod_Control:Artwork:F1024_1.ithmb"
    filename = f":iPod_Control:Artwork:F{format_id}_1.ithmb"
    encoded = filename.encode("utf-16-le")

    # Calculate padding to align to 4 bytes
    string_with_header = 36 + len(encoded)
    padding = (4 - (string_with_header % 4)) % 4

    header_size = 0x18  # 24 bytes (base mhod header size)
    total_size = 36 + len(encoded) + padding

    mhod = BytesIO()
    mhod.write(b"mhod")  # Signature
    mhod.write(struct.pack("<I", header_size))  # Header size (just base mhod header)
    mhod.write(struct.pack("<I", total_size))  # Total size
    mhod.write(struct.pack("<H", 3))  # Type 3 = filename string
    mhod.write(struct.pack("<B", 0))  # unknown13
    mhod.write(struct.pack("<B", padding))  # padding_len
    mhod.write(struct.pack("<I", 0))  # unknown1 - not used for type 3
    mhod.write(struct.pack("<I", 0))  # unknown2 - not used for type 3
    mhod.write(struct.pack("<I", len(encoded)))  # String length in bytes
    mhod.write(struct.pack("<B", 2))  # encoding: 2 = UTF-16-LE
    mhod.write(struct.pack("<B", 0))  # unknown5
    mhod.write(struct.pack("<H", 0))  # unknown6
    mhod.write(struct.pack("<I", 0))  # unknown4
    mhod.write(encoded)  # String data
    if padding > 0:
        mhod.write(b"\x00" * padding)

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

        # Record location (format_id is used as ithmb file index)
        image_data[format_id] = (format_id, offset)
        total_size += len(data)

        # Update next offset
        db.next_ithmb_offset[format_id] = offset + len(data)

    # Create image entry with unique ID
    img = ArtworkImage(
        id=db.next_image_id,
        dbid=dbid,
        image_data=image_data,
        source_size=total_size,
    )
    db.images.append(img)
    db.next_image_id += 1

    return img
