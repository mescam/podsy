"""iTunesDB parser and serializer.

This module provides functions to load and save iTunesDB files,
converting between the binary format and Python data models.
"""

import random
import struct
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from .atoms import (
    MAC_EPOCH_OFFSET,
    MHBD_HEADER_SIZE,
    MHIP_HEADER_SIZE,
    MHIT_HEADER_SIZE_V14,
    MHLP_HEADER_SIZE,
    MHLT_HEADER_SIZE,
    MHOD_HEADER_SIZE,
    MHSD_HEADER_SIZE,
    MHYP_HEADER_SIZE,
    decode_path,
    decode_string,
    encode_path,
    encode_string,
)
from .models import (
    Database,
    FileType,
    MediaType,
    MhodType,
    Playlist,
    SortOrder,
    Track,
)


class ITunesDBError(Exception):
    """Base exception for iTunesDB parsing errors."""


class InvalidDatabaseError(ITunesDBError):
    """Raised when the database format is invalid."""


# =============================================================================
# Timestamp conversion
# =============================================================================


def mac_to_datetime(timestamp: int) -> datetime:
    """Convert Mac HFS+ timestamp to Python datetime."""
    if timestamp == 0:
        return datetime(1904, 1, 1)
    unix_ts = timestamp - MAC_EPOCH_OFFSET
    return datetime.fromtimestamp(unix_ts)


def datetime_to_mac(dt: datetime) -> int:
    """Convert Python datetime to Mac HFS+ timestamp."""
    unix_ts = int(dt.timestamp())
    return unix_ts + MAC_EPOCH_OFFSET


# =============================================================================
# Binary reading helpers
# =============================================================================


def read_uint32(f: BinaryIO) -> int:
    """Read a little-endian 32-bit unsigned integer."""
    data = f.read(4)
    if len(data) < 4:
        raise InvalidDatabaseError("Unexpected end of file")
    return struct.unpack("<I", data)[0]


def read_uint64(f: BinaryIO) -> int:
    """Read a little-endian 64-bit unsigned integer."""
    data = f.read(8)
    if len(data) < 8:
        raise InvalidDatabaseError("Unexpected end of file")
    return struct.unpack("<Q", data)[0]


def read_int32(f: BinaryIO) -> int:
    """Read a little-endian 32-bit signed integer."""
    data = f.read(4)
    if len(data) < 4:
        raise InvalidDatabaseError("Unexpected end of file")
    return struct.unpack("<i", data)[0]


def read_bytes(f: BinaryIO, n: int) -> bytes:
    """Read n bytes."""
    data = f.read(n)
    if len(data) < n:
        raise InvalidDatabaseError("Unexpected end of file")
    return data


# =============================================================================
# MHOD parsing
# =============================================================================


def parse_mhod(data: bytes) -> tuple[int, str | int | bytes]:
    """Parse an MHOD atom and return (type, value).

    Returns:
        Tuple of (mhod_type, value) where value is:
        - str for string types (title, artist, etc.)
        - int for position type (100)
        - bytes for unknown types
    """
    if len(data) < MHOD_HEADER_SIZE:
        raise InvalidDatabaseError("MHOD too short")

    if data[:4] != b"mhod":
        raise InvalidDatabaseError(f"Invalid MHOD identifier: {data[:4]!r}")

    header_length = struct.unpack("<I", data[4:8])[0]
    total_length = struct.unpack("<I", data[8:12])[0]
    mhod_type = struct.unpack("<I", data[12:16])[0]

    # String types (1-14, 18-31, excluding URLs)
    string_types = set(range(1, 15)) | set(range(18, 32))
    url_types = {15, 16}

    if mhod_type in string_types:
        if len(data) < 40:
            raise InvalidDatabaseError("String MHOD too short")
        string_length = struct.unpack("<I", data[28:32])[0]
        string_data = data[40 : 40 + string_length]

        # Type 2 (location) always uses colon path format
        if mhod_type == MhodType.LOCATION:
            return mhod_type, decode_path(string_data)
        return mhod_type, decode_string(string_data)

    elif mhod_type in url_types:
        # URLs are UTF-8
        url_data = data[header_length:total_length]
        return mhod_type, url_data.decode("utf-8", errors="replace")

    elif mhod_type == MhodType.PLAYLIST_COLUMN:
        # Position in playlist
        if len(data) >= 28:
            position = struct.unpack("<I", data[24:28])[0]
            return mhod_type, position
        return mhod_type, 0

    else:
        # Unknown type - return raw data
        return mhod_type, data[header_length:total_length]


