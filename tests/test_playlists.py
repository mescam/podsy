"""Tests for playlist management."""

import pytest

from podsy.db.models import Database, Playlist, SortOrder, Track
from podsy.playlists import (
    DuplicatePlaylistError,
    PlaylistError,
    PlaylistNotFoundError,
    add_track_to_playlist,
    clear_playlist,
    create_playlist,
    delete_playlist,
    duplicate_playlist,
    get_playlist_tracks,
    get_user_playlists,
    move_track_in_playlist,
    remove_track_from_playlist,
    rename_playlist,
    reorder_playlist,
    set_playlist_sort_order,
)


class TestCreatePlaylist:
    """Tests for playlist creation."""

    def test_create_playlist_basic(self) -> None:
        """Test creating a basic playlist."""
        db = Database()

        playlist = create_playlist(db, "My Playlist")

        assert playlist.name == "My Playlist"
        assert playlist.id == 1
        assert playlist.track_ids == []
        assert playlist.is_master is False
        assert playlist in db.playlists

    def test_create_playlist_with_sort_order(self) -> None:
        """Test creating playlist with custom sort order."""
        db = Database()

        playlist = create_playlist(db, "Sorted", sort_order=SortOrder.TITLE)

        assert playlist.sort_order == SortOrder.TITLE

    def test_create_playlist_duplicate_name(self) -> None:
        """Test creating playlist with duplicate name fails."""
        db = Database()
        create_playlist(db, "Existing")

        with pytest.raises(DuplicatePlaylistError, match="already exists"):
            create_playlist(db, "Existing")

    def test_create_playlist_increments_id(self) -> None:
        """Test that playlist IDs increment."""
        db = Database()

        p1 = create_playlist(db, "Playlist 1")
        p2 = create_playlist(db, "Playlist 2")
        p3 = create_playlist(db, "Playlist 3")

        assert p1.id == 1
        assert p2.id == 2
        assert p3.id == 3


class TestDeletePlaylist:
    """Tests for playlist deletion."""

    def test_delete_playlist(self) -> None:
        """Test deleting a playlist."""
        db = Database()
        playlist = create_playlist(db, "To Delete")

        delete_playlist(db, playlist.id)

        assert playlist not in db.playlists

    def test_delete_playlist_not_found(self) -> None:
        """Test deleting non-existent playlist fails."""
        db = Database()

        with pytest.raises(PlaylistNotFoundError):
            delete_playlist(db, 999)

    def test_delete_master_playlist_fails(self) -> None:
        """Test deleting master playlist fails."""
        db = Database()
        db.playlists = [Playlist(id=1, name="Library", is_master=True)]

        with pytest.raises(PlaylistError, match="Cannot delete the master"):
            delete_playlist(db, 1)


class TestRenamePlaylist:
    """Tests for playlist renaming."""

    def test_rename_playlist(self) -> None:
        """Test renaming a playlist."""
        db = Database()
        playlist = create_playlist(db, "Old Name")

        result = rename_playlist(db, playlist.id, "New Name")

        assert result.name == "New Name"
        assert playlist.name == "New Name"

    def test_rename_playlist_not_found(self) -> None:
        """Test renaming non-existent playlist fails."""
        db = Database()

        with pytest.raises(PlaylistNotFoundError):
            rename_playlist(db, 999, "New Name")

    def test_rename_playlist_duplicate_name(self) -> None:
        """Test renaming to existing name fails."""
        db = Database()
        create_playlist(db, "Playlist A")
        playlist_b = create_playlist(db, "Playlist B")

        with pytest.raises(DuplicatePlaylistError):
            rename_playlist(db, playlist_b.id, "Playlist A")

    def test_rename_playlist_same_name(self) -> None:
        """Test renaming to same name succeeds."""
        db = Database()
        playlist = create_playlist(db, "Same Name")

        result = rename_playlist(db, playlist.id, "Same Name")

        assert result.name == "Same Name"

    def test_rename_master_playlist_fails(self) -> None:
        """Test renaming master playlist fails."""
        db = Database()
        db.playlists = [Playlist(id=1, name="Library", is_master=True)]

        with pytest.raises(PlaylistError, match="Cannot rename the master"):
            rename_playlist(db, 1, "New Name")


