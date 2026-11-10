"""Typed browser actions and action results (#36661).

Mirrors the ``ScrapeAction`` discriminated union and ``ActionResult`` model in
``services/api/app/schemas/scrape.py``. Each action class serialises to the exact
JSON the API accepts via :meth:`to_dict`; the :class:`Actions` builders are the
short way to construct them::

    from alterlab import Actions

    actions = [
        Actions.click("button.load-more"),
        Actions.wait(milliseconds=1000),
        Actions.screenshot(),
    ]

Selectors are CSS, or XPath when prefixed with ``//`` or ``xpath=``.
Constructors enforce the API's field constraints and raise ``ValueError`` so
mistakes surface before the request instead of as a 422.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Union
from uuid import UUID

__all__ = [
    "Actions",
    "ActionResult",
    "ScrapeAction",
    "WaitAction",
    "WaitForAction",
    "ClickAction",
    "FillAction",
    "PressAction",
    "ScrollAction",
    "InfiniteScrollAction",
    "ScreenshotAction",
    "EvaluateAction",
    "DismissConsentAction",
    "SelectAction",
    "HoverAction",
    "ScrollIntoViewAction",
    "ClickTextAction",
    "ExtractAction",
    "CheckAction",
    "UncheckAction",
    "WaitEventAction",
    "SnapshotAction",
    "InspectAction",
    "DownloadAction",
    "ArtifactMetadata",
    "ArtifactDelivery",
    "ActionObservation",
    "serialize_actions",
    "parse_action_results",
]

# Field limits from services/api/app/schemas/scrape.py (and
# shared.validation.js_scripts.MAX_SCRIPT_LENGTH for evaluate scripts).
_MAX_SELECTOR_LENGTH = 500
_MAX_FILL_VALUE_LENGTH = 5000
_MAX_KEY_LENGTH = 50
_MAX_SCRIPT_LENGTH = 5120
_MAX_ATTRIBUTE_LENGTH = 100
_WAIT_FOR_STATES = ("visible", "hidden", "attached", "detached")
_LOAD_EVENTS = ("load", "domcontentloaded", "networkidle")
_MAX_FRAME_DEPTH = 3
_SNAPSHOT_FORMATS = ("html", "markdown")
_MAX_URL_LENGTH = 2048
_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
_MAX_DOWNLOAD_ACTIONS = 5
_MAX_INSPECT_ELEMENTS = 500
_MAX_DOWNLOAD_FILES = 10
_MAX_DOWNLOAD_QUIET_MS = 10000
_MAX_KEY_TEMPLATE_LENGTH = 200
_KEY_TEMPLATE_SEGMENT = re.compile(
    r"^(?:[A-Za-z0-9._-]|\{(?:artifact_id|job_id|filename)\})+$"
)


def _check_range(action: str, field: str, value: int, low: int, high: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not low <= value <= high
    ):
        raise ValueError(
            f"{action} action '{field}' must be an integer {low}-{high}, got {value!r}"
        )


def _check_text(action: str, field: str, value: str, max_length: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{action} action '{field}' must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(
            f"{action} action '{field}' must be at most {max_length} characters, "
            f"got {len(value)}"
        )


def _check_choice(action: str, field: str, value: str, choices: Sequence[str]) -> None:
    if value not in choices:
        raise ValueError(
            f"{action} action '{field}' must be one of {list(choices)}, got {value!r}"
        )


def _check_frame(action: str, frame: Optional[Union[str, Sequence[str]]]) -> None:
    """Validate ``frame`` (#36692): one iframe selector, or 1-3 for nested frames."""
    if frame is None:
        return
    selectors = [frame] if isinstance(frame, str) else frame
    if (
        not isinstance(selectors, Sequence)
        or not 1 <= len(selectors) <= _MAX_FRAME_DEPTH
    ):
        raise ValueError(
            f"{action} action 'frame' must be a selector or a list of 1-"
            f"{_MAX_FRAME_DEPTH} selectors"
        )
    for selector in selectors:
        _check_text(action, "frame", selector, _MAX_SELECTOR_LENGTH)


def _with_frame(
    data: Dict[str, Any], frame: Optional[Union[str, Sequence[str]]]
) -> Dict[str, Any]:
    """Add ``frame`` to serialised action JSON only when it is set."""
    if frame is not None:
        data["frame"] = frame if isinstance(frame, str) else list(frame)
    return data


@dataclass(frozen=True)
class WaitAction:
    """Wait for a fixed delay, or until ``selector`` is visible.

    With both set, ``milliseconds`` is the selector wait timeout.
    """

    milliseconds: Optional[int] = None
    selector: Optional[str] = None
    frame: Optional[Union[str, Sequence[str]]] = None
    type: Literal["wait"] = "wait"

    def __post_init__(self) -> None:
        if self.milliseconds is None and self.selector is None:
            raise ValueError("wait action requires either 'milliseconds' or 'selector'")
        if self.milliseconds is not None:
            _check_range("wait", "milliseconds", self.milliseconds, 100, 30000)
        if self.selector is not None:
            _check_text("wait", "selector", self.selector, _MAX_SELECTOR_LENGTH)
        _check_frame("wait", self.frame)
        if self.frame is not None and self.selector is None:
            raise ValueError("wait action 'frame' requires 'selector'")

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": self.type}
        if self.milliseconds is not None:
            data["milliseconds"] = self.milliseconds
        if self.selector is not None:
            data["selector"] = self.selector
        return _with_frame(data, self.frame)


@dataclass(frozen=True)
class WaitForAction:
    """Wait for an element to reach ``state`` (fails on timeout).

    ``state`` defaults to the API's ``visible``; ``hidden`` / ``detached`` wait
    for the element to disappear (e.g. a loading spinner).
    """

    selector: str
    timeout: int = 10000
    state: Optional[Literal["visible", "hidden", "attached", "detached"]] = None
    frame: Optional[Union[str, Sequence[str]]] = None
    type: Literal["wait_for"] = "wait_for"

    def __post_init__(self) -> None:
        _check_text("wait_for", "selector", self.selector, _MAX_SELECTOR_LENGTH)
        _check_range("wait_for", "timeout", self.timeout, 1000, 30000)
        if self.state is not None:
            _check_choice("wait_for", "state", self.state, _WAIT_FOR_STATES)
        _check_frame("wait_for", self.frame)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "type": self.type,
            "selector": self.selector,
            "timeout": self.timeout,
        }
        if self.state is not None:
            data["state"] = self.state
        return _with_frame(data, self.frame)


