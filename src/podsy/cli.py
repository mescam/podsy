"""Command-line interface for Podsy."""

from podsy import __version__


def main() -> None:
    """Entry point for the podsy command."""
    print(f"Podsy v{__version__} - iPod 5.5g Manager")
    print("TUI coming soon...")


if __name__ == "__main__":
    main()
