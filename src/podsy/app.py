"""Main Textual application for Podsy."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from .db import Database, load, save
from .db.parser import InvalidDatabaseError
from .device import IPodDevice, discover_ipods, get_ipod
from .ui.screens import MainScreen, NoDeviceScreen


class PodsyApp(App[None]):
    """Podsy - iPod 5.5g Manager TUI."""

    TITLE = "Podsy"
    SUB_TITLE = "iPod 5.5g Manager"
    CSS_PATH = "ui/styles.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True, priority=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("?", "help", "Help", show=True),
    ]

    def __init__(
        self,
        *,
        device_path: Path | str | None = None,
        local_path: Path | str | None = None,
    ) -> None:
        """Initialize the Podsy application.

        Args:
            device_path: Optional specific iPod mount point
            local_path: Optional starting directory for local browser
        """
        super().__init__()
        self.device_path = Path(device_path) if device_path else None
        self.local_path = Path(local_path) if local_path else Path.home() / "Music"
        self.device: IPodDevice | None = None
        self.database: Database | None = None

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        """Handle application mount."""
        self._connect_device()

    def _connect_device(self) -> None:
        """Attempt to connect to an iPod device."""
        # Try to find a device
        if self.device_path:
            self.device = get_ipod(self.device_path)
        else:
            devices = discover_ipods()
            self.device = devices[0] if devices else None

        if self.device is None:
            self.push_screen(NoDeviceScreen())
            return

        # Try to load the database
        try:
            if self.device.db_path.exists():
                self.database = load(self.device.db_path)
            else:
                # Create a new empty database
                self.database = Database()
                save(self.database, self.device.db_path)
        except InvalidDatabaseError as e:
            self.notify(f"Database error: {e}", severity="error")
            self.database = Database()

        # Update subtitle with device info
        self.sub_title = f"{self.device.model}"

        # Push the main screen
        self.push_screen(MainScreen(self.device, self.database, self.local_path))

    def action_refresh(self) -> None:
        """Refresh device connection."""
        # Pop all screens and reconnect
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self._connect_device()

    def action_help(self) -> None:
        """Show help dialog."""
        self.notify(
            "s: Sync | d: Delete | p: New Playlist | a: Add to Playlist | Tab: Switch Pane",
            title="Keyboard Shortcuts",
        )

    def save_database(self) -> bool:
        """Save the current database to the device.

        Returns:
            True if save was successful, False otherwise.
        """
        if self.device is None or self.database is None:
            return False

        try:
            save(self.database, self.device.db_path)
            self.notify("Database saved", severity="information")
            return True
        except Exception as e:
            self.notify(f"Failed to save database: {e}", severity="error")
            return False


def run(
    device_path: Path | str | None = None,
    local_path: Path | str | None = None,
) -> None:
    """Run the Podsy application.

    Args:
        device_path: Optional specific iPod mount point
        local_path: Optional starting directory for local browser
    """
    app = PodsyApp(device_path=device_path, local_path=local_path)
    app.run()
