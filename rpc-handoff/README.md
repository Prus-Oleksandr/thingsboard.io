# RPC refactor → IoT Gateway docs update: handoff

The ThingsBoard IoT Gateway RPC processing was refactored, globally and in every connector. This folder describes the **current** behaviour of the code and how it differs from the docs, so the docs can be updated.

This folder is local working material. It is excluded from git via `.git/info/exclude`. Never commit it.

## 0. How to work with this folder

- **Source of truth is the code, not this folder.**
  - Gateway repo: `/home/oleksandr/Thingsboard_remote_work/thingsboard-gateway`, branch `master`, commit `e4e27ef2`. Add it to the session with `/add-dir`.
  - Every `file:line` reference in these files is relative to that repo and valid for `e4e27ef2`.
  - In that repo, `thingsboard_gateway/config/*.json` have uncommitted local test edits. Read shipped configs with `git show HEAD:<path>`.
- **These specs were produced by reading code; nothing was executed.** Before putting any request, response or error text into the docs, re-check it against the code.
- **Section 5 lists suspected code bugs.** Do not document that behaviour. Ask the user first: some of it will be fixed in code, and the docs should describe the fixed behaviour.
- **Gateway repo is read-only for you.** Do not modify it, do not run the gateway or its tests, and do not connect to any device or emulator.
- **Docs repo rules.** Follow this repo's `CLAUDE.md`, including the build policy: ask before `pnpm build:fast`. Work one page or connector at a time and show the diff to the user. Do not commit or push without explicit permission.
- **Language.** The docs content stays in English.

**Read order:** this file → `90-docs-map.md` (where RPC is documented today) → the spec file for the connector you are editing.

| File | Content |
|---|---|
| `10-gateway-core.md` | Classification and routing, response envelope, timeout, gateway service methods, remote shell, custom connector contract |
| `20-modbus-s7-bacnet.md` | Modbus, S7, BACnet |
| `30-mqtt-rest-request.md` | MQTT, REST, Request |
| `40-opcua-socket-xmpp.md` | OPC-UA, Socket, XMPP |
| `50-can-ble-knx.md` | CAN, BLE, KNX |
| `60-ftp-odbc-snmp-ocpp.md` | FTP, ODBC, SNMP, OCPP |
| `90-docs-map.md` | Every place in this docs repo that documents RPC, with line ranges and quotes; conventions; inconsistencies already present |

Each connector section in the spec files has the same structure:
1. Dispatch (connector RPC / reserved / device RPC)
2. Examples
3. Responses and errors
4. Config keys
5. Changes vs before
6. Open questions

**Commit range:** `8c64fa35^..e4e27ef2`. The core refactor is `60cdfe3c..0aa4bb96`. To list the RPC commits, run `git log --oneline -i --grep=rpc 8c64fa35^..e4e27ef2` in the gateway repo.

---

## 1. Cross-cutting changes (they affect every page)

### 1.1 How an incoming RPC is classified (`gateway/entities/rpc_request.py:76-119`)

The checks run in this order. The first match wins, and the presence of `device` is checked last:

1. **Gateway RPC.** The method starts with `gateway_`, or is one of the remote-shell methods `getTermInfo`, `sendCommand`, `getCommandStatus`, `terminateCommand`.
2. **Connector RPC.** The part of the method before the first `_` is a built-in connector type: `mqtt, modbus, opcua, ble, request, can, bacnet, odbc, rest, snmp, ftp, socket, xmpp, ocpp, knx, s7`. This prefix check is case-sensitive.
3. **Reserved RPC.** `method.lower()` is `get` or `set`.
4. **Device RPC.** Anything else that carries a `device`.

**What to document:**
- Configured device RPC method names must not be `get`/`set` in any case.
- They must not start with `<connectorType>_` or `gateway_`.
- They must not equal one of the four remote-shell names.

Such names are intercepted before they reach the device. Before the refactor, any request with `device` went straight to the device. See also section 5, item S1.

### 1.2 Response envelope (`gateway/entities/rpc_response.py`)

- Connector, reserved and device RPCs now reply with exactly one of:
  - `{"result": <X>}`
  - `{"error": "<message>"}`
- There are no `success` or `code` keys.
- The old shapes are gone, for example `{"result": {"value": X}}`, `{"result": {"error": …}}`, `{"success": true}` and bare lists.
- What `<X>` contains differs per connector. See each spec's "Responses" table.

