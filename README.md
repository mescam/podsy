# 🎵 Podsy

A sleek **TUI (Terminal User Interface)** for managing your iPod Classic 5.5g on Linux. Because your music deserves better than iTunes.

```
    ██████╗  ██████╗ ██████╗ ███████╗██╗   ██╗
    ██╔══██╗██╔═══██╗██╔══██╗██╔════╝╚██╗ ██╔╝
    ██████╔╝██║   ██║██║  ██║███████╗ ╚████╔╝ 
    ██╔═══╝ ██║   ██║██║  ██║╚════██║  ╚██╔╝  
    ██║     ╚██████╔╝██████╔╝███████║   ██║   
    ╚═╝      ╚═════╝ ╚═════╝ ╚══════╝   ╚═╝   
```

## ✨ Features

- **iTunesDB Compatibility** — Full read/write support for iTunesDB versions 0x13-0x15, ensuring your iPod works seamlessly
- **Music Sync** — Drag & drop folders to sync your music library with smart file handling
- **FLAC Transcoding** — Automatically converts FLAC files to AAC during sync
- **MusicBrainz Retagging** — Fix incorrect track and album metadata via MusicBrainz lookup
- **Playlist Management** — Create, edit, delete, and reorder playlists with ease
- **Album Artwork** — Browse your music by artist/album with beautiful cover art support
- **Keyboard-First** — Navigate everything with keyboard shortcuts — no mouse needed

## 🚀 Quick Start

```bash
# Clone and enter the project
git clone https://github.com/mescam/podsy.git
cd podsy

# Enter development environment
nix develop

# Sync dependencies  
uv sync

# Run Podsy
podsy
```

## ⌨️ Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate up/down |
| `Enter` | Select / Play |
| `Space` | Toggle selection |
| `a` | Add music |
| `A` | Add folder |
| `d` | Delete selected |
| `D` | Delete all |
| `p` | Create playlist |
| `e` | Edit playlist |
| `r` | Refresh |
| `q` | Quit |

## 🛠️ Development

```bash
# Run tests
uv run pytest

# Type check
uv run pyright

# Lint
uv run ruff check src tests
```

## 📋 Requirements

- Python 3.13+
- Linux (tested on NixOS)
- iPod Classic 5.5g (or compatible iPod with click wheel)

## 🎧 Supported iPods

- iPod Classic 5th Gen (5.5g recommended)
- iPod Classic 6th Gen
- iPod Video
- Other iPods supporting iTunesDB format

## 🏗️ Architecture

```
podsy/
├── src/podsy/
│   ├── db/          # iTunesDB parser & serializer
│   ├── ui/          # Textual TUI components  
│   ├── device.py    # iPod device detection
│   ├── sync.py      # Music synchronization
│   ├── playlists.py # Playlist management
│   └── artwork.py   # Album artwork handling
└── tests/           # Unit tests (140+ tests)
```

## 📜 License

MIT
