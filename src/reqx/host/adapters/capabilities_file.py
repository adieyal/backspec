"""The capabilities file: the owner's list of capabilities, kept as YAML in the analysed repository."""
from __future__ import annotations

from pathlib import Path

import yaml

from reqx.modules.capabilities.facade import CapabilitiesFileError, Capability

HEADER = """\
# The capabilities of this codebase, as reqx proposed them.
# You can edit this file: rename, merge, split, add or delete capabilities.
# `reqx extract` uses it as it is and skips the step that proposes capabilities.
# Observations are placed in these capabilities again on every run; that is not stored here.
# Each id is unique: lowercase letters, digits and underscores. A name is required.
# Keep `plumbing` for machinery no user would notice; it is added if missing.
"""


class YamlCapabilitiesFile:
    def __init__(self, path: Path):
        self.path = Path(path)

    @property
    def location(self) -> str:
        return str(self.path)

    def read(self) -> object | None:
        if not self.path.is_file():
            return None
        try:
            return yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError) as error:
            raise CapabilitiesFileError(f"{self.path} is not valid YAML: {error}") from error

    def write(self, capabilities: list[Capability]) -> None:
        body = yaml.safe_dump([c.model_dump() for c in capabilities], sort_keys=False, allow_unicode=True,
                              default_flow_style=False, width=100)
        self.path.write_text(HEADER + "\n" + body, encoding="utf-8")
