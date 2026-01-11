"""Tests for iTunesDB binary atom schemas and helper functions."""

import pytest

from podsy.db.atoms import (
    MAC_EPOCH_OFFSET,
    MHBD_HEADER_SIZE,
    MHIP_HEADER_SIZE,
    MHIT_HEADER_SIZE_V14,
    MHLP_HEADER_SIZE,
    MHLT_HEADER_SIZE,
    MHOD_HEADER_SIZE,
    MHSD_HEADER_SIZE,
    MHYP_HEADER_SIZE,
    decode_path,
    decode_string,
    encode_path,
    encode_string,
)


class TestConstants:
    """Tests for header size constants."""

    def test_mac_epoch_offset(self) -> None:
        """Test Mac HFS+ epoch offset."""
        # Seconds between 1904-01-01 and 1970-01-01
        assert MAC_EPOCH_OFFSET == 2082844800

    def test_header_sizes(self) -> None:
        """Test header size constants."""
        assert MHBD_HEADER_SIZE == 0x68  # 104 bytes
        assert MHSD_HEADER_SIZE == 0x60  # 96 bytes
        assert MHLT_HEADER_SIZE == 0x5C  # 92 bytes
        assert MHOD_HEADER_SIZE == 0x18  # 24 bytes
        assert MHLP_HEADER_SIZE == 0x5C  # 92 bytes
        assert MHYP_HEADER_SIZE == 0x6C  # 108 bytes
        assert MHIP_HEADER_SIZE == 0x4C  # 76 bytes
        assert MHIT_HEADER_SIZE_V14 == 0x184  # 388 bytes


class TestStringEncoding:
    """Tests for string encoding/decoding functions."""

    def test_encode_string_ascii(self) -> None:
        """Test encoding ASCII strings to UTF-16LE."""
        result = encode_string("Hello")
        # UTF-16LE: 'H' = 0x48 0x00, 'e' = 0x65 0x00, etc.
        assert result == b"H\x00e\x00l\x00l\x00o\x00"

    def test_encode_string_unicode(self) -> None:
        """Test encoding Unicode strings to UTF-16LE."""
        result = encode_string("Café")
        # 'é' is U+00E9 = 0xE9 0x00 in UTF-16LE
        assert result == b"C\x00a\x00f\x00\xe9\x00"

    def test_encode_string_empty(self) -> None:
        """Test encoding empty string."""
        result = encode_string("")
        assert result == b""

    def test_decode_string_ascii(self) -> None:
        """Test decoding UTF-16LE to ASCII string."""
        data = b"H\x00e\x00l\x00l\x00o\x00"
        result = decode_string(data)
        assert result == "Hello"

    def test_decode_string_unicode(self) -> None:
        """Test decoding UTF-16LE to Unicode string."""
        data = b"C\x00a\x00f\x00\xe9\x00"
        result = decode_string(data)
        assert result == "Café"

    def test_decode_string_empty(self) -> None:
        """Test decoding empty bytes."""
        result = decode_string(b"")
        assert result == ""

    def test_encode_decode_roundtrip(self) -> None:
        """Test that encode/decode are inverses."""
        original = "Test Song - Ätist"
        encoded = encode_string(original)
        decoded = decode_string(encoded)
        assert decoded == original


class TestPathEncoding:
    """Tests for path encoding/decoding functions."""

    def test_encode_path_with_leading_colon(self) -> None:
        """Test encoding path that already has leading colon."""
        result = encode_path(":iPod_Control:Music:F00:ABCD.mp3")
        expected = ":iPod_Control:Music:F00:ABCD.mp3".encode("utf-16-le")
        assert result == expected

    def test_encode_path_without_leading_colon(self) -> None:
        """Test encoding path without leading colon."""
        result = encode_path("iPod_Control:Music:F00:ABCD.mp3")
        # Should add leading colon
        expected = ":iPod_Control:Music:F00:ABCD.mp3".encode("utf-16-le")
        assert result == expected

    def test_encode_path_with_slashes(self) -> None:
        """Test encoding path with forward slashes."""
        result = encode_path("/iPod_Control/Music/F00/ABCD.mp3")
        # Path gets : prefix, then slashes become colons -> ::iPod_Control:...
        expected = "::iPod_Control:Music:F00:ABCD.mp3".encode("utf-16-le")
        assert result == expected

    def test_encode_path_too_long(self) -> None:
        """Test encoding path that exceeds 112 bytes."""
        # Create a path that would exceed 112 bytes in UTF-16LE
        long_path = ":iPod_Control:Music:F00:" + "X" * 60 + ".mp3"
        # Each char is 2 bytes in UTF-16LE
        # 26 + 60 + 4 = 90 chars = 180 bytes > 112
        with pytest.raises(ValueError, match="Path too long"):
            encode_path(long_path)

    def test_decode_path(self) -> None:
        """Test decoding path from UTF-16LE."""
        data = ":iPod_Control:Music:F00:ABCD.mp3".encode("utf-16-le")
        result = decode_path(data)
        assert result == ":iPod_Control:Music:F00:ABCD.mp3"

    def test_path_encode_decode_roundtrip(self) -> None:
        """Test that path encode/decode are inverses."""
        original = ":iPod_Control:Music:F42:TEST.m4a"
        encoded = encode_path(original)
        decoded = decode_path(encoded)
        assert decoded == original
