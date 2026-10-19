"""Run the AirPlay receiver on its own: `python -m hidagent.receiver`.

UxPlay streams the phone's screen as JPEG frames to a local TCP port, and the server follows that stream
(MIRROR_STREAM=127.0.0.1:8891), so restarting the server leaves the phone's Screen Mirroring session alone.
UxPlay exits on some disconnects; this loop starts it again and records its pid for the server's restart.
"""

import logging
import os
import subprocess
import time
from pathlib import Path

from .screen import jpeg_sink

log = logging.getLogger(__name__)


def command(name: str, fps: int, quality: int, port: int) -> list[str]:
    sink = jpeg_sink(fps, quality, f"tcpserversink host=127.0.0.1 port={port} sync=false")
    return ["uxplay", "-n", name, "-nh", "-a", "-reset", "0", "-vs", sink]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    name = os.environ.get("AIRPLAY_NAME", "iPhone Agent")
    port = int(os.environ.get("MIRROR_PORT", 8891))
    data = Path(os.environ.get("HIDAGENT_DATA", Path.home() / ".hidagent"))
    data.mkdir(parents=True, exist_ok=True)
    while True:
        proc = subprocess.Popen(command(name, 8, 75, port))
        (data / "uxplay.pid").write_text(str(proc.pid))
        log.info("AirPlay receiver '%s' started (pid %d), frames on 127.0.0.1:%d", name, proc.pid, port)
        code = proc.wait()
        log.warning("AirPlay receiver exited (code %s), restarting", code)
        time.sleep(1)


if __name__ == "__main__":
    main()
