# RPC spec for the CAN, BLE and KNX connectors (HEAD `e4e27ef2`, compared with `8c64fa35^`)

## 0. Shared context (reference only)

- **How a request is classified** (`thingsboard_gateway/gateway/entities/rpc_request.py:76-119`). The checks run in this order: GATEWAY → CONNECTOR → RESERVED → DEVICE.
  - GATEWAY: the method is in `RESERVED_RPC_NAMES` (`:46`), or its first `_` segment is `gateway`.
  - CONNECTOR: the first `_` segment is a key of `DEFAULT_CONNECTORS` (`gateway/constants.py:129-146`, which includes `can`, `ble`, `knx`).
  - RESERVED: `method.lower()` is `get`, or `set` with a `device` key present (`:110-115`). So `GET`, `Set` and similar are reserved too.
- **Timeout**: `rpc_request.timeout = content.get('timeout', RPC_DEFAULT_TIMEOUT)` (`rpc_request.py:59`). This is the top-level `timeout` key of the incoming message, not `params`. `RPC_DEFAULT_TIMEOUT = 5` (`gateway/constants.py:115`).
  - Device and reserved RPCs wait in a gateway queue until the device is registered. If they wait longer than the timeout, the reply is `{"error":"Request timeout", "code": 408}` (`tb_gateway_service.py:1688-1693`).
- **Reply body** is `RPCResponse.message`: `{"result": <x>}` from `set_message` or `{"error": <str>}` from `set_error_msg` (`rpc_response.py:23-27`).
  - Device and reserved replies go through `gw_send_rpc_reply(device, id, <message dict>)` (`tb_gateway_service.py:1713-1718`, `1855-1856`).
  - The `result` unwrapping at `:1849-1850` only applies when `success_sent` is set, so it does not apply here.
  - Connector RPCs reply on the gateway device's RPC response topic (`:1646-1662`, `:1860-1862`).
- **Connector RPC parsing**: `ConnectorRPCRequest` splits `method` on the first `_`, so `can_foo` gives `method_name = "foo"`. It requires `params` to be a dict (`.get('value')`, `rpc_request.py:138-142`).

---

## CAN (`thingsboard_gateway/connectors/can/`)

### 1. RPC kinds and dispatch

Entry point: `server_side_rpc_handler` (`can_connector.py:153-176`). Every outcome goes through a single try/except.
- Success: `{"result": {"success": true}}` (`:172`).
- Any exception: `{"error": "Failed to process '<method_name>' RPC request: <exception text>"}` (`:175`).

**(a) RPC to connector.** Not supported. A method `can_<anything>` sent to the gateway device raises `"Connector RPC is not supported by CAN connector"` (`:164-165`).

**(b) Reserved RPC.** Only `set` is supported (case-insensitive, `:215`).
- `get` gives `"Reserved RPC '<method>' is not supported by CAN connector"` (`:216`).
- Schema and pattern, verbatim from `can/constants.py:15-21`:
  ```python
  RESERVED_SET_RPC_SCHEMA = ('nodeId=<id>;type=hex|string|bool|8int|8uint|16int|16uint|32int|32uint|64int|64uint|32float;'
                             '[byteorder=big|little;][isExtendedId=true|false;]value=<value>;')
  RESERVED_SET_RPC_PATTERN = (r'^nodeId=(?P<nodeId>0[xX][0-9A-Fa-f]+|[1-9]\d*|0);'
                              r'type=(?P<type>hex|string|bool|32float|(?P<intSize>8|16|32|64)(?P<unsigned>u?)int);'
                              r'(?:byteorder=(?P<byteorder>big|little);)?'
                              r'(?:isExtendedId=(?P<isExtendedId>[Tt]rue|[Ff]alse);)?'
                              r'value=(?P<value>.+?);?$')
  ```
- **Parsing rules** (`:211-252`):
  - Matching uses `re.fullmatch`. Field order is fixed: `nodeId` → `type` → [`byteorder`] → [`isExtendedId`] → `value`. Keys and enum values are case-sensitive, except that `isExtendedId` also accepts `True`/`False`. The trailing `;` is optional.
  - Checks run in this order:
    1. Device known (`:212-213`)
    2. Method is `set` (`:215`)
    3. Params are non-empty (`:218-219`)
    4. Regex match (`:221-223`)
    5. Cast (`:240-252`)
    6. Bus connected (`:255-256`)
    7. Convert (`:258-260`)
    8. Send (`:262-263`)
  - `nodeId` is `int(x, 0)`, so hex (`0x…`) or decimal (`:226`).
  - `isExtendedId` defaults to false (`:227`).
  - `byteorder` defaults to `"big"` (`:228`, `:61`).
