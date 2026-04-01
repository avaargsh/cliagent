from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from digital_employee.domain.errors import ProviderExecutionError, ProviderNotFoundError
from digital_employee.providers.models import CompletionRequest
from digital_employee.providers.router import ProviderRouter, build_provider


class ProviderRouterTest(unittest.TestCase):
    def test_router_returns_cached_provider_instance(self) -> None:
        router = ProviderRouter({"mock": lambda: build_provider("mock", model="mock-default", timeout_seconds=5)})
        first = router.resolve("mock")
        second = router.resolve("mock")
        self.assertIs(first, second)

    def test_missing_provider_raises(self) -> None:
        router = ProviderRouter({})
        with self.assertRaises(ProviderNotFoundError):
            router.resolve("missing")

    def test_openai_provider_requires_credentials(self) -> None:
        provider = build_provider("openai", model="gpt-5.4", timeout_seconds=30)
        with self.assertRaises(ProviderExecutionError):
            asyncio.run(
                provider.complete(
                    CompletionRequest(
                        system="Employee Test",
                        prompt="Hello",
                    )
                )
            )


if __name__ == "__main__":
    unittest.main()