There are exceptions to the envelope:
- **Gateway service methods** (`gateway_*`, shell) reply with the method's raw return value, e.g. `{"code":200,"resp":"pong"}`.
- **A device RPC that waited longer than its timeout** in the gateway queue gets `{"error":"Request timeout","code":408}`.
- **A device with no connector** gets a plain string: `Received RPC … but connector for the device … not found.`
- **An MQTT two-way RPC that timed out** gets `{"success": false}`.
- **The connector RPC result for OPC-UA and Modbus** is a per-device list: `{"result": [{"result": …, "device_name": …} | {"error": …, "device_name": …}, …]}`.

### 1.3 Timeout

- The default is **5 s** (`RPC_DEFAULT_TIMEOUT`). It is read only from a **top-level** `timeout` key of the incoming message (`rpc_request.py:59`).
  - Before the refactor it was read from `params.timeout`.
  - For connector RPC the conversion drops every key except `method` and `params`, so the timeout is always 5 s.
- Several connectors reuse it as the operation timeout: BLE, KNX, Modbus, OCPP, OPC-UA, SNMP.
- SNMP and OCPP use `min(<entry/param timeout>, request timeout)`. A configured timeout above 5 s therefore has no effect.
- BACnet reserved RPCs use a fixed 10 s.

### 1.4 Reserved get/set: general rules

- `params` must be a **string** (the debug terminal sends `get <params>` / `set <params>`).
- Most connectors now validate it with a regex. That brings these rules:
  - **Fixed key order.** Keys are case-sensitive and spaces are not allowed.
  - **Trailing `;`.** Required by some connectors (Modbus, MQTT, BACnet, S7, Socket), optional for others (REST, Request, FTP, ODBC, SNMP, OCPP, CAN, BLE).
  - **Extra keys are rejected.** The old split parsers accepted any `key=value;` pairs in any order. Several connectors used to let callers pass extra config keys this way (MQTT, REST, Request); that is gone.
  - **`value` comes last** and may contain `;` and `=`. Under the old parsers, values containing `=` were silently dropped.
- On a regex mismatch the error is one of two texts:
  - `The requested RPC does not match with the schema: <schema>` (most connectors)
  - `The requested RPC either does not match with the schema <schema> or incorrect value/values provided` (Modbus, MQTT, Socket)
- Some connectors still parse without a regex:
  - **OPC-UA:** unchanged free-form grammar.
  - **KNX:** split-based, no regex.
  - **XMPP:** split-based, currently broken.
- **Case.** `get`/`set` are detected case-insensitively, but connectors differ in how they treat `GET`/`Set`:
  - REST, Request, FTP, SNMP, OCPP, CAN and BLE use `.lower()`.
  - Modbus, MQTT and BACnet apply the SET schema to anything that is not exactly `get`.
  - S7 raises KeyError, and OPC-UA returns "Unsupported function code".
  - **Docs should show lowercase only.**

### 1.5 Connector RPC ("RPC to connector")

- **How it is sent.** It goes to the **gateway device** with `method = "<connectorType>_<name>"`. The method is split on the first `_` only, so `opcua_my_method` gives `my_method`.
- **`params` must be a JSON object.** If it is not, no reply is sent.
- **Only the first connector of that type** handles it. `connectorId` is ignored.
- **The reply** goes to the gateway device's RPC response topic.
- **No reply is sent** when there is no connector of that type, or when the method has no `_` (see section 5).

Support at HEAD:

| Connector | Connector RPC |
|---|---|
| Modbus | `modbus_<any>`: params = `{type, functionCode, objectsCount, address[, value]}`. Runs on **every** slave. Reads work; **writes are broken** (5: M1) |
| S7 | `s7_<any>`: params = `{deviceName, requestType: read\|write, type: tag\|data\|vm, <address keys>, value}` |
| OPC-UA | `opcua_<method>`: params `{"arguments":[{"value":…},…]}` (optional). Calls the OPC-UA method on **every** device node of the connector |
| MQTT | `mqtt_<any>`: params = a full `serverSideRpc`-style config (`requestTopicExpression`, `valueExpression`, optional `responseTopicExpression` + `responseTimeout` for two-way, …) |
| REST | `rest_<any>`: params = config (`requestUrlExpression`, `valueExpression`, `HTTPMethod`, `httpHeaders`, `timeout`, …) |
| Request | `request_<any>`: params = config, with defaults (`httpMethod` GET, `requestValueExpression` `${params}`, `responseTimeout` 1, `timeout` 0.5, `Content-Type: application/json`) |
| FTP | `ftp_read` `{"valueExpression":"<path>"}` and `ftp_write` `{"valueExpression":"<path>;<value>"}` |
| BACnet, XMPP, Socket | Explicit error: `"Not implemented"` / `"RPC To Connector not implemented for Socket connector"` |
| CAN, BLE, KNX, ODBC, SNMP, OCPP | Explicit error: `… Connector RPC is not supported by <X> connector` |

