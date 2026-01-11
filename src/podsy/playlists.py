"""Playlist management for iPod.

This module provides functions for creating, modifying, and deleting
playlists on the iPod.
"""

from datetime import datetime

from .db.models import Database, Playlist, SortOrder


class PlaylistError(Exception):
    """Base exception for playlist operations."""


class PlaylistNotFoundError(PlaylistError):
    """Raised when a playlist is not found."""


class DuplicatePlaylistError(PlaylistError):
    """Raised when trying to create a playlist with an existing name."""


def create_playlist(
    db: Database,
    name: str,
    *,
    sort_order: SortOrder = SortOrder.MANUAL,
) -> Playlist:
    """Create a new empty playlist.

    Args:
        db: Database to modify
        name: Name of the playlist
        sort_order: Initial sort order

    Returns:
        The created Playlist object

    Raises:
        DuplicatePlaylistError: If a playlist with the same name exists
    """
    # Check for existing playlist with same name
    existing = db.get_playlist_by_name(name)
    if existing is not None:
        raise DuplicatePlaylistError(f"Playlist '{name}' already exists")

    playlist = Playlist(
        id=db.next_playlist_id(),
        name=name,
        sort_order=sort_order,
        timestamp=datetime.now(),
    )

    db.playlists.append(playlist)
    return playlist


def delete_playlist(db: Database, playlist_id: int) -> None:
    """Delete a playlist from the database.

    The master playlist cannot be deleted.

    Args:
        db: Database to modify
        playlist_id: ID of the playlist to delete

    Raises:
        PlaylistNotFoundError: If the playlist doesn't exist
        PlaylistError: If trying to delete the master playlist
    """
    playlist = db.get_playlist_by_id(playlist_id)
    if playlist is None:
        raise PlaylistNotFoundError(f"Playlist with ID {playlist_id} not found")

    if playlist.is_master:
        raise PlaylistError("Cannot delete the master playlist")

    db.playlists = [p for p in db.playlists if p.id != playlist_id]


def rename_playlist(db: Database, playlist_id: int, new_name: str) -> Playlist:
    """Rename a playlist.

    Args:
        db: Database to modify
        playlist_id: ID of the playlist to rename
        new_name: New name for the playlist

    Returns:
        The modified Playlist object

    Raises:
        PlaylistNotFoundError: If the playlist doesn't exist
        DuplicatePlaylistError: If a playlist with the new name already exists
        PlaylistError: If trying to rename the master playlist
    """
    playlist = db.get_playlist_by_id(playlist_id)
    if playlist is None:
        raise PlaylistNotFoundError(f"Playlist with ID {playlist_id} not found")

    if playlist.is_master:
        raise PlaylistError("Cannot rename the master playlist")

    # Check for name collision
    existing = db.get_playlist_by_name(new_name)
    if existing is not None and existing.id != playlist_id:
        raise DuplicatePlaylistError(f"Playlist '{new_name}' already exists")

    playlist.name = new_name
    return playlist


def add_track_to_playlist(
    db: Database,
    playlist_id: int,
    track_id: int,
    *,
    position: int | None = None,
) -> None:
    """Add a track to a playlist.

    Args:
        db: Database to modify
        playlist_id: ID of the playlist
        track_id: ID of the track to add
        position: Optional position to insert at (default: end)

    Raises:
        PlaylistNotFoundError: If the playlist doesn't exist
        PlaylistError: If the track is already in the playlist
    """
    playlist = db.get_playlist_by_id(playlist_id)
    if playlist is None:
        raise PlaylistNotFoundError(f"Playlist with ID {playlist_id} not found")

    # Check track exists
    track = db.get_track_by_id(track_id)
    if track is None:
        raise PlaylistError(f"Track with ID {track_id} not found")

    # Check if already in playlist
    if track_id in playlist.track_ids:
        raise PlaylistError(f"Track {track_id} is already in playlist")

    if position is None:
        playlist.track_ids.append(track_id)
    else:
        playlist.track_ids.insert(position, track_id)


def remove_track_from_playlist(db: Database, playlist_id: int, track_id: int) -> None:
    """Remove a track from a playlist.

    Args:
        db: Database to modify
        playlist_id: ID of the playlist
        track_id: ID of the track to remove

    Raises:
        PlaylistNotFoundError: If the playlist doesn't exist
        PlaylistError: If the track is not in the playlist
    """
    playlist = db.get_playlist_by_id(playlist_id)
    if playlist is None:
        raise PlaylistNotFoundError(f"Playlist with ID {playlist_id} not found")

    if track_id not in playlist.track_ids:
        raise PlaylistError(f"Track {track_id} is not in playlist")

    playlist.track_ids = [tid for tid in playlist.track_ids if tid != track_id]


