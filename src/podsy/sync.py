"""Music synchronization engine for iPod.

This module handles copying music files to the iPod and registering
them in the iTunesDB.
"""

import contextlib
import hashlib
import random
import shutil
import string
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from mutagen import File as MutagenFile  # type: ignore[attr-defined]
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

from .db.models import Database, FileType, MediaType, Track
from .device import IPodDevice, ensure_music_folders


class SyncError(Exception):
    """Base exception for sync errors."""


class UnsupportedFormatError(SyncError):
    """Raised when file format is not supported by iPod."""


# Supported file extensions and their FileType mappings
SUPPORTED_EXTENSIONS: dict[str, FileType] = {
    ".mp3": FileType.MP3,
    ".m4a": FileType.M4A,
    ".m4p": FileType.M4P,
    ".aac": FileType.AAC,
    ".mp4": FileType.M4A,  # Audio-only MP4
}


def generate_filename(extension: str = "") -> str:
    """Generate a unique 4-character filename for iPod.

    Args:
        extension: File extension to append (e.g., ".mp3")

    Returns:
        Random 4-character filename with extension
    """
    chars = string.ascii_uppercase + string.digits
    name = "".join(random.choices(chars, k=4))
    return name + extension


def select_music_folder(device: IPodDevice) -> Path:
    """Select the music folder with the fewest files.

    Load-balances across F00-F49 folders to prevent any single
    folder from having too many files.

    Args:
        device: iPod device

    Returns:
        Path to the selected folder
    """
    ensure_music_folders(device)

    min_count = float("inf")
    selected = device.music_dir / "F00"

    for i in range(50):
        folder = device.music_dir / f"F{i:02d}"
        try:
            count = len(list(folder.iterdir()))
            if count < min_count:
                min_count = count
                selected = folder
        except OSError:
            continue

    return selected


def get_file_hash(path: Path) -> str:
    """Calculate MD5 hash of a file for duplicate detection.

    Args:
        path: Path to the file

    Returns:
        Hex-encoded MD5 hash
    """
    hasher = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_metadata(path: Path) -> dict[str, str | int]:
    """Read metadata from an audio file.

    Args:
        path: Path to the audio file

    Returns:
        Dictionary with metadata fields
    """
    metadata: dict[str, str | int] = {
        "title": path.stem,
        "artist": "",
        "album": "",
        "album_artist": "",
        "genre": "",
        "composer": "",
        "comment": "",
        "track_number": 0,
        "total_tracks": 0,
        "disc_number": 1,
        "total_discs": 1,
        "year": 0,
        "duration_ms": 0,
        "bitrate": 0,
        "sample_rate": 44100,
    }

    try:
        audio = MutagenFile(path)
        if audio is None:
            return metadata

        # Get duration and bitrate
        if hasattr(audio, "info"):
            info = audio.info
            if hasattr(info, "length"):
                metadata["duration_ms"] = int(info.length * 1000)
            if hasattr(info, "bitrate"):
                metadata["bitrate"] = int(info.bitrate / 1000)  # kbps
            if hasattr(info, "sample_rate"):
                metadata["sample_rate"] = int(info.sample_rate)

        # Handle MP3 files
        if isinstance(audio, MP3):
            try:
                tags = EasyID3(path)
                _extract_easy_tags(tags, metadata)
            except Exception:
                # Try raw ID3
                try:
                    id3 = ID3(path)
                    _extract_id3_tags(id3, metadata)
                except Exception:
                    pass

        # Handle MP4/M4A files
        elif isinstance(audio, MP4):
            _extract_mp4_tags(audio, metadata)

        # Generic mutagen handling
        elif hasattr(audio, "tags") and audio.tags:
            _extract_generic_tags(audio.tags, metadata)

    except Exception:
        # If all else fails, just use filename
        pass

    return metadata


def _extract_easy_tags(tags: EasyID3, metadata: dict[str, str | int]) -> None:
    """Extract metadata from EasyID3 tags."""
    if "title" in tags and tags["title"]:
        metadata["title"] = tags["title"][0]
    if "artist" in tags and tags["artist"]:
        metadata["artist"] = tags["artist"][0]
    if "album" in tags and tags["album"]:
        metadata["album"] = tags["album"][0]
    if "albumartist" in tags and tags["albumartist"]:
        metadata["album_artist"] = tags["albumartist"][0]
    if "genre" in tags and tags["genre"]:
        metadata["genre"] = tags["genre"][0]
    if "composer" in tags and tags["composer"]:
        metadata["composer"] = tags["composer"][0]
    if "date" in tags and tags["date"]:
        with contextlib.suppress(ValueError, IndexError):
            metadata["year"] = int(tags["date"][0][:4])
    if "tracknumber" in tags and tags["tracknumber"]:
        tn = tags["tracknumber"][0]
        if "/" in tn:
            num, total = tn.split("/", 1)
            metadata["track_number"] = int(num)
            metadata["total_tracks"] = int(total)
        else:
            metadata["track_number"] = int(tn)
    if "discnumber" in tags and tags["discnumber"]:
        dn = tags["discnumber"][0]
        if "/" in dn:
            num, total = dn.split("/", 1)
            metadata["disc_number"] = int(num)
            metadata["total_discs"] = int(total)
        else:
            metadata["disc_number"] = int(dn)


