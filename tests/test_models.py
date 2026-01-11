"""Tests for database models."""

from datetime import datetime

from podsy.db.models import (
    Database,
    FileType,
    MediaType,
    MhodType,
    Playlist,
    SortOrder,
    Track,
)


class TestEnums:
    """Tests for enum types."""

    def test_media_type_values(self) -> None:
        """Test MediaType enum values."""
        assert MediaType.AUDIO == 0x00000001
        assert MediaType.VIDEO == 0x00000002
        assert MediaType.PODCAST == 0x00000004
        assert MediaType.AUDIOBOOK == 0x00000008

    def test_file_type_values(self) -> None:
        """Test FileType enum values (reversed 4-byte ASCII)."""
        assert FileType.MP3 == 0x4D503320
        assert FileType.AAC == 0x41414320
        assert FileType.M4A == 0x4D344120

    def test_mhod_type_values(self) -> None:
        """Test MhodType enum values."""
        assert MhodType.TITLE == 1
        assert MhodType.LOCATION == 2
        assert MhodType.ALBUM == 3
        assert MhodType.ARTIST == 4
        assert MhodType.GENRE == 5
        assert MhodType.ALBUM_ARTIST == 22

    def test_sort_order_values(self) -> None:
        """Test SortOrder enum values."""
        assert SortOrder.MANUAL == 1
        assert SortOrder.TITLE == 3
        assert SortOrder.ARTIST == 5


class TestTrack:
    """Tests for Track dataclass."""

    def test_track_creation_minimal(self) -> None:
        """Test creating a track with minimal required fields."""
        track = Track(id=1, title="Test Song", artist="Test Artist", album="Test Album")

        assert track.id == 1
        assert track.title == "Test Song"
        assert track.artist == "Test Artist"
        assert track.album == "Test Album"
        assert track.file_type == FileType.MP3
        assert track.media_type == MediaType.AUDIO

    def test_track_creation_full(self) -> None:
        """Test creating a track with all fields."""
        now = datetime.now()
        track = Track(
            id=42,
            title="Full Track",
            artist="Full Artist",
            album="Full Album",
            album_artist="Album Artist",
            genre="Rock",
            composer="Composer",
            comment="A comment",
            path=":iPod_Control:Music:F00:ABCD.mp3",
            duration_ms=180000,
            bitrate=320,
            sample_rate=44100,
            size_bytes=5760000,
            track_number=3,
            total_tracks=12,
            disc_number=1,
            total_discs=2,
            year=2024,
            rating=80,
            play_count=5,
            skip_count=1,
            date_added=now,
            last_played=now,
            last_modified=now,
            file_type=FileType.M4A,
            media_type=MediaType.AUDIO,
            compilation=True,
            dbid=12345678901234,
            pregap=576,
            postgap=1152,
            sample_count=7938000,
            gapless_data=1,
            gapless_track_flag=True,
            gapless_album_flag=True,
        )

        assert track.id == 42
        assert track.album_artist == "Album Artist"
        assert track.compilation is True
        assert track.gapless_track_flag is True

    def test_track_default_values(self) -> None:
        """Test track default values."""
        track = Track(id=1, title="T", artist="A", album="B")

        assert track.album_artist == ""
        assert track.genre == ""
        assert track.composer == ""
        assert track.comment == ""
        assert track.path == ""
        assert track.duration_ms == 0
        assert track.bitrate == 0
        assert track.sample_rate == 44100
        assert track.size_bytes == 0
        assert track.track_number == 0
        assert track.total_tracks == 0
        assert track.disc_number == 1
        assert track.total_discs == 1
        assert track.year == 0
        assert track.rating == 0
        assert track.play_count == 0
        assert track.skip_count == 0
        assert track.last_played is None
        assert track.compilation is False
        assert track.dbid == 0
        assert track.pregap == 0
        assert track.postgap == 0
        assert track.sample_count == 0
        assert track.gapless_data == 0
        assert track.gapless_track_flag is False
        assert track.gapless_album_flag is False