### 1.6 Config flags that are no longer read

- `withResponse` is no longer read by BLE, Socket, XMPP or OCPP. These connectors always reply now. The shipped example configs still contain it.
- CAN's `response` flag was removed; every CAN RPC now gets a reply.
- MQTT `serverSideRpc[].type` (`twoWay`/`oneWay`) is not read. Two-way is decided by `responseTopicExpression` + `responseTimeout`.
- Socket `serverSideRpc[].methodProcessing` and `serverSideRpc[].encoding` are not read.
- REST `responseTimeout` and `tries` are not read. Request reads `tries` but never uses it.

### 1.7 Custom connector API changed (`connectors/connector.py:67-69`)

- **Old:** `server_side_rpc_handler(content: dict)`. The connector called `gateway.send_rpc_reply(...)` itself.
- **New:** `server_side_rpc_handler(rpc_request)` receives one of these objects:
  - `DeviceRPCRequest`
  - `ReservedRPCRequest`
  - `ConnectorRPCRequest`
- The request fields are `id`, `method_name`, `params`, `device_name`, `timeout` (plus `connector_type` and `value` for connector requests).
- It **returns** an `RPCResponse(rpc_request.id, device=rpc_request.device_name)` after calling `set_message(x)` or `set_error_msg(msg)`. Returning `None` means the connector replies on its own.
- The pages `custom/methods-and-datatypes.mdx` and `custom/serial-connector.mdx` document the old dict API.
- The shipped `extensions/serial/custom_serial_connector.py` still uses the old dict API (see section 5, item S4).

---

## 2. Support matrix (HEAD)

| Connector | Reserved `get` | Reserved `set` | Device RPC config | Spec |
|---|---|---|---|---|
| Modbus | ✓ | ✓ | slave `rpc[]`, matched by `tag` | 20 |
| S7 | ✓ tag / data / vm | ✓ | device `serverSideRpc[]` by `method` | 20 |
| BACnet | ✓ | ✓ | device `serverSideRpc[]` by `method` (`requestTimeout` in seconds) | 20 |
| MQTT | ✓ two-way, fixed 5 s | ✓ one-way only | `serverSideRpc[]` (`deviceNameFilter`/`methodFilter`, regex `search`) | 30 |
| REST | ✓ | ✓ | `requestsMapping.serverSideRpc[]` (`fullmatch` filters) | 30 |
| Request | ✓ | ✓ | top-level `serverSideRpc[]` (`fullmatch` filters) | 30 |
| OPC-UA | ✓ (free-form, unchanged) | ✓ (free-form, unchanged) | `mapping[].rpc_methods[]` | 40 |
| Socket | ✗ explicit error | ✓ (now needs `encoding=`) | `devices[].serverSideRpc[].methodRPC` | 40 |
| XMPP | ✗ broken (5: X1) | ✗ broken (5: X1) | `devices[].serverSideRpc[]` (`methodRPC`, `valueExpression`) | 40 |
| CAN | ✗ explicit error | ✓ typed (new regex) | device `serverSideRpc[]` by `method` | 50 |
| BLE | ✓ | ✓ | device `serverSideRpc[].methodRPC` (`methodProcessing` read/write/scan) | 50 |
| KNX | ~ needs `requestType=read;` | ✓ (split-based, no regex) | connector-level `serverSideRpc[]` | 50 |
| FTP | ✓ | ✓ | `requestsMapping.serverSideRpc[]` | 60 |
| ODBC | ✓ (identical to set) | ✓ | `serverSideRpc.methods[]` | 60 |
| SNMP | ✓ | ✓ | `devices[].serverSideRpcRequests[]` | 60 |
| OCPP | ✓ → GetVariables | ✓ → SetVariables | `chargePoints[].serverSideRpc[]` (+ new `action`) | 60 |

### 2.1 Reserved params cheat-sheet (current code; verify against `connectors/<x>/constants.py`)

