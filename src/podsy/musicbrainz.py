"""MusicBrainz Cover Art Archive client module.

This module provides functions to search for album releases on MusicBrainz and download
cover art from the Cover Art Archive. It implements rate limiting (1 request per second)
as required by MusicBrainz API policy.

Example:
    >>> cover_bytes = fetch_cover_art("Radiohead", "OK Computer")
    >>> if cover_bytes:
    ...     # Save or display the cover art
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Final, TypedDict


class AlbumTrackInfo(TypedDict):
    title: str
    artist: str
    disc_number: int
    track_number: int
    total_tracks: int


class AlbumMetadata(TypedDict, total=False):
    album: str
    album_artist: str
    year: int
    total_discs: int
    tracks: list[AlbumTrackInfo]

__all__ = [
    "MusicBrainzError",
    "search_release",
    "search_recording",
    "fetch_track_metadata",
    "fetch_album_metadata",
    "lookup_release",
    "download_cover_art",
    "fetch_cover_art",
]

logger = logging.getLogger(__name__)

USER_AGENT: Final = "Podsy/0.1.0 (https://github.com/mescam/podsy)"
MUSICBRAINZ_API_BASE: Final = "https://musicbrainz.org/ws/2/release/"
MUSICBRAINZ_RECORDING_BASE: Final = "https://musicbrainz.org/ws/2/recording/"
COVER_ART_ARCHIVE_BASE: Final = "https://coverartarchive.org/release/"
RATE_LIMIT_SECONDS: Final = 1.0

_last_request_time: float = 0.0


class MusicBrainzError(Exception):
    """Base exception for MusicBrainz-related errors."""

    pass


def _rate_limit() -> None:
    """Ensure at least RATE_LIMIT_SECONDS seconds pass between requests.

    This function sleeps if necessary to respect MusicBrainz's rate limit policy.
    """
    global _last_request_time
    current_time = time.monotonic()
    time_since_last = current_time - _last_request_time
    if time_since_last < RATE_LIMIT_SECONDS:
        sleep_time = RATE_LIMIT_SECONDS - time_since_last
        logger.debug("Rate limiting: sleeping %.2f seconds", sleep_time)
        time.sleep(sleep_time)
    _last_request_time = time.monotonic()


def _make_request(url: str, *, timeout: int = 10) -> bytes | None:
    """Make an HTTP GET request with proper headers and error handling.

    Args:
        url: The URL to request.
        timeout: Request timeout in seconds. Defaults to 10.

    Returns:
        Response body as bytes, or None if the request fails.
    """
    _rate_limit()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.debug("Resource not found: %s", url)
        else:
            logger.error("HTTP error %s for %s: %s", e.code, url, e.reason)
        return None
    except urllib.error.URLError as e:
        logger.error("URL error for %s: %s", url, e.reason)
        return None
    except TimeoutError:
        logger.error("Timeout while requesting %s", url)
        return None
    except Exception as e:
        logger.error("Unexpected error requesting %s: %s", url, e)
        return None


def search_release(
    artist: str,
    album: str,
    *,
    timeout: int = 10,
    expected_track_count: int = 0,
) -> str | None:
    """Search MusicBrainz for a release by artist and album name.

    Args:
        artist: The artist name to search for.
        album: The album/release name to search for.
        timeout: Request timeout in seconds. Defaults to 10.
        expected_track_count: If > 0, prefer releases whose total track count
            across all media is >= this value and closest to it.

    Returns:
        The MusicBrainz ID (MBID) of the best matching release, or None if not found.
    """
    query = f'artist:{artist} AND release:{album}'
    encoded_query = urllib.parse.quote_plus(query)
    url = f"{MUSICBRAINZ_API_BASE}?query={encoded_query}&fmt=json&limit=10"

    logger.debug("Searching MusicBrainz for artist=%s, album=%s", artist, album)
    response_bytes = _make_request(url, timeout=timeout)
    if response_bytes is None:
        return None

    try:
        data = json.loads(response_bytes.decode("utf-8"))
        releases = data.get("releases", [])
        if not releases:
            logger.debug("No releases found for artist=%s, album=%s", artist, album)
            return None

        album_lower = album.lower()
        scored: list[tuple[int, dict]] = []
        for rel in releases:
            score = 0
            if rel.get("title", "").lower() == album_lower:
                score += 100
            if rel.get("status") == "Official":
                score += 20
            rg = rel.get("release-group", {}) or {}
            if rg.get("primary-type") == "Album":
                score += 10
            secondary = rg.get("secondary-types") or []
            if "Compilation" in secondary:
                score -= 30
            if "Live" in secondary:
                score -= 20
            if expected_track_count > 0:
                total = sum(m.get("track-count", 0) for m in rel.get("media", []))
                if total == expected_track_count:
                    score += 50
                elif total >= expected_track_count:
                    score += max(0, 25 - (total - expected_track_count))
            score += int(rel.get("score", 0)) // 20
            scored.append((score, rel))

        scored.sort(key=lambda x: x[0], reverse=True)
        mbid = scored[0][1].get("id")
        logger.debug("Found release MBID: %s (score=%d)", mbid, scored[0][0])
        return mbid
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON response: %s", e)
        return None
    except (KeyError, IndexError) as e:
        logger.error("Unexpected response structure: %s", e)
        return None


def download_cover_art(mbid: str, *, timeout: int = 10) -> bytes | None:
    """Download front cover art for a MusicBrainz release.

    Args:
        mbid: The MusicBrainz ID (MBID) of the release.
        timeout: Request timeout in seconds. Defaults to 10.

    Returns:
        Raw image bytes, or None if cover art is not available or download fails.
    """
    logger.debug("Fetching cover art metadata for MBID: %s", mbid)
    metadata_url = f"{COVER_ART_ARCHIVE_BASE}{mbid}/"
    response_bytes = _make_request(metadata_url, timeout=timeout)
    if response_bytes is None:
        return None

    try:
        data = json.loads(response_bytes.decode("utf-8"))
        images = data.get("images", [])
        if not images:
            logger.debug("No images found for MBID: %s", mbid)
            return None

        front_image = None
        for image in images:
            if image.get("front") is True:
                front_image = image
                break

        if front_image is None:
            front_image = images[0]
            logger.debug("No explicit front image, using first image")

        thumbnails = front_image.get("thumbnails", {})
        image_url = thumbnails.get("500") or thumbnails.get("1200") or front_image.get("image")
        if not image_url:
            logger.error("No image URL found in response for MBID: %s", mbid)
            return None

        logger.debug("Downloading cover art from: %s", image_url)
        image_bytes = _make_request(image_url, timeout=timeout)
        return image_bytes
    except json.JSONDecodeError as e:
        logger.error("Failed to parse cover art metadata JSON: %s", e)
        return None
    except (KeyError, IndexError) as e:
        logger.error("Unexpected cover art response structure: %s", e)
        return None


def search_recording(
    artist: str, title: str, *, timeout: int = 10
) -> dict[str, str | int] | None:
    """Search MusicBrainz for a recording by artist and title.

    Returns a dict with corrected metadata fields from the best match, or None
    if no match is found. Returned fields may include: title, artist, album,
    album_artist, track_number, total_tracks, disc_number, total_discs, year.
    """
    query = f"artist:{artist} AND recording:{title}"
    encoded_query = urllib.parse.quote_plus(query)
    url = (
        f"{MUSICBRAINZ_RECORDING_BASE}"
        f"?query={encoded_query}&fmt=json&limit=10"
        f"&inc=releases+media+artist-credits"
    )

    logger.debug("Searching MusicBrainz recording for artist=%s, title=%s", artist, title)
    response_bytes = _make_request(url, timeout=timeout)
    if response_bytes is None:
        return None

    try:
        data = json.loads(response_bytes.decode("utf-8"))
        recordings = data.get("recordings", [])
        if not recordings:
            logger.debug("No recordings found for artist=%s, title=%s", artist, title)
            return None
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Failed to parse recording search response: %s", e)
        return None

    best: dict[str, str | int] = {}
    best_score = -1

    for rec in recordings:
        score = 0
        metadata: dict[str, str | int] = {}

        mb_score = rec.get("score", 0)
        if mb_score < 50:
            continue

        rec_title = rec.get("title", "")
        if rec_title:
            metadata["title"] = rec_title
            if rec_title.lower() == title.lower():
                score += 10
            elif title.lower() in rec_title.lower() or rec_title.lower() in title.lower():
                score += 5

        artist_credits = rec.get("artist-credit", [])
        if artist_credits:
            artist_name = (
                artist_credits[0].get("name", "")
                or artist_credits[0].get("artist", {}).get("name", "")
            )
            if artist_name:
                metadata["artist"] = artist_name
                if artist_name.lower() == artist.lower():
                    score += 10
                elif artist.lower() in artist_name.lower():
                    score += 5
            if len(artist_credits) == 1:
                metadata["album_artist"] = artist_name

        releases = rec.get("releases", [])
        release = _pick_best_release(releases)
        if release:
            release_title = release.get("title", "")
            if release_title:
                metadata["album"] = release_title

            release_date = release.get("date", "")
            if release_date:
                with contextlib.suppress(ValueError):
                    metadata["year"] = int(release_date[:4])

            media = release.get("media", [])
            if media:
                medium = media[0]
                track_count = medium.get("track-count", 0)
                if track_count:
                    metadata["total_tracks"] = track_count

                metadata["disc_number"] = medium.get("position", 1)

                track_number = _find_track_position(medium.get("track", []), rec)
                if track_number:
                    metadata["track_number"] = track_number

        score += mb_score // 10

        if score > best_score:
            best_score = score
            best = metadata

    if best_score <= 0:
        logger.debug("No confident match for artist=%s, title=%s", artist, title)
        return None

    logger.debug("Best recording match for %s - %s: score=%d", artist, title, best_score)
    return best if best else None


def _pick_best_release(releases: list[dict]) -> dict | None:
    """Prefer official album releases over bootlegs/soundtracks."""
    if not releases:
        return None

    official = [
        r for r in releases
        if r.get("status") in ("Official", None)
        and r.get("release-group", {}).get("primary-type") == "Album"
    ]
    if official:
        return official[0]

    any_official = [r for r in releases if r.get("status") == "Official"]
    if any_official:
        return any_official[0]

    return releases[0]


def _find_track_position(tracks: list[dict], recording: dict) -> int | None:
    """Find track number for a recording within a medium's track list."""
    rec_title = (recording.get("title") or "").lower()
    rec_id = recording.get("id", "")

    for track in tracks:
        if track.get("id") == rec_id:
            pos = track.get("position")
            if pos:
                return pos
            num = track.get("number")
            if num:
                with contextlib.suppress(ValueError):
                    return int(num)
        if rec_title and track.get("title", "").lower() == rec_title:
            pos = track.get("position")
            if pos:
                return pos
            num = track.get("number")
            if num:
                with contextlib.suppress(ValueError):
                    return int(num)
    return None


