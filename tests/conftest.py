"""
Test configuration: isolate all tests from the production DB by pointing
AVS_DATA_DIR at a temporary directory before any avs module is imported.

pytest_configure fires before test collection and before any conftest
fixtures, so avs.config reads AVS_DATA_DIR at import time and picks up
the test path automatically.
"""
import os
import shutil
import tempfile

import pytest

_TEST_TMP: str | None = None


def pytest_configure(config):
    global _TEST_TMP
    _TEST_TMP = tempfile.mkdtemp(prefix="avs_test_")
    os.environ["AVS_DATA_DIR"] = _TEST_TMP


def pytest_unconfigure(config):
    os.environ.pop("AVS_DATA_DIR", None)
    if _TEST_TMP:
        shutil.rmtree(_TEST_TMP, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    """Initialise tables in the test DB once per pytest session."""
    from avs.models.db import init_db
    init_db()
