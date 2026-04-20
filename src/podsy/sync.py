"""Music synchronization engine for iPod.

This module handles copying music files to the iPod and registering
them in the iTunesDB.
"""

import contextlib
import hashlib
import logging
import random
import re
import shutil
import string
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from mutagen import File as MutagenFile  # type: ignore[attr-defined]
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

from .artwork import generate_artwork_formats, get_artwork_size, resolve_artwork
from .db.artworkdb import ArtworkDB, add_artwork_to_db
from .db.models import Database, FileType, MediaType, Track
from .device import IPodDevice, ensure_music_folders
from .musicbrainz import fetch_album_metadata, fetch_cover_art as fetch_mb_cover_art
from .musicbrainz import fetch_track_metadata
from .transcoder import TranscodingError, is_flac, transcode_flac_to_aac

logger = logging.getLogger(__name__)


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
    ".flac": FileType.M4A,  # FLAC files are transcoded to M4A
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
        "title": "",
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

        # Handle FLAC files (Vorbis comments)
        elif isinstance(audio, FLAC):
            _extract_vorbis_tags(audio, metadata)

        # Generic mutagen handling
        elif hasattr(audio, "tags") and audio.tags:
            _extract_generic_tags(audio.tags, metadata)

    except Exception:
        # If all else fails, just use filename
        pass

    if not metadata["title"]:
        metadata["title"] = path.stem

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


