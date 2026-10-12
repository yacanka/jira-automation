import pytest
import requests

from jira_test.client import JiraClient
from jira_test.config import Config
from jira_test.errors import ApiError, WriteBoundaryError


class FakeSession:
    def __init__(self, responses=()):
        self.responses = iter(responses)
        self.calls = []
        self.auth = None
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)

    def close(self):
        pass


def response(data, status=200):
    import json

    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(data).encode()
    return result


def client(session):
    return JiraClient(
        Config(base_url="https://jira.test", source_project="SRC", test_project="TST"),
        session=session,
    )


def test_pagination_collects_all_pages():
    session = FakeSession(
        [
            response({"values": [{"id": "1"}], "total": 2, "startAt": 0, "maxResults": 1}),
            response({"values": [{"id": "2"}], "total": 2, "startAt": 1, "maxResults": 1}),
        ]
    )
    assert client(session).issue_types("SRC") == [{"id": "1"}, {"id": "2"}]
    assert session.calls[1][2]["params"]["startAt"] == 1


def test_403_does_not_leak_response_or_credentials():
    session = FakeSession([response({"message": "sensitive-data"}, 403)])
    with pytest.raises(ApiError) as error:
        client(session).project("SRC")
    assert "sensitive-data" not in str(error.value)
    assert error.value.status == 403


def test_write_blocked_for_source_project():
    session = FakeSession()
    with pytest.raises(WriteBoundaryError):
        client(session).create_issue({"project": {"key": "SRC"}, "issuetype": {"id": "1"}})
    assert session.calls == []


def test_cannot_update_unowned_record():
    session = FakeSession()
    with pytest.raises(WriteBoundaryError):
        client(session).update_issue("TST-42", {"summary": "changed"})
    assert session.calls == []


def test_parent_must_belong_to_run():
    session = FakeSession()
    with pytest.raises(WriteBoundaryError):
        client(session).create_issue({"project": {"key": "TST"}, "parent": {"key": "TST-1"}})
    assert session.calls == []


def test_pagination_without_total_uses_is_last():
    session = FakeSession(
        [
            response({"values": [{"id": "1"}], "isLast": False}),
            response({"values": [{"id": "2"}], "isLast": True}),
        ]
    )
    assert len(client(session).issue_types("SRC")) == 2


def test_writes_are_not_retried_after_failure():
    session = FakeSession([response({}, 503)])
    api = client(session)
    with pytest.raises(ApiError):
        api.create_issue({"project": {"key": "TST"}, "issuetype": {"id": "1"}})
    assert len(session.calls) == 1
    assert session.calls[0][2]["allow_redirects"] is False


def test_parent_payload_cannot_mix_owned_key_and_foreign_id():
    session = FakeSession()
    api = client(session)
    api._owned.add("TST-1")
    with pytest.raises(WriteBoundaryError):
        api.create_issue(
            {"project": {"key": "TST"}, "parent": {"key": "TST-1", "id": "foreign-parent"}}
        )
    assert session.calls == []


def test_created_record_remains_reportable_if_verification_fails():
    session = FakeSession([response({"key": "TST-1"}), response({}, 503)])
    api = client(session)
    with pytest.raises(ApiError):
        api.create_issue({"project": {"key": "TST"}, "issuetype": {"id": "1"}})
    assert api.created_keys == ["TST-1"]
    with pytest.raises(WriteBoundaryError):
        api.assert_owned("TST-1")