# =============================================================================
# Track parsing
# =============================================================================


def parse_mhit(data: bytes) -> Track:
    """Parse an MHIT atom and its child MHODs into a Track."""
    if len(data) < 16:
        raise InvalidDatabaseError("MHIT too short")

    if data[:4] != b"mhit":
        raise InvalidDatabaseError(f"Invalid MHIT identifier: {data[:4]!r}")

    header_length = struct.unpack("<I", data[4:8])[0]
    total_length = struct.unpack("<I", data[8:12])[0]
    num_mhods = struct.unpack("<I", data[12:16])[0]
    unique_id = struct.unpack("<I", data[16:20])[0]

    # Parse MHIT header fields
    filetype_bytes = data[24:28]
    rating = data[31] if len(data) > 31 else 0
    last_modified = struct.unpack("<I", data[32:36])[0] if len(data) > 35 else 0
    size = struct.unpack("<I", data[36:40])[0] if len(data) > 39 else 0
    length = struct.unpack("<I", data[40:44])[0] if len(data) > 43 else 0
    track_number = struct.unpack("<I", data[44:48])[0] if len(data) > 47 else 0
    total_tracks = struct.unpack("<I", data[48:52])[0] if len(data) > 51 else 0
    year = struct.unpack("<I", data[52:56])[0] if len(data) > 55 else 0
    bitrate = struct.unpack("<I", data[56:60])[0] if len(data) > 59 else 0
    sample_rate_raw = struct.unpack("<I", data[60:64])[0] if len(data) > 63 else 0
    sample_rate = sample_rate_raw >> 16 if sample_rate_raw else 44100

    play_count = struct.unpack("<I", data[80:84])[0] if len(data) > 83 else 0
    last_played = struct.unpack("<I", data[88:92])[0] if len(data) > 91 else 0
    disc_number = struct.unpack("<I", data[92:96])[0] if len(data) > 95 else 1
    total_discs = struct.unpack("<I", data[96:100])[0] if len(data) > 99 else 1
    date_added = struct.unpack("<I", data[104:108])[0] if len(data) > 107 else 0
    dbid = struct.unpack("<Q", data[112:120])[0] if len(data) > 119 else 0
    compilation = bool(data[30]) if len(data) > 30 else False

    skip_count = struct.unpack("<I", data[156:160])[0] if len(data) > 159 else 0
    media_type_raw = struct.unpack("<I", data[208:212])[0] if len(data) > 211 else 1

    # Gapless fields (db version 0x13+)
    pregap = struct.unpack("<I", data[184:188])[0] if len(data) > 187 else 0
    sample_count = struct.unpack("<Q", data[188:196])[0] if len(data) > 195 else 0
    postgap = struct.unpack("<I", data[200:204])[0] if len(data) > 203 else 0
    gapless_data = struct.unpack("<I", data[248:252])[0] if len(data) > 251 else 0
    gapless_track_flag = struct.unpack("<H", data[256:258])[0] if len(data) > 257 else 0
    gapless_album_flag = struct.unpack("<H", data[258:260])[0] if len(data) > 259 else 0

    # Determine file type
    try:
        # Filetype is stored as reversed 4-byte ASCII
        file_type = FileType(struct.unpack("<I", filetype_bytes)[0])
    except ValueError:
        file_type = FileType.MP3

    # Determine media type
    try:
        media_type = MediaType(media_type_raw)
    except ValueError:
        media_type = MediaType.AUDIO

    # Create track with header data
    track = Track(
        id=unique_id,
        title="",
        artist="",
        album="",
        file_type=file_type,
        media_type=media_type,
        duration_ms=length,
        bitrate=bitrate,
        sample_rate=sample_rate,
        size_bytes=size,
        track_number=track_number,
        total_tracks=total_tracks,
        disc_number=disc_number or 1,
        total_discs=total_discs or 1,
        year=year,
        rating=rating,
        play_count=play_count,
        skip_count=skip_count,
        date_added=mac_to_datetime(date_added) if date_added else datetime.now(),
        last_played=mac_to_datetime(last_played) if last_played else None,
        last_modified=mac_to_datetime(last_modified) if last_modified else datetime.now(),
        compilation=compilation,
        dbid=dbid,
        pregap=pregap,
        postgap=postgap,
        sample_count=sample_count,
        gapless_data=gapless_data,
        gapless_track_flag=bool(gapless_track_flag),
        gapless_album_flag=bool(gapless_album_flag),
    )

    # Parse child MHODs for string data
    offset = header_length
    for _ in range(num_mhods):
        if offset >= total_length:
            break

        mhod_data = data[offset:]
        if len(mhod_data) < 12:
            break

        mhod_total = struct.unpack("<I", mhod_data[8:12])[0]
        if mhod_total == 0 or offset + mhod_total > total_length:
            break

        mhod_type, value = parse_mhod(mhod_data[:mhod_total])

        if isinstance(value, str):
            if mhod_type == MhodType.TITLE:
                track.title = value
            elif mhod_type == MhodType.ARTIST:
                track.artist = value
            elif mhod_type == MhodType.ALBUM:
                track.album = value
            elif mhod_type == MhodType.ALBUM_ARTIST:
                track.album_artist = value
            elif mhod_type == MhodType.GENRE:
                track.genre = value
            elif mhod_type == MhodType.COMPOSER:
                track.composer = value
            elif mhod_type == MhodType.COMMENT:
                track.comment = value
            elif mhod_type == MhodType.LOCATION:
                track.path = value

        offset += mhod_total

    return track