@dataclass(frozen=True)
class ClickAction:
    """Click the element matching a CSS selector."""

    selector: str
    frame: Optional[Union[str, Sequence[str]]] = None
    type: Literal["click"] = "click"

    def __post_init__(self) -> None:
        _check_text("click", "selector", self.selector, _MAX_SELECTOR_LENGTH)
        _check_frame("click", self.frame)

    def to_dict(self) -> Dict[str, Any]:
        return _with_frame({"type": self.type, "selector": self.selector}, self.frame)


@dataclass(frozen=True)
class FillAction:
    """Fill an input field with a value."""

    selector: str
    value: str
    frame: Optional[Union[str, Sequence[str]]] = None
    type: Literal["fill"] = "fill"

    def __post_init__(self) -> None:
        _check_text("fill", "selector", self.selector, _MAX_SELECTOR_LENGTH)
        if not isinstance(self.value, str) or len(self.value) > _MAX_FILL_VALUE_LENGTH:
            raise ValueError(
                f"fill action 'value' must be a string of at most {_MAX_FILL_VALUE_LENGTH} "
                "characters"
            )
        _check_frame("fill", self.frame)

    def to_dict(self) -> Dict[str, Any]:
        return _with_frame(
            {"type": self.type, "selector": self.selector, "value": self.value},
            self.frame,
        )


@dataclass(frozen=True)
class PressAction:
    """Press a keyboard key (e.g. ``"Enter"``, ``"Tab"``, ``"Escape"``).

    With ``selector`` the key is pressed on that element, otherwise on the page.
    """

    key: str
    selector: Optional[str] = None
    frame: Optional[Union[str, Sequence[str]]] = None
    type: Literal["press"] = "press"

    def __post_init__(self) -> None:
        _check_text("press", "key", self.key, _MAX_KEY_LENGTH)
        if self.selector is not None:
            _check_text("press", "selector", self.selector, _MAX_SELECTOR_LENGTH)
        _check_frame("press", self.frame)
        if self.frame is not None and self.selector is None:
            raise ValueError("press action 'frame' requires 'selector'")

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": self.type, "key": self.key}
        if self.selector is not None:
            data["selector"] = self.selector
        return _with_frame(data, self.frame)


@dataclass(frozen=True)
class ScrollAction:
    """Scroll the page by ``amount`` viewport heights.

    When ``target_selector`` is set, that element is scrolled into view instead
    (e.g. a row of a virtualised list) and ``direction``/``amount`` are ignored
    server-side.
    """

    direction: Literal["down", "up"] = "down"
    amount: int = 1
    target_selector: Optional[str] = None
    type: Literal["scroll"] = "scroll"

    def __post_init__(self) -> None:
        _check_choice("scroll", "direction", self.direction, ("down", "up"))
        _check_range("scroll", "amount", self.amount, 1, 20)
        if self.target_selector is not None:
            _check_text(
                "scroll",
                "target_selector",
                self.target_selector,
                _MAX_SELECTOR_LENGTH,
            )

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "type": self.type,
            "direction": self.direction,
            "amount": self.amount,
        }
        if self.target_selector is not None:
            data["target_selector"] = self.target_selector
        return data