def fetch_track_metadata(
    artist: str, title: str, *, album: str = "", timeout: int = 10
) -> dict[str, str | int] | None:
    """Look up corrected track metadata from MusicBrainz.

    Uses a two-step approach:
    1. Search for the recording by artist + title.
    2. If album is provided, also search for the release and match.

    Args:
        artist: Current artist name (may be incorrect).
        title: Current track title (may be incorrect).
        album: Current album name (optional, improves accuracy).
        timeout: Request timeout in seconds.

    Returns:
        Dict with corrected metadata fields, or None if not found.
    """
    logger.info("Fetching track metadata for %s - %s (album: %s)", artist, title, album or "N/A")
    result = search_recording(artist, title, timeout=timeout)
    if result is None:
        logger.debug("No recording match for %s - %s", artist, title)
        return None

    if album:
        mbid = search_release(artist, album, timeout=timeout)
        if mbid:
            result["album"] = album
            release_info = _lookup_release(mbid, timeout=timeout)
            if release_info:
                release_date = release_info.get("date", "")
                if release_date:
                    with contextlib.suppress(ValueError):
                        result["year"] = int(release_date[:4])
                media = release_info.get("media", [])
                if media:
                    medium = media[0]
                    track_count = medium.get("track-count", 0)
                    if track_count:
                        result["total_tracks"] = track_count
                    track_number = _find_track_in_release(
                        medium.get("track", []), title
                    )
                    if track_number:
                        result["track_number"] = track_number

    if result:
        logger.info("Retagged %s - %s: %s", artist, title, result)
    return result


