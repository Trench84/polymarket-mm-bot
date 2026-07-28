from __future__ import annotations

from pathlib import Path


class KillSwitch:
    def __init__(self, flag_path: Path) -> None:
        self._flag_path = flag_path

    def is_triggered(self) -> bool:
        return self._flag_path.exists()
