# RPC spec: OPC-UA, Socket and XMPP connectors (HEAD, compared with `8c64fa35^`)

Relevant commits: `e78e8f11` (OPC-UA), `736305c0` (Socket), `d5bb70c7` (XMPP), plus the shared commits `60cdfe3c`, `838dfdb2` and `0aa4bb96`.

**Path abbreviations** (relative to the gateway repo root):

| Abbreviation | File |
|---|---|
| `opc` | `thingsboard_gateway/connectors/opcua/opcua_connector.py` |
| `opc-dev` | `thingsboard_gateway/connectors/opcua/device.py` |
| `sock` | `thingsboard_gateway/connectors/socket/socket_connector.py` |
| `sock-const` | `thingsboard_gateway/connectors/socket/constants.py` |
| `xmpp` | `thingsboard_gateway/connectors/xmpp/xmpp_connector.py` |
| `req` | `thingsboard_gateway/gateway/entities/rpc_request.py` |
| `resp` | `thingsboard_gateway/gateway/entities/rpc_response.py` |
| `gw` | `thingsboard_gateway/gateway/tb_gateway_service.py` |
| `const` | `thingsboard_gateway/gateway/constants.py` |
| `util` | `thingsboard_gateway/tb_utility/tb_utility.py` |
| `X@old` | the same file at `8c64fa35^` |

## 0. Shared facts these connectors depend on

- **Classification order** is gateway → connector → reserved → device (`req:76-86`).
  - Connector RPC: the part of the method before the first `_` is a key of `DEFAULT_CONNECTORS`, i.e. `opcua`, `socket`, `xmpp`, … (`req:101-107`, `const:129-146`). This applies even when the RPC is addressed to a device.
  - Reserved RPC: `method.lower() == 'get'`, or `method.lower() == 'set'` together with a `device` (`req:110-115`).
  - The original casing is kept in `method_name` (`req:163`).
- **Connector RPC needs `params` to be a JSON object.** `ConnectorRPCRequest` calls `params.get('value')` and `params.get('deviceName')` (`req:141-142`). If `params` is a string, the request object cannot be built; the gateway only logs "Error while processing RPC request" and sends no reply (`gw:1663-1664`).
  - The connector part is `method.split('_', 1)` (`req:138`), so `opcua_my_method` gives `my_method`.
  - Only the **first** connector of that type handles it (`gw:1674-1675`).
- **Timeout**: `rpc_request.timeout` is the top-level `timeout` of the incoming message, default `RPC_DEFAULT_TIMEOUT = 5` seconds (`req:59`, `const:115`).
  - A device or reserved RPC that is not dispatched within that time is answered with `{"error":"Request timeout", "code": 408}` (`gw:1688-1692`).
- **Response**: the connector returns an `RPCResponse`.
  - Its `message` is `{"result": <msg>}` from `set_message` or `{"error": <msg>}` from `set_error_msg` (`resp:23-27`).
  - The gateway runs `dumps(message)` and sends that dict to ThingsBoard unchanged. Device and reserved RPCs go via `gw_send_rpc_reply` (`gw:1716-1718`, `gw:1855-1856`); connector RPCs go via `send_rpc_reply` (`gw:1658-1662`, `gw:1860-1862`).
  - None of these three connectors adds `success` or `code` keys.

---

## 1. OPC-UA

### 1a. RPC to connector
- **Method**: `opcua_<methodName>`. `params` must be an object; the optional key `arguments` is a list of `{"value": …}` items. Only `value` is read; a missing `arguments` key means no arguments (`opc:1430-1431`, `const:116`).
- **Execution**: the method is called on **every** device of the connector (`opc:1434`). The call is `__call_method(device.path, method_name, args)`:
  - It resolves the device node from the root (`root.get_child(device.path)`).
  - It calls the method id `"<deviceNodeNamespaceIndex>:<methodName>"` (`opc:1683-1685`).
  - So the OPC-UA method must be a child of the device node, in the device node's namespace.
- `deviceName` in `params` does not limit which devices are targeted. It is only copied into the response object (`opc:1428`).

### 1b. Reserved `get` / `set`
Device lookup is by name. If the device is unknown, the response is the error `Device <name> not found for RPC request` (`opc:1517-1522`). Parameters are parsed by `__parse_reserved_rpc_params` (`opc:1560-1589`); the logic was moved unchanged from the deleted `opcua/entities/rpc_request.py@old:109-137`.