def fetch_album_metadata(
    artist: str,
    album: str,
    *,
    expected_track_count: int = 0,
    timeout: int = 10,
) -> AlbumMetadata | None:
    logger.info("Fetching album metadata for %s - %s", artist, album)
    mbid = search_release(
        artist, album, timeout=timeout, expected_track_count=expected_track_count
    )
    if not mbid:
        return None

    release = _lookup_release(mbid, timeout=timeout)
    if not release:
        return None

    media = release.get("media", []) or []
    if not media:
        return None

    tracks: list[AlbumTrackInfo] = []
    for medium in media:
        disc_number = medium.get("position", 1)
        total_tracks = medium.get("track-count", 0)
        for tr in medium.get("tracks", []) or []:
            recording = tr.get("recording", {}) or {}
            track_title = tr.get("title") or recording.get("title") or ""
            track_artist = ""
            credits = tr.get("artist-credit") or recording.get("artist-credit") or []
            if credits:
                track_artist = (
                    credits[0].get("name")
                    or credits[0].get("artist", {}).get("name")
                    or ""
                )
            pos = tr.get("position")
            if not pos:
                with contextlib.suppress(ValueError, TypeError):
                    pos = int(tr.get("number") or 0)
            if not pos:
                continue
            tracks.append(AlbumTrackInfo(
                title=track_title,
                artist=track_artist,
                disc_number=disc_number,
                track_number=pos,
                total_tracks=total_tracks,
            ))

    if not tracks:
        return None

    album_artist = ""
    credits = release.get("artist-credit") or []
    if credits:
        album_artist = (
            credits[0].get("name")
            or credits[0].get("artist", {}).get("name")
            or ""
        )

    result: AlbumMetadata = {
        "album": release.get("title") or album,
        "album_artist": album_artist or artist,
        "total_discs": len(media),
        "tracks": tracks,
    }

    release_date = release.get("date") or ""
    if release_date:
        with contextlib.suppress(ValueError):
            result["year"] = int(release_date[:4])

    logger.info(
        "Album metadata: %s - %s, %d discs, %d tracks",
        result["album_artist"], result["album"], result["total_discs"], len(tracks),
    )
    return result