- **Value typing**:
  - `hex`: the value goes to `dataInHex` and becomes `bytearray.fromhex` (`:229-231`; `bytes_can_downlink_converter.py:29-30`). `byteorder` is ignored.
  - `string`: sent as-is and ASCII-encoded (converter `:64-65`; `DEFAULT_ENCODING` at `:62`).
  - `bool`: `TBUtility.str_to_bool`, which accepts y/yes/t/true/on/1 and n/no/f/false/off/0 (`tb_utility.py:203-225`). It is sent as 1 byte 0/1 (converter `:54-55`).
  - `32float`: `float()`, then `struct.pack('>f'/'<f')` according to byteorder, giving 4 bytes (`:247-248`; converter `:63`).
  - `Nint` / `Nuint`: `int()` (base 10); `dataLength = N/8`, `dataSigned = not u` (`:233-235`, `:249-250`). The converter always encodes negative values as signed (`signed=(dataSigned or value < 0)`, converter `:59-61`). An out-of-range value fails in the converter.
  - A failed cast gives `"Invalid <type> value '<value>'"` (`:251-252`).
- The CAN frame is never FD (`isFd` defaults to false, `:340`), so the payload is limited to 8 bytes. Standard IDs must be `< 0x800` unless `isExtendedId=true` (python-can `message.py:255-259`). Violations give `"Failed to send RPC data to CAN bus"`.

**(c) Per-device configured RPCs** (`:178-209`, `:446-470`):
- Lookup is `device.serverSideRpc[]` by `method`, exact and case-sensitive (`:183`, `:470`).
- If no entry matches and `enableUnknownRpc` is false: `"No configuration for '<method>' RPC request"` (`:184-186`).
- Conversion config:
  - `overrideRpcConfig` false: the configured entry is used as-is (`:198-199`).
  - Unknown RPC (no entry, `enableUnknownRpc` true): the params dict itself is the config (`:201-204`).
  - Otherwise the configured entry is merged with params, params winning (`:206`, `:366-387`).
- `enableUnknownRpc: true` forces `overrideRpcConfig = true` (`:455-456`).
- Params must be a JSON object. A missing params becomes `{}` (`:189`).
- Converter params keys (`bytes_can_downlink_converter.py:27-70`):
  - `value`
  - `dataInHex`
  - variables used by `dataExpression`

**(d) Error strings.** Each is prefixed with `Failed to process '<method>' RPC request: `.
- `Device '<device>' not found` (`:181`, `:213`)
- `No configuration for '<method>' RPC request`
- `Reserved RPC '<method>' is not supported by CAN connector`
- `No 'params' found in reserved RPC request`
- `The requested RPC does not match with the schema: nodeId=<id>;type=hex|string|bool|8int|8uint|16int|16uint|32int|32uint|64int|64uint|32float;[byteorder=big|little;][isExtendedId=true|false;]value=<value>;`
- `Invalid <type> value '<value>'`
- `CAN bus is not connected` (`:256`)
- `Failed to convert RPC data to CAN payload` (`:260`)
- `Failed to send RPC data to CAN bus` (`:263`)
- `Connector RPC is not supported by CAN connector`
- `Invalid RPC type request: <str(rpc_request)>` (`:167`). This branch is unreachable in practice.

### 2. Examples

All successful requests reply `{"result": {"success": true}}`.

Reserved `set`:
```json
{"method": "set", "params": "nodeId=0x123;type=16uint;value=1500;"}
{"method": "set", "params": "nodeId=291;type=32float;byteorder=little;value=21.5;"}
{"method": "set", "params": "nodeId=0x18FF50E5;type=hex;isExtendedId=true;value=AABBCCDD;"}
{"method": "set", "params": "nodeId=5;type=bool;value=true;"}
{"method": "set", "params": "nodeId=5;type=string;value=Hello;"}
{"method": "set", "params": "nodeId=16;type=8int;value=-5"}
```

