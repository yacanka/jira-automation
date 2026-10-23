"""Read-only project exploration. Missing contexts remain explicit coverage gaps."""

from collections.abc import Callable
from typing import Any

from playwright.sync_api import Error as PlaywrightError

from .catalog import Catalog, Observation
from .config import Config
from .errors import ApiError, JiraTestError


def normalize_fields(fields: list[dict] | dict) -> dict[str, dict]:
    if isinstance(fields, dict):
        return fields
    return {
        str(item.get("fieldId", item.get("id"))): item
        for item in fields
        if item.get("fieldId", item.get("id")) is not None
    }


class Explorer:
    def __init__(
        self,
        config: Config,
        client: Any,
        event_sink: Callable[[dict], None] | None = None,
        cancel_check: Callable[[], None] | None = None,
    ):
        self.config = config
        self.client = client
        self.event_sink = event_sink
        self.cancel_check = cancel_check

    def _checkpoint(self, phase: str, **data: Any) -> None:
        if self.cancel_check:
            self.cancel_check()
        if self.event_sink:
            self.event_sink({"phase": phase, **data})

    def discover(self, project: str, ui: Any = None) -> Catalog:
        self._checkpoint("discovery_start", project=project)
        catalog = Catalog(project=project, user="configured-user")
        catalog.issue_types = self.client.issue_types(project)
        try:
            global_fields = normalize_fields(self.client.fields())
        except (ApiError, AttributeError):
            global_fields = {}
            catalog.gaps.append({"reason": "Global field schema inventory unavailable"})
        if ui is None:
            catalog.gaps.append(
                {"reason": "UI discovery unavailable or disabled", "project": project}
            )
        for issue_type in catalog.issue_types:
            type_id = str(issue_type["id"])
            self._checkpoint("issue_type", issue_type=type_id)
            try:
                fields = normalize_fields(self.client.create_fields(project, type_id))
                self._add_fields(catalog, type_id, "create", fields)
                samples = self._samples(project, type_id)
                parent = None
                if issue_type.get("subtask"):
                    for sample in samples:
                        parent = sample.get("fields", {}).get("parent", {}).get("key")
                        if parent:
                            break
                if not issue_type.get("subtask") or parent:
                    self._observe(
                        catalog,
                        ui,
                        fields,
                        screen="create",
                        project=project,
                        issue_type=type_id,
                        parent=parent,
                    )
                else:
                    catalog.gaps.append(
                        {
                            "issue_type": type_id,
                            "screen": "create",
                            "reason": "Subtask creation needs an accessible parent",
                        }
                    )
                if not samples:
                    catalog.gaps.append(
                        {
                            "issue_type": type_id,
                            "reason": "No accessible issue; view/edit/transitions unknown",
                        }
                    )
                # Distinct statuses do not imply identical field contexts, so inspect each sample.
                for sample in samples:
                    self._checkpoint("sample", issue=sample["key"])
                    try:
                        self._issue_context(catalog, ui, project, type_id, sample, global_fields)
                    except (JiraTestError, PlaywrightError) as exc:
                        catalog.gaps.append(
                            {"issue": sample["key"], "reason": self._safe_reason(exc)}
                        )
                if len(samples) >= self.config.sample_limit:
                    catalog.gaps.append(
                        {
                            "issue_type": type_id,
                            "reason": "Sample limit reached; discovery is bounded",
                        }
                    )
            except (JiraTestError, PlaywrightError) as exc:
                catalog.gaps.append({"issue_type": type_id, "reason": self._safe_reason(exc)})
        catalog.gaps.append(
            {
                "reason": "Only observed statuses and configured samples are covered; "
                "unobserved workflow paths and dynamic validators remain unknown"
            }
        )
        return catalog

    def _samples(self, project: str, type_id: str) -> list[dict]:
        configured = self.config.samples.get(type_id)
        if configured is None:
            return self.client.sample_issues(project, type_id)
        samples = []
        for key in configured:
            issue = self.client.issue(key)
            fields = issue.get("fields", {})
            if (
                fields.get("project", {}).get("key") != project
                or str(fields.get("issuetype", {}).get("id")) != type_id
            ):
                raise ApiError("Configured sample does not match its project and issue type")
            samples.append(issue)
        return samples

    def _issue_context(
        self,
        catalog: Catalog,
        ui: Any,
        project: str,
        type_id: str,
        sample: dict,
        global_fields: dict,
    ) -> None:
        key = sample["key"]
        status = str(sample["fields"]["status"]["id"])
        record = self.client.issue(key)
        view_fields = {
            field: global_fields.get(field, {"name": field}) for field in record.get("fields", {})
        }
        self._add_fields(catalog, type_id, "view", view_fields, issue=key, status=status)
        edit_fields = self.client.edit_fields(key)
        self._add_fields(catalog, type_id, "edit", edit_fields, issue=key, status=status)
        self._observe(
            catalog,
            ui,
            view_fields,
            screen="view",
            project=project,
            issue_type=type_id,
            issue=key,
            status=status,
        )
        self._observe(
            catalog,
            ui,
            edit_fields,
            screen="edit",
            project=project,
            issue_type=type_id,
            issue=key,
            status=status,
        )
        for transition in self.client.transitions(key):
            self._checkpoint("transition", issue=key, transition=str(transition["id"]))
            tid = str(transition["id"])
            catalog.transitions.append(
                {
                    "issue_type": type_id,
                    "issue": key,
                    "status": status,
                    "id": tid,
                    "name": transition.get("name", ""),
                    "to": transition.get("to", {}),
                    "has_screen": transition.get("hasScreen", False),
                }
            )
            fields = transition.get("fields", {})
            self._add_fields(
                catalog, type_id, "transition", fields, issue=key, status=status, transition=tid
            )
            if transition.get("hasScreen"):
                self._observe(
                    catalog,
                    ui,
                    fields,
                    screen="transition",
                    project=project,
                    issue_type=type_id,
                    issue=key,
                    transition=tid,
                    status=status,
                )

    @staticmethod
    def _add_fields(
        catalog: Catalog, issue_type: str, screen: str, fields: dict[str, dict], **context: Any
    ) -> None:
        for identity, info in fields.items():
            schema = info.get("schema", {})
            options = info.get("allowedValues", [])
            if schema.get("type") == "user" or schema.get("items") == "user":
                options = []
            catalog.add(
                Observation(
                    issue_type=issue_type,
                    screen=screen,
                    field=identity,
                    source="api",
                    name=info.get("name", identity),
                    schema=schema,
                    required=info.get("required"),
                    options=options,
                    **context,
                )
            )

    def _observe(self, catalog: Catalog, ui: Any, metadata: dict, **context: Any) -> None:
        if ui is None:
            return
        status = context.pop("status", None)
        try:
            ui.open(**context)
            for observation in ui.observe(metadata):
                observation.status = status
                catalog.add(observation)
        except (JiraTestError, PlaywrightError) as exc:
            catalog.gaps.append({**context, "status": status, "reason": self._safe_reason(exc)})
        finally:
            ui.cancel()

    @staticmethod
    def _safe_reason(exc: Exception) -> str:
        if isinstance(exc, JiraTestError):
            return str(exc)
        return type(exc).__name__ + "; review locators and browser connectivity"
