from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from digital_employee.domain.errors import ProviderExecutionError, ProviderNotFoundError
from digital_employee.providers.catalog import ProviderCatalog, ProviderSlot
from digital_employee.providers.factory import ProviderFactory
from digital_employee.providers.models import CompletionRequest


class ProviderCatalogFactoryTest(unittest.TestCase):
    def test_catalog_resolves_slot(self) -> None:
        catalog = ProviderCatalog(
            {
                "mock": ProviderSlot(
                    slot_name="mock",
                    provider_name="mock",
                    model="mock-default",
                    timeout_seconds=5,
                )
            }
        )
        slot = catalog.resolve_slot("mock")
        self.assertEqual(slot.provider_name, "mock")
        self.assertEqual(catalog.list_names(), ["mock"])

    def test_catalog_missing_slot_raises(self) -> None:
        with self.assertRaises(ProviderNotFoundError):
            ProviderCatalog({}).resolve_slot("missing")

    def test_factory_caches_instance_per_slot(self) -> None:
        catalog = ProviderCatalog(
            {
                "mock": ProviderSlot(
                    slot_name="mock",
                    provider_name="mock",
                    model="mock-default",
                    timeout_seconds=5,
                )
            }
        )
        factory = ProviderFactory(catalog)
        first = factory.resolve("mock")
        second = factory.resolve("mock")
        self.assertIs(first, second)

    def test_factory_builds_openai_provider_that_requires_credentials(self) -> None:
        catalog = ProviderCatalog(
            {
                "openai": ProviderSlot(
                    slot_name="openai",
                    provider_name="openai",
                    model="gpt-5.4",
                    timeout_seconds=30,
                )
            }
        )
        provider = ProviderFactory(catalog).resolve("openai")
        with self.assertRaises(ProviderExecutionError):
            asyncio.run(provider.complete(CompletionRequest(system="test", prompt="hello")))


if __name__ == "__main__":
    unittest.main()
