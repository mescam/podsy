"""Tests for iTunesDB parser and serializer."""

import struct
import tempfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest

from podsy.db.atoms import (
    MAC_EPOCH_OFFSET,
    MHBD_HEADER_SIZE,
    MHOD_HEADER_SIZE,
    encode_string,
)
from podsy.db.models import Database, FileType, MhodType, Playlist, Track
from podsy.db.parser import (
    InvalidDatabaseError,
    _build_database,
    _build_mhit,
    _build_mhyp,
    _build_string_mhod,
    datetime_to_mac,
    load,
    mac_to_datetime,
    parse_mhit,
    parse_mhod,
    parse_mhyp,
    save,
)


class TestTimestampConversion:
    """Tests for Mac HFS+ timestamp conversion."""

    def test_mac_to_datetime_zero(self) -> None:
        """Test converting zero timestamp."""
        result = mac_to_datetime(0)
        assert result == datetime(1904, 1, 1)

    def test_mac_to_datetime_unix_epoch(self) -> None:
        """Test converting Mac timestamp for Unix epoch."""
        # Mac timestamp for 1970-01-01 00:00:00
        result = mac_to_datetime(MAC_EPOCH_OFFSET)
        assert result.year == 1970
        assert result.month == 1
        assert result.day == 1

    def test_datetime_to_mac(self) -> None:
        """Test converting datetime to Mac timestamp."""
        # Use UTC to avoid timezone issues
        dt = datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = datetime_to_mac(dt)
        assert result == MAC_EPOCH_OFFSET

    def test_roundtrip_conversion(self) -> None:
        """Test roundtrip timestamp conversion."""
        now = datetime.now().replace(microsecond=0)
        mac_ts = datetime_to_mac(now)
        back = mac_to_datetime(mac_ts)
        assert back == now


class TestMhodParsing:
    """Tests for MHOD (data object) parsing."""

    def _build_string_mhod_raw(self, mhod_type: int, text: str) -> bytes:
        """Build a raw string MHOD for testing."""
        string_data = encode_string(text)
        string_length = len(string_data)
        total_length = 40 + string_length

        buf = BytesIO()
        buf.write(b"mhod")
        buf.write(struct.pack("<I", MHOD_HEADER_SIZE))  # header_length (24)
        buf.write(struct.pack("<I", total_length))
        buf.write(struct.pack("<I", mhod_type))
        buf.write(struct.pack("<I", 0))  # unknown1
        buf.write(struct.pack("<I", 0))  # unknown2
        buf.write(struct.pack("<I", 1))  # position (UTF-16)
        buf.write(struct.pack("<I", string_length))
        buf.write(struct.pack("<I", 1))  # encoding
        buf.write(struct.pack("<I", 0))  # unknown4
        buf.write(string_data)

        return buf.getvalue()

    def test_parse_mhod_title(self) -> None:
        """Test parsing title MHOD."""
        data = self._build_string_mhod_raw(MhodType.TITLE, "Test Title")
        mhod_type, value = parse_mhod(data)

        assert mhod_type == MhodType.TITLE
        assert value == "Test Title"

    def test_parse_mhod_artist(self) -> None:
        """Test parsing artist MHOD."""
        data = self._build_string_mhod_raw(MhodType.ARTIST, "Test Artist")
        mhod_type, value = parse_mhod(data)

        assert mhod_type == MhodType.ARTIST
        assert value == "Test Artist"

    def test_parse_mhod_album(self) -> None:
        """Test parsing album MHOD."""
        data = self._build_string_mhod_raw(MhodType.ALBUM, "Test Album")
        mhod_type, value = parse_mhod(data)

        assert mhod_type == MhodType.ALBUM
        assert value == "Test Album"

    def test_parse_mhod_unicode(self) -> None:
        """Test parsing MHOD with Unicode text."""
        data = self._build_string_mhod_raw(MhodType.TITLE, "Café Müsic 日本語")
        mhod_type, value = parse_mhod(data)

        assert mhod_type == MhodType.TITLE
        assert value == "Café Müsic 日本語"

    def test_parse_mhod_too_short(self) -> None:
        """Test parsing MHOD that's too short."""
        data = b"mhod" + b"\x00" * 10
        with pytest.raises(InvalidDatabaseError, match="MHOD too short"):
            parse_mhod(data)

    def test_parse_mhod_invalid_identifier(self) -> None:
        """Test parsing MHOD with wrong identifier."""
        data = b"mhit" + b"\x00" * 40
        with pytest.raises(InvalidDatabaseError, match="Invalid MHOD identifier"):
            parse_mhod(data)


