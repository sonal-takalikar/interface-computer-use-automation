"""
Artifact Storage Utility.
Handles JSON serialization, deserialization, schema validation,
and version checks for CapabilityArtifact objects.
"""

import json
from pathlib import Path
from typing import Union
from core.artifact.schema import CapabilityArtifact


class ArtifactStorage:
    """Manages loading and saving of CapabilityArtifact JSON files."""

    @classmethod
    def save(cls, artifact: CapabilityArtifact, file_path: Union[str, Path]) -> str:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        json_data = artifact.model_dump_json(indent=2)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json_data)
        return str(path.resolve())

    @classmethod
    def load(cls, file_path: Union[str, Path]) -> CapabilityArtifact:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Capability artifact file not found: {file_path}")
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return CapabilityArtifact.model_validate(raw)

    @classmethod
    def validate_dict(cls, data: dict) -> CapabilityArtifact:
        return CapabilityArtifact.model_validate(data)