# =============================================================================
# Playlist parsing
# =============================================================================


def parse_mhyp(data: bytes) -> tuple[Playlist, list[int]]:
    """Parse an MHYP atom and its children into a Playlist.

    Returns:
        Tuple of (Playlist, list of track_ids in order)
    """
    if len(data) < 24:
        raise InvalidDatabaseError("MHYP too short")

    if data[:4] != b"mhyp":
        raise InvalidDatabaseError(f"Invalid MHYP identifier: {data[:4]!r}")

    header_length = struct.unpack("<I", data[4:8])[0]
    total_length = struct.unpack("<I", data[8:12])[0]
    num_mhods = struct.unpack("<I", data[12:16])[0]
    _ = struct.unpack("<I", data[16:20])[0]  # num_mhips (unused, we parse until end)
    is_master = bool(data[20]) if len(data) > 20 else False
    timestamp = struct.unpack("<I", data[24:28])[0] if len(data) > 27 else 0
    playlist_id = struct.unpack("<Q", data[28:36])[0] if len(data) > 35 else 0
    podcast_flag = struct.unpack("<H", data[42:44])[0] if len(data) > 43 else 0
    sort_order_raw = struct.unpack("<I", data[44:48])[0] if len(data) > 47 else 1

    try:
        sort_order = SortOrder(sort_order_raw)
    except ValueError:
        sort_order = SortOrder.MANUAL

    # Create playlist
    playlist = Playlist(
        id=int(playlist_id & 0xFFFFFFFF),  # Use lower 32 bits as ID
        name="",
        is_master=is_master,
        is_podcast=bool(podcast_flag),
        sort_order=sort_order,
        timestamp=mac_to_datetime(timestamp) if timestamp else datetime.now(),
    )

    # Parse child atoms
    offset = header_length
    track_ids: list[int] = []
    mhods_parsed = 0

    while offset < total_length:
        if offset + 12 > len(data):
            break

        atom_id = data[offset : offset + 4]
        _ = struct.unpack("<I", data[offset + 4 : offset + 8])[0]  # atom header length
        atom_total_len = struct.unpack("<I", data[offset + 8 : offset + 12])[0]

        if atom_total_len == 0:
            break

        if atom_id == b"mhod" and mhods_parsed < num_mhods:
            # Parse MHOD for playlist name
            mhod_data = data[offset : offset + atom_total_len]
            mhod_type, value = parse_mhod(mhod_data)
            if mhod_type == MhodType.TITLE and isinstance(value, str):
                playlist.name = value
            mhods_parsed += 1

        elif atom_id == b"mhip":
            # Parse MHIP for track reference
            if offset + 28 <= len(data):
                track_id = struct.unpack("<I", data[offset + 24 : offset + 28])[0]
                track_ids.append(track_id)

        offset += atom_total_len

    playlist.track_ids = track_ids
    return playlist, track_ids


