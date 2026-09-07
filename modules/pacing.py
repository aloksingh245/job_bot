"""
Conservative rate control for the main LinkedIn application workflow.

This module intentionally provides bounded cooldowns and safety stops. It does
not change browser fingerprints, bypass verification, or try to disguise the
automation as a person.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from time import sleep
from typing import Callable


# ---------------------------------------------------------------------------
# Pacing configuration. Keep the operational limits together and easy to find.
# ---------------------------------------------------------------------------
MIN_APPLICATION_COOLDOWN_SECONDS = 90.0
MAX_APPLICATION_COOLDOWN_SECONDS = 120.0
MAX_APPLICATION_ATTEMPTS_PER_SESSION = 40


@dataclass(frozen=True)
class PacingConfig:
    """Bounded limits for one bot session."""

    min_application_cooldown_seconds: float = MIN_APPLICATION_COOLDOWN_SECONDS
    max_application_cooldown_seconds: float = MAX_APPLICATION_COOLDOWN_SECONDS
    max_application_attempts_per_session: int = MAX_APPLICATION_ATTEMPTS_PER_SESSION

    def __post_init__(self) -> None:
        """Reject unsafe or contradictory pacing settings early."""
        if self.min_application_cooldown_seconds < 0:
            raise ValueError("minimum application cooldown cannot be negative")
        if self.max_application_cooldown_seconds < self.min_application_cooldown_seconds:
            raise ValueError("maximum application cooldown must be >= minimum cooldown")
        if self.max_application_attempts_per_session <= 0:
            raise ValueError("maximum application attempts must be positive")


class PacingStop(RuntimeError):
    """Signal that the runner must stop under a safety policy."""

    def __init__(self, reason: str, leave_browser_open: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.leave_browser_open = leave_browser_open


CHALLENGE_URL_MARKERS = (
    "/checkpoint",
    "/challenge",
    "captcha",
    "authwall",
)

CHALLENGE_TEXT_MARKERS = (
    "captcha",
    "security verification",
    "verify you're human",
    "verify you are human",
    "unusual activity",
    "automated activity",
    "confirm it's you",
    "account restricted",
)


def detect_challenge(driver) -> str | None:
    """
    Return a matching LinkedIn challenge signal, or ``None``.

    The check is deliberately conservative: it looks at the current URL and
    visible body text, not the whole page source, to avoid matching words in
    hidden scripts or normal job descriptions.
    """
    try:
        current_url = str(getattr(driver, "current_url", "") or "").lower()
    except Exception:
        current_url = ""

    for marker in CHALLENGE_URL_MARKERS:
        if marker in current_url:
            return f"URL marker: {marker}"

    try:
        body = driver.find_element("tag name", "body")
        visible_text = str(getattr(body, "text", "") or "").lower()
    except Exception:
        visible_text = ""

    for marker in CHALLENGE_TEXT_MARKERS:
        if marker in visible_text:
            return f"page text: {marker}"
    return None


class PacingPolicy:
    """Track application attempts, enforce the session cap, and cooldown."""

    def __init__(
        self,
        config: PacingConfig | None = None,
        rng: Random | None = None,
        sleeper: Callable[[float], None] = sleep,
        logger: Callable[..., None] = print,
    ) -> None:
        self.config = config or PacingConfig()
        self.rng = rng or Random()
        self.sleeper = sleeper
        self.logger = logger
        self.application_attempts = 0

    def begin_application(self, job_id: str, title: str, company: str) -> None:
        """Count an application attempt or stop before exceeding the cap."""
        if self.application_attempts >= self.config.max_application_attempts_per_session:
            raise PacingStop(
                "Application session limit reached: "
                f"{self.config.max_application_attempts_per_session} attempts."
            )

        self.application_attempts += 1
        self.logger(
            "Pacing: application attempt "
            f"{self.application_attempts}/{self.config.max_application_attempts_per_session} "
            f"for {title} | {company} (Job ID: {job_id})."
        )

    def finish_application(self, job_id: str, title: str, company: str) -> float:
        """Wait a bounded cooldown before the next application attempt."""
        cooldown = self.rng.uniform(
            self.config.min_application_cooldown_seconds,
            self.config.max_application_cooldown_seconds,
        )
        self.logger(
            "Pacing: waiting "
            f"{cooldown:.1f} seconds before the next application "
            f"after {title} | {company} (Job ID: {job_id})."
        )
        self.sleeper(cooldown)
        return cooldown

    def stop_on_challenge(self, driver, context: str) -> None:
        """Stop immediately when a verification or challenge page appears."""
        signal = detect_challenge(driver)
        if signal:
            reason = f"LinkedIn verification detected during {context} ({signal})."
            self.logger(f"Pacing: stopping run. {reason}")
            raise PacingStop(reason, leave_browser_open=True)
