from __future__ import annotations

from typing import Any

from app.models.schemas import PodProviderKey
from app.providers.base import BaseProviderAdapter
from app.providers.gelato import GelatoAdapter
from app.providers.printify import PrintifyAdapter


provider_adapter_map: dict[PodProviderKey, type[BaseProviderAdapter]] = {
    "printify": PrintifyAdapter,
    "gelato": GelatoAdapter,
}


def get_provider_adapter(provider: PodProviderKey, credentials: dict[str, Any]) -> BaseProviderAdapter:
    adapter_cls = provider_adapter_map.get(provider)
    if adapter_cls is None:
        raise ValueError(f"Unsupported provider '{provider}'.")
    return adapter_cls(credentials)
