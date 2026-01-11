"""iPod device detection and management.

This module provides functionality to discover and interact with
mounted iPod 5.5g devices on Linux systems.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class IPodDevice:
    """Represents a connected iPod device."""

    mount_point: Path
    model: str
    db_path: Path
    music_dir: Path
    serial: str = ""
    firmware_version: str = ""

    @property
    def is_valid(self) -> bool:
        """Check if the device has a valid iTunesDB."""
        return self.db_path.exists()

    @property
    def free_space(self) -> int:
        """Get free space on device in bytes."""
        try:
            stat = os.statvfs(self.mount_point)
            return stat.f_bavail * stat.f_frsize
        except OSError:
            return 0

    @property
    def total_space(self) -> int:
        """Get total space on device in bytes."""
        try:
            stat = os.statvfs(self.mount_point)
            return stat.f_blocks * stat.f_frsize
        except OSError:
            return 0


def discover_ipods() -> list[IPodDevice]:
    """Scan common mount points for iPod devices.

    Searches /media, /mnt, /run/media/$USER, and other common
    locations for mounted iPod filesystems.

    Returns:
        List of discovered IPodDevice objects.
    """
    devices: list[IPodDevice] = []
    search_paths: list[Path] = []

    # Common mount locations on Linux
    search_paths.append(Path("/media"))
    search_paths.append(Path("/mnt"))

    # User-specific mount points
    user = os.getenv("USER", "")
    if user:
        search_paths.append(Path(f"/run/media/{user}"))
        search_paths.append(Path(f"/media/{user}"))

    # Home directory mounts
    home = Path.home()
    search_paths.append(home / "mnt")

    # Scan each search path
    for search_path in search_paths:
        if not search_path.exists():
            continue

        # Check direct children (mount points)
        try:
            for entry in search_path.iterdir():
                if entry.is_dir():
                    device = _check_ipod_mount(entry)
                    if device:
                        devices.append(device)
        except PermissionError:
            continue

    return devices


def _check_ipod_mount(path: Path) -> IPodDevice | None:
    """Check if a path is an iPod mount point.

    Args:
        path: Path to check

    Returns:
        IPodDevice if valid iPod found, None otherwise
    """
    ipod_control = path / "iPod_Control"
    if not ipod_control.exists():
        return None

    itunes_dir = ipod_control / "iTunes"
    if not itunes_dir.exists():
        return None

    db_path = itunes_dir / "iTunesDB"
    music_dir = ipod_control / "Music"

    # Try to read device info
    model = "iPod"
    serial = ""
    firmware_version = ""

    sysinfo_path = ipod_control / "Device" / "SysInfo"
    if sysinfo_path.exists():
        model, serial, firmware_version = _parse_sysinfo(sysinfo_path)

    # Also try SysInfoExtended
    sysinfo_ext_path = ipod_control / "Device" / "SysInfoExtended"
    if sysinfo_ext_path.exists() and model == "iPod":
        model_ext, serial_ext, fw_ext = _parse_sysinfo(sysinfo_ext_path)
        if model_ext != "iPod":
            model = model_ext
        if serial_ext:
            serial = serial_ext
        if fw_ext:
            firmware_version = fw_ext

    return IPodDevice(
        mount_point=path,
        model=model,
        db_path=db_path,
        music_dir=music_dir,
        serial=serial,
        firmware_version=firmware_version,
    )


def _parse_sysinfo(path: Path) -> tuple[str, str, str]:
    """Parse SysInfo file for device information.

    Args:
        path: Path to SysInfo file

    Returns:
        Tuple of (model, serial, firmware_version)
    """
    model = "iPod"
    serial = ""
    firmware_version = ""

    try:
        content = path.read_text(errors="replace")

        # Parse key-value pairs
        for line in content.split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()

                if key == "ModelNumStr" or key == "ModelNum":
                    model = _model_number_to_name(value)
                elif key == "pszSerialNumber" or key == "SerialNumber":
                    serial = value
                elif key == "visibleBuildID" or key == "BuildID":
                    firmware_version = value
                elif key == "FirewireGuid" and not serial:
                    # Sometimes serial is here
                    serial = value

    except (OSError, UnicodeDecodeError):
        pass

    return model, serial, firmware_version


def _model_number_to_name(model_num: str) -> str:
    """Convert iPod model number to human-readable name.

    Args:
        model_num: Model number string (e.g., "MA002", "MA446")

    Returns:
        Human-readable model name
    """
    # iPod 5th Gen (Video) and 5.5 Gen model numbers
    model_map = {
        # 5th Gen (Video) - 30GB
        "MA002": "iPod Video 30GB",
        "MA146": "iPod Video 30GB",
        # 5th Gen (Video) - 60GB
        "MA003": "iPod Video 60GB",
        "MA147": "iPod Video 60GB",
        # 5.5 Gen (Enhanced) - 30GB
        "MA444": "iPod Video 30GB",
        "MA446": "iPod Video 30GB",
        # 5.5 Gen (Enhanced) - 80GB (the target device)
        "MA448": "iPod Video 80GB",
        "MA450": "iPod Video 80GB",
        # U2 Special Edition
        "MA452": "iPod Video U2 30GB",
        "MA664": "iPod Video U2 30GB",
    }

    # Clean up model number
    model_num = model_num.upper().strip()

    # Try direct match
    if model_num in model_map:
        return model_map[model_num]

    # Try with just the alphanumeric part
    match = re.match(r"([A-Z]{2}\d{3})", model_num)
    if match:
        clean_num = match.group(1)
        if clean_num in model_map:
            return model_map[clean_num]

    # Default to generic name with model number
    return f"iPod ({model_num})"


def get_ipod(mount_point: Path | str | None = None) -> IPodDevice | None:
    """Get an iPod device, either at a specific path or auto-discovered.

    Args:
        mount_point: Optional specific mount point to check.
                     If None, auto-discovers the first available iPod.

    Returns:
        IPodDevice if found, None otherwise.
    """
    if mount_point is not None:
        path = Path(mount_point)
        return _check_ipod_mount(path)

    # Auto-discover
    devices = discover_ipods()
    return devices[0] if devices else None


def ensure_music_folders(device: IPodDevice) -> None:
    """Ensure the F00-F49 music folders exist on the device.

    Args:
        device: iPod device to set up
    """
    if not device.music_dir.exists():
        device.music_dir.mkdir(parents=True)

    for i in range(50):
        folder = device.music_dir / f"F{i:02d}"
        if not folder.exists():
            folder.mkdir()


def init_device(device: IPodDevice) -> None:
    """Initialize an iPod device with required directory structure.

    Creates the iPod_Control directory structure and an empty iTunesDB
    if they don't exist.

    Args:
        device: iPod device to initialize
    """
    # Create directory structure
    (device.mount_point / "iPod_Control").mkdir(exist_ok=True)
    (device.mount_point / "iPod_Control" / "iTunes").mkdir(exist_ok=True)
    (device.mount_point / "iPod_Control" / "Music").mkdir(exist_ok=True)
    (device.mount_point / "iPod_Control" / "Device").mkdir(exist_ok=True)

    # Create music folders
    ensure_music_folders(device)
