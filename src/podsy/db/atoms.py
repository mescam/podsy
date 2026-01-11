"""Construct schemas for iTunesDB binary atoms.

This module defines the binary structure of all iTunesDB atoms using the
Construct library. All integers are little-endian. Strings are UTF-16LE.

The iPod 5.5g uses database versions 0x13-0x15 (iTunes 7.0-7.2), which
do NOT require the hash/checksum validation used in later iPod models.
"""

from construct import (
    Array,
    Bytes,
    Computed,
    Const,
    Float32l,
    GreedyBytes,
    GreedyRange,
    If,
    Int8ul,
    Int16ul,
    Int32sl,
    Int32ul,
    Int64ul,
    Padding,
    Struct,
    Switch,
    this,
)

# =============================================================================
# Constants
# =============================================================================

# Mac HFS+ epoch: seconds between 1904-01-01 and 1970-01-01
MAC_EPOCH_OFFSET = 2082844800

# Default header sizes for different atom types
MHBD_HEADER_SIZE = 0x68  # 104 bytes
MHSD_HEADER_SIZE = 0x60  # 96 bytes
MHLT_HEADER_SIZE = 0x5C  # 92 bytes
MHIT_HEADER_SIZE_V13 = 0x148  # 328 bytes (db version 0x12-0x13)
MHIT_HEADER_SIZE_V14 = 0x184  # 388 bytes (db version 0x14+)
MHOD_HEADER_SIZE = 0x18  # 24 bytes
MHLP_HEADER_SIZE = 0x5C  # 92 bytes
MHYP_HEADER_SIZE = 0x6C  # 108 bytes
MHIP_HEADER_SIZE = 0x4C  # 76 bytes

# =============================================================================
# MHOD (Data Object) - Variable-length metadata
# =============================================================================

# String MHOD (types 1-14, 18-31): contains UTF-16LE encoded strings
MhodString = Struct(
    "identifier" / Const(b"mhod"),
    "header_length" / Int32ul,
    "total_length" / Int32ul,
    "type" / Int32ul,
    "unknown1" / Int32ul,
    "unknown2" / Int32ul,
    # String-specific fields (after the 24-byte common header)
    "position" / Int32ul,  # 1 for UTF-16, 2 for UTF-8
    "string_length" / Int32ul,  # Length in bytes
    "encoding" / Int32ul,  # Encoding flag (unreliable)
    "unknown4" / Int32ul,
    "string_data" / Bytes(this.string_length),
)

# URL MHOD (types 15-16): contains UTF-8 encoded URLs
MhodUrl = Struct(
    "identifier" / Const(b"mhod"),
    "header_length" / Int32ul,
    "total_length" / Int32ul,
    "type" / Int32ul,
    "unknown1" / Int32ul,
    "unknown2" / Int32ul,
    "string_data" / Bytes(this.total_length - this.header_length),
)

# Playlist position MHOD (type 100)
MhodPlaylistPos = Struct(
    "identifier" / Const(b"mhod"),
    "header_length" / Int32ul,
    "total_length" / Int32ul,
    "type" / Int32ul,
    "unknown1" / Int32ul,
    "unknown2" / Int32ul,
    "position" / Int32ul,
    "extra_data" / Bytes(this.total_length - this.header_length - 4),
)

# Generic MHOD for unknown types
MhodGeneric = Struct(
    "identifier" / Const(b"mhod"),
    "header_length" / Int32ul,
    "total_length" / Int32ul,
    "type" / Int32ul,
    "unknown1" / Int32ul,
    "unknown2" / Int32ul,
    "data" / Bytes(this.total_length - this.header_length),
)

# =============================================================================
# MHIT (Track Item)
# =============================================================================

