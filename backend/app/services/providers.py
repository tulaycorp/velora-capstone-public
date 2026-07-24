from app.models.schemas import PodProviderKey
from app.providers.registry import provider_adapter_map


class ProviderRegistry:
    def available_provider_ids(self) -> list[PodProviderKey]:
        return list(provider_adapter_map.keys())

    def has_provider(self, provider_id: PodProviderKey) -> bool:
        return provider_id in provider_adapter_map


provider_registry = ProviderRegistry()
