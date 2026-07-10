"""Common interface every BioNER model implements.

A model exposes a single ``predict(text) -> list[Entity]`` method returning
character-offset spans. Heavy checkpoints load lazily on first predict so the
registry can be imported (and metadata listed) without pulling in torch.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Entity:
    """A single predicted span. Offsets are character-level, end-exclusive."""
    start: int
    end: int
    text: str
    label: str
    score: float = 1.0

    def as_tuple(self) -> tuple:
        """(start, end, text, label) — the tuple form the evaluator consumes."""
        return (self.start, self.end, self.text, self.label)


class BaseNERModel:
    # Populated by subclasses.
    key: str = "base"
    name: str = "Base"
    model_id: str = ""
    description: str = ""
    license: str = ""
    homepage: str = ""
    # Extra pip packages this model needs beyond the shared core.
    extras: tuple = ()
    # True if the model realistically needs a GPU to be usable.
    prefers_gpu: bool = False

    def __init__(self) -> None:
        self._loaded = False

    def load(self) -> None:
        """Download / instantiate the underlying model. Override in subclasses."""
        raise NotImplementedError

    def _predict(self, text: str) -> list[Entity]:
        """Run inference on already-loaded model. Override in subclasses."""
        raise NotImplementedError

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()
            self._loaded = True

    def predict(self, text: str) -> list[Entity]:
        self.ensure_loaded()
        return self._predict(text)

    def metadata(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "model_id": self.model_id,
            "description": self.description,
            "license": self.license,
            "homepage": self.homepage,
            "extras": list(self.extras),
            "prefers_gpu": self.prefers_gpu,
            "loaded": self._loaded,
        }