MhitHeader = Struct(
    "identifier" / Const(b"mhit"),
    "header_length" / Int32ul,
    "total_length" / Int32ul,
    "num_mhods" / Int32ul,
    "unique_id" / Int32ul,
    "visible" / Int32ul,
    "filetype" / Bytes(4),  # Reversed ASCII: "MP3 " -> b" 3PM"
    "type1" / Int8ul,  # 0x00=CBR, 0x01=VBR
    "type2" / Int8ul,  # 0x01=MP3, 0x00=AAC
    "compilation" / Int8ul,
    "rating" / Int8ul,  # rating * 20
    "last_modified" / Int32ul,  # Mac timestamp
    "size" / Int32ul,  # File size in bytes
    "length" / Int32ul,  # Duration in milliseconds
    "track_number" / Int32ul,
    "total_tracks" / Int32ul,
    "year" / Int32ul,
    "bitrate" / Int32ul,
    "sample_rate" / Int32ul,  # sample_rate * 0x10000
    "volume" / Int32sl,  # Signed: -255 to 255
    "start_time" / Int32ul,  # Start position (ms)
    "stop_time" / Int32ul,  # Stop position (ms)
    "soundcheck" / Int32ul,  # 1000 * 10^(-0.1*dB)
    "play_count" / Int32ul,
    "play_count2" / Int32ul,
    "last_played" / Int32ul,  # Mac timestamp
    "disc_number" / Int32ul,
    "total_discs" / Int32ul,
    "user_id" / Int32ul,  # DRM user ID
    "date_added" / Int32ul,  # Mac timestamp
    "bookmark_time" / Int32ul,
    "dbid" / Int64ul,  # 64-bit unique ID
    "checked" / Int8ul,
    "app_rating" / Int8ul,
    "bpm" / Int16ul,
    "artwork_count" / Int16ul,
    "unknown9" / Int16ul,  # 0xFFFF for MP3/AAC
    "artwork_size" / Int32ul,
    "unknown11" / Int32ul,
    "sample_rate_float" / Float32l,
    "date_released" / Int32ul,
    "unknown14_1" / Int16ul,
    "unknown14_2" / Int16ul,
    "unknown15" / Int32ul,
    "unknown16" / Int32ul,
    "skip_count" / Int32ul,
    "last_skipped" / Int32ul,
    "has_artwork" / Int8ul,
    "skip_when_shuffling" / Int8ul,
    "remember_position" / Int8ul,
    "podcast_flag" / Int8ul,
    "dbid2" / Int64ul,
    "has_lyrics" / Int8ul,
    "is_movie" / Int8ul,
    "played_mark" / Int8ul,
    "unknown17" / Int8ul,
    "unknown21" / Int32ul,
    "pregap" / Int32ul,  # Gapless: pregap samples
    "sample_count" / Int64ul,  # Gapless: total samples
    "unknown25" / Int32ul,
    "postgap" / Int32ul,  # Gapless: postgap samples
    "unknown27" / Int32ul,
    "media_type" / Int32ul,
    "season_number" / Int32ul,
    "episode_number" / Int32ul,
    "unknown31" / Int32ul,
    "unknown32" / Int32ul,
    "unknown33" / Int32ul,
    "unknown34" / Int32ul,
    "unknown35" / Int32ul,
    "unknown36" / Int32ul,
    # Fields added in db version 0x13+
    "unknown37" / Int32ul,
    "gapless_data" / Int32ul,
    "unknown38" / Int32ul,
    "gapless_track_flag" / Int16ul,
    "gapless_album_flag" / Int16ul,
    "unknown39" / Bytes(20),  # Hash (not checked on 5.5g)
    # Remaining padding up to header_length
    "padding" / Bytes(this.header_length - 280),
)

# =============================================================================
# MHLT (Track List)
# =============================================================================

MhltHeader = Struct(
    "identifier" / Const(b"mhlt"),
    "header_length" / Int32ul,
    "num_tracks" / Int32ul,  # NOT total_length!
    "padding" / Bytes(this.header_length - 12),
)

# =============================================================================
# MHIP (Playlist Item)
# =============================================================================