@dataclass(frozen=True)
class InfiniteScrollAction:
    """Scroll repeatedly until end of content or ``max_scrolls`` is reached."""

    max_scrolls: int = 10
    delay: int = 1000
    end_selector: Optional[str] = None
    type: Literal["infinite_scroll"] = "infinite_scroll"

    def __post_init__(self) -> None:
        _check_range("infinite_scroll", "max_scrolls", self.max_scrolls, 1, 50)
        _check_range("infinite_scroll", "delay", self.delay, 200, 5000)
        if self.end_selector is not None:
            _check_text(
                "infinite_scroll",
                "end_selector",
                self.end_selector,
                _MAX_SELECTOR_LENGTH,
            )

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "type": self.type,
            "max_scrolls": self.max_scrolls,
            "delay": self.delay,
        }
        if self.end_selector is not None:
            data["end_selector"] = self.end_selector
        return data


@dataclass(frozen=True)
class ScreenshotAction:
    """Capture a screenshot at this point in the sequence.

    The image is returned as ``screenshot_url`` on the matching action result.
    """

    full_page: bool = True
    type: Literal["screenshot"] = "screenshot"

    def __post_init__(self) -> None:
        if not isinstance(self.full_page, bool):
            raise ValueError("screenshot action 'full_page' must be a bool")

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "full_page": self.full_page}


@dataclass(frozen=True)
class EvaluateAction:
    """Run JavaScript in the page context; its return value is the action result.

    Network APIs (fetch, XMLHttpRequest, WebSocket) and dynamic code execution
    (eval, Function) are rejected by the API.
    """

    script: str
    type: Literal["evaluate"] = "evaluate"

    def __post_init__(self) -> None:
        _check_text("evaluate", "script", self.script, _MAX_SCRIPT_LENGTH)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "script": self.script}


@dataclass(frozen=True)
class DismissConsentAction:
    """Remove the cookie consent overlay from the live page.

    ``hide`` leaves consent state unchanged; ``accept`` / ``reject`` click the
    CMP's own button first.
    """

    mode: Literal["hide", "accept", "reject"] = "hide"
    type: Literal["dismiss_consent"] = "dismiss_consent"

    def __post_init__(self) -> None:
        _check_choice(
            "dismiss_consent", "mode", self.mode, ("hide", "accept", "reject")
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "mode": self.mode}


@dataclass(frozen=True)
class SelectAction:
    """Choose a ``<select>`` option by ``value`` or ``label`` (exactly one)."""

    selector: str
    value: Optional[str] = None
    label: Optional[str] = None
    frame: Optional[Union[str, Sequence[str]]] = None
    type: Literal["select"] = "select"

    def __post_init__(self) -> None:
        _check_text("select", "selector", self.selector, _MAX_SELECTOR_LENGTH)
        if (self.value is None) == (self.label is None):
            raise ValueError("select action requires exactly one of 'value' or 'label'")
        option = self.value if self.value is not None else self.label
        if not isinstance(option, str) or len(option) > _MAX_SELECTOR_LENGTH:
            raise ValueError(
                f"select action option must be a string of at most "
                f"{_MAX_SELECTOR_LENGTH} characters"
            )
        _check_frame("select", self.frame)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": self.type, "selector": self.selector}
        if self.value is not None:
            data["value"] = self.value
        else:
            data["label"] = self.label
        return _with_frame(data, self.frame)


@dataclass(frozen=True)
class HoverAction:
    """Move the pointer over an element, e.g. to open a hover menu."""

    selector: str
    frame: Optional[Union[str, Sequence[str]]] = None
    type: Literal["hover"] = "hover"

    def __post_init__(self) -> None:
        _check_text("hover", "selector", self.selector, _MAX_SELECTOR_LENGTH)
        _check_frame("hover", self.frame)

    def to_dict(self) -> Dict[str, Any]:
        return _with_frame({"type": self.type, "selector": self.selector}, self.frame)