**`get`** (exact lowercase method name):
- `params` must be a string. Trailing characters `' ;\t\n\r'` are stripped (`opc:1562-1564`).

**`set`** (exact lowercase method name), used only when `params` is a string (`opc:1565`):
- **NodeId form.** The NodeId is the first match of `r"(ns=\d+;[isgb]=[^;\s}]+)(?=;|\s|$)"` (`opc:1593`).
  - The code assumes it is at the **start** of `params`: `value = params[len(ident):]` (`opc:1571`).
  - Delimiter: the first entry of `RPC_SET_SPLIT_PATTERNS = ["; ", ";=", "=", " "]` (`opc:91`) that occurs anywhere in `params`.
  - Value: `re.sub(r"[;\s]+$", "", value.split(delimiter)[-1]).strip(' ;')` (`opc:1572-1574`).
  - Because the NodeId itself contains `=`, the delimiter resolves to `=` unless `"; "` or `";="` is present.
- **Key/path form** (no NodeId):
  - Delimiter: the first pattern from the same list found in `params`.
  - The string is split on it and empty parts are dropped. **Exactly 2 parts** are required: `<key-or-path>` and `<value>`. Trailing `;` and whitespace are stripped from the value (`opc:1577-1589`).
  - If there is no delimiter, or the part count is not 2, nothing is parsed (see open question OPC-UA 1).

**Target resolution** (`opc:1526-1539`):
- If `params` matches `r"(ns=\d+;[isgb]=[^}]+)"` at the start (`opc:1737`), it is used as a NodeId string.
- Otherwise it is matched against the configured `attributes`/`timeseries` key (`opc-dev:128-135`, filled from `key` at `opc:1066`).
- Otherwise a node path search runs (`opc:1295-1332`):
  - Only the **last segment** is used. If the string contains `Root.`, segments are split on `.`; otherwise on the literal `\.`.
  - That segment is searched as a child browse name under the device node, with a fallback to cached nodes of other devices (`find_foreign_nodes=True`).
  - The search has a fixed 10 s timeout (`opc:1316`).

**Value typing for `set`** (`opc:1614-1660`):
- The value is first written as the parsed **string**.
- On `BadWriteNotSupported` or `BadTypeMismatch`, the node's variant type is read and the value is cast:
  - `"true"`/`"false"` (case-insensitive) → bool;
  - contains `.` → float;
  - otherwise int;
  - if the cast fails → stays a string.
- It is then rewritten as `ua.DataValue(ua.Variant(value, variant_type))`.
- The response echoes the written value (string or cast). It is not a read-back.

### 1c. Per-device RPCs from config
- **Config**: `mapping[].rpc_methods[]`. `method` is matched exactly and case-sensitively against the RPC method (`opc:1478`, `opc-dev:171-175`). The same name is called as the OPC-UA method on the device node (`opc:1495`, `opc:1683-1685`).
- **Arguments** (`opc-dev:177-213`), with `params` taken as the request arguments (`opc:1485-1486`):
  - **Config `arguments` empty or absent**:
    - `params` null → `[]`;
    - `params` a list → used as is;
    - anything else → wrapped as `[params]`.
  - **Config `arguments` non-empty**: the defaults are `[a['value'] for a in arguments if a.get('value')]` (falsy values are dropped).
    - `params` truthy and not a list → error `The arguments must be specified in the square quotes []`.
    - `params` a non-empty list with the same length as the config `arguments` → `params` are used.
    - Some defaults exist but fewer than the config `arguments` → `You must either define values for arguments in config or along with rpc request`.
    - `params` a non-empty list of a different length, or no defaults and `params` is null → `Expected {N} arguments, but got {M}` (`opc-dev:210`).
    - Otherwise (falsy `params`, e.g. `[]`, `{}` or `""`) → the config defaults are used.
  - `arguments[].type` is **not read** by the connector. Only the backward-compatibility adapter generates it (`opcua/backward_compatibility_adapter.py:87-97`).

