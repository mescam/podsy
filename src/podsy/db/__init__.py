"""Database module for iTunesDB parsing.

This module provides functionality for reading and writing iTunesDB files
used by iPod 5.5g devices.
"""

from .models import Database, FileType, MediaType, MhodType, Playlist, SortOrder, Track
from .parser import InvalidDatabaseError, ITunesDBError, load, save

__all__ = [
    "Database",
    "FileType",
    "ITunesDBError",
    "InvalidDatabaseError",
    "load",
    "MediaType",
    "MhodType",
    "Playlist",
    "save",
    "SortOrder",
    "Track",
]
