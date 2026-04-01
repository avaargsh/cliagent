"""Provider metadata catalog."""

from __future__ import annotations

from dataclasses import dataclass

from digital_employee.domain.errors import ProviderNotFoundError
from digital_employee.infra.config.models import LoadedConfig


@dataclass(frozen=True, slots=True)
class ProviderSlot:
    slot_name: str
    provider_name: str
    model: str
    timeout_seconds: int
    max_output_tokens: int = 1024
    api_key_env: str = ""


class ProviderCatalog:
    def __init__(self, slots: dict[str, ProviderSlot]) -> None:
        self._slots = dict(slots)

    @classmethod
    def from_config(cls, config: LoadedConfig) -> "ProviderCatalog":
        return cls(
            {
                slot_name: ProviderSlot(
                    slot_name=slot_name,
                    provider_name=provider.name,
                    model=provider.model,
                    timeout_seconds=provider.timeout_seconds,
                    max_output_tokens=provider.max_output_tokens,
                    api_key_env=provider.api_key_env,
                )
                for slot_name, provider in config.providers.items()
            }
        )

    @classmethod
    def from_names(cls, names: list[str]) -> "ProviderCatalog":
        return cls(
            {
                name: ProviderSlot(
                    slot_name=name,
                    provider_name=name,
                    model="legacy",
                    timeout_seconds=30,
                )
                for name in names
            }
        )

    def resolve_slot(self, slot_name: str) -> ProviderSlot:
        slot = self._slots.get(slot_name)
        if slot is None:
            raise ProviderNotFoundError(slot_name)
        return slot

    def list_names(self) -> list[str]:
        return sorted(self._slots)