| Connector | `get <params>` | `set <params>` |
|---|---|---|
| Modbus | `type=<t>;functionCode=<1-4>;objectsCount=<n>;address=<n>;` | `type=<t>;functionCode=<5\|6\|15\|16>;objectsCount=<n>;address=<n>;value=<v>;` |
| S7 PLC | `type=tag;tag=<addr>;` · `type=data;dbNumber=<n>;start=<n>;dataType=<t>;size=<n>;[bit=<n>;]` | `type=tag;tag=<addr>;value=<v>;` · `type=data;dbNumber=<n>;start=<n>;dataType=<t>;[size=<n>;][bit=<n>;]value=<v>;` |
| S7 LOGO! | `type=vm;vmAddress=<addr>;` | `type=vm;vmAddress=<addr>;value=<v>;` |
| BACnet | `objectType=<t>;objectId=<n>;propertyId=<p>;` | `objectType=<t>;objectId=<n>;propertyId=<p>;[priority=<1-16>;]value=<v>;` |
| MQTT | `requestTopicExpression=<t>;responseTopicExpression=<t>;value=<v>;` | `requestTopicExpression=<t>;value=<v>;` |
| REST | `requestUrlExpression=<url>;[HTTPMethod=<m>;]` | `requestUrlExpression=<url>;[HTTPMethod=<m>;]value=<v>;` |
| Request | `requestUrlExpression=<url>;[httpMethod=<m>;]` | `requestUrlExpression=<url>;[httpMethod=<m>;]value=<v>;` |
| OPC-UA | `<key>` · `<NodeId>` · `<path>` | `<key\|NodeId\|path><delim><value>`, delim = first of `"; "`, `";="`, `"="`, `" "` |
| Socket | — | `address=<a>;port=<n>;encoding=<e>;value=<v>;` |
| CAN | — | `nodeId=<id>;type=<hex\|string\|bool\|8int…64uint\|32float>;[byteorder=big\|little;][isExtendedId=true\|false;]value=<v>;` |
| BLE | `characteristicUUID=<uuid>;` | `characteristicUUID=<uuid>;value=<v>;` |
| KNX | `groupAddress=<ga>;[dataType=<dpt>;]requestType=read;` (any order) | `groupAddress=<ga>;[dataType=<dpt>;]value=<v>;` (any order) |
| FTP | `filePath=<path>;` | `filePath=<path>;value=<v>;` |
| ODBC | `procedure_name=<n>\|query=<q>;[value=<a1>,<a2>;][with_result=true\|false;]` | same as get |
| SNMP | `oid=<oid>;[timeout=<s>;]` | `oid=<oid>;[type=<T>;][timeout=<s>;]value=<v>;` |
| OCPP | `component=<c>;[componentInstance=<i>;][evseId=<n>;]variable=<v>;[variableInstance=<i>;][timeout=<s>;]` | same + `value=<v>;` |

---

## 3. Docs vs code: reserved-RPC hub (`features/reserved-rpc.mdx`)

The line ranges are listed in `90-docs-map.md` §4.

