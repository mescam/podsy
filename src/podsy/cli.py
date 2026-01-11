"""Command-line interface for Podsy."""

import argparse
import sys
from pathlib import Path

from podsy import __version__


def main() -> None:
    """Entry point for the podsy command."""
    parser = argparse.ArgumentParser(
        prog="podsy",
        description="TUI for managing iPod 5.5g on Linux",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-d",
        "--device",
        type=Path,
        help="Path to iPod mount point",
        metavar="PATH",
    )
    parser.add_argument(
        "-l",
        "--local",
        type=Path,
        help="Starting directory for local file browser",
        metavar="PATH",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Run in non-interactive mode (for scripting)",
    )

    args = parser.parse_args()

    if args.no_tui:
        # Non-interactive mode - just print status
        from podsy.device import discover_ipods

        devices = discover_ipods()
        if not devices:
            print("No iPod devices found")
            sys.exit(1)

        for device in devices:
            print(f"Found: {device.model}")
            print(f"  Mount: {device.mount_point}")
            print(f"  Database: {device.db_path}")
            if device.db_path.exists():
                from podsy.db import load

                db = load(device.db_path)
                print(f"  Tracks: {len(db.tracks)}")
                print(f"  Playlists: {len(db.playlists)}")
        sys.exit(0)

    # Launch TUI
    from podsy.app import run

    run(
        device_path=args.device,
        local_path=args.local,
    )


if __name__ == "__main__":
    main()