@dataclass(frozen=True)
class ScrollIntoViewAction:
    """Scroll an element into view, e.g. a row of a virtualized list."""

    selector: str
    block: Literal["start", "center", "end", "nearest"] = "center"
    frame: Optional[Union[str, Sequence[str]]] = None
    type: Literal["scroll_into_view"] = "scroll_into_view"

    def __post_init__(self) -> None:
        _check_text("scroll_into_view", "selector", self.selector, _MAX_SELECTOR_LENGTH)
        if self.block not in ("start", "center", "end", "nearest"):
            raise ValueError(
                "scroll_into_view 'block' must be start, center, end or nearest"
            )
        _check_frame("scroll_into_view", self.frame)

    def to_dict(self) -> Dict[str, Any]:
        return _with_frame(
            {"type": self.type, "selector": self.selector, "block": self.block},
            self.frame,
        )


@dataclass(frozen=True)
class ClickTextAction:
    """Click the first element whose visible text matches ``text``.

    ``exact`` matches the whole text case-sensitively; otherwise a
    case-insensitive substring match is used.
    """

    text: str
    exact: bool = False
    frame: Optional[Union[str, Sequence[str]]] = None
    type: Literal["click_text"] = "click_text"

    def __post_init__(self) -> None:
        _check_text("click_text", "text", self.text, _MAX_SELECTOR_LENGTH)
        if not isinstance(self.exact, bool):
            raise ValueError("click_text action 'exact' must be a bool")
        _check_frame("click_text", self.frame)

    def to_dict(self) -> Dict[str, Any]:
        return _with_frame(
            {"type": self.type, "text": self.text, "exact": self.exact}, self.frame
        )


@dataclass(frozen=True)
class ExtractAction:
    """Read the first matching element's text, or ``attribute``, into the result.

    The value lands in ``action_results[i]["result"]`` (max 5000 chars; ``None``
    when the attribute is absent).
    """

    selector: str
    attribute: Optional[str] = None
    frame: Optional[Union[str, Sequence[str]]] = None
    type: Literal["extract"] = "extract"

    def __post_init__(self) -> None:
        _check_text("extract", "selector", self.selector, _MAX_SELECTOR_LENGTH)
        if self.attribute is not None:
            _check_text("extract", "attribute", self.attribute, _MAX_ATTRIBUTE_LENGTH)
        _check_frame("extract", self.frame)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": self.type, "selector": self.selector}
        if self.attribute is not None:
            data["attribute"] = self.attribute
        return _with_frame(data, self.frame)


@dataclass(frozen=True)
class CheckAction:
    """Check a checkbox or radio button."""

    selector: str
    frame: Optional[Union[str, Sequence[str]]] = None
    type: Literal["check"] = "check"

    def __post_init__(self) -> None:
        _check_text("check", "selector", self.selector, _MAX_SELECTOR_LENGTH)
        _check_frame("check", self.frame)

    def to_dict(self) -> Dict[str, Any]:
        return _with_frame({"type": self.type, "selector": self.selector}, self.frame)


@dataclass(frozen=True)
class UncheckAction:
    """Uncheck a checkbox."""

    selector: str
    frame: Optional[Union[str, Sequence[str]]] = None
    type: Literal["uncheck"] = "uncheck"

    def __post_init__(self) -> None:
        _check_text("uncheck", "selector", self.selector, _MAX_SELECTOR_LENGTH)
        _check_frame("uncheck", self.frame)

    def to_dict(self) -> Dict[str, Any]:
        return _with_frame({"type": self.type, "selector": self.selector}, self.frame)


@dataclass(frozen=True)
class WaitEventAction:
    """Wait for a page load event (``load``, ``domcontentloaded``, ``networkidle``)."""

    event: Literal["load", "domcontentloaded", "networkidle"] = "load"
    timeout: int = 10000
    type: Literal["wait_event"] = "wait_event"

    def __post_init__(self) -> None:
        _check_choice("wait_event", "event", self.event, _LOAD_EVENTS)
        _check_range("wait_event", "timeout", self.timeout, 1000, 30000)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "event": self.event, "timeout": self.timeout}


@dataclass(frozen=True)
class SnapshotAction:
    """Capture the page HTML or markdown at this step (#36692).

    Delivered as ``snapshot_url`` on the matching action result.
    """

    format: Literal["html", "markdown"] = "html"
    type: Literal["snapshot"] = "snapshot"

    def __post_init__(self) -> None:
        _check_choice("snapshot", "format", self.format, _SNAPSHOT_FORMATS)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "format": self.format}


@dataclass(frozen=True)
class InspectAction:
    """Return a capped map of the visible page elements (#39585).

    Delivered as ``element_map`` on the matching action result: viewport/page
    size plus elements with a document-space bounding box, tag, text and
    candidate CSS and XPath selectors.
    """

    max_elements: int = 200
    type: Literal["inspect"] = "inspect"

    def __post_init__(self) -> None:
        _check_range(
            "inspect", "max_elements", self.max_elements, 1, _MAX_INSPECT_ELEMENTS
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "max_elements": self.max_elements}