### 1d. Unknown method or bad params
| Situation | Response |
|---|---|
| Device RPC not in `rpc_methods` (`opc:1479-1483`) | `{"error": "Requested rpc method is not found in config"}` |
| `Get`, `SET` or other casing (reserved by the gateway, but not equal to `get`/`set`) (`opc:1606-1608`) | `{"result": {"response": "Unsupported function code in RPC request."}}` |
| Non-string `params` for `get` | `{"error": "Failed to process server side rpc request: <e>"}` (`opc:1420-1424`), e.g. `'NoneType' object has no attribute 'rstrip'` |
| `set` value cannot be parsed | see open question OPC-UA 1 |

### 2. Examples (device "Demo Device" from the committed `config/opcua.json`)
```json
{"method": "get", "params": "temperature"}
{"method": "get", "params": "ns=2;i=5"}
{"method": "get", "params": "Temperature"}
{"method": "get", "params": "Root\\.Objects\\.MyObject\\.Temperature"}
{"method": "set", "params": "relay true"}
{"method": "set", "params": "temperature=25.5"}
{"method": "set", "params": "temperature; 25.5"}
{"method": "set", "params": "temperature;=25.5"}
{"method": "set", "params": "ns=2;i=5 25"}
{"method": "set", "params": "ns=2;s=Relay; true"}
{"method": "multiply", "params": [3, 5]}
{"method": "multiply"}
{"method": "get_relay"}
{"method": "set_relay", "params": [true]}
{"method": "opcua_multiply", "params": {"arguments": [{"value": 3}, {"value": 5}]}}
```
- `get` with `"Temperature"` or the `Root\\.…` path is resolved by searching for the last segment `Temperature`.
- `{"method": "multiply"}` uses the config defaults `[2, 4]`.
- Forms that do **not** work:
  - `ns=2;i=5=25`: the NodeId regex swallows `=25`.
  - `temperature;25`: no pattern from the list matches.
  - `Message hello world`: produces 3 parts. Use `Message=hello world` instead.
  - String NodeIds that contain whitespace, `;` or `}`.

### 3. Responses
| Case | JSON sent to ThingsBoard | Source |
|---|---|---|
| Reserved get, OK | `{"result": {"value": <read value>}}` | `opc:1667`, `opc:1552` |
| Reserved set, OK | `{"result": {"value": <written value>}}` | `opc:1633`, `opc:1552` |
| Read or write failed | `{"result": {"error": "<str(e)>"}}`, or `"Could not find identifier in string <path>"` | `opc:1635-1644`, `opc:1669-1677` |
| Node not found by key or path, then `set` | `{"result": {"error": "'NoneType' object has no attribute 'write_value'"}}` | `opc:1618-1625` |
| Node not found by key or path, then `get` | `{"result": {"error": …}}` with the text from asyncua `get_node(None)` (not verified: asyncua not installed) | |
| Exception inside reserved processing | `{"result": {"response": {"error": "<repr(e)>"}}}` | `opc:1609-1612` |
| Device RPC, OK | `{"result": {"result": <method return>}}` | `opc:1685`, `opc:1505` |
| Device RPC, method call failed | `{"result": {"error": "<str(e)>"}}` | `opc:1687-1691` |
| Device or reserved RPC timed out | `{"error": "Failed to process rpc request for <device>, timeout has been reached"}` | `opc:1499`, `opc:1546` |
| Device not found | `{"error": "Device <name> not found for RPC request"}` | `opc:1473`, `opc:1519` |
| Argument errors | `{"error": "<message from 1c>"}` | `opc:1487-1491` |
| Connector RPC | `{"result": [ {"result": <ret>, "device_name": "<dev>"} \| {"error": "<str(e)>", "device_name": "<dev>"} \| {"error": "Timeout rpc has been reached for <dev>"} , … ]}` | `opc:1440-1454` |
| Any other exception | `{"error": "Failed to process server side rpc request: <e>"}` | `opc:1421` |
| Invalid RPC type (not reachable in practice) | `{"error": "Invalid RPC type request: <request>"}` | `opc:1415` |

**Timeouts:**
- Each read, write or method call waits up to `rpc_request.timeout` (5 s by default), polling every 0.2 s, then cancels (`opc:1458-1466`).
- A path lookup adds up to 10 s before that window starts (`opc:1316`).
- For connector RPC, the timeout applies **per device, one after another**, so the total can be N × timeout.

