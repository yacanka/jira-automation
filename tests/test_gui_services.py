import pytest

from jira_test.config import Config
from jira_test.errors import ConfigurationError
from jira_test.services import explore


def test_explore_rejects_unconfigured_project_before_connecting(tmp_path):
    config = Config("https://jira.invalid", "SRC", "TST")
    with pytest.raises(ConfigurationError, match="source or test"):
        explore(config, project="OTHER", api_only=True, output=tmp_path)
