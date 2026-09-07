"""Focused tests for the main runner's conservative pacing policy."""

import pytest

from modules.pacing import PacingConfig, PacingPolicy, PacingStop, detect_challenge


class _FixedRandom:
    def __init__(self, value):
        self.value = value

    def uniform(self, low, high):
        assert low <= self.value <= high
        return self.value


class _Body:
    def __init__(self, text):
        self.text = text


class _Driver:
    def __init__(self, url="https://www.linkedin.com/jobs", body="normal page"):
        self.current_url = url
        self.body = _Body(body)

    def find_element(self, by, value):
        assert by == "tag name"
        assert value == "body"
        return self.body


def test_finish_application_waits_inside_configured_bounds():
    sleeps = []
    logs = []
    policy = PacingPolicy(
        config=PacingConfig(90, 120, 40),
        rng=_FixedRandom(105),
        sleeper=sleeps.append,
        logger=logs.append,
    )

    policy.begin_application("J1", "Engineer", "Acme")
    cooldown = policy.finish_application("J1", "Engineer", "Acme")

    assert cooldown == 105
    assert sleeps == [105]
    assert policy.application_attempts == 1
    assert any("waiting 105.0 seconds" in message for message in logs)


def test_begin_application_stops_before_the_session_cap():
    policy = PacingPolicy(
        config=PacingConfig(90, 120, 2),
        sleeper=lambda _: None,
        logger=lambda *_: None,
    )

    policy.begin_application("J1", "Engineer", "Acme")
    policy.begin_application("J2", "Engineer", "Acme")

    with pytest.raises(PacingStop, match="session limit reached"):
        policy.begin_application("J3", "Engineer", "Acme")

    assert policy.application_attempts == 2


def test_challenge_url_is_detected_and_leaves_browser_open():
    policy = PacingPolicy(sleeper=lambda _: None, logger=lambda *_: None)

    with pytest.raises(PacingStop) as error:
        policy.stop_on_challenge(
            _Driver(url="https://www.linkedin.com/checkpoint/challenge"),
            "job details",
        )

    assert error.value.leave_browser_open is True


def test_challenge_text_is_detected():
    assert detect_challenge(_Driver(body="Please verify you're human")) == (
        "page text: verify you're human"
    )


def test_normal_linkedin_page_is_not_a_challenge():
    assert detect_challenge(_Driver()) is None
