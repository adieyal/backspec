"""The repository on disk. Uses git to list files when the root is a git checkout, so that
ignored files are left out the way git leaves them out; otherwise walks the tree."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}


class DiskRepo:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def list_paths(self) -> list[str]:
        listed = self._git_paths()
        if listed is None:
            listed = self._walk()
        inside = []
        for path in listed:
            full = (self.root / path)
            # a symlink that leaves the root is never followed
            if full.is_file() and self.root in full.resolve().parents:
                inside.append(path)
        return sorted(inside)

    def read(self, path: str) -> bytes:
        full = (self.root / path).resolve()
        if self.root not in full.parents:   # a path or symlink that leaves the root is never followed
            raise PermissionError(f"{path} is outside the root")
        return full.read_bytes()

    def _git_paths(self) -> list[str] | None:
        try:
            done = subprocess.run(["git", "-C", str(self.root), "ls-files", "-co", "--exclude-standard", "-z"],
                                  capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if done.returncode != 0:
            return None
        return [p for p in done.stdout.decode("utf-8", "replace").split("\0") if p]

    def _walk(self) -> list[str]:
        found = []
        for folder, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                found.append((Path(folder) / name).relative_to(self.root).as_posix())
        return found
