# RPC spec: MODBUS, S7, BACNET (HEAD `e4e27ef2`, compared against `8c64fa35^`)

From reading code and git history; nothing was run. Regex examples were checked by hand against the regexes (marked ✓). Items marked *suspected* come from tracing the code and were not confirmed at runtime.

## 0. Shared model (reference only, see 10-gateway-core.md)
- **Classification order** (`gateway/entities/rpc_request.py:76-119`):
  1. GATEWAY.
  2. CONNECTOR: the method's first `_` segment is in `DEFAULT_CONNECTORS` (`gateway/constants.py:129-146`; keys `modbus`, `s7`, `bacnet`).
  3. RESERVED: `method.lower()=='get'`, or `=='set'` when the message has a `device`.
  4. DEVICE: the message has a `device`.
- **Connector RPC addressing:**
  - The RPC goes to the gateway device itself, with `method = "<type>_<name>"`. It is split once on `_` (`rpc_request.py:138`), so `method_name` is everything after the first `_`.
  - `params` must be a JSON object: the code calls `.get('value')` (`:141`) and reads `deviceName` (`:142`).
  - Only the first connector of that type receives it (`tb_gateway_service.py:1666-1675`).
- **Timeout:** `rpc_request.timeout = content.get('timeout', RPC_DEFAULT_TIMEOUT)` (`rpc_request.py:59`). `RPC_DEFAULT_TIMEOUT = 5` (`gateway/constants.py:115`).
- **Reply envelope:**
  - `set_message(x)` → `{"result": x}`; `set_error_msg(m)` → `{"error": m}` (`rpc_response.py:23-27`).
  - The gateway runs `dumps(response.message)` and sends the parsed dict unchanged:
    - device/reserved replies: `tb_gateway_service.py:1716-1718` → `:1856`
    - connector replies: `:1651`, `:1659-1662` → `:1861`
  - The caller sees exactly `{"result": …}` or `{"error": "…"}`. These three connectors add no `success` or `code` keys.

---

## 1. MODBUS (`connectors/modbus/`)

### 1.1 Dispatch (`modbus_connector.py:531-550`)
**(a) RPC to connector**
- Method is `modbus_<anything>`. The suffix is not used, only logged (`:575`).
- `params` is used as the operation config: `type`, `functionCode`, `address`, `objectsCount`, plus `value` for writes (`:561-562`).
- It runs one after another on **every configured slave** (`:558-575`). `params.deviceName` is ignored for targeting.
- Each slave gets the request timeout (5 s) as its wait (`:564`).
- FC 1–4 read, FC 5/6/15/16 write (`:683-691`). **Writes are broken**, see 1.6 #1.

**(b) Reserved `get` / `set`**
- Regexes, verbatim (`constants.py:104-119`):
```
AVAILABLE_DATA_TYPES_REGEX = "string|bytes|bits|16int|16uint|16float|32int|32uint|32float|64int|64uint|64float"
GET_PATTERN_REGEX = (
    rf'^type=(?P<type>{AVAILABLE_DATA_TYPES_REGEX});'
    r'functionCode=(?P<functionCode>[1-4]);'
    r'objectsCount=(?P<objectsCount>\d+);'
    r'address=(?P<address>\d+);$'
)
SET_PATTERN_REGEX = (
    rf'^type=(?P<type>{AVAILABLE_DATA_TYPES_REGEX});'
    r'functionCode=(?P<functionCode>5|6|15|16);'
    r'objectsCount=(?P<objectsCount>\d+);'
    r'address=(?P<address>\d+);'
    r'value=(?P<value>.+);$'
)
GET_RPC_EXPECTED_SCHEMA = "get type=<type>;functionCode=<functionCode>;objectsCount=<objectsCount>;address=<address>;"
SET_RPC_EXPECTED_SCHEMA = "set type=<type>;functionCode=<functionCode>;objectsCount=<objectsCount>;address=<address>;value=<value>;"
```
- **Rules:**
  - Key order is fixed, every key is required, and each pair ends with `;`.
  - Nothing may follow `address=…;` (get) or the final `;` (set).
  - `value` is greedy: it runs to the last `;`, so it may contain `;`.
  - Pattern selection is exact: `method_name == 'get'` picks GET, **anything else** picks SET (`:623-626`).
