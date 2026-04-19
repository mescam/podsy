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

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Final

__all__ = [
    "MusicBrainzError",
    "search_release",
    "download_cover_art",
    "fetch_cover_art",
]

logger = logging.getLogger(__name__)

USER_AGENT: Final = "Podsy/0.1.0 (https://github.com/mescam/podsy)"
MUSICBRAINZ_API_BASE: Final = "https://musicbrainz.org/ws/2/release/"
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


def search_release(artist: str, album: str, *, timeout: int = 10) -> str | None:
    """Search MusicBrainz for a release by artist and album name.

    Args:
        artist: The artist name to search for.
        album: The album/release name to search for.
        timeout: Request timeout in seconds. Defaults to 10.

    Returns:
        The MusicBrainz ID (MBID) of the first matching release, or None if not found.
    """
    query = f'artist:{artist} AND release:{album}'
    encoded_query = urllib.parse.quote_plus(query)
    url = f"{MUSICBRAINZ_API_BASE}?query={encoded_query}&fmt=json&limit=5"

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
        mbid = releases[0].get("id")
        logger.debug("Found release MBID: %s", mbid)
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


def fetch_cover_art(artist: str, album: str, *, timeout: int = 10) -> bytes | None:
    """Convenience function to search for a release and download its cover art.

    This function combines search_release() and download_cover_art() with proper
    rate limiting between the two API calls.

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