class TestAddTrackToPlaylist:
    """Tests for adding tracks to playlists."""

    def test_add_track_to_playlist(self) -> None:
        """Test adding a track to a playlist."""
        db = Database()
        db.tracks = [Track(id=1, title="Song", artist="A", album="B")]
        playlist = create_playlist(db, "My Playlist")

        add_track_to_playlist(db, playlist.id, 1)

        assert 1 in playlist.track_ids

    def test_add_track_to_playlist_at_position(self) -> None:
        """Test adding track at specific position."""
        db = Database()
        db.tracks = [
            Track(id=1, title="A", artist="A", album="A"),
            Track(id=2, title="B", artist="B", album="B"),
            Track(id=3, title="C", artist="C", album="C"),
        ]
        playlist = create_playlist(db, "My Playlist")
        add_track_to_playlist(db, playlist.id, 1)
        add_track_to_playlist(db, playlist.id, 2)

        add_track_to_playlist(db, playlist.id, 3, position=1)

        assert playlist.track_ids == [1, 3, 2]

    def test_add_track_playlist_not_found(self) -> None:
        """Test adding track to non-existent playlist fails."""
        db = Database()
        db.tracks = [Track(id=1, title="Song", artist="A", album="B")]

        with pytest.raises(PlaylistNotFoundError):
            add_track_to_playlist(db, 999, 1)

    def test_add_nonexistent_track(self) -> None:
        """Test adding non-existent track fails."""
        db = Database()
        playlist = create_playlist(db, "My Playlist")

        with pytest.raises(PlaylistError, match="Track with ID 999 not found"):
            add_track_to_playlist(db, playlist.id, 999)

    def test_add_duplicate_track(self) -> None:
        """Test adding same track twice fails."""
        db = Database()
        db.tracks = [Track(id=1, title="Song", artist="A", album="B")]
        playlist = create_playlist(db, "My Playlist")
        add_track_to_playlist(db, playlist.id, 1)

        with pytest.raises(PlaylistError, match="already in playlist"):
            add_track_to_playlist(db, playlist.id, 1)


class TestRemoveTrackFromPlaylist:
    """Tests for removing tracks from playlists."""

    def test_remove_track_from_playlist(self) -> None:
        """Test removing a track from a playlist."""
        db = Database()
        db.tracks = [Track(id=1, title="Song", artist="A", album="B")]
        playlist = create_playlist(db, "My Playlist")
        add_track_to_playlist(db, playlist.id, 1)

        remove_track_from_playlist(db, playlist.id, 1)

        assert 1 not in playlist.track_ids

    def test_remove_track_playlist_not_found(self) -> None:
        """Test removing from non-existent playlist fails."""
        db = Database()

        with pytest.raises(PlaylistNotFoundError):
            remove_track_from_playlist(db, 999, 1)

    def test_remove_track_not_in_playlist(self) -> None:
        """Test removing track not in playlist fails."""
        db = Database()
        playlist = create_playlist(db, "My Playlist")

        with pytest.raises(PlaylistError, match="not in playlist"):
            remove_track_from_playlist(db, playlist.id, 1)


class TestReorderPlaylist:
    """Tests for playlist reordering."""

    def test_reorder_playlist(self) -> None:
        """Test reordering playlist tracks."""
        db = Database()
        db.tracks = [
            Track(id=1, title="A", artist="A", album="A"),
            Track(id=2, title="B", artist="B", album="B"),
            Track(id=3, title="C", artist="C", album="C"),
        ]
        playlist = Playlist(id=1, name="My Playlist", track_ids=[1, 2, 3])
        db.playlists.append(playlist)

        reorder_playlist(db, 1, [3, 1, 2])

        assert playlist.track_ids == [3, 1, 2]

    def test_reorder_playlist_not_found(self) -> None:
        """Test reordering non-existent playlist fails."""
        db = Database()

        with pytest.raises(PlaylistNotFoundError):
            reorder_playlist(db, 999, [1, 2, 3])

    def test_reorder_playlist_wrong_tracks(self) -> None:
        """Test reordering with wrong tracks fails."""
        db = Database()
        playlist = Playlist(id=1, name="My Playlist", track_ids=[1, 2, 3])
        db.playlists.append(playlist)

        with pytest.raises(PlaylistError, match="must contain the same tracks"):
            reorder_playlist(db, 1, [1, 2, 4])


class TestMoveTrackInPlaylist:
    """Tests for moving tracks within a playlist."""

    def test_move_track_forward(self) -> None:
        """Test moving track to later position."""
        db = Database()
        playlist = Playlist(id=1, name="My Playlist", track_ids=[1, 2, 3, 4])
        db.playlists.append(playlist)

        move_track_in_playlist(db, 1, 1, 2)

        assert playlist.track_ids == [2, 3, 1, 4]

    def test_move_track_backward(self) -> None:
        """Test moving track to earlier position."""
        db = Database()
        playlist = Playlist(id=1, name="My Playlist", track_ids=[1, 2, 3, 4])
        db.playlists.append(playlist)

        move_track_in_playlist(db, 1, 4, 0)

        assert playlist.track_ids == [4, 1, 2, 3]

    def test_move_track_not_in_playlist(self) -> None:
        """Test moving track not in playlist fails."""
        db = Database()
        playlist = Playlist(id=1, name="My Playlist", track_ids=[1, 2, 3])
        db.playlists.append(playlist)

        with pytest.raises(PlaylistError, match="not in playlist"):
            move_track_in_playlist(db, 1, 99, 0)


