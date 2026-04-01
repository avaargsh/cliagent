"""Provider routing and factory helpers."""

from __future__ import annotations

from typing import Callable

from digital_employee.contracts.providers import Provider
from digital_employee.domain.errors import ProviderExecutionError
from digital_employee.providers.catalog import ProviderCatalog
from digital_employee.providers.factory import ProviderFactory
from digital_employee.providers.mock_provider import MockProvider
from digital_employee.providers.models import CompletionRequest, CompletionResult
from digital_employee.providers.openai_provider import OpenAIProvider

LegacyProviderFactoryFn = Callable[[], Provider]


class ProviderRouter:
    def __init__(
        self,
        factories: dict[str, LegacyProviderFactoryFn] | None = None,
        *,
        catalog: ProviderCatalog | None = None,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        legacy_factories = dict(factories or {})
        if catalog is None:
            catalog = ProviderCatalog.from_names(list(legacy_factories))
        self._catalog = catalog
        if provider_factory is None:
            if legacy_factories:
                provider_factory = _LegacyProviderFactory(legacy_factories)
            else:
                provider_factory = ProviderFactory(catalog)
        self._provider_factory = provider_factory

    def resolve(self, provider_name: str) -> Provider:
        self._catalog.resolve_slot(provider_name)
        return self._provider_factory.resolve(provider_name)

    def list_names(self) -> list[str]:
        return self._catalog.list_names()


class _LegacyProviderFactory:
    def __init__(self, factories: dict[str, LegacyProviderFactoryFn]) -> None:
        self._factories = dict(factories)
        self._instances: dict[str, Provider] = {}

    def resolve(self, provider_name: str) -> Provider:
        if provider_name not in self._instances:
            self._instances[provider_name] = self._factories[provider_name]()
        return self._instances[provider_name]


class _UnavailableProvider:
    def __init__(self, provider_name: str) -> None:
        self.name = provider_name

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        raise ProviderExecutionError(
            self.name,
            "this provider is configured but not implemented in the bootstrap runtime",
        )


def build_provider(
    provider_name: str,
    *,
    model: str,
    timeout_seconds: int,
    max_output_tokens: int = 1024,
    api_key_env: str = "",
) -> Provider:
    if provider_name == "mock":
        return MockProvider(name=provider_name, model=model)
    if provider_name == "openai":
        return OpenAIProvider(
            name=provider_name,
            model=model,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
            api_key_env=api_key_env or "OPENAI_API_KEY",
        )
    return _UnavailableProvider(provider_name)
