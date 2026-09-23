"""
Surface Abstraction Layer.
Defines the abstract interface separating discovery and replay automation logic
from underlying browser or OS automation technology (e.g., Selenium, Desktop UIA).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BoundingBox:
    x: float
    y: float
    width: float
    height: float


@dataclass
class InteractiveControl:
    control_id: str
    tag_name: str
    role: str
    accessible_name: str
    text_content: str
    control_type: str  # text, submit, button, select, link, etc.
    rect: BoundingBox
    xpath: str
    css_selector: str
    attributes: Dict[str, str] = field(default_factory=dict)
    anchor_text: Optional[str] = None  # text in nearby/adjacent cells or labels


@dataclass
class SurfaceState:
    url: str
    title: str
    controls: List[InteractiveControl] = field(default_factory=list)
    page_text: str = ""
    screenshot_bytes: Optional[bytes] = None


@dataclass
class LiveSessionHandle:
    session_id: str
    window_handle: str
    paused_url: str
    paused_step_id: Optional[str] = None
    paused_at_iso: str = ""
    operator_actions_recorded: List[str] = field(default_factory=list)


class SurfaceDriver(ABC):
    """Abstract interface for driving an application surface."""

    @abstractmethod
    def navigate(self, url: str) -> None:
        """Navigate to a target URL."""
        pass

    @abstractmethod
    def get_current_url(self) -> str:
        """Return the current page URL."""
        pass

    @abstractmethod
    def get_title(self) -> str:
        """Return the current page title."""
        pass

    @abstractmethod
    def get_state(self) -> SurfaceState:
        """Observe and return the current surface state."""
        pass

    @abstractmethod
    def click(self, locator: Any) -> bool:
        """Click on an element identified by the locator."""
        pass

    @abstractmethod
    def type_text(self, locator: Any, text: str, clear: bool = True) -> bool:
        """Type text into an element identified by the locator."""
        pass

    @abstractmethod
    def select_option(self, locator: Any, value: str) -> bool:
        """Select a dropdown option by value or visible text."""
        pass

    @abstractmethod
    def extract_text(self, locator: Any) -> str:
        """Extract visible text content from an element."""
        pass

    @abstractmethod
    def capture_screenshot(self) -> bytes:
        """Capture and return raw PNG screenshot bytes."""
        pass

    @abstractmethod
    def pause_for_human(self, step_id: Optional[str] = None) -> LiveSessionHandle:
        """Pause automation and yield control of the live session to a human."""
        pass

    @abstractmethod
    def resume_from_human(self, handle: LiveSessionHandle) -> None:
        """Resume automation on the same live session after human intervention."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the surface session."""
        pass
