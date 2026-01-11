"""Screen definitions for Podsy TUI."""

from pathlib import Path
from typing import TYPE_CHECKING

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    Static,
)

from ..db import Database, save
from ..device import IPodDevice
from ..playlists import (
    PlaylistError,
    add_track_to_playlist,
    create_playlist,
    delete_playlist,
    remove_track_from_playlist,
)
from ..sync import SyncError, remove_track, sync_file

if TYPE_CHECKING:
    from ..db.models import Track


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
                "Please connect your iPod 5.5g and press 'r' to refresh.",
                id="no-device-message",
            ),
            Button("Refresh", id="refresh-btn", variant="primary"),
            id="no-device-container",
        )
        yield Footer()

    @on(Button.Pressed, "#refresh-btn")
    def on_refresh_pressed(self) -> None:
        """Handle refresh button press."""
        self.app.action_refresh()

    def action_refresh(self) -> None:
        """Refresh device detection."""
        self.app.action_refresh()

    def action_quit(self) -> None:
        """Quit the application."""
        self.app.exit()


class MainScreen(Screen[None]):
    """Main dual-pane synchronization screen."""

    BINDINGS = [
        Binding("tab", "switch_focus", "Switch Pane", show=True),
        Binding("s", "sync_selected", "Sync", show=True),
        Binding("d", "delete_selected", "Delete", show=True),
        Binding("p", "new_playlist", "New Playlist", show=True),
        Binding("a", "add_to_playlist", "Add to Playlist", show=True),
        Binding("escape", "cancel", "Cancel", show=False),
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
                yield Label("iPod Library", classes="pane-title")
                yield DataTable(id="ipod-table")

        # Playlist bar
        with Horizontal(id="playlist-bar"):
            yield Label("Playlists:", id="playlist-label")
            yield ListView(id="playlist-list")
            yield Button("+ New", id="new-playlist-btn", variant="primary")

        # Status bar
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Handle screen mount."""
        self._setup_ipod_table()
        self._load_tracks()
        self._load_playlists()
        self._update_status()

    def _setup_ipod_table(self) -> None:
        """Configure the iPod data table."""
        table = self.query_one("#ipod-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("Title", "Artist", "Album", "Time", "Bitrate")

    def _load_tracks(self, playlist_id: int | None = None) -> None:
        """Load tracks into the data table.

        Args:
            playlist_id: Optional playlist to filter by (None = all tracks)
        """
        table = self.query_one("#ipod-table", DataTable)
        table.clear()

        if playlist_id is not None:
            playlist = self.database.get_playlist_by_id(playlist_id)
            if playlist:
                tracks = [
                    self.database.get_track_by_id(tid)
                    for tid in playlist.track_ids
                ]
                tracks = [t for t in tracks if t is not None]
            else:
                tracks = []
        else:
            tracks = self.database.tracks

        for track in tracks:
            # Format duration
            duration_sec = track.duration_ms // 1000
            minutes = duration_sec // 60
            seconds = duration_sec % 60
            duration_str = f"{minutes}:{seconds:02d}"

            table.add_row(
                track.title or "(No Title)",
                track.artist or "(Unknown)",
                track.album or "(Unknown)",
                duration_str,
                f"{track.bitrate}k" if track.bitrate else "-",
                key=str(track.id),
            )

    def _load_playlists(self) -> None:
        """Load playlists into the playlist list."""
        playlist_list = self.query_one("#playlist-list", ListView)
        playlist_list.clear()

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

    def _update_status(self) -> None:
        """Update the status bar."""
        status = self.query_one("#status-bar", Static)
        track_count = len(self.database.tracks)
        free_mb = self.device.free_space // (1024 * 1024)
        total_mb = self.device.total_space // (1024 * 1024)
        status.update(
            f"{track_count} tracks | {free_mb}MB free / {total_mb}MB total | {self.device.model}"
        )

    def action_switch_focus(self) -> None:
        """Switch focus between panes."""
        self._focus_left = not self._focus_left
        if self._focus_left:
            self.query_one("#local-tree", DirectoryTree).focus()
        else:
            self.query_one("#ipod-table", DataTable).focus()

    def action_sync_selected(self) -> None:
        """Sync selected file(s) to iPod."""
        tree = self.query_one("#local-tree", DirectoryTree)
        selected = tree.cursor_node
        if selected is None or selected.data is None:
            self.notify("No file selected", severity="warning")
            return

        path = selected.data.path
        if not path.is_file():
            self.notify("Please select a file to sync", severity="warning")
            return

        try:
            track = sync_file(self.device, self.database, path)
            save(self.database, self.device.db_path)
            self._load_tracks(self.current_playlist_id)
            self._update_status()
            self.notify(f"Synced: {track.title}", severity="information")
        except SyncError as e:
            self.notify(f"Sync failed: {e}", severity="error")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def action_delete_selected(self) -> None:
        """Delete selected track from iPod."""
        table = self.query_one("#ipod-table", DataTable)
        if table.cursor_row is None:
            self.notify("No track selected", severity="warning")
            return

        row_key = table.get_row_at(table.cursor_row)
        if not row_key:
            return

        # Get track ID from row key
        try:
            # The row key is the cell values, we need to use the key we set
            cursor_row = table.cursor_row
            row_key_obj = table.get_row_at(cursor_row)
            # Actually we stored the key when adding, let's get it differently
            track_id = None
            for key in table.rows:
                if table.get_row_index(key) == cursor_row:
                    track_id = int(key.value)
                    break

            if track_id is None:
                return

            track = self.database.get_track_by_id(track_id)
            if track is None:
                return

            remove_track(self.device, self.database, track)
            save(self.database, self.device.db_path)
            self._load_tracks(self.current_playlist_id)
            self._update_status()
            self.notify(f"Deleted: {track.title}", severity="information")
        except Exception as e:
            self.notify(f"Delete failed: {e}", severity="error")

    def action_new_playlist(self) -> None:
        """Create a new playlist."""
        self.app.push_screen(NewPlaylistScreen(), self._on_playlist_created)

    def _on_playlist_created(self, name: str | None) -> None:
        """Handle new playlist creation result."""
        if name:
            try:
                playlist = create_playlist(self.database, name)
                save(self.database, self.device.db_path)
                self._load_playlists()
                self.notify(f"Created playlist: {name}", severity="information")
            except PlaylistError as e:
                self.notify(f"Failed: {e}", severity="error")

    def action_add_to_playlist(self) -> None:
        """Add selected track to a playlist."""
        table = self.query_one("#ipod-table", DataTable)
        if table.cursor_row is None:
            self.notify("No track selected", severity="warning")
            return

        # Get track ID
        track_id = None
        cursor_row = table.cursor_row
        for key in table.rows:
            if table.get_row_index(key) == cursor_row:
                track_id = int(key.value)
                break

        if track_id is None:
            return

        # Show playlist selection
        playlists = [p for p in self.database.playlists if not p.is_master]
        if not playlists:
            self.notify("No playlists available. Create one first.", severity="warning")
            return

        self.app.push_screen(
            SelectPlaylistScreen(playlists),
            lambda pid: self._on_playlist_selected(pid, track_id),
        )

    def _on_playlist_selected(self, playlist_id: int | None, track_id: int) -> None:
        """Handle playlist selection for adding track."""
        if playlist_id:
            try:
                add_track_to_playlist(self.database, playlist_id, track_id)
                save(self.database, self.device.db_path)
                self._load_playlists()
                playlist = self.database.get_playlist_by_id(playlist_id)
                name = playlist.name if playlist else "Unknown"
                self.notify(f"Added to playlist: {name}", severity="information")
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
        self._load_tracks(self.current_playlist_id)

    @on(Button.Pressed, "#new-playlist-btn")
    def on_new_playlist_pressed(self) -> None:
        """Handle new playlist button press."""
        self.action_new_playlist()


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