def _extract_vorbis_tags(audio: FLAC, metadata: dict[str, str | int]) -> None:
    """Extract metadata from FLAC Vorbis comments."""
    tags = audio.tags
    if tags is None:
        return

    VORBIS_MAP: dict[str, str] = {
        "title": "title",
        "artist": "artist",
        "album": "album",
        "albumartist": "album_artist",
        "genre": "genre",
        "composer": "composer",
        "comment": "comment",
        "date": "year",
    }

    for vorbis_key, meta_key in VORBIS_MAP.items():
        if vorbis_key in tags and tags[vorbis_key]:
            val = tags[vorbis_key][0]
            if meta_key == "year":
                with contextlib.suppress(ValueError, IndexError):
                    metadata["year"] = int(val[:4])
            else:
                metadata[meta_key] = val

    if "tracknumber" in tags and tags["tracknumber"]:
        tn = tags["tracknumber"][0]
        if "/" in tn:
            num, total = tn.split("/", 1)
            metadata["track_number"] = int(num)
            metadata["total_tracks"] = int(total)
        else:
            with contextlib.suppress(ValueError):
                metadata["track_number"] = int(tn)

    if "tracktotal" in tags and tags["tracktotal"]:
        with contextlib.suppress(ValueError):
            metadata["total_tracks"] = int(tags["tracktotal"][0])

    if "discnumber" in tags and tags["discnumber"]:
        dn = tags["discnumber"][0]
        if "/" in dn:
            num, total = dn.split("/", 1)
            metadata["disc_number"] = int(num)
            metadata["total_discs"] = int(total)
        else:
            with contextlib.suppress(ValueError):
                metadata["disc_number"] = int(dn)

    if "disctotal" in tags and tags["disctotal"]:
        with contextlib.suppress(ValueError):
            metadata["total_discs"] = int(tags["disctotal"][0])


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

        if "title" in key_lower and "album" not in key_lower:
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
    artwork_db: ArtworkDB | None = None,
) -> Track:
    """Copy a music file to the iPod and register it in the database.

    Args:
        device: Target iPod device
        db: Database to update
        source: Source file path
        check_duplicate: Whether to check for existing tracks with same title/artist
        artwork_db: Optional ArtworkDB for artwork storage

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

    # Handle FLAC transcoding
    _temp_file_to_cleanup: Path | None = None
    source_for_sync = source
    if is_flac(source):
        try:
            temp_m4a = transcode_flac_to_aac(source)
            source_for_sync = temp_m4a
            _temp_file_to_cleanup = temp_m4a
            ext = ".m4a"
            file_type = FileType.M4A
        except TranscodingError as e:
            raise SyncError(f"Failed to transcode FLAC file: {e}") from e

    try:
        # Read metadata from original file (FLAC Vorbis comments, not transcoded M4A)
        metadata = read_metadata(source)

        # Check for duplicates
        if check_duplicate:
            for existing in db.tracks:
                if (
                    existing.title == metadata["title"]
                    and existing.artist == metadata["artist"]
                    and existing.album == metadata["album"]
                ):
                    raise SyncError(
                        f"Track already exists: {metadata['artist']} - {metadata['title']}"
                    )

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
            shutil.copy2(source_for_sync, dest_path)
        except OSError as e:
            raise SyncError(f"Failed to copy file: {e}") from e

        # Create iPod path format (relative to mount point with colons)
        folder_name = dest_folder.name
        ipod_path = f":iPod_Control:Music:{folder_name}:{dest_filename}"

        # Calculate sample_count for gapless playback (required for iPod to not skip tracks)
        duration_ms = int(metadata.get("duration_ms", 0))
        sample_rate = int(metadata.get("sample_rate", 44100))
        if is_flac(source):
            sample_rate = 44100  # Transcoded M4A is always 44100 Hz
        sample_count = int((duration_ms / 1000.0) * sample_rate)

        # Generate unique dbid for artwork linking
        dbid = random.randint(1, 2**63 - 1)

        # Extract and process artwork
        has_artwork = False
        artwork_count = 0
        artwork_size = 0

        raw_artwork = resolve_artwork(source)
        if raw_artwork is None:
            metadata_for_art = read_metadata(source)
            artist = str(metadata_for_art.get("artist", ""))
            album = str(metadata_for_art.get("album", ""))
            if artist and album:
                raw_artwork = fetch_mb_cover_art(artist, album)
        if raw_artwork and artwork_db is not None:
            try:
                artwork_formats = generate_artwork_formats(raw_artwork)
                if artwork_formats:
                    add_artwork_to_db(
                        artwork_db,
                        device.artwork_dir,
                        dbid,
                        artwork_formats,
                    )
                    has_artwork = True
                    artwork_count = len(artwork_formats)
                    # Calculate total artwork size
                    for fmt_id in artwork_formats:
                        artwork_size += get_artwork_size(fmt_id)
            except Exception:
                # Artwork extraction failed, continue without artwork
                pass

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
            duration_ms=duration_ms,
            bitrate=int(metadata.get("bitrate", 0)),
            sample_rate=sample_rate,
            size_bytes=dest_path.stat().st_size,
            track_number=int(metadata.get("track_number", 0)),
            total_tracks=int(metadata.get("total_tracks", 0)),
            disc_number=int(metadata.get("disc_number", 1)),
            total_discs=int(metadata.get("total_discs", 1)),
            year=int(metadata.get("year", 0)),
            file_type=file_type,
            media_type=MediaType.AUDIO,
            date_added=datetime.now(),
            sample_count=sample_count,
            dbid=dbid,
            has_artwork=has_artwork,
            artwork_count=artwork_count,
            artwork_size=artwork_size,
        )

        # Add to database
        db.tracks.append(track)

        # Add to master playlist
        master = db.get_master_playlist()
        if master:
            master.track_ids.append(track.id)

        return track
    finally:
        if _temp_file_to_cleanup is not None:
            with contextlib.suppress(OSError):
                _temp_file_to_cleanup.unlink()


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


def retag_track(track: Track) -> bool:
    """Retag a track by looking up corrected metadata from MusicBrainz.

    Uses the track's current (possibly incorrect) metadata to search MusicBrainz
    and updates the track in-place with corrected fields.

    Args:
        track: The Track object to retag.

    Returns:
        True if metadata was updated, False if no match found.
    """
    artist = track.artist or ""
    title = track.title or ""
    album = track.album or ""

    if not title and not artist:
        logger.warning("Cannot retag track %d: no title or artist", track.id)
        return False

    # Strip leading track numbers like "07 - " or "07. " from titles
    # that came from filenames when tags weren't read correctly
    clean_title = re.sub(r"^\d{1,3}\s*[.\-\s]\s*", "", title)
    if clean_title and clean_title != title:
        logger.info("Stripped track number from title: %r -> %r", title, clean_title)
        title = clean_title

    result = fetch_track_metadata(artist, title, album=album)
    if result is None:
        logger.info("No MusicBrainz match for track %d: %s - %s", track.id, artist, title)
        return False

    updated = False
    if "title" in result and result["title"]:
        track.title = str(result["title"])
        updated = True
    if "artist" in result and result["artist"]:
        track.artist = str(result["artist"])
        updated = True
    if "album" in result and result["album"]:
        track.album = str(result["album"])
        updated = True
    if "album_artist" in result and result["album_artist"]:
        track.album_artist = str(result["album_artist"])
        updated = True
    if "genre" in result and result["genre"]:
        track.genre = str(result["genre"])
        updated = True

    new_total_tracks = int(result.get("total_tracks") or 0)
    new_track_number = int(result.get("track_number") or 0)
    new_disc_number = int(result.get("disc_number") or 0)
    new_total_discs = int(result.get("total_discs") or 0)

    numbers_look_valid = (
        new_track_number > 0
        and (new_total_tracks == 0 or new_track_number <= new_total_tracks)
        and (new_total_discs == 0 or new_disc_number <= new_total_discs)
    )
    if numbers_look_valid:
        if new_track_number:
            track.track_number = new_track_number
            updated = True
        if new_total_tracks:
            track.total_tracks = new_total_tracks
            updated = True
        if new_disc_number:
            track.disc_number = new_disc_number
            updated = True
        if new_total_discs:
            track.total_discs = new_total_discs
            updated = True
        if track.disc_number > track.total_discs:
            track.total_discs = track.disc_number
    else:
        logger.warning(
            "Rejected suspicious track numbers from MB for track %d: "
            "track=%d/%d disc=%d/%d (keeping original)",
            track.id, new_track_number, new_total_tracks,
            new_disc_number, new_total_discs,
        )

    if "year" in result and result["year"]:
        track.year = int(result["year"])
        updated = True

    if updated:
        logger.info("Retagged track %d: %s - %s", track.id, track.artist, track.title)
    return updated


def retag_album(tracks: list[Track]) -> int:
    if not tracks:
        return 0

    album = tracks[0].album or ""
    album_artist = tracks[0].album_artist or tracks[0].artist or ""
    if not album or not album_artist:
        logger.info("Falling back to per-track retag: missing album/artist")
        return sum(1 for t in tracks if retag_track(t))

    metadata = fetch_album_metadata(
        album_artist, album, expected_track_count=len(tracks)
    )
    if metadata is None or not metadata.get("tracks"):
        logger.info("No album match on MusicBrainz for %s - %s; per-track fallback",
                    album_artist, album)
        return sum(1 for t in tracks if retag_track(t))

    mb_tracks = metadata["tracks"]
    mb_by_title: dict[str, dict] = {}
    for mb in mb_tracks:
        key = _norm_title(mb.get("title", ""))
        if key:
            mb_by_title.setdefault(key, mb)

    updated_count = 0
    unmatched: list[Track] = []

    for track in tracks:
        current_title = _norm_title(track.title or "")
        clean_title = _norm_title(
            re.sub(r"^\d{1,3}\s*[.\-\s]\s*", "", track.title or "")
        )
        mb_match = mb_by_title.get(current_title) or mb_by_title.get(clean_title)
        if mb_match is None:
            for mb in mb_tracks:
                mb_key = _norm_title(mb.get("title", ""))
                if mb_key and (mb_key in current_title or current_title in mb_key):
                    mb_match = mb
                    break
        if mb_match is None:
            unmatched.append(track)
            continue

        if metadata.get("album"):
            track.album = str(metadata["album"])
        if metadata.get("album_artist"):
            track.album_artist = str(metadata["album_artist"])
        if metadata.get("year"):
            track.year = int(metadata["year"])
        if mb_match.get("title"):
            track.title = str(mb_match["title"])
        if mb_match.get("artist"):
            track.artist = str(mb_match["artist"])
        track.track_number = int(mb_match["track_number"])
        track.total_tracks = int(mb_match.get("total_tracks") or 0)
        track.disc_number = int(mb_match.get("disc_number") or 1)
        track.total_discs = int(metadata.get("total_discs") or 1)
        updated_count += 1
        logger.info("Retagged track %d (album-match): %s - %s",
                    track.id, track.artist, track.title)

    if unmatched:
        logger.warning("Album retag: %d tracks unmatched in release for %s - %s",
                       len(unmatched), album_artist, album)

    return updated_count


def _norm_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


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
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[Track]:
    """Sync all music files from a folder to the iPod.

    Args:
        device: Target iPod device
        db: Database to update
        folder: Source folder path
        recursive: Whether to process subfolders
        progress_callback: Optional callback(current, total, filename) for progress

    Returns:
        List of successfully synced Track objects
    """

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