MhipHeader = Struct(
    "identifier" / Const(b"mhip"),
    "header_length" / Int32ul,
    "total_length" / Int32ul,
    "num_mhods" / Int32ul,
    "podcast_group_flag" / Int16ul,
    "unknown4" / Int8ul,
    "unknown5" / Int8ul,
    "group_id" / Int32ul,
    "track_id" / Int32ul,  # Reference to mhit.unique_id
    "timestamp" / Int32ul,
    "podcast_group_ref" / Int32ul,
    "padding" / Bytes(this.header_length - 36),
)

# =============================================================================
# MHYP (Playlist Header)
# =============================================================================

MhypHeader = Struct(
    "identifier" / Const(b"mhyp"),
    "header_length" / Int32ul,
    "total_length" / Int32ul,
    "num_mhods" / Int32ul,  # String mhods before first mhip
    "num_mhips" / Int32ul,
    "is_master" / Int8ul,  # 1 = Library playlist
    "unknown_flags" / Bytes(3),
    "timestamp" / Int32ul,
    "playlist_id" / Int64ul,
    "unknown3" / Int32ul,
    "string_mhod_count" / Int16ul,
    "podcast_flag" / Int16ul,
    "sort_order" / Int32ul,
    "padding" / Bytes(this.header_length - 48),
)

# =============================================================================
# MHLP (Playlist List)
# =============================================================================

MhlpHeader = Struct(
    "identifier" / Const(b"mhlp"),
    "header_length" / Int32ul,
    "num_playlists" / Int32ul,  # NOT total_length!
    "padding" / Bytes(this.header_length - 12),
)

# =============================================================================
# MHSD (Section Descriptor)
# =============================================================================

MhsdHeader = Struct(
    "identifier" / Const(b"mhsd"),
    "header_length" / Int32ul,
    "total_length" / Int32ul,
    "type" / Int32ul,  # 1=tracks, 2=playlists, 3=podcasts, 4=albums
    "padding" / Bytes(this.header_length - 16),
)

# =============================================================================
# MHBD (Database Header)
# =============================================================================

MhbdHeader = Struct(
    "identifier" / Const(b"mhbd"),
    "header_length" / Int32ul,
    "total_length" / Int32ul,  # Size of entire file
    "unknown1" / Int32ul,  # Always 1
    "db_version" / Int32ul,  # 0x13-0x15 for 5.5g
    "num_children" / Int32ul,  # Number of mhsd sections
    "database_id" / Int64ul,
    "unknown2" / Int16ul,  # Always 2
    "unknown3" / Int32ul,
    "unknown4" / Int64ul,
    "unknown5" / Bytes(24),
    "language" / Bytes(2),  # e.g., "en"
    "library_persistent_id" / Int64ul,
    "padding" / Bytes(this.header_length - 80),
)

# =============================================================================
# Helper functions for string encoding
# =============================================================================


def encode_string(text: str) -> bytes:
    """Encode a string as UTF-16LE for iTunesDB mhod.

    Note: No BOM, no null terminator.
    """
    return text.encode("utf-16-le")


def decode_string(data: bytes) -> str:
    """Decode a UTF-16LE string from iTunesDB mhod."""
    return data.decode("utf-16-le")


def encode_path(path: str) -> bytes:
    """Encode a file path for type 2 mhod.

    Converts forward slashes to colons and ensures path starts with colon.
    Maximum 112 bytes (56 UTF-16 characters).
    """
    # Ensure path starts with colon and uses colon separators
    if not path.startswith(":"):
        path = ":" + path
    path = path.replace("/", ":")

    encoded = path.encode("utf-16-le")
    if len(encoded) > 112:
        raise ValueError(f"Path too long for iTunesDB: {len(encoded)} bytes (max 112)")
    return encoded


def decode_path(data: bytes) -> str:
    """Decode a file path from type 2 mhod."""
    return data.decode("utf-16-le")
