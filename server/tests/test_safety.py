"""The phone must not be tapped blindly: a frozen mirror, a mouse the phone ignores or a stray pointer reading
is reported or skipped instead of acted on."""

import asyncio
import time

import pytest

from hidagent import phone as phone_module
from hidagent import vision
from hidagent.phone import Phone


class Screen:
    """A mirrored screen whose frames arrive only when the board's moves reach the phone (if `mirroring`)."""

    def __init__(self, age: float):
        self.frame, self.updated, self.restarted = b"jpeg", time.time() - age, False
        self.mirroring = True

    def show_change(self):
        if self.mirroring:
            self.updated = time.time()

    async def fresh(self, since, timeout=0.8):
        deadline = time.time() + timeout
        while self.updated <= since:
            if time.time() > deadline:
                return None
            await asyncio.sleep(0.01)
        return self.frame

    async def settled(self, **_):
        await asyncio.sleep(0)

    def restart(self):
        self.restarted = True


class Device:
    links = 0

    def __init__(self, screen: Screen, mouse_works: bool = True):
        self.screen, self.mouse_works, self.sent = screen, mouse_works, []

    async def send(self, line):
        self.sent.append((time.time(), line))
        if line.startswith("move") and self.mouse_works:
            self.screen.show_change()
        return "ok"

    @property
    def lines(self):
        return [line for _, line in self.sent]


def make_phone(tmp_path, age, mouse_works=True, mirroring=True):
    screen = Screen(age)
    screen.mirroring = mirroring
    device = Device(screen, mouse_works)
    phone = Phone(device, tmp_path / "calibration.json", screen)
    phone.span = {"w": 460, "h": 1000}
    return phone, device, screen


def test_a_still_screen_is_checked_before_tapping(tmp_path):
    phone, device, _ = make_phone(tmp_path, age=30)
    asyncio.run(phone.tap(0.5, 0.5))
    nudge = phone_module.NUDGE
    assert device.lines[:2] == [f"move {nudge} 0", f"move -{nudge} 0"]
    assert device.lines[-1] == "click"


def test_a_recently_updated_screen_is_not_probed(tmp_path):
    phone, device, _ = make_phone(tmp_path, age=0)
    asyncio.run(phone.tap(0.5, 0.5))
    assert f"move {phone_module.NUDGE} 0" not in device.lines


def test_a_frozen_mirror_is_restarted_and_nothing_is_clicked(tmp_path):
    phone, device, screen = make_phone(tmp_path, age=300, mirroring=False)
    with pytest.raises(phone_module.PhoneUnavailable, match="Screen Mirroring"):
        asyncio.run(phone.tap(0.5, 0.5))
    assert screen.restarted
    assert "click" not in device.lines


def test_a_phone_that_was_never_mirrored_is_reported_without_restarting_the_receiver(tmp_path):
    phone, device, screen = make_phone(tmp_path, age=0, mirroring=False)
    screen.updated = 0.0  # no frame has ever arrived: Screen Mirroring was not started
    with pytest.raises(phone_module.PhoneUnavailable, match="Screen Mirroring"):
        asyncio.run(phone.tap(0.5, 0.5))
    assert not screen.restarted
    assert "click" not in device.lines


def test_a_mouse_the_phone_ignores_is_reported_and_nothing_is_clicked(tmp_path):
    # a phone locked a moment ago looks the same (board still answers, nothing changes on screen): say both
    phone, device, screen = make_phone(tmp_path, age=10, mouse_works=False)
    with pytest.raises(phone_module.PhoneUnavailable, match="unlock.*plug"):
        asyncio.run(phone.tap(0.5, 0.5))
    assert not screen.restarted
    assert "click" not in device.lines


def test_typing_is_checked_too(tmp_path):
    phone, device, _ = make_phone(tmp_path, age=10, mouse_works=False)
    with pytest.raises(phone_module.PhoneUnavailable):
        asyncio.run(phone.type("hello"))
    assert not any(line.startswith("type") for line in device.lines)


def test_aim_ignores_a_pointer_reading_far_from_the_target(tmp_path, monkeypatch):
    # a moving clock hand elsewhere on the screen looked like the pointer once
    phone, device, _ = make_phone(tmp_path, age=0)
    monkeypatch.setattr(vision, "pointer", lambda *a, **k: (0.86, 0.23))
    seen_before = {axis: list(v) for axis, v in phone._seen.items()}
    asyncio.run(phone.tap(0.39, 0.48, aim=True))
    after_aim = device.lines[device.lines.index(f"move -{phone_module.NUDGE} 0") + 1:]
    assert after_aim == ["click"]  # no "correction" toward the stray reading
    assert {axis: list(v) for axis, v in phone._seen.items()} == seen_before  # and nothing learned from it


def test_a_forgotten_position_makes_the_next_gesture_start_from_the_corner(tmp_path):
    phone, device, _ = make_phone(tmp_path, age=0)
    asyncio.run(phone.tap(0.5, 0.5))
    phone.forget_position()  # e.g. after raw board commands the server did not track
    device.sent.clear()
    asyncio.run(phone.tap(0.6, 0.6))
    assert device.lines[0] == "home"


def test_the_pointer_settles_after_a_long_move_before_clicking(tmp_path):
    phone, device, _ = make_phone(tmp_path, age=0)
    asyncio.run(phone.tap(0.9, 0.9))  # from the corner: a long move
    times = {line: t for t, line in device.sent}
    last_move = max(t for t, line in device.sent if line.startswith("move"))
    assert times["click"] - last_move >= phone_module.SETTLE_AFTER_LONG_MOVE * 0.9