Error replies:
- Field order swapped, e.g. `"type=8int;nodeId=5;value=1;"`: `{"error": "Failed to process 'set' RPC request: The requested RPC does not match with the schema: nodeId=<id>;…value=<value>;"}`
- `{"method":"get","params":"…"}`: `{"error": "Failed to process 'get' RPC request: Reserved RPC 'get' is not supported by CAN connector"}`
- `{"method":"set","params":"nodeId=5;type=bool;value=maybe;"}`: `{"error": "Failed to process 'set' RPC request: Invalid bool value 'maybe'"}`

Configured RPCs. The device needs `overrideRpcConfig` false; see Q1 for why.
- Entry `{"method":"setLightLevel","nodeId":5,"dataLength":2,"dataByteorder":"little","dataBefore":"00AA"}`, request `{"method":"setLightLevel","params":{"value":70}}`. Payload: `00 AA 46 00`.
- Entry with `"dataExpression": "userSpeed if maxAllowedSpeed > userSpeed else maxAllowedSpeed"`, request `{"method":"setSpeed","params":{"userSpeed":120,"maxAllowedSpeed":100}}`.

Unknown RPC (`enableUnknownRpc: true`):
```json
{"method":"anyName","params":{"nodeId":291,"value":5,"dataLength":1}}
```

Connector RPC:
- `{"method":"can_status","params":{}}` replies `{"error": "Failed to process 'status' RPC request: Connector RPC is not supported by CAN connector"}`.

### 3. Response and timeout

- Success is always `{"result": {"success": true}}`. Error is always `{"error": "Failed to process '<method>' RPC request: <reason>"}`.
- The integration test asserts both shapes (`tests/integration/connectors/can/test_can_connector.py:516`, `:534-537`).
- There is no connector-level timeout; the send is synchronous. Only the gateway queue timeout (408) applies.

### 4. Config keys affecting RPC (device level)

Device level (`can_connector.py:446-470`):

| Key | Default | Cite |
|---|---|---|
| `enableUnknownRpc` | `false` | `:64`, `:453-454` |
| `overrideRpcConfig` | `false`; forced `true` when `enableUnknownRpc` | `:65`, `:455-456` |
| `strictEval` | `true`; injected into each RPC entry | `:66`, `:450`, `:469` |
| `serverSideRpc[]` | — | `:463-470` |
| `converters.downlink` | built-in `BytesCanDownlinkConverter` | `:466`, `:661-672` |

Per-entry keys (`:338-342`, `:366-381`, converter):

| Key | Default |
|---|---|
| `method` | — |
| `nodeId` | — |
| `isExtendedId` | `false` |
| `isFd` | `false` |
| `bitrateSwitch` | `false` |
| `dataLength` | `1` |
| `dataByteorder` | `"big"` |
| `dataSigned` | `false` |
| `dataExpression` | — |
| `dataEncoding` | `"ascii"` |
| `dataBefore` | — |
| `dataAfter` | — |
| `dataInHex` | — |

`response` is no longer read (see 5).

### 5. Changes vs `8c64fa35^`

- **NEW** — `can/constants.py`, a typed regex schema for reserved `set`, and a schema mismatch error.
  - **Before:** free `key=value` split with untyped string values (old `can_connector.py:129-145`). Reading the code, the old path passed `nodeId` as a `str` to python-can `Message(check=True)`, so the send would raise `TypeError` and reply `{"set": "Error during sending message to CANbus"}`. The old reserved `set` therefore could not succeed. This is static analysis only.
  - Old error replies were keyed by method name: `{"set": "RPC params are empty."}` (unreachable), `{"set": "Converted data is empty."}`, `{"set": "Error during sending message to CANbus"}`.
- **CHANGED** — Reserved detection is now case-insensitive. `get` is now reserved and rejected. The old CAN treated `get` as an ordinary configured method name, so a `serverSideRpc` entry named `get`, `set` or any case variant is now unreachable.
- **CHANGED** — Every device RPC now gets a reply.
  - **Before:** a reply `{"success": <bool>}` was sent only when `"response": true` was in the conversion config (old `:118-119`, `DEFAULT_RPC_RESPONSE_SEND_FLAG = False`).
- **REMOVED** — The `response` flag and `DEFAULT_RPC_RESPONSE_SEND_FLAG`.
- **CHANGED** — An unknown method now gets an error reply.
  - **Before:** warning log only, no reply (old `:80-83`).
- **NEW** — Device-not-found and bus-not-connected errors. An explicit error for `can_*` connector RPCs.
- **Unchanged** — The merge logic and the downlink converter.

### 6. Open questions (CAN)

