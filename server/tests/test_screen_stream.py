"""The AirPlay receiver can run on its own and stream frames over local TCP, so restarting the server does not
end the phone's Screen Mirroring session."""

import os
import socket
import subprocess
import threading
import time

import pytest

from hidagent import receiver
from hidagent.screen import Screen


def wait_for(check, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


def listener():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    srv.settimeout(3)
    return srv, srv.getsockname()[1]


def test_frames_are_read_from_a_tcp_stream():
    srv, port = listener()
    screen = Screen(stream=f"127.0.0.1:{port}")
    screen.start()
    conn, _ = srv.accept()
    conn.sendall(b"half a frame\xff\xd9\xff\xd8first\xff\xd9\xff\xd8second\xff\xd9")
    assert wait_for(lambda: screen.frame == b"\xff\xd8second\xff\xd9")
    screen.stop()
    conn.close()
    srv.close()


def test_the_stream_is_followed_again_after_the_receiver_restarts():
    srv, port = listener()
    screen = Screen(stream=f"127.0.0.1:{port}")
    screen.start()
    conn, _ = srv.accept()
    conn.sendall(b"\xff\xd8before\xff\xd9")
    assert wait_for(lambda: screen.frame == b"\xff\xd8before\xff\xd9")
    conn.close()  # the receiver went away
    assert wait_for(lambda: screen.frame is None)
    conn, _ = srv.accept()  # and came back
    conn.sendall(b"\xff\xd8after\xff\xd9")
    assert wait_for(lambda: screen.frame == b"\xff\xd8after\xff\xd9")
    screen.stop()
    conn.close()
    srv.close()


def test_restart_stops_the_standalone_receiver_so_its_loop_starts_a_new_one(tmp_path):
    srv, port = listener()
    fake_uxplay = subprocess.Popen(["sleep", "30"])
    pidfile = tmp_path / "uxplay.pid"
    pidfile.write_text(str(fake_uxplay.pid))
    screen = Screen(stream=f"127.0.0.1:{port}", pidfile=pidfile)
    try:
        screen.start()
        conn, _ = srv.accept()
        assert wait_for(lambda: screen._sock is not None)
        screen.restart()
        assert wait_for(lambda: fake_uxplay.poll() is not None)
    finally:
        fake_uxplay.kill()
        fake_uxplay.wait()
        screen.stop()
        srv.close()


def test_restart_signals_nothing_when_no_receiver_is_streaming(tmp_path):
    # the receiver is gone, so the pid it recorded may belong to an unrelated process by now
    other = subprocess.Popen(["sleep", "30"])
    pidfile = tmp_path / "uxplay.pid"
    pidfile.write_text(str(other.pid))
    try:
        Screen(stream="127.0.0.1:9", pidfile=pidfile).restart()
        time.sleep(0.2)
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_after_a_restart_the_screen_counts_as_never_mirrored():
    screen = Screen()
    screen.frame, screen.updated = b"\xff\xd8old\xff\xd9", time.time() - 300
    screen.restart()
    assert screen.frame is None and not screen.updated


class Mirror:
    """What the standalone receiver runs on: the latest frame of a phone that is mirroring."""

    def __init__(self, frame):
        self.frame, self.updated = frame, time.time() - 30  # the phone has been still for a while


def serve(mirror):
    port = free_port()
    threading.Thread(target=receiver.serve, args=(mirror, port), daemon=True).start()
    return port


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_server_that_connects_late_gets_the_current_screen_at_once():
    # a still phone sends no new frames, so a restarted server must not have to wait for the screen to change
    port = serve(Mirror(b"\xff\xd8current\xff\xd9"))
    screen = Screen(stream=f"127.0.0.1:{port}")
    screen.start()
    assert wait_for(lambda: screen.frame == b"\xff\xd8current\xff\xd9")
    screen.stop()


def test_the_receiver_forwards_new_frames_and_says_when_the_phone_is_gone():
    mirror = Mirror(b"\xff\xd8first\xff\xd9")
    screen = Screen(stream=f"127.0.0.1:{serve(mirror)}")
    screen.start()
    assert wait_for(lambda: screen.frame == b"\xff\xd8first\xff\xd9")
    mirror.frame, mirror.updated = b"\xff\xd8next\xff\xd9", time.time()
    assert wait_for(lambda: screen.frame == b"\xff\xd8next\xff\xd9")
    mirror.frame = None  # UxPlay exited
    assert wait_for(lambda: screen.frame is None)
    screen.stop()


def test_uxplay_s_pid_is_recorded_for_the_server_s_restart(tmp_path, monkeypatch):
    fake = tmp_path / "uxplay"
    fake.write_text("#!/bin/sh\nexec sleep 30\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    pidfile = tmp_path / "uxplay.pid"
    screen = Screen(pidfile=pidfile)
    screen.start()
    try:
        assert wait_for(lambda: screen._proc is not None and pidfile.exists()
                        and pidfile.read_text() == str(screen._proc.pid))
    finally:
        screen.stop()


def test_stop_ends_the_follower_thread():
    srv, port = listener()
    screen = Screen(stream=f"127.0.0.1:{port}")
    screen.start()
    conn, _ = srv.accept()
    assert wait_for(lambda: screen._sock is not None)
    screen.stop()
    assert wait_for(lambda: not screen._thread.is_alive())
    conn.close()
    srv.close()


def test_a_stream_without_a_port_is_refused_at_once():
    with pytest.raises(ValueError, match="host:port"):
        Screen(stream="127.0.0.1")


def test_a_followed_stream_reports_whether_it_is_live():
    srv, port = listener()
    screen = Screen(stream=f"127.0.0.1:{port}")
    assert not screen.live  # nothing followed yet
    screen.start()
    conn, _ = srv.accept()
    conn.sendall(b"\xff\xd8frame\xff\xd9")
    assert wait_for(lambda: screen.frame is not None)
    assert screen.live
    screen.stop()
    conn.close()
    srv.close()
