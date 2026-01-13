"""Screen definitions for Podsy TUI."""

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    Select,
    Static,
    Tree,
)
from textual.worker import Worker, WorkerState

from ..db import Database, save
from ..db.models import Track
from ..device import IPodDevice
from ..playlists import (
    PlaylistError,
    add_track_to_playlist,
    create_playlist,
)
from ..sync import SyncError, remove_track, sync_file

if TYPE_CHECKING:
    pass


class NoDeviceScreen(Screen[None]):
    """Screen shown when no iPod is connected."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def compose(self) -> ComposeResult:
        """Compose the no-device screen."""
        yield Header()
        yield Container(
            Static("No iPod Detected", id="no-device-title"),
            Static(
                "Connect your iPod and press 'r' to refresh,\n"
                "or enter the mount point manually below:",
                id="no-device-message",
            ),
            Input(
                placeholder="/path/to/ipod/mount...",
                id="mount-path-input",
            ),
            Horizontal(
                Button("Refresh", id="refresh-btn", variant="primary"),
                Button("Connect", id="connect-btn", variant="success"),
                id="no-device-buttons",
            ),
            id="no-device-container",
        )
        yield Footer()

    @on(Button.Pressed, "#refresh-btn")
    def on_refresh_pressed(self) -> None:
        """Handle refresh button press."""
        if hasattr(self.app, "action_refresh"):
            self.app.action_refresh()  # type: ignore[attr-defined]

    @on(Button.Pressed, "#connect-btn")
    def on_connect_pressed(self) -> None:
        """Handle connect button press."""
        self._try_manual_connect()

    @on(Input.Submitted, "#mount-path-input")
    def on_mount_path_submitted(self) -> None:
        """Handle mount path input submission."""
        self._try_manual_connect()

    def _try_manual_connect(self) -> None:
        """Try to connect to manually entered mount path."""
        mount_input = self.query_one("#mount-path-input", Input)
        path_str = mount_input.value.strip()

        if not path_str:
            self.notify("Please enter a mount path", severity="warning")
            return

        path = Path(path_str).expanduser()
        if not path.exists():
            self.notify(f"Path does not exist: {path}", severity="error")
            return

        if not path.is_dir():
            self.notify(f"Path is not a directory: {path}", severity="error")
            return

        # Check for iPod structure
        ipod_control = path / "iPod_Control"
        if not ipod_control.exists():
            self.notify(
                f"Not a valid iPod: {path} (missing iPod_Control folder)",
                severity="error",
            )
            return

        # Try to connect via app
        if hasattr(self.app, "connect_to_path"):
            self.app.connect_to_path(path)  # type: ignore[attr-defined]

    def action_refresh(self) -> None:
        """Refresh device detection."""
        if hasattr(self.app, "action_refresh"):
            self.app.action_refresh()  # type: ignore[attr-defined]

    def action_quit(self) -> None:
        """Quit the application."""
        self.app.exit()


class MainScreen(Screen[None]):
    """Main dual-pane synchronization screen."""

    BINDINGS = [
        Binding("tab", "switch_focus", "Switch Pane", show=True),
        Binding("s", "sync_selected", "Sync File/Folder", show=True),
        Binding("d", "delete_selected", "Delete", show=True),
        Binding("p", "new_playlist", "New Playlist", show=True),
        Binding("a", "add_to_playlist", "Add to Playlist", show=True),
        Binding("f", "focus_filter", "Filter", show=True),
        Binding("l", "change_local_path", "Change Local Path", show=True),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    SORT_OPTIONS = [
        ("artist", "Artist"),
        ("album", "Album"),
        ("title", "Title"),
        ("date_added", "Date Added"),
    ]

    def __init__(
        self,
        device: IPodDevice,
        database: Database,
        local_path: Path,
    ) -> None:
        """Initialize the main screen.

        Args:
            device: Connected iPod device
            database: Loaded iTunesDB database
            local_path: Starting path for local file browser
        """
        super().__init__()
        self.device = device
        self.database = database
        self.local_path = local_path
        self.current_playlist_id: int | None = None
        self._focus_left = True
        self._filter_text = ""
        self._sort_by = "artist"
        # Track active sync worker
        self._sync_worker: Worker[list] | None = None

    def compose(self) -> ComposeResult:
        """Compose the main screen layout."""
        yield Header()

        with Horizontal(id="main-container"):
            # Left pane - Local files
            with Vertical(id="left-pane", classes="pane"):
                yield Label("Local Files", classes="pane-title")
                yield DirectoryTree(str(self.local_path), id="local-tree")

            # Right pane - iPod contents
            with Vertical(id="right-pane", classes="pane"):
                with Horizontal(id="library-header"):
                    yield Label("iPod Library", classes="pane-title")
                    yield Input(
                        placeholder="Filter...",
                        id="filter-input",
                    )
                    yield Select(
                        options=[(label, value) for value, label in self.SORT_OPTIONS],
                        value="artist",
                        id="sort-select",
                        allow_blank=False,
                    )
                yield Tree("Library", id="ipod-tree")

        # Playlist bar
        with Horizontal(id="playlist-bar"):
            yield Label("Playlists:", id="playlist-label")
            yield ListView(id="playlist-list")
            yield Button("+ New", id="new-playlist-btn", variant="primary")

        # Progress bar for sync operations (hidden by default)
        with Horizontal(id="progress-container"):
            yield Label("Syncing...", id="progress-label")
            yield ProgressBar(total=100, id="sync-progress", show_eta=False)
            yield Button("Cancel", id="cancel-sync-btn", variant="error")

        # Status bar
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Handle screen mount."""
        self._load_library_tree()
        self._load_playlists()
        self._update_status()
        # Hide progress bar initially
        self.query_one("#progress-container").display = False

    def _get_filtered_tracks(self) -> list[Track]:
        """Get tracks filtered by current filter text and playlist."""
        if self.current_playlist_id is not None:
            playlist = self.database.get_playlist_by_id(self.current_playlist_id)
            if playlist:
                tracks = [self.database.get_track_by_id(tid) for tid in playlist.track_ids]
                tracks = [t for t in tracks if t is not None]
            else:
                tracks = []
        else:
            tracks = self.database.tracks

        # Apply filter
        if self._filter_text:
            filter_lower = self._filter_text.lower()
            tracks = [
                t
                for t in tracks
                if (t.title and filter_lower in t.title.lower())
                or (t.artist and filter_lower in t.artist.lower())
                or (t.album and filter_lower in t.album.lower())
            ]

        return tracks

    def _load_library_tree(self) -> None:
        """Load tracks into the tree view organized by artist/album."""
        tree: Tree[list[int]] = self.query_one("#ipod-tree", Tree)
        tree.clear()
        tree.root.expand()
        tree.show_root = False  # Hide the "Library" root node

        tracks = self._get_filtered_tracks()

        # Sort tracks
        if self._sort_by == "artist":
            tracks.sort(key=lambda t: (t.artist or "", t.album or "", t.title or ""))
        elif self._sort_by == "album":
            tracks.sort(key=lambda t: (t.album or "", t.artist or "", t.title or ""))
        elif self._sort_by == "title":
            tracks.sort(key=lambda t: (t.title or "", t.artist or "", t.album or ""))
        elif self._sort_by == "date_added":
            tracks.sort(key=lambda t: t.date_added, reverse=True)

        # Build tree structure - store track IDs in node.data
        if self._sort_by in ("artist", "title", "date_added"):
            # Group by Artist -> Album -> Track
            artists: dict[str, dict[str, list[Track]]] = defaultdict(lambda: defaultdict(list))
            for track in tracks:
                artist = track.artist or "(Unknown Artist)"
                album = track.album or "(Unknown Album)"
                artists[artist][album].append(track)

            for artist_name in sorted(artists.keys()):
                artist_label = f"[bold]{artist_name}[/bold]"
                artist_track_ids: list[int] = []

                for album_name in sorted(artists[artist_name].keys()):
                    for track in artists[artist_name][album_name]:
                        artist_track_ids.append(track.id)

                artist_node = tree.root.add(artist_label, data=artist_track_ids, expand=False)

                for album_name in sorted(artists[artist_name].keys()):
                    album_label = f"[dim]{album_name}[/dim]"
                    album_track_ids: list[int] = []

                    for track in artists[artist_name][album_name]:
                        album_track_ids.append(track.id)

                    album_node = artist_node.add(album_label, data=album_track_ids, expand=False)

                    for track in artists[artist_name][album_name]:
                        duration = self._format_duration(track.duration_ms)
                        label = f"{track.title or '(No Title)'} [{duration}]"
                        album_node.add_leaf(label, data=[track.id])

        elif self._sort_by == "album":
            # Group by Album -> Artist -> Track
            albums: dict[str, dict[str, list[Track]]] = defaultdict(lambda: defaultdict(list))
            for track in tracks:
                album = track.album or "(Unknown Album)"
                artist = track.artist or "(Unknown Artist)"
                albums[album][artist].append(track)

            for album_name in sorted(albums.keys()):
                album_label = f"[bold]{album_name}[/bold]"
                album_track_ids: list[int] = []

                for artist_name in sorted(albums[album_name].keys()):
                    for track in albums[album_name][artist_name]:
                        album_track_ids.append(track.id)

                album_node = tree.root.add(album_label, data=album_track_ids, expand=False)

                for artist_name in sorted(albums[album_name].keys()):
                    artist_label = f"[dim]{artist_name}[/dim]"
                    artist_track_ids: list[int] = []

                    for track in albums[album_name][artist_name]:
                        artist_track_ids.append(track.id)

                    artist_node = album_node.add(artist_label, data=artist_track_ids, expand=False)

                    for track in albums[album_name][artist_name]:
                        duration = self._format_duration(track.duration_ms)
                        label = f"{track.title or '(No Title)'} [{duration}]"
                        artist_node.add_leaf(label, data=[track.id])

        # Update status with track count
        self._update_status(len(tracks))

        # Ensure cursor is set to first item if tree has content
        if tree.cursor_line < 0 and len(tracks) > 0:
            tree.cursor_line = 0

    def _format_duration(self, duration_ms: int) -> str:
        """Format duration in milliseconds to mm:ss."""
        duration_sec = duration_ms // 1000
        minutes = duration_sec // 60
        seconds = duration_sec % 60
        return f"{minutes}:{seconds:02d}"

    def _load_playlists(self) -> None:
        """Load playlists into the playlist list."""
        playlist_list = self.query_one("#playlist-list", ListView)
        # Remove all children to avoid ID conflicts
        playlist_list.remove_children()

        # Add "All Songs" option
        playlist_list.append(ListItem(Label("All Songs"), id="playlist-all"))

        # Add user playlists
        for playlist in self.database.playlists:
            if not playlist.is_master:
                playlist_list.append(
                    ListItem(
                        Label(f"{playlist.name} ({len(playlist.track_ids)})"),
                        id=f"playlist-{playlist.id}",
                    )
                )

    def _update_status(self, visible_count: int | None = None) -> None:
        """Update the status bar."""
        status = self.query_one("#status-bar", Static)
        total_count = len(self.database.tracks)
        if visible_count is None:
            visible_count = total_count

        free_bytes = self.device.free_space
        total_bytes = self.device.total_space
        used_bytes = total_bytes - free_bytes

        # Format sizes intelligently (GB for large values, MB otherwise)
        def format_size(size_bytes: int) -> str:
            if size_bytes >= 1024 * 1024 * 1024:  # >= 1 GB
                return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"
            else:
                return f"{size_bytes // (1024 * 1024)}MB"

        free_str = format_size(free_bytes)
        used_str = format_size(used_bytes)
        total_str = format_size(total_bytes)

        # Calculate usage percentage
        used_pct = (used_bytes / total_bytes * 100) if total_bytes > 0 else 0

        if visible_count != total_count:
            count_str = f"{visible_count}/{total_count} tracks"
        else:
            count_str = f"{total_count} tracks"

        disk_info = f"Disk: {used_str}/{total_str} ({used_pct:.0f}%) - {free_str} free"
        status.update(f"{count_str} | {disk_info} | {self.device.model}")

    def action_switch_focus(self) -> None:
        """Switch focus between panes."""
        self._focus_left = not self._focus_left
        if self._focus_left:
            self.query_one("#local-tree", DirectoryTree).focus()
        else:
            self.query_one("#ipod-tree", Tree).focus()

    def action_focus_filter(self) -> None:
        """Focus the filter input."""
        self.query_one("#filter-input", Input).focus()

    @on(Input.Changed, "#filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        """Handle filter text change."""
        self._filter_text = event.value
        self._load_library_tree()

    @on(Select.Changed, "#sort-select")
    def on_sort_changed(self, event: Select.Changed) -> None:
        """Handle sort selection change."""
        if event.value:
            self._sort_by = str(event.value)
            self._load_library_tree()

    def action_sync_selected(self) -> None:
        """Sync selected file or folder to iPod."""
        tree = self.query_one("#local-tree", DirectoryTree)
        selected = tree.cursor_node
        if selected is None or selected.data is None:
            self.notify("No file or folder selected", severity="warning")
            return

        path = selected.data.path

        if path.is_file():
            # Sync single file (fast, no progress bar needed)
            try:
                track = sync_file(self.device, self.database, path)
                save(self.database, self.device.db_path)
                self._load_library_tree()
                self.notify(f"Synced: {track.title}", severity="information")
            except SyncError as e:
                self.notify(f"Sync failed: {e}", severity="error")
            except Exception as e:
                self.notify(f"Error: {e}", severity="error")

        elif path.is_dir():
            # Sync entire folder with progress bar
            self._start_folder_sync(path)

    def _start_folder_sync(self, folder: Path) -> None:
        """Start syncing a folder with progress tracking."""
        # Show progress bar
        progress_container = self.query_one("#progress-container")
        progress_container.display = True
        progress_bar = self.query_one("#sync-progress", ProgressBar)
        progress_label = self.query_one("#progress-label", Label)

        # Reset progress
        progress_bar.update(total=100, progress=0)
        progress_label.update(f"Scanning {folder.name}...")

        # Start worker thread
        self._sync_worker = self.run_worker(
            lambda: self._sync_folder_worker(folder),
            name="folder_sync",
            exclusive=True,
            thread=True,
        )

    def _sync_folder_worker(self, folder: Path) -> list:
        """Worker to sync folder in background thread."""
        from ..sync import SUPPORTED_EXTENSIONS

        # First, count files to set up progress bar
        files = list(folder.rglob("*"))
        music_files = [f for f in files if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS]
        total = len(music_files)

        if total == 0:
            self.app.call_from_thread(self._on_sync_complete, [], folder.name)
            return []

        # Update progress bar total
        self.app.call_from_thread(self._update_progress_total, total)

        synced: list = []
        errors: list[tuple[Path, str]] = []

        for i, file in enumerate(sorted(music_files), 1):
            # Update progress
            self.app.call_from_thread(self._update_progress, i, total, file.name)

            try:
                track = sync_file(self.device, self.database, file, check_duplicate=True)
                synced.append(track)
            except SyncError as e:
                errors.append((file, str(e)))
            except Exception as e:
                errors.append((file, f"Unexpected error: {e}"))

        # Create playlist if we synced some tracks
        if synced:
            from ..playlists import DuplicatePlaylistError
            from ..playlists import create_playlist as make_playlist

            playlist_name = folder.name
            base_name = playlist_name
            counter = 1
            while self.database.get_playlist_by_name(playlist_name) is not None:
                counter += 1
                playlist_name = f"{base_name} ({counter})"

            try:
                playlist = make_playlist(self.database, playlist_name)
                for track in synced:
                    playlist.track_ids.append(track.id)
            except DuplicatePlaylistError:
                pass

        # Save database and update UI
        self.app.call_from_thread(self._on_sync_complete, synced, folder.name)
        return synced

    def _update_progress_total(self, total: int) -> None:
        """Update progress bar total (called from worker thread)."""
        progress_bar = self.query_one("#sync-progress", ProgressBar)
        progress_bar.update(total=total, progress=0)

    def _update_progress(self, current: int, total: int, filename: str) -> None:
        """Update progress bar (called from worker thread)."""
        progress_bar = self.query_one("#sync-progress", ProgressBar)
        progress_label = self.query_one("#progress-label", Label)
        progress_bar.update(progress=current)
        progress_label.update(f"[{current}/{total}] {filename}")

    def _on_sync_complete(self, synced: list, folder_name: str) -> None:
        """Handle sync completion (called from worker thread)."""
        # Hide progress bar
        progress_container = self.query_one("#progress-container")
        progress_container.display = False

        # Save database
        save(self.database, self.device.db_path)

        # Refresh UI
        self._load_library_tree()
        self._load_playlists()

        # Show result notification
        if synced:
            self.notify(
                f"Synced {len(synced)} tracks from {folder_name}",
                severity="information",
            )
        else:
            self.notify(f"No music files found in {folder_name}", severity="warning")

        self._sync_worker = None

    @on(Button.Pressed, "#cancel-sync-btn")
    def on_cancel_sync_pressed(self) -> None:
        """Handle cancel sync button press."""
        if self._sync_worker and self._sync_worker.state == WorkerState.RUNNING:
            self._sync_worker.cancel()
            self.query_one("#progress-container").display = False
            self.notify("Sync cancelled", severity="warning")
            # Save any progress made so far
            save(self.database, self.device.db_path)
            self._load_library_tree()
            self._load_playlists()
            self._sync_worker = None

    def _get_selected_node_tracks(self) -> tuple[list[int], str]:
        """Get track IDs for the currently selected tree node.

        Returns:
            Tuple of (list of track IDs, description of what's selected)
        """
        tree: Tree[list[int]] = self.query_one("#ipod-tree", Tree)

        if tree.cursor_node is None or tree.cursor_node.is_root:
            return [], ""

        node = tree.cursor_node
        track_ids = node.data

        if not track_ids:
            return [], ""

        # Get clean label for description
        label = str(node.label)

        if len(track_ids) == 1:
            # Single track
            title = label.rsplit(" [", 1)[0]  # Remove duration
            return track_ids, f"track '{title}'"
        else:
            # Multiple tracks (artist or album)
            return track_ids, f"'{label}' ({len(track_ids)} tracks)"

    def action_delete_selected(self) -> None:
        """Delete selected track, album, or artist from iPod."""
        track_ids, description = self._get_selected_node_tracks()

        if not track_ids:
            self.notify("No track selected", severity="warning")
            return

        try:
            deleted_count = 0
            for track_id in track_ids:
                track = self.database.get_track_by_id(track_id)
                if track is not None:
                    remove_track(self.device, self.database, track)
                    deleted_count += 1

            save(self.database, self.device.db_path)
            self._load_library_tree()
            self._load_playlists()

            if deleted_count == 1:
                self.notify(f"Deleted: {description}", severity="information")
            else:
                self.notify(
                    f"Deleted {deleted_count} tracks from {description}", severity="information"
                )
        except Exception as e:
            self.notify(f"Delete failed: {e}", severity="error")

    def action_new_playlist(self) -> None:
        """Create a new playlist."""
        self.app.push_screen(NewPlaylistScreen(), self._on_playlist_created)

    def _on_playlist_created(self, name: str | None) -> None:
        """Handle new playlist creation result."""
        if name:
            try:
                create_playlist(self.database, name)
                save(self.database, self.device.db_path)
                self._load_playlists()
                self.notify(f"Created playlist: {name}", severity="information")
            except PlaylistError as e:
                self.notify(f"Failed: {e}", severity="error")

    def action_add_to_playlist(self) -> None:
        """Add selected track(s) to a playlist."""
        track_ids, description = self._get_selected_node_tracks()
        if not track_ids:
            self.notify("No track selected", severity="warning")
            return

        # Show playlist selection
        playlists = [p for p in self.database.playlists if not p.is_master]
        if not playlists:
            self.notify("No playlists available. Create one first.", severity="warning")
            return

        self.app.push_screen(
            SelectPlaylistScreen(playlists),
            lambda pid: self._on_playlist_selected(pid, track_ids, description),
        )

    def _on_playlist_selected(
        self, playlist_id: int | None, track_ids: list[int], description: str
    ) -> None:
        """Handle playlist selection for adding tracks."""
        if playlist_id:
            try:
                added = 0
                for track_id in track_ids:
                    try:
                        add_track_to_playlist(self.database, playlist_id, track_id)
                        added += 1
                    except PlaylistError:
                        pass  # Skip duplicates
                save(self.database, self.device.db_path)
                self._load_playlists()
                playlist = self.database.get_playlist_by_id(playlist_id)
                name = playlist.name if playlist else "Unknown"
                if added == 1:
                    self.notify(f"Added to playlist: {name}", severity="information")
                else:
                    self.notify(f"Added {added} tracks to: {name}", severity="information")
            except PlaylistError as e:
                self.notify(f"Failed: {e}", severity="error")

    @on(ListView.Selected, "#playlist-list")
    def on_playlist_selected(self, event: ListView.Selected) -> None:
        """Handle playlist selection."""
        item_id = event.item.id or ""
        if item_id == "playlist-all":
            self.current_playlist_id = None
        elif item_id.startswith("playlist-"):
            try:
                self.current_playlist_id = int(item_id.replace("playlist-", ""))
            except ValueError:
                self.current_playlist_id = None
        self._load_library_tree()

    @on(Button.Pressed, "#new-playlist-btn")
    def on_new_playlist_pressed(self) -> None:
        """Handle new playlist button press."""
        self.action_new_playlist()

    def action_change_local_path(self) -> None:
        """Change the local files path."""
        self.app.push_screen(
            ChangePathScreen(self.local_path),
            self._on_local_path_changed,
        )

    def _on_local_path_changed(self, new_path: Path | None) -> None:
        """Handle local path change."""
        if new_path:
            self.local_path = new_path
            # Update the directory tree
            tree = self.query_one("#local-tree", DirectoryTree)
            tree.path = new_path
            tree.reload()
            self.notify(f"Changed path to: {new_path}", severity="information")


class ChangePathScreen(Screen[Path | None]):
    """Modal screen for changing the local path."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("enter", "submit", "Change", show=True),
    ]

    def __init__(self, current_path: Path) -> None:
        """Initialize with current path."""
        super().__init__()
        self.current_path = current_path

    def compose(self) -> ComposeResult:
        """Compose the change path screen."""
        yield Container(
            Label("Change Local Path", id="dialog-title"),
            Static(f"Current: {self.current_path}", id="current-path-display"),
            Input(
                placeholder="/path/to/music...",
                value=str(self.current_path),
                id="path-input",
            ),
            Horizontal(
                Button("Cancel", id="cancel-btn", variant="default"),
                Button("Change", id="change-btn", variant="primary"),
                id="dialog-buttons",
            ),
            id="dialog-container",
        )

    def on_mount(self) -> None:
        """Focus and select input on mount."""
        path_input = self.query_one("#path-input", Input)
        path_input.focus()
        path_input.select_all()

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_pressed(self) -> None:
        """Handle cancel button press."""
        self.dismiss(None)

    @on(Button.Pressed, "#change-btn")
    def on_change_pressed(self) -> None:
        """Handle change button press."""
        self._submit()

    @on(Input.Submitted)
    def on_input_submitted(self) -> None:
        """Handle input submission."""
        self._submit()

    def _submit(self) -> None:
        """Submit the new path."""
        path_input = self.query_one("#path-input", Input)
        path_str = path_input.value.strip()

        if not path_str:
            self.notify("Please enter a path", severity="warning")
            return

        path = Path(path_str).expanduser()
        if not path.exists():
            self.notify(f"Path does not exist: {path}", severity="error")
            return

        if not path.is_dir():
            self.notify(f"Path is not a directory: {path}", severity="error")
            return

        self.dismiss(path)

    def action_cancel(self) -> None:
        """Cancel path change."""
        self.dismiss(None)

    def action_submit(self) -> None:
        """Submit path change."""
        self._submit()


class NewPlaylistScreen(Screen[str | None]):
    """Modal screen for creating a new playlist."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("enter", "submit", "Create", show=True),
    ]

    def compose(self) -> ComposeResult:
        """Compose the new playlist screen."""
        yield Container(
            Label("Create New Playlist", id="dialog-title"),
            Input(placeholder="Playlist name...", id="playlist-name-input"),
            Horizontal(
                Button("Cancel", id="cancel-btn", variant="default"),
                Button("Create", id="create-btn", variant="primary"),
                id="dialog-buttons",
            ),
            id="dialog-container",
        )

    def on_mount(self) -> None:
        """Focus the input on mount."""
        self.query_one("#playlist-name-input", Input).focus()

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_pressed(self) -> None:
        """Handle cancel button press."""
        self.dismiss(None)

    @on(Button.Pressed, "#create-btn")
    def on_create_pressed(self) -> None:
        """Handle create button press."""
        self._submit()

    @on(Input.Submitted)
    def on_input_submitted(self) -> None:
        """Handle input submission."""
        self._submit()

    def _submit(self) -> None:
        """Submit the playlist name."""
        name_input = self.query_one("#playlist-name-input", Input)
        name = name_input.value.strip()
        if name:
            self.dismiss(name)
        else:
            self.notify("Please enter a playlist name", severity="warning")

    def action_cancel(self) -> None:
        """Cancel playlist creation."""
        self.dismiss(None)

    def action_submit(self) -> None:
        """Submit playlist creation."""
        self._submit()


class SelectPlaylistScreen(Screen[int | None]):
    """Modal screen for selecting a playlist."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, playlists: list) -> None:
        """Initialize with available playlists."""
        super().__init__()
        self.playlists = playlists

    def compose(self) -> ComposeResult:
        """Compose the playlist selection screen."""
        yield Container(
            Label("Select Playlist", id="dialog-title"),
            ListView(id="select-playlist-list"),
            Button("Cancel", id="cancel-btn", variant="default"),
            id="dialog-container",
        )

    def on_mount(self) -> None:
        """Populate the playlist list."""
        playlist_list = self.query_one("#select-playlist-list", ListView)
        for playlist in self.playlists:
            playlist_list.append(
                ListItem(
                    Label(f"{playlist.name} ({len(playlist.track_ids)} tracks)"),
                    id=f"select-{playlist.id}",
                )
            )

    @on(ListView.Selected, "#select-playlist-list")
    def on_playlist_selected(self, event: ListView.Selected) -> None:
        """Handle playlist selection."""
        item_id = event.item.id or ""
        if item_id.startswith("select-"):
            try:
                playlist_id = int(item_id.replace("select-", ""))
                self.dismiss(playlist_id)
            except ValueError:
                pass

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_pressed(self) -> None:
        """Handle cancel button press."""
        self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel selection."""
        self.dismiss(None)