| Tab | Docs today | Code now | Action |
|---|---|---|---|
| OPC-UA | `set ns=3;i=1001; value=23;` · responses `{"result": 25.34}`, `{"success": "true", "code": 200}` | With `"; "` as delimiter the value becomes the literal `value=23` (`opcua_connector.py:1568-1574`). The correct form is `set ns=3;i=1001; 23`. Responses: `{"result": {"value": <v>}}` | Fix syntax and responses (pre-existing error); align with `config/opc-ua.mdx`. The sample config there uses the old `"path"` key |
| Modbus | Schema ✓ · responses `{"result": {"value": 13}}` | `{"result": 13}`; set echoes the value string: `{"result": "80"}` | Fix responses; trailing `;` is required |
| MQTT | Schema ✓, no response examples | get: `value=` required, fixed 5 s, reply `{"result":"<payload string>"}`, timeout `{"success": false}`. set: one-way, `{"result":"success"}` | Add responses; mention the fixed timeout and that extra keys are no longer accepted. Check section 5 (MQ1) before showing `${params}` |
| BACnet | Responses `{"result": "30.5"}`, `{"result": "{\"status\":\"ok\"}"}` | Read `{"result": "<str>"}` ✓; set echoes `{"result": <value>}`; `priority` optional; `objectType` limited to 6 types; `propertyId` letters only | Fix the set response; list the limits |
| S7 | Schemas and responses ✓ | Same, plus the `bit` / `size` rules | Minor: `size` optional for set data, `bit` optional |
| REST | `get …;value=<value>;` · `set …;value=<value>;HTTPMethod=<method>;` | get takes **no** `value`. set order is `HTTPMethod` **before** `value`. The documented order silently puts `;HTTPMethod=…` into the body and sends GET | Fix both strings; set without `HTTPMethod` sends GET (5: R1) |
| Request | `set …;value=<value>;httpMethod=<method>;` | Order must be `httpMethod` before `value`. Result is the parsed JSON body: `{"result": {"light-level": 30}}`, not a JSON string | Fix order and responses |
| FTP | Read `{"result": 30}`, set `{"result": "{\"success\": true}"}` | Read `{"result": "<file content string>"}`. Set `{"result": "<value>"}` (if under 80 chars) or `{"result": true}` | Fix responses |
| OCPP | Order not stated, no responses | Fixed order (see 2.1); trailing `;` optional; reply is the OCPP CallResult as snake_case JSON, e.g. `{"result": {"get_variable_result": [...], "custom_data": null}}` | Add order and responses |
| Socket | `set address=<address>;port=<port>;value=<value>;` | `set address=<a>;port=<n>;encoding=<e>;value=<v>;` (encoding required but ignored); get gives an error | Fix schema; see 5: SO1 before promising it works |
| *missing* | No tabs for CAN, BLE, KNX, ODBC, SNMP, XMPP | CAN (set only), BLE, ODBC, SNMP: implemented with regex. KNX: split-based. XMPP: broken | Ask the user which tabs to add now. Suggested: CAN, BLE, ODBC, SNMP now; KNX and XMPP after the code is fixed |

## 4. Docs impact: other pages

- **`features/service-rpc-methods.mdx`**
  - `gateway_ping` and `gateway_devices` are unchanged.
  - **`gateway_restart` / `gateway_reboot`:** `params` is now **milliseconds**, not seconds; the default is 1000 and there is no minimum. The reply is the string `Success`, which currently fails to send (5: G1). **Hold until the user decides.**
  - `gateway_remove_provisioned_credentials`: responses ✓, but `params: {}` gets no reply (5: G3).
  - **Undocumented methods that exist:** `gateway_stats`, `gateway_version`, `gateway_update`, custom `gateway_<name>` methods from `/etc/thingsboard-gateway/rpc/*.py`, and the remote-shell methods. Ask the user whether to document them. `remote-configuration.mdx:426` already lists Stats, Update and Version.
  - "Every command prefixed with `gateway_`…" stays true. Add that these names also take priority over device RPC names (1.1).
- **Per-connector pages (`config/<x>.mdx`).** Use each spec's "Changes" section plus `90-docs-map.md` §5/§6. Main points:
  - **Response examples:** update to the new envelope on every page.
  - **`withResponse`:** remove from the BLE, Socket, XMPP and OCPP field tables, or mark it as ignored.
  - **CAN:** remove the `response` field. Configured method names `get`/`set` are now intercepted.
  - **MQTT:** the `type` field is not read; two-way needs `responseTopicExpression` + `responseTimeout` (ms). Recommend `${requestId}` in response topics.
  - **OCPP:** new optional `action` key. Payload keys are snake_case `ocpp.v21.call` fields; without `action` a DataTransfer is sent.
  - **BACnet:** `requestTimeout` is in **seconds** (the shipped config uses `10000`: 5: B1).
  - **S7:** "Connector RPC" is mentioned but has no example. Now it can be documented (1.5).
  - **REST vs Request:** reserved key spelling differs (`HTTPMethod` vs `httpMethod`). REST accepts both in config; reserved strings accept only their own spelling.
  - **Socket:** the `socket.mdx` "required parameters" text is wrong (see 3).
  - **KNX:** `knx.mdx:354` claims a built-in `set`. It exists (split-based), and `get` needs `requestType=read`.
  - **Modbus:** several docs bugs are listed in `90-docs-map.md` §6. Keep the anchor `#subsection-rpc-requests`: a redirect targets it.
- **`custom/methods-and-datatypes.mdx`, `custom/serial-connector.mdx`:** new connector RPC contract (1.7).
- **`reference/gateway-api/rpc.mdx`** is shared with CE/PE/PaaS. The MQTT wire format is unchanged, so no change should be needed. Do not edit it without asking.
- **Anchors used by other pages or redirects:** `service-rpc-methods/#gateway_remove_provisioned_credentials` (provisioning.mdx) and `config/modbus/#subsection-rpc-requests` (redirects.ts). Do not rename these headings.