### 4. Config keys read for RPC
- `mapping[].rpc_methods` (default `[]`), with `.method`, `.arguments` (default `[]`) and `.arguments[].value`.
- `mapping[].attributes[].key` and `mapping[].timeseries[].key`, used as names for reserved get/set.
- The device node (from `deviceNodePattern`), which is where methods are called.
- There is no RPC timeout key in the config.

### 5. Changes vs `8c64fa35^`
- **REMOVED**: `opcua/entities/rpc_request.py` (`OpcUaRpcRequest`, `OpcUaRpcType`). The connector now takes the shared request objects and returns `RPCResponse`. It no longer calls `send_rpc_reply` itself (before: `opc@old:1442,1462,1469,1478,1497,1504,1512,1522,1546,1553`).
- **FIXED**: duplicate replies. Before, the gateway also sent `dumps(result)` with `success=False` whenever the returned dict had an `error` key (`gw@old:1697-1699`).
- **CHANGED, connector RPC response**: was a bare list `[…]` (old path: `gw@old:1672`, content sent raw). Now it is `{"result": […]}`.
- **CHANGED, connector RPC `arguments`**: now optional. Before, a missing key gave `{"error": "KeyError('arguments')", "success": false}` (`opcua/entities/rpc_request.py@old:105`, `opc@old:1418`).
- **CHANGED, connector RPC per-device exception**: now added to the list as `{"error", "device_name"}`. Before, a separate reply was sent (`opc@old:1442`).
- **CHANGED, error shapes for device and reserved RPCs**:
  - Device not found: was `{"result": {"error": "Device not found"}}`, now `{"error": "Device <name> not found for RPC request"}`.
  - Method not in config: was `{"result": {"error": …}}`, now `{"error": …}`.
  - Argument errors: were `{"result": "<msg>"}`, now `{"error": "<msg>"}`.
  - Timeout: was `{"result": {"error": "Timeout rpc has been reached for <dev>"}}`, now `{"error": "Failed to process rpc request for <dev>, timeout has been reached"}`.
  - Top-level exception: was `{"error": "<repr>", "success": false}`, now `{"error": "Failed to process server side rpc request: <e>"}`.
- **FIXED, device not found for device RPC**: before, `device.config` was read before the None check and raised `AttributeError` (`opc@old:1458-1459`).
- **FIXED, config `arguments` empty**: scalar `params` are now wrapped in a list, and null gives `[]` (`opc-dev:185-190`). Before, `params` was unpacked as is with `*arguments` (`opc-dev@old:186-187`): null gave a TypeError, and a string was split into characters.
- **UNCHANGED**:
  - The reserved get/set grammar and `RPC_SET_SPLIT_PATTERNS`.
  - Success shapes `{"result": {"value"…}}` and `{"result": {"result"…}}`.
  - Default timeout of 5 s (`opcua/entities/rpc_request.py@old:42`).
  - Case-sensitive `get`/`set`.

---

## 2. Socket

### 1a. RPC to connector
Any `socket_<x>` gets `{"error": "RPC To Connector not implemented for Socket connector"}` (`sock:444-447`). If `params` is a string, as in the old `socket_set` format, no reply is sent at all (see section 0).

### 1b. Reserved RPC
- Only `set` (exact lowercase). Anything else, including `get`, `Set` and `SET`, gets ``{"error": "Only `set` method is supported"}`` (`sock:452-454`).
- Schema, verbatim (`sock-const:15`): `^address=(?P<address>.+?);port=(?P<port>\d+);encoding=(?P<encoding>.+?);value=(?P<value>.*);$`
- Expected-schema string (`sock-const:16`): `set address=<address>;port=<port>;encoding=<encoding>;value=<value>;`
- Matched with `re.match`, so the string is anchored at the start (`sock:456-458`).
  - The order is fixed and all four keys are required.
  - A trailing `;` is required; no surrounding whitespace is allowed.
  - `value` may contain `;` (greedy match).
  - `port` must be digits only.
- **`encoding` is captured but never used** (`sock:463-464`).
- The device the RPC was sent to is ignored; the target comes from `address` and `port`.
- The value is sent as a string (see "Write path" below).
- Schema mismatch error (`sock:460`): `The requested RPC either does not match with the schema set address=<address>;port=<port>;encoding=<encoding>;value=<value>; or incorrect value/values provided`
- Non-string `params`: `{"error": "Failed to process RPC with error: <e>"}` (`sock:437-442`), where `<e>` is the TypeError raised by `re.match`.

