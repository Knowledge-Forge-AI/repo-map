from pytest import fixture


@fixture
def fake_secret_fixture():
    value = "fake-pytest-fixture-secret"
    return value


def test_uses_fixture(fake_secret_fixture):
    assert fake_secret_fixture
