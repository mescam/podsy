"""Tests for iPod device detection and management."""

import tempfile
from pathlib import Path

from podsy.device import (
    IPodDevice,
    _check_ipod_mount,
    _model_number_to_name,
    _parse_sysinfo,
    ensure_music_folders,
    get_ipod,
    init_device,
)


class TestModelNumberToName:
    """Tests for model number mapping."""

    def test_5th_gen_30gb(self) -> None:
        """Test 5th gen 30GB model numbers."""
        assert _model_number_to_name("MA002") == "iPod Video 30GB"
        assert _model_number_to_name("MA146") == "iPod Video 30GB"

    def test_5th_gen_60gb(self) -> None:
        """Test 5th gen 60GB model numbers."""
        assert _model_number_to_name("MA003") == "iPod Video 60GB"
        assert _model_number_to_name("MA147") == "iPod Video 60GB"

    def test_55_gen_30gb(self) -> None:
        """Test 5.5 gen 30GB model numbers."""
        assert _model_number_to_name("MA444") == "iPod Video 30GB"
        assert _model_number_to_name("MA446") == "iPod Video 30GB"

    def test_55_gen_80gb(self) -> None:
        """Test 5.5 gen 80GB model numbers."""
        assert _model_number_to_name("MA448") == "iPod Video 80GB"
        assert _model_number_to_name("MA450") == "iPod Video 80GB"

    def test_u2_edition(self) -> None:
        """Test U2 special edition model numbers."""
        assert _model_number_to_name("MA452") == "iPod Video U2 30GB"
        assert _model_number_to_name("MA664") == "iPod Video U2 30GB"

    def test_lowercase(self) -> None:
        """Test that lowercase model numbers work."""
        assert _model_number_to_name("ma448") == "iPod Video 80GB"

    def test_with_whitespace(self) -> None:
        """Test model numbers with whitespace."""
        assert _model_number_to_name("  MA448  ") == "iPod Video 80GB"

    def test_unknown_model(self) -> None:
        """Test unknown model number."""
        result = _model_number_to_name("XX999")
        assert result == "iPod (XX999)"