def _extract_id3_tags(id3: ID3, metadata: dict[str, str | int]) -> None:
    """Extract metadata from raw ID3 tags."""
    if "TIT2" in id3:
        metadata["title"] = str(id3["TIT2"])
    if "TPE1" in id3:
        metadata["artist"] = str(id3["TPE1"])
    if "TALB" in id3:
        metadata["album"] = str(id3["TALB"])
    if "TPE2" in id3:
        metadata["album_artist"] = str(id3["TPE2"])
    if "TCON" in id3:
        metadata["genre"] = str(id3["TCON"])
    if "TCOM" in id3:
        metadata["composer"] = str(id3["TCOM"])
    if "TDRC" in id3:
        with contextlib.suppress(ValueError, IndexError):
            metadata["year"] = int(str(id3["TDRC"])[:4])
    if "TRCK" in id3:
        tn = str(id3["TRCK"])
        if "/" in tn:
            num, total = tn.split("/", 1)
            metadata["track_number"] = int(num)
            metadata["total_tracks"] = int(total)
        else:
            metadata["track_number"] = int(tn)


def _extract_mp4_tags(audio: MP4, metadata: dict[str, str | int]) -> None:
    """Extract metadata from MP4/M4A tags."""
    tags = audio.tags
    if not tags:
        return

    if "\xa9nam" in tags:
        metadata["title"] = tags["\xa9nam"][0]
    if "\xa9ART" in tags:
        metadata["artist"] = tags["\xa9ART"][0]
    if "\xa9alb" in tags:
        metadata["album"] = tags["\xa9alb"][0]
    if "aART" in tags:
        metadata["album_artist"] = tags["aART"][0]
    if "\xa9gen" in tags:
        metadata["genre"] = tags["\xa9gen"][0]
    if "\xa9wrt" in tags:
        metadata["composer"] = tags["\xa9wrt"][0]
    if "\xa9cmt" in tags:
        metadata["comment"] = tags["\xa9cmt"][0]
    if "\xa9day" in tags:
        with contextlib.suppress(ValueError, IndexError):
            metadata["year"] = int(str(tags["\xa9day"][0])[:4])
    if "trkn" in tags:
        track_info = tags["trkn"][0]
        if isinstance(track_info, tuple):
            metadata["track_number"] = track_info[0]
            if len(track_info) > 1:
                metadata["total_tracks"] = track_info[1]
    if "disk" in tags:
        disc_info = tags["disk"][0]
        if isinstance(disc_info, tuple):
            metadata["disc_number"] = disc_info[0]
            if len(disc_info) > 1:
                metadata["total_discs"] = disc_info[1]


def _extract_generic_tags(
    tags: dict[str, list[str]] | object, metadata: dict[str, str | int]
) -> None:
    """Extract metadata from generic tag format."""
    tag_dict: dict[str, list[str]] = {}
    if isinstance(tags, dict):
        tag_dict = tags
    elif hasattr(tags, "items"):
        tag_dict = dict(tags.items())  # type: ignore[union-attr]

    for key, value in tag_dict.items():
        key_lower = key.lower()
        val = str(value[0]) if isinstance(value, list) and value else str(value)

        if "title" in key_lower and not metadata.get("title"):
            metadata["title"] = val
        elif "artist" in key_lower and "album" not in key_lower:
            metadata["artist"] = val
        elif "album" in key_lower and "artist" not in key_lower:
            metadata["album"] = val


