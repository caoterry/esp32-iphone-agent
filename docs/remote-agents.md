# Remote agents (legacy version)

The optional CLI and stdio MCP bridge control the existing Python server over
HTTP. They use the legacy Wi-Fi/TCP firmware and UxPlay setup described in the
README. They do not work with the BLE/iPhone-app version.

Use this route when an external agent runs on a Mac/Linux host or Raspberry Pi
and supplies the decisions. It reuses the existing Wi-Fi/TCP board setup and
requires no app installation or code signing on the iPhone. A separate host
running UxPlay is still required.

Install on the controlling computer:

```sh
pip install -e './server[mcp]'
iphone-agent --url http://127.0.0.1:8890 status
iphone-agent --url http://127.0.0.1:8890 screenshot phone.jpg
```

Use the actual server address if it runs elsewhere, including on a Raspberry Pi.
`IPHONE_AGENT_URL` supplies the default; otherwise the bridge uses localhost.
The legacy server has no authentication, so it listens on this computer only unless `HOST` says otherwise;
the bridge adds no public listener. Install without `[mcp]` if only the CLI is needed.

Configure an MCP client to launch this command (stdio transport):

```json
{
  "mcpServers": {
    "iphone": {
      "command": "iphone-agent",
      "args": ["--url", "http://127.0.0.1:8890", "mcp"]
    }
  }
}
```

Start with `iphone_status` and `iphone_screenshot`. Coordinates are image fractions
from 0 to 1. The bridge exposes tap, swipe, scroll, type, key, Home, Back and
calibration. Direct controls need no model credentials. Keyboard input is one
printable line: the board types ASCII, and other text such as Chinese is pasted
through Universal Clipboard (server on a Mac with the phone's Apple Account and
Handoff on). A paste takes about 5 s and may first show iOS's "Allow Paste"
prompt; to skip it, set Settings > the app > Paste from Other Apps to Allow. The
pasted text stays on the Mac's clipboard. If Universal Clipboard did not deliver
(Handoff off, another Apple Account, too slow), Cmd+V pastes whatever the phone's
clipboard already held and the command still answers `ok`: check the field in a
screenshot before submitting anything. If the phone's keyboard is a Chinese input
method, typed ASCII goes through it; switch to an English keyboard first.
Use `iphone_key` for Enter or editing combinations.
Only type into a visibly focused field. Observe after each action: an `ok` reply
is a command acknowledgement, and the latest AirPlay frame can precede its effect.
Home/Back use the existing gestures and need visual confirmation.

`delegate_task` starts the server's existing configured vision agent. `task_status`
reads its single current task (`running`, `task`, `steps`); it is not a job history
and returns no task ID. Poll until `running` is false, inspect the last step for
done/fail/error, and check the screen. `stop_task` invokes the existing emergency
stop, which cancels the agent and releases/re-homes the pointer. The CLI equivalents
are `task 'Open Clock'`, `task-status` and `stop`.

The server rejects direct actions during an agent run and overlapping direct
actions. Use one controller at a time: there are no controller ownership leases.
Do not start another action until the previous one has returned. Calibration
returns `auto: false` when the user must locate the pointer; finish with both
coordinates, e.g. `iphone-agent calibrate --pointer 0.5 0.4`.

The bridge forwards existing controls; it does not add autonomous strategies,
change prompts or firmware, or establish new hardware/performance results.