## 5. Hold list: suspected code bugs (do not document as behaviour; ask the user)

All of these come from reading code and were not reproduced. "pre" means the bug predates the refactor.

**Gateway core** (`10-gateway-core.md` §6)
- **S1.** Child-device RPC named `gateway_*`, `<connectorType>_*`, `sendCommand`, `getTermInfo`, `getCommandStatus` or `terminateCommand` is executed at gateway or connector level, not on the device. The reply then fails, because the id is the MQTT client object.
- **S2.** "Connector of type X not found" is never sent (`tb_gateway_service.py:1668-1672`), so there is no reply.
- **S3.** The device-RPC thread only catches `TimeoutError`/`Empty` (`:1719`). A connector exception, a non-`RPCResponse` return, or a non-JSON-serializable result stops all later device RPCs.
- **S4.** `extensions/serial/custom_serial_connector.py`, the gRPC connector and `DummyCustomConnector` still use the old dict contract, which triggers S3.
- **S5.** `get` sent to the gateway device itself is classified as reserved with no device; it is re-queued in a busy loop for 5 s.
- **G1.** `gateway_restart`/`gateway_reboot` reply `'Success'`, which fails to publish because it is not JSON. The delay unit changed to milliseconds; the log line still says seconds.
- **G2.** Exceptions in gateway or connector RPC now produce no reply; before the refactor they replied with a 500.
- **G3.** `gateway_stats` and `gateway_remove_provisioned_credentials` with `params: {}` get no reply. It is not known what ThingsBoard sends when params are empty.

**Connectors**
- **M1.** Modbus connector-RPC writes: `int(dict)` raises TypeError, which is reported as a timeout.
- **M2.** Modbus: every operation error is reported as "timeout has been reached".
- **MQ1.** MQTT `${params}` in `valueExpression` now produces a Python repr, e.g. `"{'pin': 1}"`. The shipped config uses it.
- **MQ2.** MQTT topic placeholders: `${params.x}` no longer resolves; `${x}` does.
- **MQ3.** MQTT: a one-way RPC reports success even when the broker is disconnected (pre).
- **MQ4.** MQTT: a two-way connector RPC with `deviceName` is replied on the wrong topic.
- **S7a.** S7 per-type schema mismatch returns the text `cannot access local variable 'err_msg'` (`s7_connector.py:409`).
- **S7b.** S7 `GET`/`SET` in uppercase raise KeyError.
- **B1.** BACnet `requestTimeout` is in seconds, but the shipped `bacnet.json` uses `10000`.
- **B2.** BACnet: a bad `priority` returns an AttributeError text (pre).
- **X1.** XMPP reserved RPC is broken for string params (`xmpp_connector.py:335,349`).
- **X2.** XMPP: the shipped `${params}` `valueExpression` is no longer substituted.
- **SO1.** Socket outbound TCP/UDP writes pass `str` to `sendall`/`sendto`; only an active inbound TCP peer works.
- **SO2.** Socket: an unknown device name gives an IndexError text (`socket_connector.py:501`).
- **K1.** KNX was not migrated to a regex schema; `get` requires `requestType=read`.
- **K2.** KNX `{}` params turn a configured read into a write (pre).
- **K3.** KNX config lookup ignores `deviceNameFilter` per entry (pre).
- **C1.** CAN with `overrideRpcConfig`/`enableUnknownRpc` drops configured `dataExpression`, `dataBefore`, `dataAfter` and `dataInHex` (pre). The shipped `can.json` has `enableUnknownRpc: true`.
- **O1.** OPC-UA: an unparseable `set` returns a raw AttributeError instead of a schema message.
- **R1.** REST reserved `set` without `HTTPMethod` sends GET.
- **RQ1.** Request: the shipped `echo` entry lacks `requestValueExpression` (pre).
- **F1.** FTP: a configured RPC is a write only if the method name is exactly `write` (pre).
- **OD1.** ODBC: empty `serverSideRpc.methods` drops `enableUnknownRpc`/`overrideRpcConfig` (pre).
- **SN1.** SNMP `requestFilter` regex arguments are swapped (pre).
- **SN2.** SNMP: the shipped `multiSetData` entry has no `mappings` (pre).