# =============================================================================
# Database loading
# =============================================================================


def load(path: Path) -> Database:
    """Load an iTunesDB file and return a Database object.

    Args:
        path: Path to the iTunesDB file

    Returns:
        Database object containing all tracks and playlists

    Raises:
        InvalidDatabaseError: If the file format is invalid
        FileNotFoundError: If the file doesn't exist
    """
    with open(path, "rb") as f:
        return _parse_database(f)


def _parse_database(f: BinaryIO) -> Database:
    """Parse an iTunesDB from a file handle."""
    # Read MHBD header
    header_id = read_bytes(f, 4)
    if header_id != b"mhbd":
        raise InvalidDatabaseError(f"Invalid database header: {header_id!r}")

    header_length = read_uint32(f)
    _ = read_uint32(f)  # total_length (we don't need it for parsing)
    _ = read_uint32(f)  # unknown1
    db_version = read_uint32(f)
    num_children = read_uint32(f)
    database_id = read_uint64(f)

    # Skip to language field
    f.seek(70)
    language = read_bytes(f, 2).decode("ascii", errors="replace")

    library_persistent_id = read_uint64(f)

    # Create database
    db = Database(
        version=db_version,
        database_id=database_id,
        library_persistent_id=library_persistent_id,
        language=language,
    )

    # Move to start of sections
    f.seek(header_length)

    # Parse MHSD sections
    for _ in range(num_children):
        pos = f.tell()

        section_id = read_bytes(f, 4)
        if section_id != b"mhsd":
            raise InvalidDatabaseError(f"Expected mhsd, got {section_id!r}")

        _ = read_uint32(f)  # section_header_len
        section_total_len = read_uint32(f)
        section_type = read_uint32(f)

        # Read entire section
        f.seek(pos)
        section_data = read_bytes(f, section_total_len)

        if section_type == 1:
            # Track list
            _parse_track_section(section_data, db)
        elif section_type == 2:
            # Playlist list
            _parse_playlist_section(section_data, db)
        # Types 3 (podcasts) and 4 (albums) are skipped for now

    return db


def _parse_track_section(data: bytes, db: Database) -> None:
    """Parse an MHSD type 1 (track list) section."""
    # Skip MHSD header
    mhsd_header_len = struct.unpack("<I", data[4:8])[0]
    offset = mhsd_header_len

    # Parse MHLT header
    if data[offset : offset + 4] != b"mhlt":
        raise InvalidDatabaseError("Expected mhlt in track section")

    mhlt_header_len = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
    num_tracks = struct.unpack("<I", data[offset + 8 : offset + 12])[0]
    offset += mhlt_header_len

    # Parse MHIT atoms
    for _ in range(num_tracks):
        if offset >= len(data):
            break

        if data[offset : offset + 4] != b"mhit":
            break

        mhit_total_len = struct.unpack("<I", data[offset + 8 : offset + 12])[0]
        if mhit_total_len == 0:
            break

        mhit_data = data[offset : offset + mhit_total_len]
        track = parse_mhit(mhit_data)
        db.tracks.append(track)

        offset += mhit_total_len


def _parse_playlist_section(data: bytes, db: Database) -> None:
    """Parse an MHSD type 2 (playlist list) section."""
    # Skip MHSD header
    mhsd_header_len = struct.unpack("<I", data[4:8])[0]
    offset = mhsd_header_len

    # Parse MHLP header
    if data[offset : offset + 4] != b"mhlp":
        raise InvalidDatabaseError("Expected mhlp in playlist section")

    mhlp_header_len = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
    num_playlists = struct.unpack("<I", data[offset + 8 : offset + 12])[0]
    offset += mhlp_header_len

    # Parse MHYP atoms
    for _ in range(num_playlists):
        if offset >= len(data):
            break

        if data[offset : offset + 4] != b"mhyp":
            break

        mhyp_total_len = struct.unpack("<I", data[offset + 8 : offset + 12])[0]
        if mhyp_total_len == 0:
            break

        mhyp_data = data[offset : offset + mhyp_total_len]
        playlist, _ = parse_mhyp(mhyp_data)
        db.playlists.append(playlist)

        offset += mhyp_total_len