### 1c. Per-device RPCs from config
- **Matching**: `devices[].serverSideRpc[].methodRPC` must equal the method exactly (`sock:506-513`). The device is found by `deviceName` in `devices` (`sock:499-504`).
- **Payload**: `params` is written raw (`sock:491`).
  - `params` null → `{"error": "Nothing to write. Params are empty."}` (`sock:485-487`).
- **Target**: `devices[].address`, split on `:` (`sock:489`). The connector overwrites this field at runtime with the last client `ip:port` it received data from (`sock:255`).

**Write path** (`sock:515-522`, `sock:385-406`):
- **TCP, with an active inbound connection from exactly (`address`, `port`)**: the payload is sent as `bytes(value, encoding='utf-8')` and the call returns `'ok'`.
- **TCP, no such connection**: a new outbound connection is opened and `sendall(value)` is called with the raw value.
  - On `ConnectionRefusedError`, the exception object itself is returned.
- **UDP**: `sendto(value)` is called with the raw value; it returns nothing.

### 1d. Errors
- `{"error": "Device <name> not found"}` (`sock:477`). Only reachable when the name is empty; see open questions.
- `{"error": "RPC method <method> config not found"}` (`sock:482`).
- Every exception: `{"error": "Failed to process RPC with error: <e>"}` (`sock:438`).
- `{"error": "Invalid RPC type request: <request>"}` (`sock:435`).

### 2. Examples (committed `config/socket.json`)
```json
{"method": "set", "params": "address=192.168.1.10;port=50001;encoding=utf-8;value=Hello;"}
{"method": "rpcMethod1", "params": "Hello"}
{"method": "socket_anything", "params": {}}
```

### 3. Responses
| Case | JSON sent to ThingsBoard |
|---|---|
| Writer returned `'ok'` (TCP) | `{"result": "ok"}` (`sock:468`, `sock:495`) |
| Writer returned `None` (UDP only) | `{"result": "Success"}` (`sock:466`, `sock:493`); not reachable in practice, see open questions |
| All errors | `{"error": …}` as listed above |

There is no connector-level timeout. The outbound TCP `connect()` has no timeout set (`sock:392-393`).

### 4. Config keys read for RPC
- `socket.type` (default `"TCP"`) (`sock:78`).
- `devices[].deviceName`.
- `devices[].serverSideRpc[].methodRPC`.
- `devices[].address` (overwritten at runtime).

**Not read**, although they appear in the shipped config: `serverSideRpc[].withResponse`, `serverSideRpc[].encoding`, `methodProcessing`, and `devices[].encoding` (for RPC).

### 5. Changes vs `8c64fa35^` (`sock@old:417-489`)
- **REMOVED**: connector-level `socket_set`.
  - Before, the device was taken from `params.split(' ')[0].split('=')[-1]` (`sock@old:426-430`).
  - Now it returns the "not implemented" error, or no reply if `params` is a string.
- **CHANGED, reserved `set` grammar**:
  - Before: any order of `k=v;` pairs, with only `address`, `port` and `value` required (`sock@old:438-451`).
  - Now: the strict regex above; `encoding=` and the trailing `;` are mandatory.
- **CHANGED, reserved `set` messages**:
  - Before: `{"result": "Not enough params"}`, `{"result": "Param \"port\" have to be int type"}`, `{"result": "<str(result)>"}` (`sock@old:455-463`).
  - Now: the new error and success strings above.
- **NEW**: non-`set` reserved methods get an explicit error. Before, they produced no reply.
- **CHANGED, device RPC**:
  - Before: `methodProcessing` (only `WRITE` wrote anything) and `withResponse` were required config keys. The payload was `bytes(str(params), <device encoding>)`. Matching compared `methodRPC` against **any** value in `data` (`sock@old:465-485`).
  - Now: exact method match; `params` written raw; a response is always sent.
- **NEW error strings**: device not found, config not found, empty params, generic.

---

## 3. XMPP

### 1a. RPC to connector
- `xmpp_<x>` returns `{"error": "Not implemented"}` (`xmpp:280-284`).
- The device lookup runs **first** (`xmpp:273-278`). Without a known `params.deviceName`, the reply is `{"error": "None device not found"}`, or `"<deviceName> device not found"` for an unknown name.