class TestSetPlaylistSortOrder:
    """Tests for setting playlist sort order."""

    def test_set_sort_order(self) -> None:
        """Test setting playlist sort order."""
        db = Database()
        playlist = create_playlist(db, "My Playlist")

        set_playlist_sort_order(db, playlist.id, SortOrder.ARTIST)

        assert playlist.sort_order == SortOrder.ARTIST

    def test_set_sort_order_not_found(self) -> None:
        """Test setting sort order on non-existent playlist fails."""
        db = Database()

        with pytest.raises(PlaylistNotFoundError):
            set_playlist_sort_order(db, 999, SortOrder.TITLE)


class TestClearPlaylist:
    """Tests for clearing playlists."""

    def test_clear_playlist(self) -> None:
        """Test clearing all tracks from a playlist."""
        db = Database()
        playlist = Playlist(id=1, name="My Playlist", track_ids=[1, 2, 3, 4, 5])
        db.playlists.append(playlist)

        clear_playlist(db, 1)

        assert playlist.track_ids == []

    def test_clear_playlist_not_found(self) -> None:
        """Test clearing non-existent playlist fails."""
        db = Database()

        with pytest.raises(PlaylistNotFoundError):
            clear_playlist(db, 999)

    def test_clear_master_playlist_fails(self) -> None:
        """Test clearing master playlist fails."""
        db = Database()
        db.playlists = [Playlist(id=1, name="Library", is_master=True, track_ids=[1, 2, 3])]

        with pytest.raises(PlaylistError, match="Cannot clear the master"):
            clear_playlist(db, 1)


class TestDuplicatePlaylist:
    """Tests for playlist duplication."""

    def test_duplicate_playlist(self) -> None:
        """Test duplicating a playlist."""
        db = Database()
        source = Playlist(id=1, name="Original", track_ids=[1, 2, 3], sort_order=SortOrder.TITLE)
        db.playlists.append(source)

        copy = duplicate_playlist(db, 1, "Copy")

        assert copy.name == "Copy"
        assert copy.track_ids == [1, 2, 3]
        assert copy.sort_order == SortOrder.TITLE
        assert copy.id != source.id

    def test_duplicate_playlist_not_found(self) -> None:
        """Test duplicating non-existent playlist fails."""
        db = Database()

        with pytest.raises(PlaylistNotFoundError):
            duplicate_playlist(db, 999, "Copy")

    def test_duplicate_playlist_name_exists(self) -> None:
        """Test duplicating with existing name fails."""
        db = Database()
        db.playlists = [
            Playlist(id=1, name="Original"),
            Playlist(id=2, name="Existing"),
        ]

        with pytest.raises(DuplicatePlaylistError):
            duplicate_playlist(db, 1, "Existing")


class TestGetPlaylistTracks:
    """Tests for getting playlist tracks."""

    def test_get_playlist_tracks(self) -> None:
        """Test getting track IDs from a playlist."""
        db = Database()
        playlist = Playlist(id=1, name="My Playlist", track_ids=[5, 3, 8, 1])
        db.playlists.append(playlist)

        tracks = get_playlist_tracks(db, 1)

        assert tracks == [5, 3, 8, 1]

    def test_get_playlist_tracks_returns_copy(self) -> None:
        """Test that returned list is a copy."""
        db = Database()
        playlist = Playlist(id=1, name="My Playlist", track_ids=[1, 2, 3])
        db.playlists.append(playlist)

        tracks = get_playlist_tracks(db, 1)
        tracks.append(99)

        assert 99 not in playlist.track_ids

    def test_get_playlist_tracks_not_found(self) -> None:
        """Test getting tracks from non-existent playlist fails."""
        db = Database()

        with pytest.raises(PlaylistNotFoundError):
            get_playlist_tracks(db, 999)


class TestGetUserPlaylists:
    """Tests for getting user playlists."""

    def test_get_user_playlists(self) -> None:
        """Test getting non-master playlists."""
        db = Database()
        db.playlists = [
            Playlist(id=1, name="Library", is_master=True),
            Playlist(id=2, name="Rock"),
            Playlist(id=3, name="Jazz"),
        ]

        user_playlists = get_user_playlists(db)

        assert len(user_playlists) == 2
        assert all(not p.is_master for p in user_playlists)
        names = {p.name for p in user_playlists}
        assert names == {"Rock", "Jazz"}

    def test_get_user_playlists_empty(self) -> None:
        """Test getting user playlists when only master exists."""
        db = Database()
        db.playlists = [Playlist(id=1, name="Library", is_master=True)]

        user_playlists = get_user_playlists(db)

        assert user_playlists == []