@dataclass(frozen=True)
class DownloadAction:
    """Capture one file download started by the page (#30596).

    Exactly one trigger: ``selector`` clicks an element that starts the
    download, ``url`` opens a download link in a fresh tab of the same session.
    Delivered as ``artifact`` metadata on the matching action result.

    Multi-file (#38735): ``max_files`` > 1 collects up to that many files (the
    result carries ``artifacts``); ``max_total_bytes`` caps their aggregate
    size, ``quiet_ms`` ends collection after that idle time and
    ``bundle="zip"`` also stores one ZIP of all files (``bundle`` on the result).
    """

    selector: Optional[str] = None
    url: Optional[str] = None
    timeout_ms: int = 15000
    max_bytes: Optional[int] = None
    frame: Optional[Union[str, Sequence[str]]] = None
    integration_id: Optional[str] = None
    key_template: Optional[str] = None
    max_files: int = 1
    max_total_bytes: Optional[int] = None
    quiet_ms: int = 1000
    bundle: Literal["none", "zip"] = "none"
    type: Literal["download"] = "download"

    def __post_init__(self) -> None:
        if (self.selector is None) == (self.url is None):
            raise ValueError(
                "download action requires exactly one of 'selector' or 'url'"
            )
        if self.selector is not None:
            _check_text("download", "selector", self.selector, _MAX_SELECTOR_LENGTH)
        if self.url is not None:
            _check_text("download", "url", self.url, _MAX_URL_LENGTH)
            parsed = urlparse(self.url.strip())
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError(
                    "download action 'url' must be an absolute http(s) URL"
                )
            if self.frame is not None:
                raise ValueError(
                    "download action 'frame' only applies to selector downloads"
                )
        _check_range("download", "timeout_ms", self.timeout_ms, 1000, 30000)
        if self.max_bytes is not None:
            _check_range(
                "download", "max_bytes", self.max_bytes, 1, _MAX_DOWNLOAD_BYTES
            )
        _check_frame("download", self.frame)
        _check_range("download", "max_files", self.max_files, 1, _MAX_DOWNLOAD_FILES)
        _check_range("download", "quiet_ms", self.quiet_ms, 100, _MAX_DOWNLOAD_QUIET_MS)
        if self.max_total_bytes is not None:
            _check_range(
                "download",
                "max_total_bytes",
                self.max_total_bytes,
                1,
                _MAX_DOWNLOAD_BYTES,
            )
        if self.bundle not in ("none", "zip"):
            raise ValueError("download action 'bundle' must be 'none' or 'zip'")
        if self.max_files == 1 and (
            self.bundle != "none" or self.max_total_bytes is not None
        ):
            raise ValueError(
                "download action 'bundle' and 'max_total_bytes' require max_files > 1"
            )
        if self.integration_id is not None:
            try:
                UUID(str(self.integration_id))
            except ValueError:
                raise ValueError(
                    "download action 'integration_id' must be a UUID"
                ) from None
        if self.key_template is not None:
            self._check_key_template(self.key_template)
            if self.integration_id is None:
                raise ValueError(
                    "download action 'key_template' requires 'integration_id'"
                )

    @staticmethod
    def _check_key_template(value: str) -> None:
        if len(value) > _MAX_KEY_TEMPLATE_LENGTH:
            raise ValueError(
                f"download action 'key_template' must be at most "
                f"{_MAX_KEY_TEMPLATE_LENGTH} characters"
            )
        segments = value.split("/")
        if not all(
            _KEY_TEMPLATE_SEGMENT.match(seg) and seg not in (".", "..")
            for seg in segments
        ) or any(".." in seg for seg in segments):
            raise ValueError(
                "download action 'key_template' must be '/'-separated segments of "
                "[A-Za-z0-9._-] and {artifact_id}/{job_id}/{filename} tokens"
            )

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": self.type, "timeout_ms": self.timeout_ms}
        if self.selector is not None:
            data["selector"] = self.selector
        if self.url is not None:
            data["url"] = self.url.strip()
        if self.max_bytes is not None:
            data["max_bytes"] = self.max_bytes
        if self.integration_id is not None:
            data["integration_id"] = str(self.integration_id)
        if self.key_template is not None:
            data["key_template"] = self.key_template
        if self.max_files != 1:
            data["max_files"] = self.max_files
        if self.max_total_bytes is not None:
            data["max_total_bytes"] = self.max_total_bytes
        if self.quiet_ms != 1000:
            data["quiet_ms"] = self.quiet_ms
        if self.bundle != "none":
            data["bundle"] = self.bundle
        return _with_frame(data, self.frame)