class TestPlaylist:
    """Tests for Playlist dataclass."""

    def test_playlist_creation_minimal(self) -> None:
        """Test creating a playlist with minimal fields."""
        playlist = Playlist(id=1, name="My Playlist")

        assert playlist.id == 1
        assert playlist.name == "My Playlist"
        assert playlist.track_ids == []
        assert playlist.is_master is False
        assert playlist.is_podcast is False
        assert playlist.sort_order == SortOrder.MANUAL

    def test_playlist_creation_with_tracks(self) -> None:
        """Test creating a playlist with tracks."""
        playlist = Playlist(id=1, name="My Playlist", track_ids=[1, 2, 3, 4, 5])

        assert len(playlist.track_ids) == 5
        assert playlist.track_ids == [1, 2, 3, 4, 5]

    def test_master_playlist(self) -> None:
        """Test creating a master (Library) playlist."""
        playlist = Playlist(id=1, name="Library", is_master=True)

        assert playlist.is_master is True


class TestDatabase:
    """Tests for Database dataclass."""

    def test_database_creation_empty(self) -> None:
        """Test creating an empty database."""
        db = Database()

        assert db.version == 0x15
        assert db.database_id == 0
        assert db.library_persistent_id == 0
        assert db.language == "en"
        assert db.tracks == []
        assert db.playlists == []

    def test_get_track_by_id(self) -> None:
        """Test finding a track by ID."""
        db = Database()
        track1 = Track(id=1, title="Song 1", artist="Artist", album="Album")
        track2 = Track(id=2, title="Song 2", artist="Artist", album="Album")
        db.tracks = [track1, track2]

        assert db.get_track_by_id(1) is track1
        assert db.get_track_by_id(2) is track2
        assert db.get_track_by_id(3) is None

    def test_get_playlist_by_id(self) -> None:
        """Test finding a playlist by ID."""
        db = Database()
        playlist1 = Playlist(id=1, name="Playlist 1")
        playlist2 = Playlist(id=2, name="Playlist 2")
        db.playlists = [playlist1, playlist2]

        assert db.get_playlist_by_id(1) is playlist1
        assert db.get_playlist_by_id(2) is playlist2
        assert db.get_playlist_by_id(3) is None

    def test_get_playlist_by_name(self) -> None:
        """Test finding a playlist by name."""
        db = Database()
        playlist1 = Playlist(id=1, name="Rock")
        playlist2 = Playlist(id=2, name="Jazz")
        db.playlists = [playlist1, playlist2]

        assert db.get_playlist_by_name("Rock") is playlist1
        assert db.get_playlist_by_name("Jazz") is playlist2
        assert db.get_playlist_by_name("Pop") is None

    def test_get_master_playlist(self) -> None:
        """Test finding the master playlist."""
        db = Database()
        master = Playlist(id=1, name="Library", is_master=True)
        user = Playlist(id=2, name="My Music")
        db.playlists = [master, user]

        assert db.get_master_playlist() is master

    def test_get_master_playlist_not_found(self) -> None:
        """Test when no master playlist exists."""
        db = Database()
        db.playlists = [Playlist(id=1, name="User Playlist")]

        assert db.get_master_playlist() is None

    def test_next_track_id_empty(self) -> None:
        """Test next track ID with empty database."""
        db = Database()

        assert db.next_track_id() == 1

    def test_next_track_id_with_tracks(self) -> None:
        """Test next track ID with existing tracks."""
        db = Database()
        db.tracks = [
            Track(id=1, title="A", artist="B", album="C"),
            Track(id=5, title="D", artist="E", album="F"),
            Track(id=3, title="G", artist="H", album="I"),
        ]

        assert db.next_track_id() == 6

    def test_next_playlist_id_empty(self) -> None:
        """Test next playlist ID with empty database."""
        db = Database()

        assert db.next_playlist_id() == 1

    def test_next_playlist_id_with_playlists(self) -> None:
        """Test next playlist ID with existing playlists."""
        db = Database()
        db.playlists = [
            Playlist(id=1, name="A"),
            Playlist(id=10, name="B"),
            Playlist(id=5, name="C"),
        ]

        assert db.next_playlist_id() == 11