1. **Possible bug (unchanged by the range).** With `overrideRpcConfig: true`, or `enableUnknownRpc: true` which forces it, `__merge_rpc_configs` (`:382-386`) copies keys with a `None` default only from params. Those keys are `dataExpression`, `dataBefore`, `dataAfter` and `dataInHex`. Their configured values are dropped, and `strictEval` is not carried over either.
   - The committed `config/can.json` device "Car" has `enableUnknownRpc: true`, so its `setSpeed` expression, `setLightLevel` `dataBefore` and `sendSameData` hex would be ignored unless sent in params.
2. Reserved `set` to a device with neither `serverSideRpc` nor `attributeUpdates`: no `downlink` converter is created (`:463-478`), so the reply is `"…: 'downlink'"` (KeyError text).
3. Non-string reserved params (a non-empty JSON object) make `re.fullmatch` raise `TypeError`, and the raw Python text appears in the error. `{}` gives `"No 'params' found…"`.
4. An unknown RPC without `nodeId` gives `KeyError 'nodeId'` from `send_data_to_bus` (`:338`; not caught there), so the reply reads `"…: 'nodeId'"`.
5. Reserved `set` cannot send FD frames (no `isFd`) and cannot choose the string encoding.

---

## BLE (`thingsboard_gateway/connectors/ble/`)

### 1. RPC kinds and dispatch

Entry point: `server_side_rpc_handler` (`ble_connector.py:286-309`).
- Success: `{"result": <coroutine result>}` (`:304`).
- Any exception: `{"error": "Failed to process '<method_name>' RPC request: <exception text>"}` (`:307`).

**(a) RPC to connector.** Not supported: `"Connector RPC is not supported by BLE connector"` (`:298-299`).

**(b) Reserved RPC** (`:322-335`). `set` (case-insensitive) means WRITE; anything else, in practice `get`, means READ.
- Verbatim from `ble/constants.py:15-23`:
  ```python
  RESERVED_GET_RPC_SCHEMA = 'characteristicUUID=<uuid>;'
  RESERVED_SET_RPC_SCHEMA = 'characteristicUUID=<uuid>;value=<value>;'
  RESERVED_GET_RPC_PATTERN = (r'^characteristicUUID=(?P<characteristicUUID>'
                              r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}'
                              r'|[0-9A-Fa-f]{8}|[0-9A-Fa-f]{4});?$')
  RESERVED_SET_RPC_PATTERN = (r'^characteristicUUID=(?P<characteristicUUID>'
                              r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}'
                              r'|[0-9A-Fa-f]{8}|[0-9A-Fa-f]{4});'
                              r'value=(?P<value>.+?);?$')
  ```
- `re.fullmatch` is used. Accepted UUID forms are a full 128-bit UUID, 8 hex digits, or 4 hex digits, in any case. The `;` after the UUID is optional for `get` and required for `set`.
- `value` is untyped. It is written as the UTF-8 bytes of the string (`:360`) and may contain `;` or `=`.
- Empty params give `"No 'params' found in reserved RPC request"` (`:324-325`).

**(c) Per-device configured RPCs** (`:311-320`):
- Lookup is the first `serverSideRpc[]` entry whose `methodRPC` equals the method, exact match. If none matches: `"No configuration for '<method>' RPC request"`.
- Keys read: `methodRPC`, `methodProcessing` (required), `characteristicUUID` (optional).
- `methodProcessing` is case-insensitive (`:350`):
  - `READ`: returns the characteristic decoded as UTF-8 (`:352-357`).
  - `WRITE`: writes `bytes(str(params), 'utf-8')`, i.e. the whole `params` value stringified (`:359-364`). Write is always with response (`device.py:328`), followed by a fixed 1 s sleep (`device.py:329`). Returns `'Ok'` (`device.py:330`).
  - `SCAN`: returns `device.scan_self(True)`, the GATT map string starting `MAP FOR <NAME>` (`:366-367`; `device.py:291-323`).
  - Anything else: `"Unsupported methodProcessing '<UPPERCASED>'"` (`:369`).
- `enableUnknownRpc`, `overrideRpcConfig`, `strictEval` and `withResponse` are **not read**.

