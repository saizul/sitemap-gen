import pytest

from fakesite import FakeSite


@pytest.fixture
def site() -> FakeSite:
    return FakeSite()