- **Typing** (`:631-634`): `functionCode`, `objectsCount` and `address` become `int`. `type` and `value` stay strings.
- **Writing the value** (`bytes_modbus_downlink_converter.py:46-89`):
  - `*int`/`*uint` → `int(value)`; `*float` → `float(value)`; `string` → used as-is.
  - `bits` with `objectsCount=1` → `int(value)`, so it must be `0` or `1` (`:76-77`).
  - `bits` with `objectsCount>1` is broken (1.6 #4).
  - `bytes` passes the regex but the write converter has no handler (`:87-89`). The task then raises `Converted data is empty` (`modbus_connector.py:735-736`), which is reported as a timeout.
- **`objectsCount` must match the register width** (16-bit → 1, 32-bit → 2, 64-bit → 4). Otherwise only the first register is written (`downlink:52-53, 114-122`). FC 6 always writes one register (`modbus_connector.py:729-733`).

**(c) Device RPCs from config**
- Slave key `rpc` (`slave.py:99`, default `[]`).
- List form: entries matched by `"tag" == method` (`slave.py:329-331`).
- Dict form: keyed by method name (`slave.py:326-327`).
- Matching is exact and case-sensitive. The value written is TB `params` as-is (`modbus_connector.py:726`). Reads ignore `params`.

**(d) Unknown method / mismatch:** see the table in 1.3.

### 1.2 Examples
- **Reserved, sent to the device:**
  - `{"method":"get","params":"type=16int;functionCode=3;objectsCount=1;address=0;"}` ✓
  - `{"method":"get","params":"type=32float;functionCode=4;objectsCount=2;address=10;"}` ✓
  - `{"method":"get","params":"type=bits;functionCode=1;objectsCount=1;address=1;"}` ✓ → `{"result": true}` (`bitTargetType` defaults to bool, `bytes_modbus_uplink_converter.py:335-337`)
  - `{"method":"set","params":"type=16int;functionCode=6;objectsCount=1;address=0;value=123;"}` ✓ → `{"result": "123"}` (the value string is echoed back, `modbus_connector.py:749`)
  - `{"method":"set","params":"type=32float;functionCode=16;objectsCount=2;address=10;value=21.5;"}` ✓
  - `{"method":"set","params":"type=bits;functionCode=5;objectsCount=1;address=1;value=1;"}` ✓
  - `{"method":"set","params":"type=string;functionCode=16;objectsCount=2;address=0;value=abcd;"}` ✓
- **Device RPC** (committed `modbus.json` with `setRelay`/`getRelay`):
  - `{"method":"setRelay","params":1}` → `{"result": 1}`
  - `{"method":"getRelay","params":{}}` → `{"result": true}`
- **Connector RPC, sent to the gateway device:**
  - `{"method":"modbus_read","params":{"type":"16int","functionCode":3,"objectsCount":1,"address":0}}` → `{"result":[{"result":123,"device_name":"Demo Device"}, …]}`
  - Writes do not work at HEAD (1.6 #1).

### 1.3 Responses (`modbus_connector.py`)
| Case | Reply |
|---|---|
| reserved/device read OK | `{"result": <decoded value>}` (`:617`, `:667`) |
| reserved/device write OK | `{"result": <params / value string as sent>}` (`:749`) |
| read when slave not connected | `{"result": null}`, not an error (`:696-710`) |
| connector RPC | `{"result": [ {"result": <v>, "device_name": "<slave>"} \| {"error": "Timeout rpc has been reached for <slave>"} , … ]}` (`:569-577`) |
| empty params | `{"error": "No 'params' found in reserved RPC request '<method>'"}` (`:585`) |
| device not found | `"Device <device> not found in connector <connectorName>"` (`:591`, `:643`) |
| schema mismatch | `"The requested RPC either does not match with the schema <GET\|SET_RPC_EXPECTED_SCHEMA> or incorrect value/values provided"` (`:598`) |
| reserved timeout **or any error during the operation** | `"Failed to process reserved rpc request for <device>, timeout has been reached"` (`:610`) |
| device RPC not configured | `"RPC <method> method not found in config for <connectorName>."` (`:651`) |
| device RPC timeout **or any error during the operation** | `"Failed to process rpc request for <device> device, timeout has been reached"` (`:662`) |
| device RPC outer exception | `"An error occurred during task handling <e>"` (`:673`) |
| any other exception, e.g. non-string reserved params, list entry without `tag` | `"Failed to process RPC with error: <e>"` (`:546`) |

### 1.4 Config keys read by the code
- **Slave level:**
  - `rpc` (default `[]`)
  - `byteOrder`, `wordOrder` (default `"LITTLE"`, `slave.py:94-95`)
  - `repack` (default `false`, `:93`)
  - These apply to all RPC kinds (`modbus_connector.py:704-705`, `715-724`).
- **Per `rpc` entry:**
  - `tag`: the method name. It is also the fallback for `type` on writes (`:722`).
  - `type`: required for reads (`uplink:259`).
  - `functionCode`: required (`:684`).
  - `address`.
  - `objectsCount`: required for reads (`:698`). On writes it falls back to `registersCount` → `registerCount` → 1 (`:720`).
  - Read-only extras:
    - `divider`/`multiplier` (`uplink:228-231`)
    - `variants` (`:356-363`)
    - `bit` (`:331-333`)
    - `bitTargetType` (default `"bool"`, `:335`)
    - `round` (default 6, `:341`)
- **Timeout:** the request `timeout`, default 5 s (`:564`, `:606`, `:658`). There is no config key.
- There is **no** `withResponse` key in this connector.

### 1.5 Changes vs `8c64fa35^`
- **CHANGED, reply shape:**
  - Reserved/device success went from `{"result":{"value":X}}` to `{"result":X}` (old `modbus_connector.py:707`, `:649-651`).
  - Errors went from `{"result":{"error":…}}` (old `:645`, `:675`) or `{"error":…,"success":false}` (old mismatch path, old gateway `:1698-1699`) to `{"error":…}`.
  - Connector RPC went from a bare list `[…]` (old gateway `:1672`) to `{"result":[…]}`.
- **CHANGED, messages:**
  - Unknown device RPC: old `"Method not found for <method>"` → new `"RPC <method> method not found in config for <connectorName>."`.
  - Timeouts: old `"Timeout rpc has been reached for <device>"` → new messages in 1.3.
- **CHANGED, GET regex now ends with `$`.**
  - Old regex (no end anchor): `rf'^type=(?:{AVAILABLE_DATA_TYPES_REGEX});functionCode=[1-4];objectsCount=\d+;address=\d+;'` (old `constants.py:105`).
  - Old parsing also put every `key=value` pair in the string into the config (old `entities/rpc_request.py:140-155`). Trailing pairs such as `divider=10;` used to be accepted; now they are rejected.
  - The SET regex logic is unchanged (old `:106`). It now uses named groups instead of `split("value=")`.
- **REMOVED:**
  - Connector RPC to an ad-hoc device described by `host`/`port`/`unitId` in params (old `rpc_request.py:160-161`; old `modbus_connector.py:546`, `574-625`).
  - The `modbus/entities/rpc_request.py` entity was deleted.
- **CHANGED, worse error reporting:** errors during the operation used to come back as `{"error": str(e)}` (old `:716-719`, `728-736`). Now they are reported as timeouts (1.6 #2).
- **CHANGED:** connector method names may now contain more than one `_` (old `rpc_request.py:81` required exactly one).
- **FIXED:** device-not-found used to send an empty reply (old `:665`); it now returns an error.
- **FIXED (not RPC-specific, but it changes RPC results):** bit order of coils/discrete inputs on read (`uplink:284-291`) and on write (`downlink:104-109`). Commits `a85e8ef8`, `a4a2a412`.

### 1.6 Open questions / suspected bugs
1. **Connector-RPC writes are broken.** The whole `params` dict is passed as config (`:562`) and also used as the value (`data.params`, `:726`). Then `int(dict)` raises TypeError, which is reported as `"Timeout rpc has been reached for <slave>"`. The old code used `params.value` (old `rpc_request.py:112`, old `:760`).
2. `__wait_task_with_timeout` turns any exception raised in the task into `(False, None)` (`:484-492`). So "Device is not connected", conversion errors, `ModbusPDU response error`, and unsupported function code all appear as "timeout has been reached".
3. A read on a disconnected slave returns `{"result": null}` (`:696-710`). A write in the same state errors (`:738-740`).
4. Reserved `set` with `type=bits` and `objectsCount>1`:
   - The string is turned into `bytes(value)` and passed to `add_bits` (`downlink:70-71`).
   - pymodbus `pack_bitstring` (`pymodbus/pdu/pdu.py:163-169`) then either sets **all bits to 1** (length a multiple of 8) or raises TypeError.
   - This bug predates the range. Device RPC with a JSON list works (`:72-73`).
5. *Suspected:* FC 15 with `objectsCount=1`.
   - `value=0` becomes `b'\x00'` (`downlink:77`), which is wrapped as `[b'\x00']` (`slave.py:306-307`).
   - pymodbus treats that element as truthy, so the coil would be written ON.
6. *Suspected:* if a write returns something other than a `Write*Response` (e.g. an exception PDU), that object becomes the result (`:744-751`). It is likely not JSON-serializable (see X1).
7. `"GET"`/`"Get"` count as reserved at the gateway level, but the connector applies the SET regex to them and returns the mismatch error with the SET schema.

---

## 2. S7 (`connectors/s7/`)

### 2.1 Dispatch (`s7_connector.py:339-368`)
The device is always looked up first by `rpc_request.device_name` (`:343-348`). For connector RPC that name comes from `params.deviceName`.

**(a) RPC to connector**
- Method is `s7_<name>`. `<name>` only appears in messages.
- `params` is the full op config:
  - `deviceName`
  - `requestType`: `"read"` or `"write"`
  - `type`: `tag` / `data` / `vm`
  - address keys for that type
  - `value` for writes (`:354-359`, `:440-457`)

**(b) Reserved `get` / `set`**
- Regexes, verbatim (`constants.py:25-51`):
```
RESERVED_RPC_TYPE_PATTERN = r'^type=(?P<type>tag|data|vm);'
RESERVED_GET_TAG_RPC_PATTERN = r'^type=tag;tag=(?P<tag>[^;]+);$'
RESERVED_SET_TAG_RPC_PATTERN = r'^type=tag;tag=(?P<tag>[^;]+);value=(?P<value>.+);$'
RESERVED_GET_DATA_RPC_PATTERN = (r'^type=data;dbNumber=(?P<dbNumber>\d+);start=(?P<start>\d+);'
                                 r'dataType=(?P<dataType>\w+);size=(?P<size>\d+);(bit=(?P<bit>\d+);)?$')
RESERVED_SET_DATA_RPC_PATTERN = (r'^type=data;dbNumber=(?P<dbNumber>\d+);start=(?P<start>\d+);'
                                 r'dataType=(?P<dataType>\w+);(size=(?P<size>\d+);)?(bit=(?P<bit>\d+);)?'
                                 r'value=(?P<value>.+);$')
RESERVED_GET_VM_RPC_PATTERN = r'^type=vm;vmAddress=(?P<vmAddress>[^;]+);$'
RESERVED_SET_VM_RPC_PATTERN = r'^type=vm;vmAddress=(?P<vmAddress>[^;]+);value=(?P<value>.+);$'
RESERVED_GET_TAG_RPC_SCHEMA = 'type=tag;tag=<S7 tag address>;'
RESERVED_SET_TAG_RPC_SCHEMA = 'type=tag;tag=<S7 tag address>;value=<value>;'
RESERVED_GET_DATA_RPC_SCHEMA = r'type=data;dbNumber=\d;start=\d;dataType=<type>;size=\d;[bit=\d;]'
RESERVED_SET_DATA_RPC_SCHEMA = (r'type=data;dbNumber=\d;start=\d;dataType=<type>;' r'[size=\d;][bit=\d;]value=<value>;')
RESERVED_GET_VM_RPC_SCHEMA = 'type=vm;vmAddress=<LOGO VM address>;'
RESERVED_SET_VM_RPC_SCHEMA = 'type=vm;vmAddress=<LOGO VM address>;value=<value>;'
RESERVED_GET_RPC_SCHEMA = ("type=tag;tag=<S7 tag address>; OR " r"type=data;dbNumber=\d;start=\d;dataType=<type>;size=\d;[bit=\d;] OR " "type=vm;vmAddress=<LOGO VM address>;")
RESERVED_SET_RPC_SCHEMA = ("type=tag;tag=<S7 tag address>;value=<value>; OR " r"type=data;dbNumber=\d;start=\d;dataType=<type>;[size=\d;][bit=\d;]value=<value>; OR " "type=vm;vmAddress=<LOGO VM address>;value=<value>;")
```
- **Parsing, two stages** (`:393-414`):
  1. The `type=` prefix selects the pattern for `(type, method)`.
  2. The full match is checked.
- **Building the config** (`:467-486`):
  - `dbNumber`, `start`, `size`, `bit` become `int`.
  - `requestType` = `write` for `set`, otherwise `read`.
  - `value` stays a string (`:420`).
- **Field rules:**
  - `size` is required for `get type=data` and optional for `set`.
  - `bit` is optional; the order is `size` then `bit`.
  - `dataType` must match `\w+`, so `char[10]` is impossible (`fstring10` passes the regex).
  - `tag` and `vmAddress` cannot contain `;`.
- **Value conversion on write:**
  - `tag`: by the tag's datatype (`s7_downlink_converter.py:252-281`, `297-399`).
    - BOOL uses `TBUtility.str_to_bool`: y/yes/t/true/on/1 and n/no/f/false/off/0 (`tb_utility.py:203-218`).
    - Integer types → `int()`; REAL/LREAL → `float()`.
    - Also handles CHAR/WCHAR, strings, TIME, DATE, DT/DTL, TOD/LTOD, LTIME, LDT.
    - Arrays need a list, which the reserved string cannot express (`:269-274`).
  - `data`: by `dataType` (`:42-250`). The full list of names is in that function. The buffer offset is always 0 for reserved RPCs.
  - `vm`: `int(value)`, falling back to `str_to_bool` → 0/1 (`:283-295`).
- **Read results:**
  - `tag` and `vm`: the raw snap7 value (`s7_uplink_converter.py:91-92`).
  - `data`: decoded per `dataType` (`:99-233`).
- **Device-type limits:**
  - On a PLC, `vm` raises `"Unsupported request type 'vm' for reading data from PLC device '<name>'"` (or the writing variant) (`device.py:187-221`).
  - On a LOGO, only `vmAddress` is read (`device.py:268-272`). `tag`/`data` give KeyError `'vmAddress'`.

**(c) Device RPCs from config**
- Device key `serverSideRpc` (`device_configs.py:49`, default `[]`).
- An entry is matched by exact `method` (`:371-372`). Only the first match runs (`:379-384`).
- The value written is TB `params` (`:383`).

### 2.2 Examples (reserved ones sent to the device)
- **Reserved:**
  - `{"method":"get","params":"type=tag;tag=DB1.DBD204:REAL;"}` ✓
  - `{"method":"set","params":"type=tag;tag=DB1.DBD204:REAL;value=21.5;"}` ✓
  - `{"method":"set","params":"type=tag;tag=DB1.DBX0.0:BOOL;value=true;"}` ✓
  - `{"method":"get","params":"type=data;dbNumber=1;start=0;dataType=bool;size=1;bit=0;"}` ✓ → `{"result": true}`
  - `{"method":"get","params":"type=data;dbNumber=1;start=2;dataType=int;size=2;"}` ✓
  - `{"method":"set","params":"type=data;dbNumber=1;start=0;dataType=bool;bit=0;value=true;"}` ✓
  - `{"method":"set","params":"type=data;dbNumber=1;start=2;dataType=int;value=-5;"}` ✓
  - `{"method":"set","params":"type=data;dbNumber=1;start=4;dataType=real;size=4;value=3.14;"}` ✓
  - LOGO: `{"method":"get","params":"type=vm;vmAddress=VW30;"}` ✓, `{"method":"set","params":"type=vm;vmAddress=VW30;value=1;"}` ✓
- **Device RPC** (committed `s7.json`):
  - `{"method":"setRelay","params":true}` to "S7 PLC"
  - `{"method":"getLight","params":{}}` to "LOGO"
- **Connector RPC:**
  - `{"method":"s7_read","params":{"deviceName":"S7 PLC","requestType":"read","type":"tag","tag":"DB1.DBD204:REAL"}}`
  - `{"method":"s7_write","params":{"deviceName":"S7 PLC","requestType":"write","type":"data","dbNumber":1,"start":0,"dataType":"bool","bit":0,"value":true}}`
  - A connector `type=data` read also needs `size` (`device.py:216`).

### 2.3 Responses (`s7_connector.py`)
`<method>` is `get`/`set` for reserved RPCs, the part after `s7_` for connector RPCs, and the method name for device RPCs.

| Case | Reply |
|---|---|
| read OK | `{"result": <value>}` (`:449-451`) |
| write OK | `{"result": "Successfully wrote value <converted_value> to device <deviceName> for RPC method <method>"}` (`:502`). For `data` the value appears as e.g. `bytearray(b'\x01')`. |
| device not found | `"Device with name <name> not found for RPC request: <str(rpc_request)>"` (`:345`) |
| device RPC not configured | `"Neither of configured device rpc methods match with <method>"` (`:374`) |
| reserved, empty params | `"No 'params' found in reserved RPC request '<method>'"` (`:388`) |
| reserved, `type=` prefix mismatch | `"The requested RPC does not match with the schema: <RESERVED_GET_RPC_SCHEMA\|RESERVED_SET_RPC_SCHEMA>"` (`:393-400`) |
| reserved, per-type mismatch (**bug**) | Intended: same text with the per-type schema. Actual: `"Error processing RPC request <str(rpc_request)>: cannot access local variable 'err_msg' where it is not associated with a value"` (Py ≥3.11 wording; 3.10 says `local variable 'err_msg' referenced before assignment`) (`:409`, `:364-368`) |
| write with no value | `"No 'params' found in RPC request for method <method>"` (`:490`) |
| write result ≠ 0 | `"Failed to write value <v> to device <d> for RPC method <method>"` (`:498`) |
| bad or missing `requestType` | `"Unsupported requestType <requestType> for RPC method <method>"` (`:453`) |
| any other exception (snap7, converter, KeyError) | `"Error processing RPC request <str(rpc_request)>: <e>"` (`:365`) |

`str(rpc_request)` formats are defined at `rpc_request.py:145`, `:156`, `:167`.

### 2.4 Config keys
- `serverSideRpc[]` entries:
  - `method`
  - `requestType` (`read`/`write`)
  - `type` (`tag`/`data`/`vm`)
  - `tag`; or `dbNumber`, `start`, `size`, `dataType`, `bit` (alias `bitIndex`), `offset` (default 0), `maxLength`; or `vmAddress`
  - Sources: `s7_downlink_converter.py:43-46`, `100-101`; `s7_uplink_converter.py:103-105`; `device.py:187-221`, `268-272`.
- Device `uplinkConverter`/`downlinkConverter` (`device_configs.py:43-44`): custom converters replace the conversion.
- No RPC timeout. Calls are synchronous.

### 2.5 Changes vs `8c64fa35^`
- **CHANGED, errors:**
  - Old replies were `{"result":"<msg>"}` (`_send_error_rpc_reply`, old `:501-507`) or `{"result":{"error":…}}` (schema mismatch, old `:454`).
  - Write failure and unsupported requestType came back under `"result"` (old `:405`, `:490-492`).
  - All of these are now `{"error":"<msg>"}`.
- **CHANGED, write success:** old `{"result": 0}` (old `:494`) → new success message (`fe31d1b2`, in range).
- **REMOVED:** `"Method name not found in RPC request: …"` (old `:346-351`).
- **FIXED:** the device-not-found and exception paths used to send a reply *and* return an error dict, which the old gateway sent again (old `:341-344`, `:380-384`; old gateway `:1697-1699`).
- **REGRESSION:** the per-type schema-mismatch message is lost (`:409`). `e9fa3efb` fixed `set_error_msg` but left `self.__log.error(err_msg)`.
- **Unchanged:** the reserved regexes and schemas. The only `constants.py` change in range is `DEFAULT_HEARTBEAT_INTERVAL` 0→5. Connector RPC still takes the device from `params.deviceName`.

### 2.6 Open questions
1. The `:409` bug above.
2. *Suspected:* tag reads of DATE/TOD/LTIME/LTOD/LDT/DTL return `date`/`timedelta`/`datetime` objects (snap7 `client.py:97-127`). These are passed through unchanged, and `dumps` fails (X1).
3. `set type=data;dataType=bool` writes a whole 1-byte buffer, so the other 7 bits of that byte become 0 (`s7_downlink_converter.py:106-111` + `device.py:190`). This predates the range.
4. The converter returns `None` on failure (bad tag, array, bad vm value), and the code still calls `device.write(…, None)` (`:494-496`). The resulting error text comes from snap7 and was not verified.
5. `"GET"`/`"SET"` raise KeyError at `:403`, giving `"Error processing RPC request …: ('tag', 'GET')"`.
6. The schema strings contain a literal `\d`, which appears as `\\d` in the reply JSON. Docs should show a readable form.

---

## 3. BACNET (`connectors/bacnet/`)

### 3.1 Dispatch (`bacnet_connector.py:847-877`)
The device is looked up first, waiting up to 10 s (`:852-857`, `816-829`).

**(a) RPC to connector:** always `{"error":"Not implemented"}` (`:859-863`). Without `params.deviceName` the reply is `"Failed to found device None"` instead.

**(b) Reserved `get` / `set`**
- Regexes, verbatim (`constants.py:32-46`):
```
GET_RPC_PATTERN = (
    r'^objectType=(?P<objectType>[A-Za-z]+);'
    r'objectId=(?P<objectId>\d+);'
    r'propertyId=(?P<propertyId>[A-Za-z]+);$'
)
SET_RPC_PATTERN = (
    r'^objectType=(?P<objectType>[A-Za-z]+);'
    r'objectId=(?P<objectId>\d+);'
    r'propertyId=(?P<propertyId>[A-Za-z]+);'
    r'(?:priority=(?P<priority>\d+);)?'
    r'value=(?P<value>.+);$'
)
RESERVED_GET_RPC_SCHEMA = "get objectType=<objectType>;objectId=<objectId>;propertyId=<propertyId>;"
RESERVED_SET_RPC_SCHEMA = "set objectType=<objectType>;objectId=<objectId>;propertyId=<propertyId>;priority=<priority>;value=<value>;"
DEFAULT_RPC_TIMEOUT = 10
```
- **Rules:**
  - `propertyId` must be letters only (camelCase, e.g. `presentValue`; no hyphens).
  - `priority` is optional and must be 1–16 (`:628-633`).
  - `objectType` must be one of `analogInput`, `analogOutput`, `analogValue`, `binaryInput`, `binaryOutput`, `binaryValue` (`constants.py:24-31`; checked at `:996`).
  - Pattern selection is exact: `== 'get'`, otherwise SET (`:986`).
- **Processing:**
  - The object id is built as `ObjectIdentifier("<objectType>:<objectId>")` (`device.py:322-323`).
  - `value` is passed as a **string** to bacpypes3 `write_property` (`:650`). The gateway does no type conversion. How bacpypes3 coerces it is unverified (the library is not installed in the venv).
  - Timeout is fixed at 10 s (`:1010` → `:936`).

**(c) Device RPCs from config**
- Device key `serverSideRpc` (`device.py:79`).
- The first entry with an exact `method` match is used (`:908-913`).
- The entry is validated (`:915-934`).
- The value is TB `params` (`:897`). Reads ignore it (`:968`).
- Timeout is `requestTimeout` (`:898`).

### 3.2 Examples
- **Reserved:**
  - `{"method":"get","params":"objectType=analogValue;objectId=1;propertyId=presentValue;"}` ✓ → `{"result":"25.0"}`. Reads always return strings (`str(result)`, `:611`).
  - `{"method":"set","params":"objectType=analogValue;objectId=1;propertyId=presentValue;value=25.5;"}` ✓ → `{"result":"25.5"}` (echoes the value, `:651`)
  - `{"method":"set","params":"objectType=binaryOutput;objectId=1;propertyId=presentValue;priority=8;value=active;"}` ✓. Whether bacpypes3 accepts `active` is not verified.
- **Device RPC** (committed `bacnet.json`):
  - `{"method":"get_state","params":{}}`
  - `{"method":"set_state","params":<value>}`
- **Connector RPC:** `{"method":"bacnet_x","params":{"deviceName":"…"}}` → `{"error":"Not implemented"}`.

### 3.3 Responses
| Case | Reply |
|---|---|
| read OK | `{"result":"<str(value)>"}` (`:611`, `:964`) |
| write OK | `{"result":<value as sent>}` (`:651`) |
| device not found | `"Failed to found device <name>"` (`:854`) |
| connector RPC | `"Not implemented"` (`:860`) |
| device RPC not configured | `"Neither of configured device rpc methods match with <method>"` (`:884`) |
| device RPC, bad objectType | `"Invalid objectType: '<t>'. Expected one of ['analogInput', 'analogOutput', 'analogValue', 'binaryInput', 'binaryOutput', 'binaryValue']."` (`:920-926`) |
| device RPC, bad requestType | `"Invalid requestType: '<t>'. Expected 'writeProperty' or 'readProperty'."` (`:928-934`) |
| reserved, empty params | `"No params section found in RPC request: <str(rpc_request)>"` (`:978`) |
| mismatch | `"The requested RPC does not match with the schema: <RESERVED_GET\|SET_RPC_SCHEMA>"` (`:990`) |
| reserved, bad objectType | `"The objectType must be from '['analogInput', 'analogOutput', 'analogValue', 'binaryInput', 'binaryOutput', 'binaryValue']', but got'<t>"` (quoting as in code, `:997`) |
| timeout | `"Timeout rpc has been reached for <device.name>"` (`:954`) |
| BACnet error/reject/abort or exception | `"An error occurred during RPC request: <err>"` (`:957-961`; error text from `:612-618`, `:654-661`) |
| other exceptions | `"Error processing RPC request <method>: <e>"` (`:874`) |

### 3.4 Config keys
- `serverSideRpc[]` entries:
  - `method`
  - `requestType`: `readProperty` / `writeProperty`
  - `objectType`: one of the 6
  - `objectId`
  - `propertyId`
  - `priority` (optional)
  - `requestTimeout`: **seconds**, default 10 (`:898`)
- Reserved RPCs have no config key; the timeout is a constant 10 s.

### 3.5 Changes vs `8c64fa35^`
- **NEW:** named-group regexes anchored with `$` (`constants.py:32-43`) replace the inline patterns (old `:977-979`), which had no end anchor, and the `split(';')`/`split('=')` parsing (old `:989-997`).
  - GET now rejects trailing text.
  - SET values may now contain `=` and `;`. Old parsing silently dropped a pair containing a second `=`.
- **NEW:** `DEFAULT_RPC_TIMEOUT = 10`, and the device RPC key `requestTimeout` is now read. Old timeout was the request `timeout`, default 5 s (old `:924`).
- **NEW:** connector RPC now returns an explicit `"Not implemented"`. By code reading, the old handler raised `KeyError 'data'` (old `:845-847`) and the old gateway replied `{"error":"'data'","code":500}` (old gateway `:1673-1674`).
- **CHANGED, reply shape:**
  - Old success: `{"result":"<str of response dict>"}`, e.g. `"{'value': '25.0'}"` (old `:942-944`). BACnet errors were stringified into `result` the same way.
  - Old timeout: `{"result":"None"}` (old `:931` + `:944`).
  - Old other errors: `{"result":{"error":…}}`.
  - New: `{"result":<value>}` and `{"error":"…"}`.
- **CHANGED:** only the first matching device-RPC config runs; the old code ran each match (old `:871-885`). A result of `value is None` now counts as an error (`:957`); the old code only logged falsy values.
- **FIXED:**
  - The schema-mismatch path crashed with no reply (old `:984-987` overwrote `content`).
  - Device-not-found now returns a proper error.
  - `caf3c8f4`: the confirmation handler no longer exits on an unmatched or late APDU, such as the one left after an RPC timeout cancel. Before, all later reads and RPCs would hang (`application.py:97-118`).

### 3.6 Open questions
1. **`requestTimeout` units.** The code treats it as seconds (`:898`, `:832-839`), but the committed `bacnet.json` uses `10000` (`HEAD:thingsboard_gateway/config/bacnet.json:62,70`), which becomes about 2.8 h. While waiting, the shared device-RPC thread is blocked. In practice the bacpypes3 APDU timeout probably ends it sooner (unverified).
2. **Bad priority**, or both value and priority null. `__write_property` *returns* a `ValueError` object instead of a dict (`:623-633`). The reply is `"Error processing RPC request set: 'ValueError' object has no attribute 'get'"`. This predates the range.
3. The schema text shows `priority=<priority>;` as required, but the regex makes it optional.
4. Read values always come back as strings.
5. *Suspected:* a device-RPC `writeProperty` with null `params` and a configured `priority` echoes `Null(())` as the result (`:635-636`, `:651`). That is not JSON-serializable (X1).
6. The 6-type `objectType` limit also applies to device RPC (`:920`), so the `weeklySchedule` and `listOfObjectPropertyReferences` write paths (`:638-648`) cannot be reached via RPC.
7. "Failed to found device" (wording) and the objectType message quoting are odd in the code; docs should quote them as-is unless the code is fixed.

---

## X. Shared issues these connectors hit
- **X1** *(suspected)*: `dumps(response.message)` at `tb_gateway_service.py:1718` sits inside a `try` that only catches `(TimeoutError, Empty)` (`:1719`). A non-serializable result raises out of the loop and would end the device-RPC thread for all connectors.
- **X2**: connector RPC reaches only the first connector of a given type (`:1674`). With several S7 instances, `deviceName` lookups can fail.
- **X3**: classification runs before the device check (`rpc_request.py:76-115`):
  - A device RPC method named `<connectorType>_…` (e.g. `modbus_reset`, `s7_x`) or `gateway_…` is treated as a connector or gateway RPC.
  - `get`/`set` in any case are treated as reserved.
  - Such names cannot be used for configured device RPCs.
- **X4**: connector-RPC `params` must be an object (`rpc_request.py:141`). Otherwise the exception is only logged (`tb_gateway_service.py:1663-1664`) and no reply is sent.
