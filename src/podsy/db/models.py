"""Data models for iTunesDB structures."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


class MediaType(IntEnum):
    """Media type flags for tracks."""

    AUDIO_VIDEO = 0x00000000  # Shows in both Audio and Video
    AUDIO = 0x00000001
    VIDEO = 0x00000002
    PODCAST = 0x00000004
    VIDEO_PODCAST = 0x00000006
    AUDIOBOOK = 0x00000008
    MUSIC_VIDEO = 0x00000020
    TV_SHOW = 0x00000040


class FileType(IntEnum):
    """Audio file types (stored as reversed 4-byte ASCII)."""

    MP3 = 0x4D503320  # "MP3 " reversed
    AAC = 0x41414320  # "AAC " reversed
    M4A = 0x4D344120  # "M4A " reversed
    M4P = 0x4D345020  # "M4P " reversed
    WAV = 0x57415620  # "WAV " reversed


class MhodType(IntEnum):
    """MHOD (data object) type codes."""

    TITLE = 1
    LOCATION = 2
    ALBUM = 3
    ARTIST = 4
    GENRE = 5
    FILETYPE = 6
    EQ_SETTING = 7
    COMMENT = 8
    CATEGORY = 9
    COMPOSER = 12
    GROUPING = 13
    DESCRIPTION = 14
    PODCAST_ENCLOSURE_URL = 15
    PODCAST_RSS_URL = 16
    CHAPTER_DATA = 17
    SUBTITLE = 18
    TV_SHOW = 19
    TV_EPISODE = 20
    TV_NETWORK = 21
    ALBUM_ARTIST = 22
    SORT_ARTIST = 23
    KEYWORDS = 24
    SORT_TITLE = 27
    SORT_ALBUM = 28
    SORT_ALBUM_ARTIST = 29
    SORT_COMPOSER = 30
    SORT_TV_SHOW = 31
    SMART_PLAYLIST_DATA = 50
    SMART_PLAYLIST_RULES = 51
    LIBRARY_PLAYLIST_INDEX = 52
    PLAYLIST_COLUMN = 100


class SortOrder(IntEnum):
    """Playlist sort order values."""

    MANUAL = 1
    TITLE = 3
    ALBUM = 4
    ARTIST = 5
    BITRATE = 6
    GENRE = 7
    TIME = 12
    YEAR = 13
    PLAY_COUNT = 20
    LAST_PLAYED = 21
    RATING = 23
    RELEASE_DATE = 24


@dataclass
class Track:
    """Represents a single track in the iPod library."""

    id: int
    title: str
    artist: str
    album: str
    album_artist: str = ""
    genre: str = ""
    composer: str = ""
    comment: str = ""
    path: str = ""  # :iPod_Control:Music:F00:XXXX.mp3
    duration_ms: int = 0
    bitrate: int = 0
    sample_rate: int = 44100
    size_bytes: int = 0
    track_number: int = 0
    total_tracks: int = 0
    disc_number: int = 1
    total_discs: int = 1
    year: int = 0
    rating: int = 0  # 0-100 in steps of 20
    play_count: int = 0
    skip_count: int = 0
    date_added: datetime = field(default_factory=datetime.now)
    last_played: datetime | None = None
    last_modified: datetime = field(default_factory=datetime.now)
    file_type: FileType = FileType.MP3
    media_type: MediaType = MediaType.AUDIO
    compilation: bool = False
    dbid: int = 0  # 64-bit unique ID for artwork linking

    # Gapless playback fields
    pregap: int = 0
    postgap: int = 0
    sample_count: int = 0
    gapless_data: int = 0
    gapless_track_flag: bool = False
    gapless_album_flag: bool = False


@dataclass
class Playlist:
    """Represents a playlist on the iPod."""

    id: int
    name: str
    track_ids: list[int] = field(default_factory=list)
    is_master: bool = False
    is_podcast: bool = False
    sort_order: SortOrder = SortOrder.MANUAL
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Database:
    """Represents the entire iTunesDB."""

    version: int = 0x15  # Default to iTunes 7.2 format
    database_id: int = 0
    library_persistent_id: int = 0
    language: str = "en"
    tracks: list[Track] = field(default_factory=list)
    playlists: list[Playlist] = field(default_factory=list)

    def get_track_by_id(self, track_id: int) -> Track | None:
        """Find a track by its unique ID."""
        for track in self.tracks:
            if track.id == track_id:
                return track
        return None

    def get_playlist_by_id(self, playlist_id: int) -> Playlist | None:
        """Find a playlist by its ID."""
        for playlist in self.playlists:
            if playlist.id == playlist_id:
                return playlist
        return None

    def get_playlist_by_name(self, name: str) -> Playlist | None:
        """Find a playlist by name."""
        for playlist in self.playlists:
            if playlist.name == name:
                return playlist
        return None

    def get_master_playlist(self) -> Playlist | None:
        """Get the master (Library) playlist."""
        for playlist in self.playlists:
            if playlist.is_master:
                return playlist
        return None

    def next_track_id(self) -> int:
        """Generate the next available track ID."""
        if not self.tracks:
            return 1
        return max(t.id for t in self.tracks) + 1

    def next_playlist_id(self) -> int:
        """Generate the next available playlist ID."""
        if not self.playlists:
            return 1
        return max(p.id for p in self.playlists) + 1