**(d) Error strings.** Each is prefixed with `Failed to process '<method>' RPC request: `.
- `Device '<name>' not found` (`:282`)
- `No configuration for '<method>' RPC request`
- `No 'params' found in reserved RPC request`
- `The requested RPC does not match with the schema: characteristicUUID=<uuid>;value=<value>;` for `set`
- `The requested RPC does not match with the schema: characteristicUUID=<uuid>;` for `get` (`:329-331`)
- `RPC request timeout (<timeout>s)` (`:343`)
- `Device '<name>' is not connected` (`:347-348`)
- `Failed to read characteristic <uuid>` (`:354-355`; `device.read_char` swallows the bleak exception and returns `None`, `device.py:335-339`)
- On write failure, the bleak exception text (`:361-362`; `device.py:331-333`)
- `Unsupported methodProcessing '<X>'`
- `Connector RPC is not supported by BLE connector`
- `Invalid RPC type request: <rpc_request>` (unreachable in practice)

### 2. Examples

Reserved:
- `{"method":"get","params":"characteristicUUID=00002A00-0000-1000-8000-00805F9B34FB;"}` replies `{"result":"<decoded string>"}`.
- `{"method":"set","params":"characteristicUUID=226CAA55-6476-4566-7562-66734470666D;value=Hello;"}` replies `{"result":"Ok"}`.
- `{"method":"get","params":"characteristicUUID=2A00"}` matches the regex. Whether bleak resolves short UUIDs is unverified (Q2).
- `{"method":"set","params":"characteristicUUID=2A00value=1"}` replies `{"error":"Failed to process 'set' RPC request: The requested RPC does not match with the schema: characteristicUUID=<uuid>;value=<value>;"}`.

Configured, using the committed `config/ble.json`:
- `rpcMethod1` (read): `{"method":"rpcMethod1","params":{}}` replies `{"result":"<string>"}`.
- `rpcMethod2` (write): `{"method":"rpcMethod2","params":"Hello"}` writes `Hello` and replies `{"result":"Ok"}`. Note that `params:{"v":1}` would write `{'v': 1}`.
- `rpcMethod3` (scan): `{"method":"rpcMethod3","params":{}}` replies `{"result":"MAP FOR …"}`.

Connector RPC:
- `{"method":"ble_x","params":{}}` replies `{"error":"Failed to process 'x' RPC request: Connector RPC is not supported by BLE connector"}`.

### 3. Response and timeout

- Success: `{"result": "<string>"}`. The value is the UTF-8 read value, `"Ok"`, or the scan map.
- Error: `{"error": "Failed to process '<method>' RPC request: <reason>"}`.
- **Timeout**: the coroutine runs via `run_coroutine_threadsafe` and `future.result(rpc_request.timeout)`, default 5 s. When it expires the future is cancelled and the reply is `…: RPC request timeout (5s)` (`:337-343`).
- The WRITE path always includes a 1 s sleep, and SCAN reads every readable characteristic and descriptor, so SCAN may exceed 5 s.

### 4. Config keys affecting RPC

- Device level:
  - `serverSideRpc[]` (default `[]`, `device.py:96`), with entries `methodRPC`, `methodProcessing`, `characteristicUUID`.
  - `name` is used for device lookup (`ble_connector.py:279-284`).
- The device `timeout` (default 10000 ms, `device.py:50`) is **not** used for RPC. It is used for connect and for attribute-update writes (`ble_connector.py:275`).

### 5. Changes vs `8c64fa35^`

- **NEW** — `ble/constants.py` with regex schemas and a mismatch error.
  - **Before:** `key=value` split on `;`/`=`, no validation, and values containing `=` were silently dropped (old `ble_connector.py:315-336`).
- **CHANGED** — Reserved `get`/`set` matching is now case-insensitive.
  - **Before:** exact `('get','set')`.
- **CHANGED** — Success reply is now `{"result": <value>}`.
  - **Before:** the bare `str(result)` was the reply body, sent only if `withResponse` was true (old `:383-384`).
- **CHANGED** — Error reply is now `{"error": "Failed to process '<m>' RPC request: …"}`.
  - **Before:** `{"error": "<str(e)>", "success": false}`, `{"error": "RPC request timeout", "success": false}`, or `{"error": "<repr(e)>", "success": false}` (old `:303-313`, `:342-346`, `:386-390`).
- **REMOVED** — `withResponse` is no longer read; RPCs always reply and SCAN always returns the map. The committed `config/ble.json:56,62,68` still contains it.
- **NEW** — Error replies for unknown method, device not found and device not connected.
  - **Before:** unknown method and missing device were logged only.
