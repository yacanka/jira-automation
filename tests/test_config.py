import pytest

from jira_test.config import Config
from jira_test.errors import ConfigurationError


def test_credentials_are_environment_only(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(
        "base_url: https://jira.example.test/jira\nsource_project: SRC\ntest_project: TST\n"
    )
    monkeypatch.setenv("JIRA_USERNAME", "local-user")
    monkeypatch.setenv("JIRA_PASSWORD", "private-value")
    config = Config.load(path)
    assert config.base_url == "https://jira.example.test/jira"
    assert "private-value" not in repr(config)
    assert config.timeout == 20


@pytest.mark.parametrize(
    "url", ["http://jira.example.test", "https://user:pass@jira.test", "file:///tmp/a"]
)
def test_unsafe_urls_rejected(url):
    with pytest.raises(ConfigurationError):
        Config(base_url=url, source_project="SRC", test_project="TST")


def test_source_project_cannot_be_test_project():
    with pytest.raises(ConfigurationError):
        Config(base_url="https://jira.test", source_project="SRC", test_project="src")


@pytest.mark.parametrize("verify", ["", "   "])
def test_empty_ca_path_cannot_disable_tls(verify):
    with pytest.raises(ConfigurationError):
        Config(
            base_url="https://jira.test",
            source_project="SRC",
            test_project="TST",
            verify_tls=verify,
        )