### 1b. Reserved RPC
- The method name is **not checked**. Every RPC the gateway classifies as reserved goes to `_process_reserved_rpc`: `get`, `set` or `GET` (any casing) (`xmpp:285-286`).
- Intended grammar (`__get_reserved_rpc_params`, `xmpp:346-362`):
  - Split on `;`; each piece must be exactly `key=value`, with both sides non-empty. Other pieces are skipped silently.
  - Any keys are allowed.
  - The resulting dict is sent to the device as JSON, all values as strings (`xmpp:342`).
- **As coded, it is broken.** It receives `rpc_request.params`, a string such as `"value=25;"`, but calls `.get('data', {})` on it (`xmpp:335`, `xmpp:349`). See open questions.
- Empty-params error: `{"error": "RPC params are empty, expected format: set value=<value>;"}` (`xmpp:337`).

### 1c. Per-device RPCs from config
- **Config**: `devices[].serverSideRpc[]` (default `[]`) (`xmpp:102`). `methodRPC` is matched exactly (`xmpp:325-330`).
- **`valueExpression` processing**:
  - Each `${tag}` is resolved by `TBUtility.get_values` against **`params`** with `value_type="string"` (`xmpp:311-314`).
  - It is replaced by the JSON-encoded value (`xmpp:316-318`).
  - The result is sent as an XMPP chat message to the device JID (`xmpp:242-245`).
- **Resolution rules** (`util:121-166`):
  - A top-level key of a `params` object is converted to a **string**, so after `dumps` it is quoted (`25` becomes `"25"`).
  - A nested JSONPath keeps its raw type.
  - An unresolved tag stays as the literal `${tag}`, quoted.
  - String `params` are first parsed with orjson `loads`. Invalid JSON raises, giving `Failed to process RPC with error: <orjson message>`.
- A missing `valueExpression` raises TypeError, which is returned through the generic error.

### 1d. Errors
| Case | Response | Source |
|---|---|---|
| Device not known yet | `{"error": "<device_name> device not found"}` | `xmpp:275` |
| Method not in config | `{"error": "Config for <method> not found"}` | `xmpp:306` |
| Any exception | `{"error": "Failed to process RPC with error: <e>"}` | `xmpp:295` |
| Invalid RPC type | `{"error": "Invalid RPC type request: <request>"}` | `xmpp:290` |

A device counts as known only after its first message has been converted (`xmpp:195-196`).

### 2. Examples
```json
{"method": "rpc1", "params": {"value": 25}}
{"method": "set", "params": "value=25;"}
{"method": "xmpp_anything", "params": {"deviceName": "<device name>"}}
```
- `rpc1` with the shipped `"valueExpression": "${params}"` sends the literal `"${params}"` (see open questions).
- With `"valueExpression": "{\"temp\": ${value}}"`, the device receives `{"temp": "25"}`.
- `set` with `"value=25;"`: intended result is that the device receives `{"value": "25"}`. The actual result today is `{"error": "Failed to process RPC with error: 'str' object has no attribute 'get'"}`.

### 3. Responses
- Success (device or reserved): `{"result": "success"}` (`xmpp:322`, `xmpp:343`). This means the message was handed to slixmpp; there is no device acknowledgement and no timeout.

### 4. Config keys read for RPC
- `devices[].jid`, `devices[].serverSideRpc[].methodRPC`, `devices[].serverSideRpc[].valueExpression`.
- `server.jid` (used as the sender).
- **Not read**: `withResponse`.

### 5. Changes vs `8c64fa35^` (`xmpp@old:265-354`)
- **CHANGED, device RPC success**:
  - Before: `{"success": true}`, only if `withResponse` was true (default true) (`xmpp@old:294-296`).
  - Now: always `{"result": "success"}`; `withResponse` is ignored.
- **CHANGED, `valueExpression` context**:
  - Before: resolved against the whole RPC `data` object with `value_type='params'` (raw values), so the shipped `${params}` worked (`xmpp@old:281-286`).
  - Now: resolved against `params` with string conversion.