def reorder_playlist(db: Database, playlist_id: int, track_ids: list[int]) -> None:
    """Reorder tracks in a playlist.

    Args:
        db: Database to modify
        playlist_id: ID of the playlist
        track_ids: New order of track IDs (must contain same tracks)

    Raises:
        PlaylistNotFoundError: If the playlist doesn't exist
        PlaylistError: If track_ids don't match the current playlist
    """
    playlist = db.get_playlist_by_id(playlist_id)
    if playlist is None:
        raise PlaylistNotFoundError(f"Playlist with ID {playlist_id} not found")

    # Verify same tracks
    if set(track_ids) != set(playlist.track_ids):
        raise PlaylistError("New track order must contain the same tracks")

    playlist.track_ids = track_ids


def move_track_in_playlist(
    db: Database,
    playlist_id: int,
    track_id: int,
    new_position: int,
) -> None:
    """Move a track to a new position within a playlist.

    Args:
        db: Database to modify
        playlist_id: ID of the playlist
        track_id: ID of the track to move
        new_position: New position (0-indexed)

    Raises:
        PlaylistNotFoundError: If the playlist doesn't exist
        PlaylistError: If the track is not in the playlist
    """
    playlist = db.get_playlist_by_id(playlist_id)
    if playlist is None:
        raise PlaylistNotFoundError(f"Playlist with ID {playlist_id} not found")

    if track_id not in playlist.track_ids:
        raise PlaylistError(f"Track {track_id} is not in playlist")

    # Remove from current position
    playlist.track_ids = [tid for tid in playlist.track_ids if tid != track_id]

    # Insert at new position
    new_position = max(0, min(new_position, len(playlist.track_ids)))
    playlist.track_ids.insert(new_position, track_id)


def set_playlist_sort_order(db: Database, playlist_id: int, sort_order: SortOrder) -> None:
    """Set the sort order for a playlist.

    Args:
        db: Database to modify
        playlist_id: ID of the playlist
        sort_order: New sort order

    Raises:
        PlaylistNotFoundError: If the playlist doesn't exist
    """
    playlist = db.get_playlist_by_id(playlist_id)
    if playlist is None:
        raise PlaylistNotFoundError(f"Playlist with ID {playlist_id} not found")

    playlist.sort_order = sort_order


def clear_playlist(db: Database, playlist_id: int) -> None:
    """Remove all tracks from a playlist.

    Args:
        db: Database to modify
        playlist_id: ID of the playlist

    Raises:
        PlaylistNotFoundError: If the playlist doesn't exist
        PlaylistError: If trying to clear the master playlist
    """
    playlist = db.get_playlist_by_id(playlist_id)
    if playlist is None:
        raise PlaylistNotFoundError(f"Playlist with ID {playlist_id} not found")

    if playlist.is_master:
        raise PlaylistError("Cannot clear the master playlist")

    playlist.track_ids = []


def duplicate_playlist(db: Database, playlist_id: int, new_name: str) -> Playlist:
    """Create a copy of an existing playlist.

    Args:
        db: Database to modify
        playlist_id: ID of the playlist to copy
        new_name: Name for the new playlist

    Returns:
        The new Playlist object

    Raises:
        PlaylistNotFoundError: If the source playlist doesn't exist
        DuplicatePlaylistError: If a playlist with the new name exists
    """
    source = db.get_playlist_by_id(playlist_id)
    if source is None:
        raise PlaylistNotFoundError(f"Playlist with ID {playlist_id} not found")

    # Check for name collision
    existing = db.get_playlist_by_name(new_name)
    if existing is not None:
        raise DuplicatePlaylistError(f"Playlist '{new_name}' already exists")

    new_playlist = Playlist(
        id=db.next_playlist_id(),
        name=new_name,
        track_ids=source.track_ids.copy(),
        sort_order=source.sort_order,
        timestamp=datetime.now(),
    )

    db.playlists.append(new_playlist)
    return new_playlist


def get_playlist_tracks(db: Database, playlist_id: int) -> list[int]:
    """Get the track IDs in a playlist in order.

    Args:
        db: Database to query
        playlist_id: ID of the playlist

    Returns:
        List of track IDs in playlist order

    Raises:
        PlaylistNotFoundError: If the playlist doesn't exist
    """
    playlist = db.get_playlist_by_id(playlist_id)
    if playlist is None:
        raise PlaylistNotFoundError(f"Playlist with ID {playlist_id} not found")

    return playlist.track_ids.copy()


def get_user_playlists(db: Database) -> list[Playlist]:
    """Get all non-master playlists.

    Args:
        db: Database to query

    Returns:
        List of user-created playlists
    """
    return [p for p in db.playlists if not p.is_master]