def _lookup_release(mbid: str, *, timeout: int = 10) -> dict | None:
    """Look up a release by MBID to get full details including date and tracklist."""
    url = f"{MUSICBRAINZ_API_BASE}{mbid}?inc=recordings+artist-credits+release-groups&fmt=json"
    response_bytes = _make_request(url, timeout=timeout)
    if response_bytes is None:
        return None

    try:
        return json.loads(response_bytes.decode("utf-8"))
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Failed to parse release lookup response: %s", e)
        return None


def _find_track_in_release(tracks: list[dict], title: str) -> int | None:
    """Find track number by title match within a release's track list."""
    title_lower = title.lower()
    for track in tracks:
        if track.get("title", "").lower() == title_lower:
            pos = track.get("position")
            if pos:
                return pos
            num = track.get("number")
            if num:
                with contextlib.suppress(ValueError):
                    return int(num)
    for track in tracks:
        if title_lower in track.get("title", "").lower():
            pos = track.get("position")
            if pos:
                return pos
            num = track.get("number")
            if num:
                with contextlib.suppress(ValueError):
                    return int(num)
    return None


def fetch_cover_art(artist: str, album: str, *, timeout: int = 10) -> bytes | None:
    """Search for a release and download its cover art.

    Combines search_release() and download_cover_art() with rate limiting.

    Args:
        artist: The artist name to search for.
        album: The album/release name to search for.
        timeout: Request timeout in seconds. Defaults to 10.

    Returns:
        Raw image bytes, or None if the release or cover art is not found.
    """
    logger.info("Fetching cover art for %s - %s", artist, album)
    mbid = search_release(artist, album, timeout=timeout)
    if mbid is None:
        logger.debug("Release not found: %s - %s", artist, album)
        return None

    cover_bytes = download_cover_art(mbid, timeout=timeout)
    if cover_bytes is None:
        logger.debug("Cover art not available for MBID: %s", mbid)
        return None

    logger.info("Successfully fetched cover art for %s - %s", artist, album)
    return cover_bytes