- **NEW** — An explicit error for `ble_*` connector RPCs.
- **CHANGED** — A READ that fails now returns the error `Failed to read characteristic <uuid>`, and an empty read returns `""`.
  - **Before:** both returned `"None"` (old `:375`).
- **CHANGED** — The timeout is now thread-safe (`run_coroutine_threadsafe`). Its value source is unchanged (top-level `timeout`, default 5).
- **FIXED** (not RPC, commit `53a761fa`) — Attribute updates were never written because the coroutine was not awaited. Now they run with the device `timeout`.

### 6. Open questions (BLE)

1. A configured WRITE with `params` null or absent writes the literal string `None` (`:320`, `:360`). JSON object params are written as a Python repr. Is this intended?
2. Short 4- and 8-hex UUIDs pass the regex and are passed to bleak unchanged. Not checked whether bleak resolves them (bleak is not installed in the venv).
3. `read_char` hides the real bleak error, so the user only sees `Failed to read characteristic <uuid>`. The BLE RPC refactor plan for this is postponed.
4. A configured READ or WRITE without `characteristicUUID` passes `None` to bleak; the resulting error text depends on bleak.

---

## KNX (`thingsboard_gateway/connectors/knx/`)

There is **no `knx/constants.py` and no regex schema**. Reserved RPC parsing is still split-based.

### 1. RPC kinds and dispatch

Entry point: `server_side_rpc_handler` (`knx_connector.py:280-304`).

**(a) RPC to connector.** Not supported: `{"error": "Connector RPC is not supported by KNX connector"}` (`:290-294`). Unlike CAN and BLE, there is no `Failed to process…` prefix.

**(b) Reserved RPC** (`:306-321`):
- Parsing:
  - `params` (`None` becomes `''`) is split on `;`.
  - Each piece is split on `=` and must yield exactly 2 parts; otherwise it is skipped with a trace log. Both key and value must be non-empty.
  - `value` is popped and becomes the write value, as a string.
  - The remaining keys form the config: `groupAddress` (required), `dataType` (optional), `requestType`.
- **The method name is ignored.** In `__process_rpc_request` (`:369-379`), a write happens when `value` is present **or** `requestType == 'write'`. Otherwise `config['requestType']` is evaluated and a read happens.
  - A reserved `get` without `requestType=…` therefore fails with `KeyError` (Q2).
- There is no type conversion in the gateway. The value goes as-is to xknx `group_value_write(client, groupAddress, value, dataType)`, which uses the DPT transcoder from `dataType` (`:381-383`; xknx 4.0.0 `tools/group_communication.py:55-71`).

**(c) Configured RPCs.** Top-level connector `serverSideRpc[]` (`:389-398`), keys:
- `deviceNameFilter`: regex, `fullmatch` on device name
- `method`: exact match
- `groupAddress`: required
- `dataType`: optional
- `requestType`: `write` or anything else, which means read

The whole `params` value is the write value. A read happens only if `params` is `None` and `requestType != 'write'`. No match gives `"No RPC config found for method '<method>'"` (`:326-331`). `enableUnknownRpc`, `overrideRpcConfig` and `strictEval` are not read.

**(d) Error strings:**
- `No RPC config found for method '<method>'` (`:328`)
- `Failed to process rpc request for <device_name>, timeout has been reached` (`:355`)
- `Error processing RPC request: <e>` (`:364`). Examples: `Error processing RPC request: KNX bus is not connected` (`:370-371`), `Error processing RPC request: 'groupAddress'`, `Error processing RPC request: 'requestType'`, and xknx conversion errors.
- `Error processing RPC request <str(rpc_request)>: <e>` (`:300-304`), for example when `params` is not a string (`'dict' object has no attribute 'split'`) or `deviceNameFilter` is missing or invalid
- `Connector RPC is not supported by KNX connector`
- `Invalid RPC type request: <rpc_request>` (unreachable)

### 2. Examples

Reserved:
- `{"method":"set","params":"groupAddress=1/0/5;dataType=string;value=Hello;"}` replies `{"result":"Hello"}`.
- `{"method":"get","params":"groupAddress=1/0/5;dataType=string;requestType=read;"}` replies `{"result":"<str(value)>"}`.
- `{"method":"get","params":"groupAddress=1/0/5;dataType=string;"}` replies `{"error":"Error processing RPC request: 'requestType'"}`.