class TestMhodBuilding:
    """Tests for building MHOD atoms."""

    def test_build_string_mhod_title(self) -> None:
        """Test building a title MHOD."""
        data = _build_string_mhod(MhodType.TITLE, "Test Title")

        # Verify header
        assert data[:4] == b"mhod"
        header_len = struct.unpack("<I", data[4:8])[0]
        assert header_len == MHOD_HEADER_SIZE

        # Verify type
        mhod_type = struct.unpack("<I", data[12:16])[0]
        assert mhod_type == MhodType.TITLE

    def test_build_string_mhod_roundtrip(self) -> None:
        """Test that building and parsing MHOD are inverses."""
        original = "Test Song Title"
        built = _build_string_mhod(MhodType.TITLE, original)
        parsed_type, parsed_value = parse_mhod(built)

        assert parsed_type == MhodType.TITLE
        assert parsed_value == original


class TestMhitParsing:
    """Tests for MHIT (track item) parsing."""

    def test_parse_mhit_minimal(self) -> None:
        """Test parsing a minimal MHIT."""
        # Build a minimal MHIT with one MHOD
        track = Track(
            id=42,
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            path=":iPod_Control:Music:F00:TEST.mp3",
        )
        mhit_data = _build_mhit(track)

        # Parse it back
        parsed = parse_mhit(mhit_data)

        assert parsed.id == 42
        assert parsed.title == "Test Song"
        assert parsed.artist == "Test Artist"
        assert parsed.album == "Test Album"
        assert parsed.path == ":iPod_Control:Music:F00:TEST.mp3"

    def test_parse_mhit_full_metadata(self) -> None:
        """Test parsing MHIT with full metadata."""
        now = datetime.now().replace(microsecond=0)
        track = Track(
            id=100,
            title="Full Track",
            artist="Full Artist",
            album="Full Album",
            album_artist="Album Artist",
            genre="Rock",
            composer="Composer",
            path=":iPod_Control:Music:F05:FULL.mp3",
            duration_ms=240000,
            bitrate=256,
            sample_rate=48000,
            size_bytes=7680000,
            track_number=5,
            total_tracks=12,
            disc_number=2,
            total_discs=3,
            year=2023,
            rating=80,
            play_count=10,
            date_added=now,
            file_type=FileType.MP3,
        )
        mhit_data = _build_mhit(track)
        parsed = parse_mhit(mhit_data)

        assert parsed.id == 100
        assert parsed.title == "Full Track"
        assert parsed.artist == "Full Artist"
        assert parsed.album == "Full Album"
        assert parsed.album_artist == "Album Artist"
        assert parsed.genre == "Rock"
        assert parsed.composer == "Composer"
        assert parsed.duration_ms == 240000
        assert parsed.bitrate == 256
        assert parsed.track_number == 5
        assert parsed.total_tracks == 12
        assert parsed.disc_number == 2
        assert parsed.total_discs == 3
        assert parsed.year == 2023
        assert parsed.rating == 80
        assert parsed.play_count == 10