def sync_file(
    device: IPodDevice,
    db: Database,
    source: Path,
    *,
    check_duplicate: bool = True,
) -> Track:
    """Copy a music file to the iPod and register it in the database.

    Args:
        device: Target iPod device
        db: Database to update
        source: Source file path
        check_duplicate: Whether to check for existing tracks with same title/artist

    Returns:
        The created Track object

    Raises:
        UnsupportedFormatError: If the file format is not supported
        SyncError: If the sync operation fails
    """
    # Check file extension
    ext = source.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(f"Unsupported file format: {ext}")

    file_type = SUPPORTED_EXTENSIONS[ext]

    # Read metadata
    metadata = read_metadata(source)

    # Check for duplicates
    if check_duplicate:
        for existing in db.tracks:
            if (
                existing.title == metadata["title"]
                and existing.artist == metadata["artist"]
                and existing.album == metadata["album"]
            ):
                raise SyncError(f"Track already exists: {metadata['artist']} - {metadata['title']}")

    # Select destination folder and generate filename
    dest_folder = select_music_folder(device)
    dest_filename = generate_filename(ext)
    dest_path = dest_folder / dest_filename

    # Ensure unique filename
    while dest_path.exists():
        dest_filename = generate_filename(ext)
        dest_path = dest_folder / dest_filename

    # Copy file
    try:
        shutil.copy2(source, dest_path)
    except OSError as e:
        raise SyncError(f"Failed to copy file: {e}") from e

    # Create iPod path format (relative to mount point with colons)
    folder_name = dest_folder.name
    ipod_path = f":iPod_Control:Music:{folder_name}:{dest_filename}"

    # Create track
    track = Track(
        id=db.next_track_id(),
        title=str(metadata["title"]),
        artist=str(metadata["artist"]),
        album=str(metadata["album"]),
        album_artist=str(metadata.get("album_artist", "")),
        genre=str(metadata.get("genre", "")),
        composer=str(metadata.get("composer", "")),
        comment=str(metadata.get("comment", "")),
        path=ipod_path,
        duration_ms=int(metadata.get("duration_ms", 0)),
        bitrate=int(metadata.get("bitrate", 0)),
        sample_rate=int(metadata.get("sample_rate", 44100)),
        size_bytes=dest_path.stat().st_size,
        track_number=int(metadata.get("track_number", 0)),
        total_tracks=int(metadata.get("total_tracks", 0)),
        disc_number=int(metadata.get("disc_number", 1)),
        total_discs=int(metadata.get("total_discs", 1)),
        year=int(metadata.get("year", 0)),
        file_type=file_type,
        media_type=MediaType.AUDIO,
        date_added=datetime.now(),
    )

    # Add to database
    db.tracks.append(track)

    # Add to master playlist
    master = db.get_master_playlist()
    if master:
        master.track_ids.append(track.id)

    return track


def remove_track(device: IPodDevice, db: Database, track: Track) -> None:
    """Remove a track from the iPod.

    Deletes the file and removes the track from the database.

    Args:
        device: iPod device
        db: Database to update
        track: Track to remove
    """
    # Convert iPod path to filesystem path
    if track.path:
        # :iPod_Control:Music:F00:ABCD.mp3 -> iPod_Control/Music/F00/ABCD.mp3
        rel_path = track.path.lstrip(":").replace(":", "/")
        file_path = device.mount_point / rel_path

        # Delete file if it exists
        with contextlib.suppress(OSError):
            if file_path.exists():
                file_path.unlink()

    # Remove from database
    db.tracks = [t for t in db.tracks if t.id != track.id]

    # Remove from all playlists
    for playlist in db.playlists:
        playlist.track_ids = [tid for tid in playlist.track_ids if tid != track.id]


class SyncProgressCallback(Protocol):
    """Protocol for sync progress callbacks."""

    def __call__(
        self,
        current: int,
        total: int,
        filename: str,
        *,
        error: str | None = None,
    ) -> None:
        """Report sync progress.

        Args:
            current: Current file number (1-indexed)
            total: Total number of files
            filename: Name of the file being processed
            error: Error message if this file failed, None if successful
        """
        ...


def sync_folder(
    device: IPodDevice,
    db: Database,
    folder: Path,
    *,
    recursive: bool = True,
    create_playlist: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[Track]:
    """Sync all music files from a folder to the iPod.

    Args:
        device: Target iPod device
        db: Database to update
        folder: Source folder path
        recursive: Whether to process subfolders
        create_playlist: Whether to create a playlist with the folder name
        progress_callback: Optional callback(current, total, filename) for progress

    Returns:
        List of successfully synced Track objects
    """
    from .playlists import DuplicatePlaylistError
    from .playlists import create_playlist as make_playlist

    synced: list[Track] = []
    errors: list[tuple[Path, str]] = []

    # Collect files
    files = list(folder.rglob("*")) if recursive else list(folder.iterdir())

    # Filter to supported formats
    music_files = [f for f in files if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS]

    # Sort by path for consistent ordering
    music_files.sort()

    total = len(music_files)
    for i, file in enumerate(music_files, 1):
        if progress_callback:
            progress_callback(i, total, file.name)

        try:
            track = sync_file(device, db, file, check_duplicate=True)
            synced.append(track)
        except SyncError as e:
            errors.append((file, str(e)))
        except Exception as e:
            errors.append((file, f"Unexpected error: {e}"))

    # Create playlist if requested and we synced some tracks
    if create_playlist and synced:
        playlist_name = folder.name
        # Find a unique name if needed
        base_name = playlist_name
        counter = 1
        while db.get_playlist_by_name(playlist_name) is not None:
            counter += 1
            playlist_name = f"{base_name} ({counter})"

        try:
            playlist = make_playlist(db, playlist_name)
            for track in synced:
                playlist.track_ids.append(track.id)
        except DuplicatePlaylistError:
            # Should not happen due to check above, but handle gracefully
            pass

    return synced


def get_track_file_path(device: IPodDevice, track: Track) -> Path | None:
    """Get the filesystem path for a track's audio file.

    Args:
        device: iPod device
        track: Track to locate

    Returns:
        Path to the file, or None if not found
    """
    if not track.path:
        return None

    # Convert iPod path to filesystem path
    rel_path = track.path.lstrip(":").replace(":", "/")
    file_path = device.mount_point / rel_path

    if file_path.exists():
        return file_path
    return None
