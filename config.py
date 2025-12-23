"""Configuration loader for RTSP camera settings."""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import yaml


@dataclass
class CameraConfig:
    """Configuration for a single RTSP camera."""

    name: str
    address: str
    port: int
    username: str
    password: str
    path: str = ""

    @property
    def rtsp_url(self) -> str:
        """Generate the RTSP URL with credentials."""
        # URL-encode username and password to handle special characters
        encoded_user = quote(self.username, safe="")
        encoded_pass = quote(self.password, safe="")

        # Build the path, ensuring it starts with / if non-empty
        path = self.path
        if path and not path.startswith("/"):
            path = "/" + path

        return f"rtsp://{encoded_user}:{encoded_pass}@{self.address}:{self.port}{path}"

    @property
    def rtsp_url_display(self) -> str:
        """Generate the RTSP URL without credentials for display."""
        path = self.path
        if path and not path.startswith("/"):
            path = "/" + path
        return f"rtsp://{self.address}:{self.port}{path}"


def load_cameras(config_path: str | Path = "cameras.yaml") -> list[CameraConfig]:
    """Load camera configurations from a YAML file."""
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    if not data or "cameras" not in data:
        return []

    cameras = []
    for cam_data in data["cameras"]:
        camera = CameraConfig(
            name=cam_data.get("name", "Unnamed Camera"),
            address=cam_data["address"],
            port=cam_data.get("port", 554),
            username=cam_data.get("username", ""),
            password=cam_data.get("password", ""),
            path=cam_data.get("path", ""),
        )
        cameras.append(camera)

    return cameras
