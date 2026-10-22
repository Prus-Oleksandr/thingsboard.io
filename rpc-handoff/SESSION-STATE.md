# IoT Gateway RPC docs: session state (2026-10-22, end of day)

Start here when you resume this work on another machine. This file covers where things stand now.
Background material:
- `README.md` and `10-…`–`90-…` in this folder: the original handoff (RPC refactor analysis, per-connector specs, docs map, suspected bugs in section 5).
- `pending-verification-log.md`: the full running log from the previous sessions. It records what was tested, every decision and every bug, in chronological order. When this file and the log disagree, this file wins.
- `tools/`: screenshot text-rendering helpers (see "Screenshots").

## 0. At the start of the session

1. **Ask the user for local paths.** They differ on this machine. You need:
   - the docs repo (thingsboard.io, branch `draft-rpc-docs`);
   - the gateway repo (thingsboard-gateway, source of truth for code).
2. **Permissions.** The user allows you to read both projects freely. Ask before reading anything outside them.
3. **Gateway repo is read-only.** Never edit it. Never run the gateway or its tests. Never connect to devices or emulators. The user runs all tests and pastes the output.
4. **Docs repo rules.** Follow `CLAUDE.md`:
   - Ask before any build ("Run `pnpm build:fast` to verify, or skip?").
   - Working build command used before:
     `node ./scripts/generate-nav-sprite.mjs && SKIP_OG=true NODE_OPTIONS=--max-old-space-size=12288 pnpm exec astro build`
   - Work one page or connector at a time and show the diff.
   - Never commit or push without explicit permission.
5. **This branch is a draft.** `rpc-handoff/` is normally excluded via `.git/info/exclude`. It was force-added only to carry state between machines. Remove it, and restore the exclude, before any real PR.

## 1. Working rules (user feedback, still valid)

- **Scope is the refactor only.** Adapt only what the RPC refactor changed. Do not add explanations of behaviour that did not change. Label each diff item:
  - A: refactor change, keep;
  - B: pre-existing docs error, ask the user;
  - C: extra info, remove.
- **Never document suspected code bugs.** Ask the user first.
- **Keep text minimal.** One reply sentence per page, in the style "The gateway always replies to ThingsBoard: …". No regex details and no "Must match…" phrases.
- **Examples must work.** They must run with default settings and the standard test servers or emulators.
- **Screenshots always show "Demo Device".** This covers the terminal prompt, commands and replies. Edit or render screenshots instead of retaking them.
- **Before any commit or PR,** go through every pending item and bug in this file with the user.

## 2. Current situation

The pages and connectors below are DONE: verified by the user on emulators or hardware where noted in the log, and cross-checked against the code.
- **Connector config pages:** Modbus, MQTT, OPC-UA, BACnet, S7, REST, Request, FTP, OCPP, ODBC, SNMP, Socket, BLE, CAN.
- **Reserved RPC page:** tabs OPC-UA, Modbus, MQTT, BACnet, S7 (PLC + Logo!), REST, Request, FTP, OCPP, Socket, BLE, CAN, ODBC, SNMP.
- **Service RPC methods page:** `gateway_update` section removed by user decision.
- **Remote shell page:** UI label changes only.
- **Custom pages:** `custom/methods-and-datatypes.mdx` and `custom/serial-connector.mdx`, updated to gateway branch IOTGW-777 (not merged yet).

The final cross-check ran on 2026-10-22: five read-only agents compared all 19 changed pages with gateway master and the fix branches. Group 1 of its findings is fixed. Groups 2–3 are waiting for user decisions (section 4).

Nothing has been built yet. `pnpm build:fast` and `pnpm lint:linkcheck` have not been run on these changes.

## 3. Waiting for gateway fixes (do not finalize these until the fixes land)