- **CHANGED, reserved RPC**:
  - Before: only the exact `set` (`xmpp@old:302-308`). Success was `{"result": {"success": true}}`; the empty error was `{"set": "RPC params are empty, expected format: set value={value};"}`.
  - Now: any reserved method; `{"result": "success"}`; `{"error": "RPC params are empty, expected format: set value=<value>;"}`.
  - **REGRESSION**: parsing of string `params` now fails (see open questions).
- **NEW**: explicit errors for device not found, config not found, connector RPC and the generic case. Before, these were only logged and no reply was sent.

---

## 6. Open questions and likely bugs (from reading code; nothing was run)

**Shared (affects all three):**
1. **Device RPC method names can be captured as connector or gateway RPCs.** Before the refactor, any RPC with a `device` went to that device's connector (`gw@old:1640-1642`). Now a configured device RPC method whose name has the form `<connectorType>_…` or `gateway_…`, or is one of `getTermInfo`, `sendCommand`, `getCommandStatus`, `terminateCommand`, is classified as a connector or gateway RPC (`req:46`, `req:76-107`).
2. **A non-JSON-serializable message can stop all device RPC processing.** `dumps(response.message)` at `gw:1718` is only protected by `except (TimeoutError, Empty)` (`gw:1684-1720`). If it raises, the single RPC-to-devices thread (`gw:214-216`) would stop. Candidates:
   - OPC-UA `get` or method results of types such as datetime, LocalizedText or bytes;
   - the Socket `ConnectionRefusedError` object returned at `sock:399`.

   Before the refactor, serialization happened inside a try block (`__send_rpc_reply`).

**OPC-UA:**
1. **Unparseable `set` gives a raw AttributeError.** This happens with a non-string `params`, no delimiter, or not exactly 2 parts. `ReservedRPCRequest` has no `arguments` attribute (`req:159-164`), so the response is `{"result": {"response": {"error": "AttributeError(\"'ReservedRPCRequest' object has no attribute 'arguments'\")"}}}`. There is no schema or mismatch message like other connectors have. Before, `arguments` defaulted to `None`.
2. **OPC-UA operation errors arrive under `result`**, as `{"result": {"error": …}}`, while gateway-side errors use top-level `error`. This was already the case before.
3. **Falsy config argument values are dropped** (`0`, `false`, `""`) (`opc-dev:194`). This leads to wrong counts or the "You must either define…" error.
4. **Non-list `params` are wrapped as one argument when config `arguments` is empty.** This includes `{}` and `""` (`opc-dev:188-190`). If ThingsBoard sends `{}` for a parameterless call, the method receives one dict argument. Not verified what ThingsBoard sends.
5. **Dead code**: the `if not identifier` branch at `opc:1530-1533` cannot trigger and does not return.
6. **Only the first OPC-UA connector handles connector RPCs**, and it calls all of its devices (`gw:1674-1675`, `opc:1434`).

**Socket:**
1. **Outbound TCP and UDP writes always fail with string payloads.** Both pass a `str` to `sendall` or `sendto` (`sock:394`, `sock:405`), giving `Failed to process RPC with error: a bytes-like object is required, not 'str'`. So `"Success"` is effectively unreachable, and over TCP only an active inbound peer works.
   - For reserved `set`, this was already the case before.
   - For device RPC, it is a regression: the old code converted to bytes.
2. **Non-string device RPC `params` fail on the existing-connection path**: `bytes(dict, encoding=…)` raises TypeError "encoding without a string argument".
3. **Unknown device name gives an IndexError text.** `_find_device_config_by_name` checks `len(device_name)` instead of `len(device_list)` (`sock:501`), so the reply is `Failed to process RPC with error: tuple index out of range`.
4. **RPC before any data from the device** uses the config address: `"*:*"` gives "invalid literal for int()…", and a missing address gives `'address'`.
5. **The required `encoding` is ignored**; writes are always UTF-8 (`sock:388`).

**XMPP:**
1. **Reserved RPC is broken for normal string params** (`xmpp:335`, `xmpp:349`). It only works if `params` is `{"data": {"params": "value=25;"}}`.
2. **The shipped `config/xmpp.json` example no longer substitutes.** `"valueExpression": "${params}"` sends the literal `"${params}"`.
3. **Reserved `get` would send `params` to the device as a write** once parsing is fixed, because the method name is not checked.
4. **Connector RPC reports "device not found" instead of "Not implemented"** when `deviceName` is missing (`xmpp:273-284`).
