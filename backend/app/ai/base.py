from __future__ import annotations

from typing import Protocol

from app.ai.schemas import ProviderGenerationResult


class AIProvider(Protocol):
    def generate(self, *, prompt: str, image_data_url: str) -> ProviderGenerationResult: ...