ScrapeAction = Union[
    WaitAction,
    WaitForAction,
    ClickAction,
    FillAction,
    PressAction,
    ScrollAction,
    InfiniteScrollAction,
    ScreenshotAction,
    EvaluateAction,
    DismissConsentAction,
    SelectAction,
    HoverAction,
    ScrollIntoViewAction,
    ClickTextAction,
    ExtractAction,
    CheckAction,
    UncheckAction,
    WaitEventAction,
    SnapshotAction,
    InspectAction,
    DownloadAction,
]
"""Any typed browser action, discriminated by its ``type`` field."""

_ACTION_CLASSES = ScrapeAction.__args__  # type: ignore[attr-defined]


class Actions:
    """Builders for typed browser actions."""

    @staticmethod
    def wait(
        milliseconds: Optional[int] = None,
        selector: Optional[str] = None,
        frame: Optional[Union[str, Sequence[str]]] = None,
    ) -> WaitAction:
        return WaitAction(milliseconds=milliseconds, selector=selector, frame=frame)

    @staticmethod
    def wait_for(
        selector: str,
        timeout: int = 10000,
        state: Optional[Literal["visible", "hidden", "attached", "detached"]] = None,
        frame: Optional[Union[str, Sequence[str]]] = None,
    ) -> WaitForAction:
        return WaitForAction(
            selector=selector, timeout=timeout, state=state, frame=frame
        )

    @staticmethod
    def click(
        selector: str, frame: Optional[Union[str, Sequence[str]]] = None
    ) -> ClickAction:
        return ClickAction(selector=selector, frame=frame)

    @staticmethod
    def fill(
        selector: str, value: str, frame: Optional[Union[str, Sequence[str]]] = None
    ) -> FillAction:
        return FillAction(selector=selector, value=value, frame=frame)

    @staticmethod
    def press(
        key: str,
        selector: Optional[str] = None,
        frame: Optional[Union[str, Sequence[str]]] = None,
    ) -> PressAction:
        return PressAction(key=key, selector=selector, frame=frame)

    @staticmethod
    def scroll(
        direction: Literal["down", "up"] = "down",
        amount: int = 1,
        target_selector: Optional[str] = None,
    ) -> ScrollAction:
        return ScrollAction(
            direction=direction, amount=amount, target_selector=target_selector
        )

    @staticmethod
    def infinite_scroll(
        max_scrolls: int = 10, delay: int = 1000, end_selector: Optional[str] = None
    ) -> InfiniteScrollAction:
        return InfiniteScrollAction(
            max_scrolls=max_scrolls, delay=delay, end_selector=end_selector
        )

    @staticmethod
    def screenshot(full_page: bool = True) -> ScreenshotAction:
        return ScreenshotAction(full_page=full_page)

    @staticmethod
    def evaluate(script: str) -> EvaluateAction:
        return EvaluateAction(script=script)

    @staticmethod
    def dismiss_consent(
        mode: Literal["hide", "accept", "reject"] = "hide",
    ) -> DismissConsentAction:
        return DismissConsentAction(mode=mode)

    @staticmethod
    def select(
        selector: str,
        value: Optional[str] = None,
        label: Optional[str] = None,
        frame: Optional[Union[str, Sequence[str]]] = None,
    ) -> SelectAction:
        return SelectAction(selector=selector, value=value, label=label, frame=frame)

    @staticmethod
    def hover(
        selector: str, frame: Optional[Union[str, Sequence[str]]] = None
    ) -> HoverAction:
        return HoverAction(selector=selector, frame=frame)

    @staticmethod
    def scroll_into_view(
        selector: str,
        block: Literal["start", "center", "end", "nearest"] = "center",
        frame: Optional[Union[str, Sequence[str]]] = None,
    ) -> ScrollIntoViewAction:
        return ScrollIntoViewAction(selector=selector, block=block, frame=frame)

    @staticmethod
    def click_text(
        text: str,
        exact: bool = False,
        frame: Optional[Union[str, Sequence[str]]] = None,
    ) -> ClickTextAction:
        return ClickTextAction(text=text, exact=exact, frame=frame)

    @staticmethod
    def extract(
        selector: str,
        attribute: Optional[str] = None,
        frame: Optional[Union[str, Sequence[str]]] = None,
    ) -> ExtractAction:
        return ExtractAction(selector=selector, attribute=attribute, frame=frame)

    @staticmethod
    def check(
        selector: str, frame: Optional[Union[str, Sequence[str]]] = None
    ) -> CheckAction:
        return CheckAction(selector=selector, frame=frame)

    @staticmethod
    def uncheck(
        selector: str, frame: Optional[Union[str, Sequence[str]]] = None
    ) -> UncheckAction:
        return UncheckAction(selector=selector, frame=frame)

    @staticmethod
    def wait_event(
        event: Literal["load", "domcontentloaded", "networkidle"] = "load",
        timeout: int = 10000,
    ) -> WaitEventAction:
        return WaitEventAction(event=event, timeout=timeout)

    @staticmethod
    def snapshot(format: Literal["html", "markdown"] = "html") -> SnapshotAction:
        return SnapshotAction(format=format)

    @staticmethod
    def inspect(max_elements: int = 200) -> InspectAction:
        return InspectAction(max_elements=max_elements)

    @staticmethod
    def download(
        selector: Optional[str] = None,
        url: Optional[str] = None,
        timeout_ms: int = 15000,
        max_bytes: Optional[int] = None,
        frame: Optional[Union[str, Sequence[str]]] = None,
        integration_id: Optional[str] = None,
        key_template: Optional[str] = None,
        max_files: int = 1,
        max_total_bytes: Optional[int] = None,
        quiet_ms: int = 1000,
        bundle: Literal["none", "zip"] = "none",
    ) -> DownloadAction:
        return DownloadAction(
            selector=selector,
            url=url,
            timeout_ms=timeout_ms,
            max_bytes=max_bytes,
            frame=frame,
            integration_id=integration_id,
            key_template=key_template,
            max_files=max_files,
            max_total_bytes=max_total_bytes,
            quiet_ms=quiet_ms,
            bundle=bundle,
        )


