"""Tests for music synchronization engine."""

import tempfile
from pathlib import Path

import pytest

from podsy.db.models import Database, FileType, Playlist, Track
from podsy.device import IPodDevice, ensure_music_folders
from podsy.sync import (
    SUPPORTED_EXTENSIONS,
    UnsupportedFormatError,
    generate_filename,
    get_file_hash,
    get_track_file_path,
    remove_track,
    select_music_folder,
    sync_file,
)


class TestGenerateFilename:
    """Tests for filename generation."""

    def test_generate_filename_length(self) -> None:
        """Test that generated filename is 4 chars + extension."""
        result = generate_filename(".mp3")
        assert len(result) == 8  # 4 chars + ".mp3"
        assert result.endswith(".mp3")

    def test_generate_filename_uppercase(self) -> None:
        """Test that filename uses uppercase letters and digits."""
        result = generate_filename()
        assert len(result) == 4
        for char in result:
            assert char.isupper() or char.isdigit()

    def test_generate_filename_unique(self) -> None:
        """Test that generated filenames are likely unique."""
        filenames = {generate_filename(".mp3") for _ in range(100)}
        # Should be at least 95 unique (very high probability)
        assert len(filenames) >= 95


class TestSelectMusicFolder:
    """Tests for music folder selection."""

    def test_select_music_folder_empty(self) -> None:
        """Test selecting folder when all are empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            device = IPodDevice(
                mount_point=Path(tmpdir),
                model="iPod",
                db_path=Path(tmpdir) / "iTunesDB",
                music_dir=Path(tmpdir) / "Music",
            )
            ensure_music_folders(device)

            folder = select_music_folder(device)

            # Should return F00 for empty
            assert folder == device.music_dir / "F00"

    def test_select_music_folder_load_balance(self) -> None:
        """Test that folder with fewest files is selected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            device = IPodDevice(
                mount_point=Path(tmpdir),
                model="iPod",
                db_path=Path(tmpdir) / "iTunesDB",
                music_dir=Path(tmpdir) / "Music",
            )
            ensure_music_folders(device)

            # Add files to F00-F09
            for i in range(10):
                folder = device.music_dir / f"F{i:02d}"
                for j in range(5):
                    (folder / f"file{j}.mp3").touch()

            # F10 should be selected (it's empty)
            folder = select_music_folder(device)
            assert folder == device.music_dir / "F10"