class TestMhypParsing:
    """Tests for MHYP (playlist) parsing."""

    def test_parse_mhyp_basic(self) -> None:
        """Test parsing a basic playlist."""
        playlist = Playlist(
            id=1,
            name="My Playlist",
            track_ids=[1, 2, 3],
        )
        mhyp_data = _build_mhyp(playlist)
        parsed, track_ids = parse_mhyp(mhyp_data)

        assert parsed.name == "My Playlist"
        assert track_ids == [1, 2, 3]
        assert parsed.is_master is False

    def test_parse_mhyp_master(self) -> None:
        """Test parsing master playlist."""
        playlist = Playlist(
            id=1,
            name="Library",
            track_ids=[1, 2, 3, 4, 5],
            is_master=True,
        )
        mhyp_data = _build_mhyp(playlist)
        parsed, track_ids = parse_mhyp(mhyp_data)

        assert parsed.is_master is True
        assert track_ids == [1, 2, 3, 4, 5]


class TestDatabaseRoundtrip:
    """Tests for complete database save/load roundtrip."""

    def test_save_load_empty_database(self) -> None:
        """Test saving and loading an empty database."""
        db = Database(
            version=0x15,
            language="en",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "iTunesDB"
            save(db, db_path)

            assert db_path.exists()
            assert db_path.stat().st_size > 0

            loaded = load(db_path)

            assert loaded.version == 0x15
            assert loaded.language == "en"
            # Master playlist should be created
            assert loaded.get_master_playlist() is not None

    def test_save_load_with_tracks(self) -> None:
        """Test saving and loading database with tracks."""
        db = Database()
        db.tracks = [
            Track(
                id=1,
                title="Song One",
                artist="Artist A",
                album="Album X",
                path=":iPod_Control:Music:F00:S001.mp3",
            ),
            Track(
                id=2,
                title="Song Two",
                artist="Artist B",
                album="Album Y",
                path=":iPod_Control:Music:F01:S002.mp3",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "iTunesDB"
            save(db, db_path)
            loaded = load(db_path)

            assert len(loaded.tracks) == 2
            assert loaded.tracks[0].title == "Song One"
            assert loaded.tracks[1].title == "Song Two"

    def test_save_load_with_playlists(self) -> None:
        """Test saving and loading database with playlists."""
        db = Database()
        db.tracks = [
            Track(id=1, title="A", artist="B", album="C", path=":iPod_Control:Music:F00:A.mp3"),
            Track(id=2, title="D", artist="E", album="F", path=":iPod_Control:Music:F00:B.mp3"),
        ]
        db.playlists = [
            Playlist(id=1, name="Library", is_master=True, track_ids=[1, 2]),
            Playlist(id=2, name="Favorites", track_ids=[1]),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "iTunesDB"
            save(db, db_path)
            loaded = load(db_path)

            # Should have master + 1 user playlist
            assert len(loaded.playlists) >= 2

            # Find non-master playlist
            user_playlists = [p for p in loaded.playlists if not p.is_master]
            assert len(user_playlists) == 1
            assert user_playlists[0].name == "Favorites"
            assert user_playlists[0].track_ids == [1]

    def test_build_database_generates_ids(self) -> None:
        """Test that building database generates missing IDs."""
        db = Database()
        assert db.database_id == 0
        assert db.library_persistent_id == 0

        _build_database(db)

        # IDs should be generated during build
        assert db.database_id != 0
        assert db.library_persistent_id != 0


class TestDatabaseHeader:
    """Tests for database header parsing."""

    def test_invalid_header_identifier(self) -> None:
        """Test loading file with invalid header."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "iTunesDB"
            db_path.write_bytes(b"INVALID HEADER DATA" + b"\x00" * 100)

            with pytest.raises(InvalidDatabaseError, match="Invalid database header"):
                load(db_path)

    def test_database_file_structure(self) -> None:
        """Test that saved database has correct structure."""
        db = Database()
        db.tracks = [
            Track(id=1, title="Test", artist="A", album="B", path=":iPod_Control:Music:F00:X.mp3")
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "iTunesDB"
            save(db, db_path)

            with open(db_path, "rb") as f:
                # Check MHBD header
                assert f.read(4) == b"mhbd"
                header_len = struct.unpack("<I", f.read(4))[0]
                assert header_len == MHBD_HEADER_SIZE

                # Skip to sections
                f.seek(header_len)

                # First section should be MHSD
                assert f.read(4) == b"mhsd"
