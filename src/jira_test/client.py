"""Bounded Jira REST v2 access. Only records created by this run may be modified."""

import re
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import requests

from .config import Config
from .errors import ApiError, WriteBoundaryError


def identifier(value: str) -> str:
    return quote(str(value), safe="")


class JiraClient:
    def __init__(self, config: Config, session: Any = None):
        self.config = config
        self.session = session if session is not None else requests.Session()
        self.session.auth = (config.username, config.password)
        self.session.headers.update({"Accept": "application/json"})
        self.run_id = uuid4().hex[:12]
        self._owned: set[str] = set()
        self._created: set[str] = set()

    def close(self) -> None:
        self.session.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            result = self.session.request(
                method,
                self.config.base_url + "/rest/api/2/" + path,
                timeout=self.config.timeout,
                verify=self.config.verify_tls,
                allow_redirects=False,
                **kwargs,
            )
        except requests.RequestException:
            raise ApiError(
                "Jira API connection failed; inspect connectivity and CA settings"
            ) from None
        if result.status_code >= 300:
            raise ApiError(f"Jira API returned HTTP {result.status_code}", result.status_code)
        if result.status_code == 204:
            return None
        try:
            return result.json()
        except ValueError:
            raise ApiError("Jira API returned a non-JSON response (possible login page)") from None

    def _pages(self, path: str, params: dict | None = None) -> list[dict]:
        collected: list[dict] = []
        start = 0
        for _ in range(1000):
            page = self._request(
                "GET", path, params={**(params or {}), "startAt": start, "maxResults": 100}
            )
            if isinstance(page, list):
                return page
            entries = page.get("values", page.get("issues", []))
            if not isinstance(entries, list):
                raise ApiError("Unexpected paginated API response")
            collected.extend(entries)
            start += len(entries)
            if (
                page.get("isLast")
                or not entries
                or ("total" in page and start >= page["total"])
                or ("total" not in page and "isLast" not in page)
            ):
                return collected
        raise ApiError("Jira API pagination exceeded the safety limit")

    def server_info(self) -> dict:
        return self._request("GET", "serverInfo")

    def current_user(self) -> dict:
        return self._request("GET", "myself")

    def fields(self) -> list[dict]:
        return self._request("GET", "field")

    def project(self, key: str) -> dict:
        return self._request("GET", f"project/{identifier(key)}")

    def permissions(self, project: str) -> dict:
        return self._request("GET", "mypermissions", params={"projectKey": project})

    def issue_types(self, project: str) -> list[dict]:
        return self._pages(f"issue/createmeta/{identifier(project)}/issuetypes")

    def create_fields(self, project: str, issue_type: str) -> list[dict]:
        return self._pages(
            f"issue/createmeta/{identifier(project)}/issuetypes/{identifier(issue_type)}"
        )

    def issue(self, key: str) -> dict:
        return self._request("GET", f"issue/{identifier(key)}")

    def edit_fields(self, key: str) -> dict:
        return self._request("GET", f"issue/{identifier(key)}/editmeta").get("fields", {})

    def transitions(self, key: str) -> list[dict]:
        return self._request(
            "GET", f"issue/{identifier(key)}/transitions", params={"expand": "transitions.fields"}
        ).get("transitions", [])

    def sample_issues(self, project: str, issue_type: str) -> list[dict]:
        # Inputs are identifiers, never arbitrary JQL fragments.
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", project) or not str(issue_type).isdigit():
            raise ApiError("Invalid project or issue type identifier")
        data = self._request(
            "GET",
            "search",
            params={
                "jql": f'project = "{project}" AND issuetype = {issue_type} ORDER BY key ASC',
                "fields": "issuetype,status,project,parent",
                "maxResults": self.config.sample_limit,
            },
        )
        return data.get("issues", [])

    def _assert_fields(self, fields: dict) -> None:
        project = fields.get("project", {})
        if project != {"key": self.config.test_project}:
            raise WriteBoundaryError("Writes require the configured test project key")
        parent = fields.get("parent")
        if parent is not None and (
            not isinstance(parent, dict)
            or set(parent) != {"key"}
            or parent["key"] not in self._owned
        ):
            raise WriteBoundaryError("Subtask parent must be an owned key without other attributes")

    def assert_owned(self, key: str) -> None:
        if key not in self._owned:
            raise WriteBoundaryError("Only issues created in this run may be changed")

    def create_issue(self, fields: dict) -> dict:
        self._assert_fields(fields)
        fields = dict(fields)
        fields["summary"] = self.summary(str(fields.get("summary", "fixture")))
        created = self._request("POST", "issue", json={"fields": fields})
        self._created.add(created["key"])
        self.register_created(created["key"])
        return created

    def summary(self, text: str) -> str:
        prefix = f"[jira-test:{self.run_id}] "
        return text if text.startswith(prefix) else prefix + text

    def register_created(self, key: str) -> None:
        record = self.issue(key)
        fields = record.get("fields", {})
        project = fields.get("project", {}).get("key")
        marker = f"[jira-test:{self.run_id}] "
        if project != self.config.test_project or not fields.get("summary", "").startswith(marker):
            raise WriteBoundaryError("Created issue does not match this run and test project")
        self._owned.add(key)
        self._created.add(key)

    def update_issue(self, key: str, fields: dict) -> None:
        self.assert_owned(key)
        if {"project", "parent", "issuetype"} & fields.keys():
            raise WriteBoundaryError("Moving or reparenting issues is unsupported")
        self._request("PUT", f"issue/{identifier(key)}", json={"fields": fields})

    def transition_issue(self, key: str, transition: str, fields: dict | None = None) -> None:
        self.assert_owned(key)
        if {"project", "parent", "issuetype"} & (fields or {}).keys():
            raise WriteBoundaryError("Moving or reparenting issues is unsupported")
        self._request(
            "POST",
            f"issue/{identifier(key)}/transitions",
            json={"transition": {"id": str(transition)}, "fields": fields or {}},
        )

    def run_issue_keys(self) -> list[str]:
        """Read-only check for accidental creations, including unregistered UI records."""
        return [
            item["key"]
            for item in self._pages(
                "search",
                {
                    "jql": f'project = "{self.config.test_project}" AND summary ~ "{self.run_id}"',
                    "fields": "key",
                },
            )
        ]

    @property
    def owned_keys(self) -> list[str]:
        return sorted(self._owned)

    @property
    def created_keys(self) -> list[str]:
        """Include API-created records even if the later ownership check failed."""
        return sorted(self._created)