| Docs | Waiting for | Status |
|---|---|---|
| `config/knx.mdx`, plus a new KNX tab on the Reserved RPC page | K1: `get` needs `requestType=read`, not migrated to a regex schema. K2: `{}` params turn a read into a write. K3: lookup ignores `deviceNameFilter`. | No fix yet. Not started in docs. Also `knx.mdx:354-356` links to Reserved RPC "for details", but there is no KNX tab. |
| `config/xmpp.mdx`, plus a new XMPP tab on the Reserved RPC page | X1: reserved RPC breaks on string params. X2: `${params}` is not substituted. Also `withResponse`. | A colleague is fixing it. Not started in docs. |
| `custom/*.mdx` | Gateway branch **IOTGW-777** (user's): Serial and DummyCustomConnector migrated to the `RPCResponse` contract. | Docs already match the branch. Re-check if the branch changes before merge. Not covered by 777: the demo connector returns None (no reply); S3, where the device-RPC thread dies on any connector exception; the gRPC wrapper. |
| `config/snmp.mdx` | Gateway branch **IOTGW-776** (user's, local): `requestFilter`/`attributeFilter` now use `fullmatch`, which fixes SN1. | Docs already match. No change needed. |
| `config/odbc.mdx` | Gateway branch **IOTGW-773** (user's): reconnect keeps the iterator. | No docs impact. |
| Socket (config + Reserved RPC tab) | Master `d97308db` fixed outgoing TCP writes. Verified. A colleague is now fixing the attribute-update regression that `d97308db` introduced (`bytes(bytes, encoding)`). | Docs are done. Still broken and not documented: UDP writes; `encoding` ignored everywhere; device RPC with non-string params errors. |
| `features/service-rpc-methods.mdx` restart/reboot | G1: the reply is a bare `'Success'`, which fails to publish. | Docs intentionally keep `{"success": true}`, the intended reply. |

## 4. Open decisions (ask the user)

**From the final cross-check, group 2 (the page contradicts the earlier log):**
- `config/rest.mdx` serverSideRpc table and JSON still have `responseTimeout` and `tries`. The code never reads them, and did not before the refactor either. They also show `timeout` default `0.5`, while the code default is 10. The log says these were removed. Did the user restore them on purpose during the "refactor-only" trim?
- `features/service-rpc-methods.mdx` has no 404 reply for `gateway_remove_provisioned_credentials`. The code returns `{"code": 404, "message": "Provisioned credentials file does not exist."}`. The log says the 404 case was added and verified. Was it removed on purpose?

**Group 3 (pre-existing docs errors, type B; Claude's recommendation in bold):**
- **`config/request.mdx:112, 377, 392`:** `attributeUpdates` uses `valueExpression`, but the code reads `requestValueExpression`. A config written from the docs raises KeyError. Recommend fixing.
- **"Every telemetry and attribute key has built-in GET/SET":** `config/mqtt.mdx:1652, 3216` and `config/bacnet.mdx:718, 839, 1136`. The same wording was already fixed on Modbus. Recommend fixing the same way.
- `config/request.mdx`: `responseValueExpression` is undocumented.
- `config/bacnet.mdx:1552`: `schedule` is listed, but RPC rejects it because it is not in `SUPPORTED_OBJECTS_TYPES`.
- "Default" column values for keys that the code requires:
  - `config/snmp.mdx` `community` shows `public`;
  - `config/ftp.mdx` `deviceNameFilter` shows `.*`;
  - `config/ble.mdx` `methodProcessing` shows `read`.
- `config/ftp.mdx`: `write` echoes the value only when it is under 80 characters; otherwise it returns `true`.
- `custom/serial-connector.mdx`: code that we did not touch has drifted from the gateway file. `is_connected` is inverted (around line 343), the timeout is read before the None check (around 314), and the run loop differs (around 235).
- Reserved RPC page:
  - the intro says the terminal is "on the gateway dashboard", but reserved RPC works only from the connected device's terminal (S5);
  - these optional parameters are not marked optional: MQTT GET `responseTopicExpression`, REST/Request GET `HTTPMethod`, S7 SET `size`;
  - ODBC `with_result=true` on UPDATE or a procedure returns an error, not `null`.
- `config/rest.mdx` `no-reply` example: the relative URL means the request goes to host `sensor`.
- `config/s7.mdx:538`: the read/write reply envelope is not shown.

**Other open questions:**
- Reserved RPC ODBC SET example: keep `set procedure_name=set_setpoint;value=23.5;` (a function created by the emulator), or switch to `set query=UPDATE device_state SET setpoint = ?;value=23.5;`?

## 5. Contested decisions already made (keep unless the user changes them)

- **MQTT:**
  - `${params}` is kept in `valueExpression` (6 places). The MQ1 fix was merged as gateway `332fef36`.
  - The timeout reply is documented as-is, `"{\"success\": false}"`: a double-encoded JSON string, which is a bug to report.
  - The one-way reserved `get` example was kept; gateway `6f01fab0` made `responseTopicExpression` optional.
  - Reserved RPC MQTT examples use the relay on Demo Device. The demo broker's `get_light_level` handler is incompatible.
- **BACnet:** the RPC timeout is documented as `requestTimeout` in seconds (default 10), although the shipped `bacnet.json` uses `10000` (B1).
- **5 s cap not documented:** OCPP and SNMP reserved `timeout` is capped at 5 s (`min(timeout, 5)`). The OCPP example keeps `"timeout": 10`.
- **Request:** serverSideRpc uses `requestValueExpression` (the shipped `request.json` `echo` entry lacks it, RQ1). `tries` was removed from serverSideRpc only.
- **REST:** `${requestId}` was replaced with `${restId}`, the name used in code. Ask the developers whether `${requestId}` was intended.
- **Modbus:** connector RPC (`modbus_<name>`) is intentionally undocumented.
- **OPC-UA:**
  - read and method errors arrive as `{"result": {"error": …}}`, not `{"error": …}`. This is not documented, and the reply sentence was narrowed to the success case;
  - set without a type cast is not documented.
- **Socket:**
  - the Reserved RPC example stays `192.168.0.200:50003` with `encoding=utf-8`;
  - `withResponse`/`methodProcessing` were removed from socket.mdx;
  - the old UI screenshots that still show the "With Response" toggle are kept, by user decision.
- **ODBC:** `save` was renamed to `persistent` (a pre-existing error that the user approved fixing). The connector name in the iterator file hash is not documented.
- **SNMP B fixes approved:** per-entry `timeout`/`community` removed; device `timeout` row added; `type` default `OCTETSTRING`.
- **Service RPC methods:**
  - `gateway_update` removed entirely; do not re-add it without the user;
  - restart/reboot delay is in milliseconds (default 1000);
  - `gateway_version` shows placeholders.
- **Custom:** the line under `send_rpc_reply` ("A connector that returns an `RPCResponse`… does not call this method") stays. The `RPCResponse` data type section was added.
- **FTP:** F1 (a configured RPC writes only if the method is exactly `write`) is not documented.
- **ODBC:** OD1 (empty `methods` drops `enableUnknownRpc`) is not documented.
- **CAN:** C1 (`overrideRpcConfig`/`enableUnknownRpc` drops configured data options) is not documented.

## 6. Not tested (code-derived only), so remind the user

- S7 Logo! (no hardware), S7 tag set, S7 `err_msg` bug case.
- BLE `set` reply `"Ok"`. The real sensor rejects writes, and the screenshot is generated.
- CAN error cases (`get`, schema error).
- ODBC SQL error, unknown method, empty result.
- Socket attribute-update regression (waiting for the colleague's fix).
- "From code reading" response examples on the Reserved RPC page that the log still lists as unverified.

## 7. Gateway bugs to report (collected, not yet reported unless noted)

- **Core:**
  - U1: `gateway_update` never really updates.
  - G1: restart/reboot reply.
  - G2/G3: no reply on exceptions or empty params.
  - S1: a connector-prefixed or `gateway_*` RPC to a sub-device runs at gateway level, and the reply fails because its id is the MQTT client object.
  - S2: "Connector of type X not found" is never sent.
  - S3: the device-RPC thread dies on a connector exception.
  - S5: reserved `get` on the gateway device busy-loops.
- **MQTT:**
  - double-encoded timeout reply;
  - a one-way publish failure still replies `{"result": "success"}` (`_publish` returns `False`, but the check is `is not None`);
  - the `type` (`twoWay`/`oneWay`) key is never read;
  - the UI saved a two-way mapping as one-way after a Value expression edit;
  - the demo broker `get_light_level` handler (ask to always reply on `data/response`).
- **BACnet:** B1 (`bacnet.json` timeout `10000`, host `0.0.0.0` breaks I-Am); `schedule` is unsupported for RPC.
- **Socket:**
  - UDP `sendto(str)`;
  - `encoding` ignored;
  - non-string device RPC params error;
  - `__connections.pop` KeyError;
  - connection refused comes as `{"result"}`;
  - the attribute-update regression from `d97308db` (being fixed).
- **OPC-UA:** `{"result": {"error"}}` inconsistency; set without type cast; O1 (unparseable `set` returns a raw AttributeError).
- **SNMP:** SN1 is fixed on IOTGW-776; `community` has no default.
- **S7:** `s7_connector.py` ~409 undefined `err_msg`.
- **KNX:** K1–K3.
- **XMPP:** X1, X2 (being fixed).
- **Request:** RQ1 (shipped `echo` entry without `requestValueExpression`).
- **FTP:** F1.
- **ODBC:** OD1.
- **CAN:** C1.
- **Custom:** S4 (IOTGW-777 covers Serial and Dummy; demo connector and gRPC are still open).

## 8. Screenshots

- **Workflow.** The user takes the real test and pastes the output. Claude then edits the existing screenshot (keeping the "Demo Device" prompt and header) or renders the new text into it.
- **Originals.** The scratchpad originals from the previous machine are gone. The pre-edit versions of every screenshot are on `main`: `git show main:<path>`.
- **`tools/termtext.py`.** Renders terminal text: Ubuntu Sans Mono with LCD filtering, colour 167. `FONT` points to `/usr/share/fonts/truetype/ubuntu/UbuntuSansMono[wght].ttf`; adjust it on the new machine. Calibrate each image with `tools/fit.py`:
  - usage: `fit.py img text cell y0 y1 x0min x0max blmin blmax`;
  - typical values: X0 ≈ 336–341, pitch 9.01–9.03, size 15.8–16.2, line height 18.

  `tools/mk_socket_example.py` is a complete example: re-render one line and widen the orange frame. It needs numpy and pillow.
- **Emulators** live outside this repo. The user will set them up on the new machine.

## 9. Final steps before a PR (not done yet)

1. Resolve section 4 with the user.
2. Wait for or re-check the gateway fixes in section 3, then do KNX and XMPP.
3. Go through sections 6–7 with the user. Hand the bug list to the gateway team.
4. Ask, then run `pnpm build:fast` and `pnpm lint:linkcheck`.
5. Remove `rpc-handoff/` from the branch, rebase or squash as the user wants, and open the PR only with permission.