class TestParseSysInfo:
    """Tests for SysInfo file parsing."""

    def test_parse_sysinfo_complete(self) -> None:
        """Test parsing SysInfo with all fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sysinfo = Path(tmpdir) / "SysInfo"
            sysinfo.write_text(
                "ModelNumStr: MA448\n"
                "pszSerialNumber: ABC123DEF456\n"
                "visibleBuildID: 1.2.3\n"
            )

            model, serial, firmware = _parse_sysinfo(sysinfo)

            assert model == "iPod Video 80GB"
            assert serial == "ABC123DEF456"
            assert firmware == "1.2.3"

    def test_parse_sysinfo_minimal(self) -> None:
        """Test parsing SysInfo with minimal fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sysinfo = Path(tmpdir) / "SysInfo"
            sysinfo.write_text("ModelNum: MA002\n")

            model, serial, firmware = _parse_sysinfo(sysinfo)

            assert model == "iPod Video 30GB"
            assert serial == ""
            assert firmware == ""

    def test_parse_sysinfo_missing_file(self) -> None:
        """Test parsing non-existent SysInfo file."""
        model, serial, firmware = _parse_sysinfo(Path("/nonexistent/SysInfo"))

        assert model == "iPod"
        assert serial == ""
        assert firmware == ""

    def test_parse_sysinfo_alternate_keys(self) -> None:
        """Test parsing SysInfo with alternate key names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sysinfo = Path(tmpdir) / "SysInfo"
            sysinfo.write_text(
                "ModelNum: MA450\n"
                "SerialNumber: XYZ789\n"
                "BuildID: 2.0.1\n"
            )

            model, serial, firmware = _parse_sysinfo(sysinfo)

            assert model == "iPod Video 80GB"
            assert serial == "XYZ789"
            assert firmware == "2.0.1"


class TestCheckIPodMount:
    """Tests for iPod mount point detection."""

    def test_check_valid_ipod(self) -> None:
        """Test detecting a valid iPod mount."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mount = Path(tmpdir)

            # Create iPod directory structure
            ipod_control = mount / "iPod_Control"
            ipod_control.mkdir()
            (ipod_control / "iTunes").mkdir()
            (ipod_control / "Device").mkdir()

            # Create SysInfo
            sysinfo = ipod_control / "Device" / "SysInfo"
            sysinfo.write_text("ModelNumStr: MA448\n")

            device = _check_ipod_mount(mount)

            assert device is not None
            assert device.mount_point == mount
            assert device.model == "iPod Video 80GB"
            assert device.db_path == ipod_control / "iTunes" / "iTunesDB"
            assert device.music_dir == ipod_control / "Music"

    def test_check_no_ipod_control(self) -> None:
        """Test mount point without iPod_Control."""
        with tempfile.TemporaryDirectory() as tmpdir:
            device = _check_ipod_mount(Path(tmpdir))
            assert device is None

    def test_check_no_itunes_dir(self) -> None:
        """Test mount point without iTunes directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mount = Path(tmpdir)
            (mount / "iPod_Control").mkdir()

            device = _check_ipod_mount(mount)
            assert device is None


class TestIPodDevice:
    """Tests for IPodDevice dataclass."""

    def test_is_valid_with_db(self) -> None:
        """Test is_valid when iTunesDB exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mount = Path(tmpdir)
            db_path = mount / "iTunesDB"
            db_path.touch()

            device = IPodDevice(
                mount_point=mount,
                model="iPod Video 80GB",
                db_path=db_path,
                music_dir=mount / "Music",
            )

            assert device.is_valid is True

    def test_is_valid_without_db(self) -> None:
        """Test is_valid when iTunesDB doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            device = IPodDevice(
                mount_point=Path(tmpdir),
                model="iPod Video 80GB",
                db_path=Path(tmpdir) / "nonexistent",
                music_dir=Path(tmpdir) / "Music",
            )

            assert device.is_valid is False

    def test_free_space(self) -> None:
        """Test getting free space."""
        with tempfile.TemporaryDirectory() as tmpdir:
            device = IPodDevice(
                mount_point=Path(tmpdir),
                model="iPod",
                db_path=Path(tmpdir) / "iTunesDB",
                music_dir=Path(tmpdir) / "Music",
            )

            # Should return non-zero for valid mount point
            assert device.free_space > 0

    def test_total_space(self) -> None:
        """Test getting total space."""
        with tempfile.TemporaryDirectory() as tmpdir:
            device = IPodDevice(
                mount_point=Path(tmpdir),
                model="iPod",
                db_path=Path(tmpdir) / "iTunesDB",
                music_dir=Path(tmpdir) / "Music",
            )

            # Should return non-zero for valid mount point
            assert device.total_space > 0
            # Total should be >= free
            assert device.total_space >= device.free_space


class TestEnsureMusicFolders:
    """Tests for music folder creation."""

    def test_ensure_music_folders_creates_all(self) -> None:
        """Test that all F00-F49 folders are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            device = IPodDevice(
                mount_point=Path(tmpdir),
                model="iPod",
                db_path=Path(tmpdir) / "iTunesDB",
                music_dir=Path(tmpdir) / "Music",
            )

            ensure_music_folders(device)

            assert device.music_dir.exists()
            for i in range(50):
                folder = device.music_dir / f"F{i:02d}"
                assert folder.exists(), f"F{i:02d} should exist"

    def test_ensure_music_folders_idempotent(self) -> None:
        """Test that calling twice doesn't fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            device = IPodDevice(
                mount_point=Path(tmpdir),
                model="iPod",
                db_path=Path(tmpdir) / "iTunesDB",
                music_dir=Path(tmpdir) / "Music",
            )

            ensure_music_folders(device)
            ensure_music_folders(device)  # Should not raise

            assert device.music_dir.exists()


class TestInitDevice:
    """Tests for device initialization."""

    def test_init_device_creates_structure(self) -> None:
        """Test that init_device creates directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mount = Path(tmpdir)
            device = IPodDevice(
                mount_point=mount,
                model="iPod",
                db_path=mount / "iPod_Control" / "iTunes" / "iTunesDB",
                music_dir=mount / "iPod_Control" / "Music",
            )

            init_device(device)

            assert (mount / "iPod_Control").exists()
            assert (mount / "iPod_Control" / "iTunes").exists()
            assert (mount / "iPod_Control" / "Music").exists()
            assert (mount / "iPod_Control" / "Device").exists()

            # Check music folders
            for i in range(50):
                folder = device.music_dir / f"F{i:02d}"
                assert folder.exists()


class TestGetIPod:
    """Tests for get_ipod function."""

    def test_get_ipod_specific_path(self) -> None:
        """Test getting iPod at specific path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mount = Path(tmpdir)

            # Create iPod structure
            ipod_control = mount / "iPod_Control"
            ipod_control.mkdir()
            (ipod_control / "iTunes").mkdir()

            device = get_ipod(mount)

            assert device is not None
            assert device.mount_point == mount

    def test_get_ipod_invalid_path(self) -> None:
        """Test getting iPod at non-iPod path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            device = get_ipod(tmpdir)
            assert device is None
