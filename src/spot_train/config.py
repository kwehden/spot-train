"""Runtime configuration models and loading helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpotConnectionConfig:
    """Spot robot connection details read from environment variables."""

    hostname: str
    username: str
    password: str

    @classmethod
    def from_env(cls) -> SpotConnectionConfig:
        return cls(
            hostname=os.environ["SPOT_HOSTNAME"],
            username=os.environ["SPOT_USERNAME"],
            password=os.environ["SPOT_PASSWORD"],
        )