class TestGetFileHash:
    """Tests for file hashing."""

    def test_get_file_hash(self) -> None:
        """Test getting MD5 hash of a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_bytes(b"Hello, World!")

            hash1 = get_file_hash(test_file)

            # MD5 hash is 32 hex characters
            assert len(hash1) == 32
            assert all(c in "0123456789abcdef" for c in hash1)

    def test_get_file_hash_same_content(self) -> None:
        """Test that same content produces same hash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "file1.txt"
            file2 = Path(tmpdir) / "file2.txt"

            file1.write_bytes(b"Same content")
            file2.write_bytes(b"Same content")

            assert get_file_hash(file1) == get_file_hash(file2)

    def test_get_file_hash_different_content(self) -> None:
        """Test that different content produces different hash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "file1.txt"
            file2 = Path(tmpdir) / "file2.txt"

            file1.write_bytes(b"Content A")
            file2.write_bytes(b"Content B")

            assert get_file_hash(file1) != get_file_hash(file2)


class TestSupportedExtensions:
    """Tests for supported file extensions."""

    def test_mp3_supported(self) -> None:
        """Test that MP3 is supported."""
        assert ".mp3" in SUPPORTED_EXTENSIONS
        assert SUPPORTED_EXTENSIONS[".mp3"] == FileType.MP3

    def test_m4a_supported(self) -> None:
        """Test that M4A is supported."""
        assert ".m4a" in SUPPORTED_EXTENSIONS
        assert SUPPORTED_EXTENSIONS[".m4a"] == FileType.M4A

    def test_aac_supported(self) -> None:
        """Test that AAC is supported."""
        assert ".aac" in SUPPORTED_EXTENSIONS
        assert SUPPORTED_EXTENSIONS[".aac"] == FileType.AAC

    def test_flac_not_supported(self) -> None:
        """Test that FLAC is not supported."""
        assert ".flac" not in SUPPORTED_EXTENSIONS

    def test_wav_not_supported(self) -> None:
        """Test that WAV is not in supported (iPod 5.5g doesn't support WAV well)."""
        # Note: We might want to add WAV support, but it's not in current mapping
        assert ".wav" not in SUPPORTED_EXTENSIONS


class TestRemoveTrack:
    """Tests for track removal."""

    def test_remove_track_deletes_file(self) -> None:
        """Test that removing track deletes the file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mount = Path(tmpdir)
            music_dir = mount / "iPod_Control" / "Music" / "F00"
            music_dir.mkdir(parents=True)

            # Create a fake music file
            music_file = music_dir / "TEST.mp3"
            music_file.write_bytes(b"fake mp3 data")

            device = IPodDevice(
                mount_point=mount,
                model="iPod",
                db_path=mount / "iPod_Control" / "iTunes" / "iTunesDB",
                music_dir=mount / "iPod_Control" / "Music",
            )

            db = Database()
            track = Track(
                id=1,
                title="Test",
                artist="Artist",
                album="Album",
                path=":iPod_Control:Music:F00:TEST.mp3",
            )
            db.tracks = [track]

            remove_track(device, db, track)

            assert not music_file.exists()
            assert len(db.tracks) == 0

    def test_remove_track_from_playlists(self) -> None:
        """Test that removing track removes from all playlists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mount = Path(tmpdir)

            device = IPodDevice(
                mount_point=mount,
                model="iPod",
                db_path=mount / "iTunesDB",
                music_dir=mount / "Music",
            )

            db = Database()
            track = Track(
                id=1,
                title="Test",
                artist="Artist",
                album="Album",
                path=":iPod_Control:Music:F00:TEST.mp3",
            )
            db.tracks = [track]
            db.playlists = [
                Playlist(id=1, name="Library", is_master=True, track_ids=[1]),
                Playlist(id=2, name="Favorites", track_ids=[1]),
            ]

            remove_track(device, db, track)

            assert len(db.tracks) == 0
            assert db.playlists[0].track_ids == []
            assert db.playlists[1].track_ids == []

    def test_remove_track_nonexistent_file(self) -> None:
        """Test that removing track with nonexistent file doesn't error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mount = Path(tmpdir)

            device = IPodDevice(
                mount_point=mount,
                model="iPod",
                db_path=mount / "iTunesDB",
                music_dir=mount / "Music",
            )

            db = Database()
            track = Track(
                id=1,
                title="Test",
                artist="Artist",
                album="Album",
                path=":iPod_Control:Music:F00:GONE.mp3",
            )
            db.tracks = [track]

            # Should not raise
            remove_track(device, db, track)
            assert len(db.tracks) == 0


class TestGetTrackFilePath:
    """Tests for getting track file path."""

    def test_get_track_file_path_exists(self) -> None:
        """Test getting path when file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mount = Path(tmpdir)
            music_dir = mount / "iPod_Control" / "Music" / "F00"
            music_dir.mkdir(parents=True)

            music_file = music_dir / "TEST.mp3"
            music_file.touch()

            device = IPodDevice(
                mount_point=mount,
                model="iPod",
                db_path=mount / "iTunesDB",
                music_dir=mount / "iPod_Control" / "Music",
            )

            track = Track(
                id=1,
                title="Test",
                artist="Artist",
                album="Album",
                path=":iPod_Control:Music:F00:TEST.mp3",
            )

            result = get_track_file_path(device, track)

            assert result == music_file

    def test_get_track_file_path_not_exists(self) -> None:
        """Test getting path when file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            device = IPodDevice(
                mount_point=Path(tmpdir),
                model="iPod",
                db_path=Path(tmpdir) / "iTunesDB",
                music_dir=Path(tmpdir) / "Music",
            )

            track = Track(
                id=1,
                title="Test",
                artist="Artist",
                album="Album",
                path=":iPod_Control:Music:F00:MISSING.mp3",
            )

            result = get_track_file_path(device, track)

            assert result is None

    def test_get_track_file_path_no_path(self) -> None:
        """Test getting path when track has no path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            device = IPodDevice(
                mount_point=Path(tmpdir),
                model="iPod",
                db_path=Path(tmpdir) / "iTunesDB",
                music_dir=Path(tmpdir) / "Music",
            )

            track = Track(
                id=1,
                title="Test",
                artist="Artist",
                album="Album",
                path="",
            )

            result = get_track_file_path(device, track)

            assert result is None


class TestSyncFileErrors:
    """Tests for sync_file error handling."""

    def test_sync_file_unsupported_format(self) -> None:
        """Test syncing unsupported file format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mount = Path(tmpdir)
            source = Path(tmpdir) / "test.flac"
            source.touch()

            device = IPodDevice(
                mount_point=mount,
                model="iPod",
                db_path=mount / "iTunesDB",
                music_dir=mount / "Music",
            )

            db = Database()

            with pytest.raises(UnsupportedFormatError, match="Unsupported file format"):
                sync_file(device, db, source)
