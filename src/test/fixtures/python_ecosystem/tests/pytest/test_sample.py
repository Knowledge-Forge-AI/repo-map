import pytest


@pytest.fixture
def client():
    return object()


@pytest.mark.parametrize("value", [1, 2])
def test_works(client, value):
    assert value in {1, 2}


class TestFeature:
    @pytest.mark.slow
    def test_method(self):
        assert True
