"""
Shared test configuration.
Sets up pytest-asyncio and common fixtures.
"""

import pytest


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