Configured, using the committed `config/knx.json`:
- `{"method":"set_name","params":"Kitchen"}` replies `{"result":"Kitchen"}`.
- `{"method":"get_name"}` with params absent or null reads `1/0/5`. With `"params":{}` it would attempt a write (Q1).

Connector RPC:
- `{"method":"knx_x","params":{}}` replies `{"error":"Connector RPC is not supported by KNX connector"}`.

### 3. Response and timeout

- Success: `{"result": "<str(value written)>"}` or `{"result": "<str(value read)>"}` (`:361`, `:383`, `:387`).
- Error: `{"error": "<message as above>"}`.
- **Timeout**: the task is polled every 0.2 s up to `rpc_request.timeout` (default 5 s), then cancelled, and the reply is `Failed to process rpc request for <device>, timeout has been reached` (`:335-358`).
- xknx `read_group_value` has its own 2.0 s reader timeout (xknx `core/value_reader.py:42`). On no response it returns `None`, so the reply is `{"result":"None"}`.

### 4. Config keys affecting RPC

Connector-level `serverSideRpc[]` with `deviceNameFilter`, `method`, `groupAddress`, `dataType`, `requestType` (`:373-376`, `:389-395`). There are no defaults other than `dataType` being `None`.

### 5. Changes vs `8c64fa35^`

- **CHANGED** — Success reply is now `{"result":"<value>"}`.
  - **Before:** `{"result": "{'value': '<v>'}"}`, a Python repr of a dict (old `__process_rpc`, `{'result': str(result.get('response'))}`).
- **CHANGED** — Errors are now `{"error": …}` replies.
  - **Before:**
    - Bus-not-connected and read/write errors were embedded in a "result" string, e.g. `{"result":"{'error': 'KNX bus is not connected'}"}`.
    - Exceptions were sent with `success_sent=False`, which made the reply body the bare JSON string of the exception text.
    - A timeout replied `{"result":"None"}` (old code built `{"error": "Timeout rpc has been reached for <device>"}` and then read its `response` key).
- **NEW** — Error replies for no matching config (old: log only), connector RPCs, and null reserved params (old: `AttributeError`, no reply).
- **CHANGED** — Reserved `get`/`set` matching is now case-insensitive via the gateway.
- **Unchanged** — Split-based reserved parsing (no regex or mismatch error), the `requestType` requirement, the read/write decision and the config matching logic. The timeout value source is also unchanged.
- **FIXED** (not RPC, commit `a3aa1f25`) — The uplink converter now skips group addresses that have no response yet (`knx_uplink_converter.py`).

### 6. Open questions (KNX)

1. Any non-null `params`, including `{}`, turns a `requestType: read` RPC into a write (`:376`). This is unchanged from before. What ThingsBoard sends when params are empty decides whether configured reads work.
2. Reserved `get` vs `set` is not distinguished: `get` needs `requestType=read` (or the call fails with `'requestType'`), and `get` with `value=` writes. Was KNX meant to get a regex schema like CAN, BLE, S7 and REST? It was not migrated.
3. **Bug (unchanged).** `__find_rpc_config_by_device_and_name` filters by device and by method independently (`:390-398`). It returns the first config with a matching method even if that config's `deviceNameFilter` does not match the device, as long as any config's filter matches.
4. A read with no bus response returns `{"result":"None"}` instead of an error.
5. `create_task` is called on the connector loop from the gateway's RPC thread (`:400-402`), which is not thread-safe. BLE uses `run_coroutine_threadsafe`. If the loop has stopped, every RPC times out.

---

## Cross-connector open questions (shared code, affects all three)

1. A device RPC whose method's first `_` segment is a connector type (`can_`, `ble_`, `knx_`, `modbus_`, …) or `gateway`, or whose method is `sendCommand`, `getTermInfo`, `getCommandStatus` or `terminateCommand`, is classified as connector or gateway RPC even when it carries `device` (`rpc_request.py:76-107`).
   - Its id becomes the MQTT client object (`tb_gateway_mqtt.py:166` passes `self`), so the reply likely fails.
   - Before the range, any request with `device` went to the device queue. Docs should warn that configured method names must avoid these prefixes.
2. The top-level `timeout` key: is it ever present in ThingsBoard gateway RPC messages? If not, the 5 s default always applies.
3. `_process_rpc_to_connector` returns a plain string when no connector of that type exists (`tb_gateway_service.py:1672`). The caller then sets `.to_connector_rpc` on it, so `can_*`, `ble_*` or `knx_*` sent with no such connector configured gets no reply.
