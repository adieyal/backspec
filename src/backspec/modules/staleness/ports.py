"""What staleness needs from the outside world: reading a file by relative path. This is
discovery's `RepoPort`; only its `read` is used."""
from __future__ import annotations

from backspec.modules.discovery.facade import RepoPort

__all__ = ["RepoPort"]
