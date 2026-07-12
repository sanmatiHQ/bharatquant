import os, sys

import pytest

# Add src to sys.path for test imports
BASE_DIR = os.path.dirname(__file__)
SRC = os.path.join(BASE_DIR, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)

pytest_plugins = ("pytest_asyncio",)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