# =============================================================================
# Database saving
# =============================================================================


def save(db: Database, path: Path) -> None:
    """Save a Database object to an iTunesDB file.

    Uses atomic write (write to temp file, then rename) to prevent
    corruption if interrupted.

    Args:
        db: Database object to save
        path: Path to write the iTunesDB file
    """
    # Build database in memory
    data = _build_database(db)

    # Atomic write
    temp_path = path.with_suffix(".tmp")
    try:
        with open(temp_path, "wb") as f:
            f.write(data)
        temp_path.rename(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def _build_database(db: Database) -> bytes:
    """Build the complete iTunesDB binary data."""
    output = BytesIO()

    # Ensure we have a master playlist
    master = db.get_master_playlist()
    if master is None:
        master = Playlist(
            id=db.next_playlist_id(),
            name="Library",
            track_ids=[t.id for t in db.tracks],
            is_master=True,
        )
        db.playlists.insert(0, master)
    else:
        # Update master playlist with all track IDs
        master.track_ids = [t.id for t in db.tracks]

    # Generate database ID if not set
    if db.database_id == 0:
        db.database_id = random.randint(1, 2**63 - 1)
    if db.library_persistent_id == 0:
        db.library_persistent_id = random.randint(1, 2**63 - 1)

    # Build sections
    track_section = _build_track_section(db)
    playlist_section = _build_playlist_section(db)

    # Calculate total size
    num_sections = 2  # tracks + playlists
    total_size = MHBD_HEADER_SIZE + len(track_section) + len(playlist_section)

    # Build MHBD header
    mhbd = BytesIO()
    mhbd.write(b"mhbd")
    mhbd.write(struct.pack("<I", MHBD_HEADER_SIZE))
    mhbd.write(struct.pack("<I", total_size))
    mhbd.write(struct.pack("<I", 1))  # unknown1
    mhbd.write(struct.pack("<I", db.version))
    mhbd.write(struct.pack("<I", num_sections))
    mhbd.write(struct.pack("<Q", db.database_id))
    mhbd.write(struct.pack("<H", 2))  # unknown2
    mhbd.write(struct.pack("<I", 0))  # unknown3
    mhbd.write(struct.pack("<Q", 0))  # unknown4
    mhbd.write(b"\x00" * 24)  # unknown5
    mhbd.write(db.language.encode("ascii")[:2].ljust(2, b"\x00"))
    mhbd.write(struct.pack("<Q", db.library_persistent_id))
    # Padding to header size
    padding_needed = MHBD_HEADER_SIZE - mhbd.tell()
    mhbd.write(b"\x00" * padding_needed)

    output.write(mhbd.getvalue())
    output.write(track_section)
    output.write(playlist_section)

    return output.getvalue()


def _build_track_section(db: Database) -> bytes:
    """Build MHSD type 1 (track list) section."""
    # Build all MHIT atoms
    mhits = BytesIO()
    for track in db.tracks:
        mhits.write(_build_mhit(track))

    # Build MHLT header
    mhlt = BytesIO()
    mhlt.write(b"mhlt")
    mhlt.write(struct.pack("<I", MHLT_HEADER_SIZE))
    mhlt.write(struct.pack("<I", len(db.tracks)))
    padding_needed = MHLT_HEADER_SIZE - mhlt.tell()
    mhlt.write(b"\x00" * padding_needed)

    mhlt_data = mhlt.getvalue() + mhits.getvalue()

    # Build MHSD header
    mhsd = BytesIO()
    total_size = MHSD_HEADER_SIZE + len(mhlt_data)
    mhsd.write(b"mhsd")
    mhsd.write(struct.pack("<I", MHSD_HEADER_SIZE))
    mhsd.write(struct.pack("<I", total_size))
    mhsd.write(struct.pack("<I", 1))  # type = tracks
    padding_needed = MHSD_HEADER_SIZE - mhsd.tell()
    mhsd.write(b"\x00" * padding_needed)

    return mhsd.getvalue() + mhlt_data


def _build_mhit(track: Track) -> bytes:
    """Build an MHIT atom with its child MHODs."""
    # Build MHODs for string data
    mhods = BytesIO()
    mhod_count = 0

    # Title (required)
    if track.title:
        mhods.write(_build_string_mhod(MhodType.TITLE, track.title))
        mhod_count += 1

    # Location (required)
    if track.path:
        mhods.write(_build_string_mhod(MhodType.LOCATION, track.path))
        mhod_count += 1

    # Artist
    if track.artist:
        mhods.write(_build_string_mhod(MhodType.ARTIST, track.artist))
        mhod_count += 1

    # Album
    if track.album:
        mhods.write(_build_string_mhod(MhodType.ALBUM, track.album))
        mhod_count += 1

    # Album Artist
    if track.album_artist:
        mhods.write(_build_string_mhod(MhodType.ALBUM_ARTIST, track.album_artist))
        mhod_count += 1

    # Genre
    if track.genre:
        mhods.write(_build_string_mhod(MhodType.GENRE, track.genre))
        mhod_count += 1

    # Composer
    if track.composer:
        mhods.write(_build_string_mhod(MhodType.COMPOSER, track.composer))
        mhod_count += 1

    # Comment
    if track.comment:
        mhods.write(_build_string_mhod(MhodType.COMMENT, track.comment))
        mhod_count += 1

    mhod_data = mhods.getvalue()
    total_length = MHIT_HEADER_SIZE_V14 + len(mhod_data)

    # Build MHIT header
    mhit = BytesIO()
    mhit.write(b"mhit")
    mhit.write(struct.pack("<I", MHIT_HEADER_SIZE_V14))
    mhit.write(struct.pack("<I", total_length))
    mhit.write(struct.pack("<I", mhod_count))
    mhit.write(struct.pack("<I", track.id))
    mhit.write(struct.pack("<I", 1))  # visible

    # File type as reversed 4-byte ASCII
    mhit.write(struct.pack("<I", track.file_type.value))

    mhit.write(struct.pack("<B", 0))  # type1 (VBR flag)
    mhit.write(struct.pack("<B", 1 if track.file_type == FileType.MP3 else 0))  # type2
    mhit.write(struct.pack("<B", 1 if track.compilation else 0))
    mhit.write(struct.pack("<B", track.rating))
    mhit.write(struct.pack("<I", datetime_to_mac(track.last_modified)))
    mhit.write(struct.pack("<I", track.size_bytes))
    mhit.write(struct.pack("<I", track.duration_ms))
    mhit.write(struct.pack("<I", track.track_number))
    mhit.write(struct.pack("<I", track.total_tracks))
    mhit.write(struct.pack("<I", track.year))
    mhit.write(struct.pack("<I", track.bitrate))
    mhit.write(struct.pack("<I", track.sample_rate << 16))  # sample_rate * 0x10000
    mhit.write(struct.pack("<i", 0))  # volume
    mhit.write(struct.pack("<I", 0))  # start_time
    mhit.write(struct.pack("<I", 0))  # stop_time
    mhit.write(struct.pack("<I", 0))  # soundcheck
    mhit.write(struct.pack("<I", track.play_count))
    mhit.write(struct.pack("<I", track.play_count))  # play_count2
    mhit.write(
        struct.pack("<I", datetime_to_mac(track.last_played) if track.last_played else 0)
    )
    mhit.write(struct.pack("<I", track.disc_number))
    mhit.write(struct.pack("<I", track.total_discs))
    mhit.write(struct.pack("<I", 0))  # user_id
    mhit.write(struct.pack("<I", datetime_to_mac(track.date_added)))
    mhit.write(struct.pack("<I", 0))  # bookmark_time

    # Generate dbid if not set
    dbid = track.dbid if track.dbid else random.randint(1, 2**63 - 1)
    mhit.write(struct.pack("<Q", dbid))

    mhit.write(struct.pack("<B", 0))  # checked
    mhit.write(struct.pack("<B", 0))  # app_rating
    mhit.write(struct.pack("<H", 0))  # bpm
    mhit.write(struct.pack("<H", 0))  # artwork_count
    mhit.write(struct.pack("<H", 0xFFFF))  # unknown9
    mhit.write(struct.pack("<I", 0))  # artwork_size
    mhit.write(struct.pack("<I", 0))  # unknown11
    mhit.write(struct.pack("<f", float(track.sample_rate)))  # sample_rate_float
    mhit.write(struct.pack("<I", 0))  # date_released
    mhit.write(struct.pack("<H", 0x000C if track.file_type == FileType.MP3 else 0x0033))
    mhit.write(struct.pack("<H", 0))  # unknown14_2
    mhit.write(struct.pack("<I", 0))  # unknown15
    mhit.write(struct.pack("<I", 0))  # unknown16
    mhit.write(struct.pack("<I", track.skip_count))
    mhit.write(struct.pack("<I", 0))  # last_skipped
    mhit.write(struct.pack("<B", 0x02))  # has_artwork (0x02 = no)
    mhit.write(struct.pack("<B", 0))  # skip_when_shuffling
    mhit.write(struct.pack("<B", 0))  # remember_position
    mhit.write(struct.pack("<B", 0))  # podcast_flag
    mhit.write(struct.pack("<Q", dbid))  # dbid2
    mhit.write(struct.pack("<B", 0))  # has_lyrics
    mhit.write(struct.pack("<B", 0))  # is_movie
    mhit.write(struct.pack("<B", 0))  # played_mark
    mhit.write(struct.pack("<B", 0))  # unknown17
    mhit.write(struct.pack("<I", 0))  # unknown21
    mhit.write(struct.pack("<I", track.pregap))
    mhit.write(struct.pack("<Q", track.sample_count))
    mhit.write(struct.pack("<I", 0))  # unknown25
    mhit.write(struct.pack("<I", track.postgap))
    mhit.write(struct.pack("<I", 0))  # unknown27
    mhit.write(struct.pack("<I", track.media_type.value))
    mhit.write(struct.pack("<I", 0))  # season_number
    mhit.write(struct.pack("<I", 0))  # episode_number
    mhit.write(b"\x00" * 24)  # unknown31-36
    mhit.write(struct.pack("<I", 0))  # unknown37
    mhit.write(struct.pack("<I", track.gapless_data))
    mhit.write(struct.pack("<I", 0))  # unknown38
    mhit.write(struct.pack("<H", 1 if track.gapless_track_flag else 0))
    mhit.write(struct.pack("<H", 1 if track.gapless_album_flag else 0))
    mhit.write(b"\x00" * 20)  # unknown39 (hash - not checked on 5.5g)

    # Padding to header size
    padding_needed = MHIT_HEADER_SIZE_V14 - mhit.tell()
    if padding_needed > 0:
        mhit.write(b"\x00" * padding_needed)

    return mhit.getvalue() + mhod_data


def _build_string_mhod(mhod_type: MhodType, value: str) -> bytes:
    """Build a string MHOD atom."""
    # Encode string
    if mhod_type == MhodType.LOCATION:
        string_data = encode_path(value)
    else:
        string_data = encode_string(value)

    string_length = len(string_data)
    total_length = 40 + string_length  # 24 header + 16 string header + data

    mhod = BytesIO()
    mhod.write(b"mhod")
    mhod.write(struct.pack("<I", MHOD_HEADER_SIZE))  # header_length (24)
    mhod.write(struct.pack("<I", total_length))
    mhod.write(struct.pack("<I", mhod_type.value))
    mhod.write(struct.pack("<I", 0))  # unknown1
    mhod.write(struct.pack("<I", 0))  # unknown2
    mhod.write(struct.pack("<I", 1))  # position (1 = UTF-16)
    mhod.write(struct.pack("<I", string_length))
    mhod.write(struct.pack("<I", 1))  # encoding
    mhod.write(struct.pack("<I", 0))  # unknown4
    mhod.write(string_data)

    return mhod.getvalue()


def _build_playlist_section(db: Database) -> bytes:
    """Build MHSD type 2 (playlist list) section."""
    # Build all MHYP atoms
    mhyps = BytesIO()
    for playlist in db.playlists:
        mhyps.write(_build_mhyp(playlist))

    # Build MHLP header
    mhlp = BytesIO()
    mhlp.write(b"mhlp")
    mhlp.write(struct.pack("<I", MHLP_HEADER_SIZE))
    mhlp.write(struct.pack("<I", len(db.playlists)))
    padding_needed = MHLP_HEADER_SIZE - mhlp.tell()
    mhlp.write(b"\x00" * padding_needed)

    mhlp_data = mhlp.getvalue() + mhyps.getvalue()

    # Build MHSD header
    mhsd = BytesIO()
    total_size = MHSD_HEADER_SIZE + len(mhlp_data)
    mhsd.write(b"mhsd")
    mhsd.write(struct.pack("<I", MHSD_HEADER_SIZE))
    mhsd.write(struct.pack("<I", total_size))
    mhsd.write(struct.pack("<I", 2))  # type = playlists
    padding_needed = MHSD_HEADER_SIZE - mhsd.tell()
    mhsd.write(b"\x00" * padding_needed)

    return mhsd.getvalue() + mhlp_data


def _build_mhyp(playlist: Playlist) -> bytes:
    """Build an MHYP atom with its child MHODs and MHIPs."""
    # Build name MHOD (unless master playlist)
    mhods = BytesIO()
    mhod_count = 0
    if not playlist.is_master and playlist.name:
        mhods.write(_build_string_mhod(MhodType.TITLE, playlist.name))
        mhod_count += 1

    mhod_data = mhods.getvalue()

    # Build MHIPs for track references
    mhips = BytesIO()
    for i, track_id in enumerate(playlist.track_ids):
        mhips.write(_build_mhip(track_id, i))

    mhip_data = mhips.getvalue()

    total_length = MHYP_HEADER_SIZE + len(mhod_data) + len(mhip_data)

    # Build MHYP header
    mhyp = BytesIO()
    mhyp.write(b"mhyp")
    mhyp.write(struct.pack("<I", MHYP_HEADER_SIZE))
    mhyp.write(struct.pack("<I", total_length))
    mhyp.write(struct.pack("<I", mhod_count))
    mhyp.write(struct.pack("<I", len(playlist.track_ids)))
    mhyp.write(struct.pack("<B", 1 if playlist.is_master else 0))
    mhyp.write(b"\x00" * 3)  # unknown_flags
    mhyp.write(struct.pack("<I", datetime_to_mac(playlist.timestamp)))
    mhyp.write(struct.pack("<Q", playlist.id))  # playlist_id as 64-bit
    mhyp.write(struct.pack("<I", 0))  # unknown3
    mhyp.write(struct.pack("<H", mhod_count))  # string_mhod_count
    mhyp.write(struct.pack("<H", 1 if playlist.is_podcast else 0))
    mhyp.write(struct.pack("<I", playlist.sort_order.value))

    # Padding to header size
    padding_needed = MHYP_HEADER_SIZE - mhyp.tell()
    if padding_needed > 0:
        mhyp.write(b"\x00" * padding_needed)

    return mhyp.getvalue() + mhod_data + mhip_data


def _build_mhip(track_id: int, position: int) -> bytes:
    """Build an MHIP atom."""
    # Build position MHOD (type 100)
    pos_mhod = BytesIO()
    pos_mhod.write(b"mhod")
    pos_mhod.write(struct.pack("<I", MHOD_HEADER_SIZE))
    pos_mhod.write(struct.pack("<I", 28))  # total_length
    pos_mhod.write(struct.pack("<I", MhodType.PLAYLIST_COLUMN))
    pos_mhod.write(struct.pack("<I", 0))  # unknown1
    pos_mhod.write(struct.pack("<I", 0))  # unknown2
    pos_mhod.write(struct.pack("<I", position))
    pos_mhod_data = pos_mhod.getvalue()

    total_length = MHIP_HEADER_SIZE + len(pos_mhod_data)

    # Build MHIP header
    mhip = BytesIO()
    mhip.write(b"mhip")
    mhip.write(struct.pack("<I", MHIP_HEADER_SIZE))
    mhip.write(struct.pack("<I", total_length))
    mhip.write(struct.pack("<I", 1))  # num_mhods
    mhip.write(struct.pack("<H", 0))  # podcast_group_flag
    mhip.write(struct.pack("<B", 0))  # unknown4
    mhip.write(struct.pack("<B", 0))  # unknown5
    mhip.write(struct.pack("<I", position + 1))  # group_id (1-based)
    mhip.write(struct.pack("<I", track_id))
    mhip.write(struct.pack("<I", 0))  # timestamp
    mhip.write(struct.pack("<I", 0))  # podcast_group_ref

    # Padding to header size
    padding_needed = MHIP_HEADER_SIZE - mhip.tell()
    if padding_needed > 0:
        mhip.write(b"\x00" * padding_needed)

    return mhip.getvalue() + pos_mhod_data