def serialize_actions(
    actions: Sequence[Union[ScrapeAction, Mapping[str, Any]]],
) -> List[Dict[str, Any]]:
    """Serialise typed actions to API JSON; raw dicts pass through unchanged."""
    serialized: List[Dict[str, Any]] = []
    downloads = sum(
        1
        for action in actions
        if isinstance(action, DownloadAction)
        or (isinstance(action, dict) and action.get("type") == "download")
    )
    if downloads > _MAX_DOWNLOAD_ACTIONS:
        raise TypeError(
            f"at most {_MAX_DOWNLOAD_ACTIONS} download actions are allowed per "
            f"request, got {downloads}"
        )
    for index, action in enumerate(actions):
        if isinstance(action, _ACTION_CLASSES):
            serialized.append(action.to_dict())
        elif isinstance(action, dict):
            serialized.append(action)
        else:
            raise TypeError(
                f"actions[{index}] must be an action from alterlab.Actions or a dict, "
                f"got {type(action).__name__}"
            )
    return serialized


class ArtifactMetadata(Dict[str, Any]):
    """A privately stored browser download (``download`` actions, #30596).

    Fetch it with ``GET /api/v1/artifacts/{artifact_id}/url``. Never carries a
    storage key.
    """

    @property
    def artifact_id(self) -> Optional[str]:
        return self.get("artifact_id")

    @property
    def filename(self) -> Optional[str]:
        return self.get("filename")

    @property
    def media_type(self) -> Optional[str]:
        return self.get("media_type")

    @property
    def size_bytes(self) -> Optional[int]:
        return self.get("size_bytes")

    @property
    def sha256(self) -> Optional[str]:
        return self.get("sha256")

    @property
    def status(self) -> Optional[str]:
        return self.get("status")

    @property
    def scan_status(self) -> Optional[str]:
        """``not_scanned``, ``clean`` or ``quarantined`` (#38735)."""
        return self.get("scan_status")

    @property
    def expires_at(self) -> Optional[float]:
        return self.get("expires_at")


class ArtifactDelivery(Dict[str, Any]):
    """Outcome of delivering a download artifact to a storage integration (#38734).

    ``status`` is ``"delivered"`` or ``"failed"``; a failure never affects the
    platform-stored artifact.
    """

    @property
    def integration_id(self) -> Optional[str]:
        return self.get("integration_id")

    @property
    def status(self) -> Optional[str]:
        return self.get("status")

    @property
    def key(self) -> Optional[str]:
        return self.get("key")

    @property
    def bytes(self) -> Optional[int]:
        return self.get("bytes")

    @property
    def error(self) -> Optional[str]:
        return self.get("error")


