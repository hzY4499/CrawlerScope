from crawler_scope import __version__
from crawler_scope.healthcheck import check_agentscope_import


def test_check_agentscope_import_returns_version() -> None:
    version = check_agentscope_import()

    assert isinstance(version, str)
    assert version


def test_package_version_is_readable() -> None:
    assert __version__ == "0.1.0"
