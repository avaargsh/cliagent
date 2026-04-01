"""Provider instance factory and cache."""

from __future__ import annotations

from typing import Callable

from digital_employee.contracts.providers import Provider
from digital_employee.domain.errors import ProviderExecutionError
from digital_employee.providers.catalog import ProviderCatalog, ProviderSlot
from digital_employee.providers.mock_provider import MockProvider
from digital_employee.providers.models import CompletionRequest, CompletionResult
from digital_employee.providers.openai_provider import OpenAIProvider


ProviderBuilder = Callable[[], Provider]


class ProviderFactory:
    def __init__(
        self,
        catalog: ProviderCatalog,
        builders: dict[str, ProviderBuilder] | None = None,
    ) -> None:
        self._catalog = catalog
        self._builders = dict(builders or {})
        self._instances: dict[str, Provider] = {}

    def resolve(self, slot_name: str) -> Provider:
        slot = self._catalog.resolve_slot(slot_name)
        if slot_name not in self._instances:
            self._instances[slot_name] = self._build(slot)
        return self._instances[slot_name]

    def _build(self, slot: ProviderSlot) -> Provider:
        builder = self._builders.get(slot.slot_name)
        if builder is not None:
            return builder()
        return _build_default_provider(slot)


class _UnavailableProvider:
    def __init__(self, provider_name: str) -> None:
        self.name = provider_name

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        raise ProviderExecutionError(
            self.name,
            "this provider is configured but not implemented in the bootstrap runtime",
        )


def _build_default_provider(slot: ProviderSlot) -> Provider:
    if slot.provider_name == "mock":
        return MockProvider(name=slot.provider_name, model=slot.model)
    if slot.provider_name == "openai":
        return OpenAIProvider(
            name=slot.provider_name,
            model=slot.model,
            timeout_seconds=slot.timeout_seconds,
            max_output_tokens=slot.max_output_tokens,
            api_key_env=slot.api_key_env or "OPENAI_API_KEY",
        )
    return _UnavailableProvider(slot.provider_name)
