"""The AirPlay receiver can run on its own and stream frames over local TCP, so restarting the server does not
end the phone's Screen Mirroring session."""

import os
import socket
import subprocess
import time

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
    fake_uxplay = subprocess.Popen(["sleep", "30"])
    pidfile = tmp_path / "uxplay.pid"
    pidfile.write_text(str(fake_uxplay.pid))
    Screen(stream="127.0.0.1:9", pidfile=pidfile).restart()
    assert wait_for(lambda: fake_uxplay.poll() is not None)


def test_the_standalone_receiver_streams_jpegs_to_a_local_port():
    cmd = receiver.command("iPhone Agent", fps=8, quality=75, port=8891)
    assert cmd[:3] == ["uxplay", "-n", "iPhone Agent"]
    sink = cmd[cmd.index("-vs") + 1]
    assert "jpegenc quality=75" in sink and "tcpserversink host=127.0.0.1 port=8891" in sink
    assert os.environ.get("PATH")  # sanity: the command is run as-is, found on PATH


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