class ActionObservation(Dict[str, Any]):
    """Page state after an action settled (actions sent with ``observe: True``, #30579).

    Add ``"observe": True`` to an action dict to request it. URLs arrive redacted.

    Fields:
        verified: True only when the DOM settled within the budget.
        readiness: ``stable``, ``timeout``, ``error`` or ``not_run``.
        url: Current URL.
        route: Last route transition, if any.
        transitions: Route transitions caused by the action.
        snapshot: Bounded page snapshot (dict).
        diagnostics: Typed diagnostic codes.
    """

    @property
    def action_index(self) -> Optional[int]:
        return self.get("action_index")

    @property
    def url(self) -> Optional[str]:
        return self.get("url")

    @property
    def verified(self) -> Optional[bool]:
        return self.get("verified")

    @property
    def readiness(self) -> Optional[str]:
        return self.get("readiness")

    @property
    def route(self) -> Optional[Dict[str, Any]]:
        return self.get("route")

    @property
    def transitions(self) -> List[Dict[str, Any]]:
        return self.get("transitions") or []

    @property
    def snapshot(self) -> Optional[Dict[str, Any]]:
        return self.get("snapshot")

    @property
    def waited_ms(self) -> Optional[int]:
        return self.get("waited_ms")

    @property
    def diagnostics(self) -> List[str]:
        return self.get("diagnostics") or []


class ActionResult(Dict[str, Any]):
    """Result of one browser action, as returned in ``result["action_results"]``.

    A ``dict`` subclass, so ``r["success"]`` keeps working, with typed
    attribute access on top.

    Fields:
        index: Action index in the sequence (0-based).
        type: Action type that was executed.
        success: Whether the action completed successfully.
        error: Error message if the action failed.
        result: Return value (for ``evaluate`` and ``extract`` actions).
        screenshot: Base64-encoded screenshot (legacy).
        screenshot_url: Public URL of the stored screenshot (``screenshot`` actions).
        snapshot_url: Public URL of the stored HTML/markdown (``snapshot`` actions).
        artifact: :class:`ArtifactMetadata` of the stored file (``download`` actions).
        artifacts: list of :class:`ArtifactMetadata` (multi-file ``download`` actions).
        bundle: :class:`ArtifactMetadata` of the ZIP (``download`` with ``bundle="zip"``).
        delivery: :class:`ArtifactDelivery` outcome (``download`` actions with ``integration_id``).
        observation: :class:`ActionObservation` (actions sent with ``observe: True``).
        element_map: Capped element map dict (``inspect`` actions).
        truncated: True when a snapshot or element map was cut at the size cap.
    """

    @property
    def index(self) -> Optional[int]:
        return self.get("index")

    @property
    def type(self) -> Optional[str]:
        return self.get("type")

    @property
    def success(self) -> Optional[bool]:
        return self.get("success")

    @property
    def error(self) -> Optional[str]:
        return self.get("error")

    @property
    def result(self) -> Optional[str]:
        return self.get("result")

    @property
    def screenshot(self) -> Optional[str]:
        return self.get("screenshot")

    @property
    def screenshot_url(self) -> Optional[str]:
        return self.get("screenshot_url")

    @property
    def snapshot_url(self) -> Optional[str]:
        return self.get("snapshot_url")

    @property
    def element_map(self) -> Optional[Dict[str, Any]]:
        return self.get("element_map")

    @property
    def truncated(self) -> Optional[bool]:
        return self.get("truncated")

    @property
    def artifact(self) -> Optional[ArtifactMetadata]:
        value = self.get("artifact")
        if isinstance(value, ArtifactMetadata):
            return value
        return ArtifactMetadata(value) if isinstance(value, dict) else None

    @property
    def artifacts(self) -> Optional[List[ArtifactMetadata]]:
        value = self.get("artifacts")
        if not isinstance(value, list):
            return None
        return [
            v if isinstance(v, ArtifactMetadata) else ArtifactMetadata(v)
            for v in value
            if isinstance(v, dict)
        ]

    @property
    def bundle(self) -> Optional[ArtifactMetadata]:
        value = self.get("bundle")
        if isinstance(value, ArtifactMetadata):
            return value
        return ArtifactMetadata(value) if isinstance(value, dict) else None

    @property
    def delivery(self) -> Optional[ArtifactDelivery]:
        value = self.get("delivery")
        if isinstance(value, ArtifactDelivery):
            return value
        return ArtifactDelivery(value) if isinstance(value, dict) else None

    @property
    def observation(self) -> Optional[ActionObservation]:
        value = self.get("observation")
        if isinstance(value, ActionObservation):
            return value
        return ActionObservation(value) if isinstance(value, dict) else None


def parse_action_results(result: Any) -> Any:
    """Wrap ``result["action_results"]`` entries as :class:`ActionResult` in place."""
    if not isinstance(result, dict):
        return result
    action_results = result.get("action_results")
    if isinstance(action_results, list):
        result["action_results"] = [
            ActionResult(entry) if isinstance(entry, dict) else entry
            for entry in action_results
        ]
    return result
