"""Jira screens share field components and keep browser writes inside the test boundary."""

from typing import Any, Literal
from urllib.parse import urlencode

from playwright.sync_api import Locator

from .browser import Browser
from .catalog import Observation
from .client import JiraClient, identifier
from .components import FieldRegistry, css_attribute, field_identity, field_label
from .errors import ApiError, ContextUnavailable, UnsupportedFieldError, WriteBoundaryError
from .waiting import wait_until


class JiraUI:
    def __init__(
        self,
        browser: Browser,
        client: JiraClient,
        registry: FieldRegistry | None = None,
        readonly: bool = False,
    ):
        self.browser = browser
        self.client = client
        self.page = browser.start()
        self.locators = browser.locators
        self.registry = registry or FieldRegistry()
        self.readonly = readonly
        self.screen = "view"
        self.issue_key: str | None = None
        self.project_key = ""
        self.issue_type = ""
        self.transition_id: str | None = None
        self.metadata: dict[str, dict] = {}
        self.root: Locator | None = None
        self.parent: str | None = None
        self.immediate_outcome: dict | None = None

    def open(
        self,
        *,
        screen: str,
        project: str,
        issue_type: str,
        issue: str | None = None,
        transition: str | None = None,
        parent: str | None = None,
    ) -> None:
        self.screen, self.project_key, self.issue_type = screen, project, issue_type
        self.issue_key, self.transition_id, self.parent = issue, transition, parent
        self.immediate_outcome = None
        self.root = None
        if screen == "create":
            project_id = self.client.project(project)["id"]
            if parent:
                parent_id = self.client.issue(parent)["id"]
                route = "secure/CreateSubTaskIssue!default.jspa"
                params = {"parentIssueId": parent_id, "issuetype": issue_type}
            else:
                route = "secure/CreateIssue!default.jspa"
                params = {"pid": project_id, "issuetype": issue_type}
            self.page.goto(self.browser.config.base_url + "/" + route + "?" + urlencode(params))
            root_selector = self.locators.get("create.root", "#issue-create, #create-issue-dialog")
        elif screen == "edit":
            if issue is None:
                raise ContextUnavailable("Edit screen needs an issue fixture")
            issue_id = self.client.issue(issue)["id"]
            self.page.goto(
                self.browser.config.base_url
                + "/secure/EditIssue!default.jspa?"
                + urlencode({"id": issue_id})
            )
            root_selector = self.locators.get("edit.root", "#issue-edit, #edit-issue-dialog")
        elif screen in {"view", "transition"}:
            if issue is None:
                raise ContextUnavailable("View and transition screens need an issue fixture")
            self.page.goto(self.browser.config.base_url + "/browse/" + identifier(issue))
            root_selector = self.locators.get("view.root", "#issue-content, #issue-view")
            self.root = self._visible_locator(root_selector)
            if screen == "transition":
                self._open_transition(str(transition))
                return
        else:
            raise ContextUnavailable("Unsupported screen")
        self.browser.assert_origin()
        self.root = self._visible_locator(root_selector)

    def _open_transition(self, transition: str) -> None:
        choices = self.client.transitions(str(self.issue_key))
        matches = [t for t in choices if str(t["id"]) == transition]
        if not matches:
            raise ContextUnavailable("Transition is unavailable in this issue/user context")
        choice = matches[0]
        target = str(choice.get("to", {}).get("id", ""))
        before = None
        if not choice.get("hasScreen"):
            if self.readonly:
                raise ContextUnavailable("Screenless transitions cannot be opened read-only")
            self._assert_write()
            if not target:
                raise ContextUnavailable("Cannot confirm target status for this transition")
            before = self.client.issue(str(self.issue_key))["fields"]
        self.metadata = choice.get("fields", {})
        selector = self.locators.get(
            f"transition.{transition}.button",
            f'[id="action_id_{css_attribute(transition)}"], '
            f'[data-transition-id="{css_attribute(transition)}"]',
        )
        buttons = self.page.locator("css=" + selector).all()
        visible = [button for button in buttons if button.is_visible()]
        if not visible:
            more = self.locators.get("transition.more", "#opsbar-transitions_more")
            self._visible_locator(more).click()
        self.browser.assert_origin()
        self._visible_locator(selector).click()
        if not choice.get("hasScreen"):
            self.immediate_outcome = self._screenless_outcome(before or {}, target)
            return
        selector = self.locators.get(
            "transition.root",
            "#workflow-transition, #issue-workflow-transition, #transition-dialog, "
            'form[action*="CommentAssignIssue"], form[action*="WorkflowUIDispatcher"]',
        )
        self.root = self._visible_locator(selector)

    def _assert_write(self) -> None:
        self.browser.assert_origin()
        if self.readonly or self.project_key != self.browser.config.test_project:
            raise WriteBoundaryError("UI writes are restricted to the test project")
        if self.issue_key:
            self.client.assert_owned(self.issue_key)
            if self.client.issue(self.issue_key)["fields"]["project"]["key"] != self.project_key:
                raise WriteBoundaryError("Issue project changed since fixture creation")
        if self.parent:
            self.client.assert_owned(self.parent)

    def element(self, field: str) -> Locator:
        scope = self.root if self.root is not None else self.page
        selector = self.locators.field(self.screen, field)
        return scope.locator("css=" + selector).first

    def _visible_locator(self, selector: str) -> Locator:
        # Some Jira versions retain hidden copies of dialogs and toolbar buttons.
        locator = self.page.locator("css=" + selector).filter(visible=True).first
        locator.wait_for(state="visible")
        return locator

    def visible(self, field: str) -> bool:
        return self.element(field).is_visible()

    def editable(self, field: str) -> bool:
        if self.screen == "view" or not self.visible(field):
            return False
        element = self.element(field)
        return element.is_enabled() and element.get_attribute("readonly") is None

    def required(self, field: str) -> bool | None:
        if not self.visible(field):
            return None
        element = self.element(field)
        if (
            element.get_attribute("required") is not None
            or element.get_attribute("aria-required") == "true"
        ):
            return True
        ancestors = element.locator(
            'xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), '
            '" field-group ")][1]'
        )
        if ancestors.count():
            return bool(
                ancestors.locator(".aui-icon-required, .icon-required, label .required").count()
            )
        return None

    def fill(self, field: str, value: Any) -> None:
        self._assert_write()
        if field in {"project", "issuetype", "parent", "parentIssueId", "parentIssueKey"}:
            raise WriteBoundaryError("Project, issue type and parent are fixture-controlled")
        if not self.editable(field):
            raise ContextUnavailable(f"Field {field} is not editable on {self.screen}")
        schema = self.metadata.get(field, {}).get("schema")
        if not schema:
            raise UnsupportedFieldError(f"No schema metadata for field {field}")
        component = self.registry.resolve(schema)(self.element(field), schema)
        component.fill(value)

    def clear(self, field: str) -> None:
        self._assert_write()
        schema = self.metadata.get(field, {}).get("schema")
        if not schema:
            raise UnsupportedFieldError(f"No schema metadata for field {field}")
        if field in {"project", "issuetype", "parent", "parentIssueId", "parentIssueKey"}:
            raise WriteBoundaryError("Identity fields cannot be cleared")
        component = self.registry.resolve(schema)(self.element(field), schema)
        component.clear()

    def _validate_create_identity(self) -> None:
        project_id = str(self.client.project(self.project_key)["id"])
        scope = self.root if self.root is not None else self.page
        project_selector = self.locators.get("create.project_identity", '[name="pid"], #project')
        project_controls = scope.locator("css=" + project_selector).all()
        if not project_controls or any(el.input_value() != project_id for el in project_controls):
            raise WriteBoundaryError("Cannot verify the create form's selected test project")
        types = scope.locator(
            "css=" + self.locators.get("create.type_identity", '#issuetype, [name="issuetype"]')
        ).all()
        if not types or any(el.input_value() != self.issue_type for el in types):
            raise WriteBoundaryError("Cannot verify the create form's issue type")
        if self.parent:
            parent_id = str(self.client.issue(self.parent)["id"])
            controls = scope.locator(
                "css=" + self.locators.get("create.parent_identity", '[name="parentIssueId"]')
            ).all()
            if not controls or any(el.input_value() != parent_id for el in controls):
                raise WriteBoundaryError("Cannot verify the subtask form's parent")

    def errors(self) -> dict[str, str]:
        scope = self.root if self.root is not None else self.page
        errors: dict[str, str] = {}
        for field in self.metadata:
            selector = self.locators.get(
                f"{self.screen}.{field}.error",
                f'[id="{css_attribute(field)}-error"], [id="{css_attribute(field)}-errors"]',
            )
            elements = scope.locator("css=" + selector).all()
            group = self.element(field).locator(
                'xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), '
                '" field-group ")][1]'
            )
            elements += group.locator(".error, .error-message").all()
            messages = [
                el.inner_text().strip()
                for el in elements
                if el.is_visible() and el.inner_text().strip()
            ]
            if messages:
                errors[field] = " | ".join(messages)
        global_errors = scope.locator(
            "css=" + self.locators.get("form.errors", ".aui-message-error, .error-message")
        ).all()
        messages = [
            el.inner_text().strip()
            for el in global_errors
            if el.is_visible() and el.inner_text().strip()
        ]
        if messages:
            errors["_form"] = " | ".join(messages)
        return errors

    def submit(self) -> dict:
        self._assert_write()
        if self.screen == "view":
            raise ContextUnavailable("View screens cannot be submitted")
        if self.immediate_outcome:
            return self.immediate_outcome
        if self.screen == "create":
            self._validate_create_identity()
        before = self.client.issue(self.issue_key)["fields"] if self.issue_key else None
        selectors = {
            "create": "#issue-create-submit, #create-issue-submit",
            "edit": "#issue-edit-submit, #edit-issue-submit",
            "transition": "#issue-workflow-transition-submit, #workflow-transition-submit",
        }
        selector = self.locators.get(f"{self.screen}.submit", selectors[self.screen])
        self._visible_locator(selector).click()
        return self._form_outcome(before)

    def _form_outcome(self, before: dict | None) -> dict:
        def outcome() -> dict | Literal[False]:
            self.browser.assert_origin()
            form_visible = self.root is not None and self.root.is_visible()
            if not form_visible:
                self.root = None
            errors = self.errors()
            if errors:
                return {"accepted": False, "errors": errors, "key": self.issue_key}
            if form_visible:
                return False
            keys = self.page.locator("css=" + self.locators.get("issue.key", "#key-val")).all()
            visible_keys = [key for key in keys if key.is_visible()]
            if not visible_keys:
                return False
            key = visible_keys[0].inner_text().strip()
            if self.screen != "create" and key != self.issue_key:
                return False
            if self.screen == "create":
                self.client.record_created(key)
            try:
                fields = self.client.issue(key)["fields"]
            except ApiError as exc:
                if exc.status == 404:
                    return False
                raise
            if self.screen == "create":
                if fields.get("project", {}).get(
                    "key"
                ) != self.browser.config.test_project or not fields.get("summary", "").startswith(
                    self.client.summary("")
                ):
                    raise WriteBoundaryError("Created record does not match the test run")
            elif before is not None and (
                not fields.get("updated") or fields.get("updated") == before.get("updated")
            ):
                return False
            return {"accepted": True, "errors": {}, "key": key}

        # Form disappearance is not success: require issue-view and persisted-write evidence.
        return wait_until(outcome, self.browser.config.timeout)

    def _screenless_outcome(self, before: dict, target: str) -> dict:
        key = self.issue_key
        if key is None:
            raise ContextUnavailable("A transition result needs an issue fixture")

        def outcome() -> dict | Literal[False]:
            self.browser.assert_origin()
            if self.root is not None and not self.root.is_visible():
                self.root = None
            errors = self.errors()
            if errors:
                return {"accepted": False, "errors": errors, "key": self.issue_key}
            fields = self.client.issue(key)["fields"]
            status = str(fields.get("status", {}).get("id", ""))
            previous = str(before.get("status", {}).get("id", ""))
            changed = status != previous or (
                fields.get("updated") and fields.get("updated") != before.get("updated")
            )
            if status == target and changed:
                return {"accepted": True, "errors": {}, "key": self.issue_key}
            return False

        return wait_until(outcome, self.browser.config.timeout)

    def cancel(self) -> None:
        # Navigating away never submits the form and clears modal state.
        self.page.goto(self.browser.config.base_url + "/secure/Dashboard.jspa")
        self.root = None

    def observe(self, metadata: dict[str, dict]) -> list[Observation]:
        self.metadata = metadata
        discovered = dict(metadata)
        if self.root is not None:
            for element in self.root.locator("input, select, textarea").all():
                identity = field_identity(element)
                if identity and identity not in discovered:
                    discovered[identity] = {"name": field_label(element, identity)}
        observations = []
        for identity, info in discovered.items():
            visible = self.visible(identity)
            observations.append(
                Observation(
                    issue_type=self.issue_type,
                    screen=self.screen,
                    field=identity,
                    source="ui",
                    name=info.get("name", identity),
                    schema=info.get("schema", {}),
                    required=self.required(identity) if visible else None,
                    visible=visible,
                    editable=self.editable(identity),
                    locator=self.locators.field(self.screen, identity),
                    issue=self.issue_key,
                    transition=self.transition_id,
                )
            )
        return observations
