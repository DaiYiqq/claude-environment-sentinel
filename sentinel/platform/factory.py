"""Platform adapter factory."""

from __future__ import annotations

import sys
from functools import lru_cache

from sentinel.platform.base import PlatformAdapter


@lru_cache(maxsize=1)
def get_platform() -> PlatformAdapter:
    if sys.platform.startswith("win"):
        from sentinel.platform.windows import WindowsPlatform

        return WindowsPlatform()
    if sys.platform == "darwin":
        from sentinel.platform.darwin import DarwinPlatform

        return DarwinPlatform()
    from sentinel.platform.linux import LinuxPlatform

    return LinuxPlatform()
