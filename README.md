# Podsy

TUI for managing iPod 5.5g on Linux.

## Features

- Parse and write iTunesDB (versions 0x13-0x15)
- Sync music files to iPod
- Create and manage playlists
- Keyboard-driven terminal interface

## Requirements

- Python 3.13+
- Nix (for development environment)

## Development

```bash
# Enter development shell
nix develop

# Sync dependencies
uv sync

# Run the application
uv run podsy

# Run tests
uv run pytest

# Type check
uv run pyright

# Lint
uv run ruff check src tests
```

## Usage

```bash
podsy
```

## License

MIT
