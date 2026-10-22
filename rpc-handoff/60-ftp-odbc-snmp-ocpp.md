# RPC spec for the FTP, ODBC, SNMP and OCPP connectors (HEAD = e4e27ef2, baseline = `8c64fa35^`)

Read-only work. Committed configs were read with `git show HEAD:`. Library behaviour was read from `venv/.../site-packages`: ocpp 2.1.0 and puresnmp.

## 0. Shared model (summary)

- **How a request is classified** (`thingsboard_gateway/gateway/entities/rpc_request.py:28-43, 76-119`). Checks run in this order:
  1. GATEWAY: method is in `RESERVED_RPC_NAMES`, or its first `_` token is `gateway` (:46, :89-98).
  2. CONNECTOR: the first `_` token is a key of `DEFAULT_CONNECTORS`, i.e. `ftp`, `odbc`, `snmp`, `ocpp` and the others (:101-107; `gateway/constants.py:129`).
  3. RESERVED: `method.lower()` is `get`, or is `set` and a `device` is present (:110-115).
  4. DEVICE: a `device` is present (:117-119).
- **Consequence for per-device method names.** A name like `snmp_get` or `ocpp_reset` is routed as a connector RPC even when the request targets a device. `get`/`set` (any case) are always reserved.
- **Connector RPC** (`ConnectorRPCRequest`, :133-142): `method_name` is the part after the first `_`. `params` must be a JSON object, because `.get('value')` and `.get('deviceName')` are called on it (:141-142). If it is not an object, the constructor throws, the gateway only logs it (`tb_gateway_service.py:1663-1664`), and no reply is sent. The request goes only to the first connector of that type (`tb_gateway_service.py:1674-1675`).
- **Timeout.** `rpc_request.timeout` is the top-level `timeout` field of the incoming message, default `5` (`rpc_request.py:59`, `gateway/constants.py:115`). The gateway checks it only before dispatching a device/reserved RPC; if the device is still unknown by then it replies `{"error":"Request timeout", "code": 408}` (`tb_gateway_service.py:1688-1692, 1700-1702`). Not determined whether ThingsBoard actually sends a top-level `timeout`.
- **Response body.**
  - `RPCResponse.set_message(x)` gives `{"result": x}` and `set_error_msg(s)` gives `{"error": s}` (`rpc_response.py:23-27`).
  - Device/reserved replies go out as `gw_send_rpc_reply(device, id, {"result"|"error": ...})` (`tb_gateway_service.py:1716-1718, 1855-1856`).
  - Connector-RPC replies go to the gateway's own RPC response topic with the same body (`:1658-1662, 1860-1862`).
  - All four connectors always return an `RPCResponse` and catch every exception, so every dispatched RPC gets a reply.

---

## 1. FTP (`thingsboard_gateway/connectors/ftp/`)

### 1.1 Dispatch
`server_side_rpc_handler` (`ftp_connector.py:435-455`) branches on `rpc_type` (:440-448). Each branch resolves `(file_path, value)`, then `__execute_file_operation` (:515-531) runs. `value is None` means read (`RETR`, decoded as UTF-8, :522-523, :533-537). Otherwise it is a write: `STOR` overwrites the file with the UTF-8 encoding of `value` (:525, :539-542, `_get_io_stream` :427-428). Every RPC opens a new FTP connection (:516-517).

**(a) RPC to connector: `ftp_read`, `ftp_write`** (:491-499)
- The method after the prefix must be exactly `read` or `write`, otherwise: `"Unsupported FTP connector RPC method, expected 'read' or 'write'"` (:492-493).
- `params.valueExpression` is required, otherwise: `"Connector RPC requires 'valueExpression' param"` (:495-497).
- `valueExpression` must be a string, otherwise: `"Value must be a string, got <type>"` (:503-504).
- `read`: `valueExpression` is the file path (:506-507).
- `write`: all `'` characters are removed from the whole expression, then it is split on the **first** `;` into path and value (:509). Without a `;`: `"Value must be in format '<filePath>;<value>', got '<valueExpression>'"` (:510-511). The message shows the original string.

**(b) Reserved `get`/`set`** (:477-489). Method matching is case-insensitive: `set` selects the set pattern, anything else selects the get pattern (:482-483). From `constants.py:15-18`:
```
RESERVED_GET_RPC_SCHEMA = 'filePath=<path>;'
RESERVED_SET_RPC_SCHEMA = 'filePath=<path>;value=<value>;'
RESERVED_GET_RPC_PATTERN = r'^filePath=(?P<filePath>[^;]+);?$'
RESERVED_SET_RPC_PATTERN = r'^filePath=(?P<filePath>[^;]+);value=(?P<value>.+?);?$'
```
- Matched with `fullmatch`. Keys are case-sensitive and the order is fixed. No spaces are allowed around `=`/`;`. The trailing `;` is optional.
- `filePath` cannot contain `;`.
- `value` is everything after `value=` minus one optional trailing `;`. It may contain `;` and `=`, but not a newline (`.`). It is written verbatim; apostrophes are **not** stripped here.
- Empty or missing params: `"No 'params' found in reserved RPC request"` (:479-480).
- No match: `"The requested RPC does not match with the schema: <schema>"` (:485-487).
- If params is not a string (e.g. a JSON object), `fullmatch` raises `TypeError` and the text is Python's (`expected string or bytes-like object...`).

**(c) Per-device RPCs** (:457-475)
- Entries come from `requestsMapping.serverSideRpc`, or from top-level `serverSideRpc` in the old config format via the adapter (`backward_compatibility_adapter.py:51, 101-102`).
- The **first** entry where `fullmatch(deviceNameFilter, device)` and `fullmatch(methodFilter, method)` both match is used (:470-475).
- `valueExpression` is reduced to its `${tag}` name and then looked up as a **top-level** key of `{'id','method','params'}` (:462-464). So `${params}` works; `${params.x}`, or an expression without `${}`, gives `"Value for '<valueExpression>' not found in RPC params"` (:465-466).
- The resolved value goes through the same parser as connector RPC (:468). It is a **write only when the RPC method name is exactly `write`**; any other matched method is a read (:506).

**(d) Unknown or mismatched requests**
- No config match: `"Neither of configured device rpc methods match"` (:459-460).
- All errors are wrapped as `"Failed to process '<method_name>' RPC request: <e>"` (:452-453). For connector RPC, `<method_name>` is `read`/`write`.
- Further texts:
  - `"Cannot connect to FTP server <host>:<port>"` (:518-519; `__connect` also sleeps 10 s on failure, :186-189)
  - `"FTP error while processing file '<path>': <ftplib error>"` (:528-529)
  - `"File '<path>' is not a valid UTF-8 text file"` (:530-531)

### 1.2 Examples
```json
{"method": "get", "params": "filePath=/upload/report.txt;"}
{"method": "set", "params": "filePath=/upload/report.txt;value=Hello; world=1;"}
{"method": "ftp_read",  "params": {"valueExpression": "/upload/report.txt"}}
{"method": "ftp_write", "params": {"valueExpression": "/upload/report.txt;Hello world"}}
{"method": "read",  "params": "/upload/report.txt"}
{"method": "write", "params": "/upload/report.txt;Hello world"}
```
- The `set` example writes the value `Hello; world=1`.
- The last two examples assume the committed config (`methodFilter` `read`/`write`, `valueExpression` `${params}`; `git show HEAD:thingsboard_gateway/config/ftp.json` lines 53-64).

### 1.3 Responses
- Read: `{"result": "<file content>"}`.
- Write: `{"result": "<value>"}` if `len(value) < 80`, else `{"result": true}` (:527).
- Error: `{"error": "Failed to process '<method>' RPC request: ..."}`.
- There is no connector-side timeout; the FTP socket defaults apply.

### 1.4 Config keys
- `requestsMapping.serverSideRpc[]` (default `[]`, :431), with `deviceNameFilter`, `methodFilter`, `valueExpression`, all required (otherwise a KeyError text inside the error).
- Connection, used by RPC as well: `parameters.host`, `parameters.port` (21), `parameters.TLSSupport` (false), `parameters.security` (`type: basic` with username/password, else anonymous) (:64-67, :86-88).

### 1.5 Changes vs baseline
- **FIXED: connector RPC replies.** At baseline the handler returned `None` (`8c64fa35^:.../ftp_connector.py:437-443`), so the gateway replied `{"success": false}` (`8c64fa35^:tb_gateway_service.py:1665-1666`). It now returns the real result or error.
- **CHANGED: write success shape.** Baseline was `{"result": {"value": "<v>"}}` (old :504); it is now flat `{"result": "<v>"}` or `true`. The flat form arrived in e1905286, which is in the range.
- **CHANGED: errors are always `{"error": ...}`.** At baseline, read errors produced no reply (old :484-487), and write errors were sent as `{"result": "{\"error\": ...}"}` (old :509, :520-521).
- **FIXED: write values containing `;`.** Baseline wrote only the text between the first and second `;` (old :499-500). The split is now `;`-once.
- **CHANGED: reserved params parsing.**
  - Baseline: free key order, and any `key=value` segment with more than one `=` was silently dropped (old :450-457).
  - Now: fixed order and regex. `value` may contain `;`/`=`.
  - Reserved `set` no longer strips `'` (baseline routed it through the write path, old :464, :499).
- **CHANGED: get/set are case-insensitive** (baseline exact, old :448).
- **CHANGED: per-device matching.** Only the first matching `serverSideRpc` entry runs; baseline executed every match (old :471-482).
- **NEW error texts:** schema mismatch, connection, UTF-8.

### 1.6 Open questions
- A per-device RPC is a write only if the method name equals `write` exactly (:506). For example, `methodFilter: "write.*"` with method `writeFile` performs a **read** of `"path;value"`. This is pre-existing (old :497).
- `valueExpression` supports only top-level tags; nested paths fail. This is pre-existing.
- A connection failure blocks for 10 s inside `__connect` (:189) on the gateway's single device-RPC thread.

---

## 2. ODBC (`thingsboard_gateway/connectors/odbc/`)

### 2.1 Dispatch (`odbc_connector.py:132-151`)

**(a) Connector RPC (`odbc_*`): not supported.** Error: `"Connector RPC is not supported by ODBC connector"` (:141-142).

**(b) Reserved `get`/`set`.** Both behave identically (:139-140, :176-189). From `constants.py:15-18`:
```
RESERVED_RPC_SCHEMA = 'procedure_name=<name>|query=<query>;[value=<arg1>,<arg2>;][with_result=true|false;]'
RESERVED_RPC_PATTERN = (r'^(?:procedure_name=(?P<procedure_name>[^;]+)|query=(?P<query>[^;]+))'
                        r'(?:;value=(?P<value>[^;]+))?'
                        r'(?:;with_result=(?P<with_result>[Tt]rue|[Ff]alse))?;?$')
```
- Exactly one of `procedure_name` or `query` is allowed, and it must come first. Then optional `value`, then optional `with_result`, then an optional trailing `;`.
- No field may contain `;`. `=`, `,` and `?` are allowed inside `query`.
- `value` is split on `,` into a list of **strings**, with no type conversion (:188).
- `with_result` accepts only `True`/`true`/`False`/`false`; the default is false (:189).
- Execution (:227-241):
  - With `query`: `cursor.execute(query, args)`, where args fill the `?` placeholders.
  - With a procedure: `{CALL <name> (?,?..)}`, or `{CALL <name>}` when there are no args.

**(c) Per-device RPCs** (:153-174, config parsed at :508-537)
- `serverSideRpc.methods` is a list of either a string (the method name) or an object `{name, query?, args? | params? (legacy), result?}`. Lookup uses the exact method name (:155).
- **Unknown method:**
  - If `enableUnknownRpc` is false: `"Unknown RPC method"` (:158-159).
  - Otherwise params must be an object, else `"Unknown RPC requires params as an object with 'query' and optional 'args', 'result'"` (:160-162).
- **Known method with `overrideRpcConfig` true and non-empty params:** params must be an object, else `"Params must be an object to override the RPC config"`; it is merged over the config (:163-166). If override is false, params are ignored.
- **Resolved values:** procedure name = RPC method name; `query` (default `""`); args from `args`, else `params`, else `[]`; `with_result` from `result` (default false, :59) (:170-174). Configured args keep their JSON types.

**(d) Other errors**
- All errors are wrapped as `"Failed to process '<method>' RPC request: <e>"` (:148-149).
- Reserved: `"No 'params' found in reserved RPC request"` (:178-179); `"The requested RPC does not match with the schema: <RESERVED_RPC_SCHEMA>"` (:181-183).
- `"Not connected to database"` (:192-193); this is checked after config resolution.
- `"Query returned no result set"` (:204-205).
- pyodbc exception text otherwise.

### 2.2 Examples
```json
{"method": "set", "params": "procedure_name=reset_counters;"}
{"method": "set", "params": "procedure_name=set_setpoint;value=kitchen,21.5;"}
{"method": "get", "params": "query=SELECT name, value FROM settings WHERE id = ?;value=5;with_result=true;"}
{"method": "procedureOne", "params": {}}
{"method": "procedureTwo", "params": {"args": ["Two", 5, 1.5], "result": true}}
{"method": "anyName", "params": {"query": "SELECT COUNT(*) AS cnt FROM ts_kv WHERE ts > ?", "args": [0], "result": true}}
```
- `procedureOne` and `procedureTwo` come from the committed config (odbc.json lines 42-55). `procedureTwo` with params needs `overrideRpcConfig: true`, which the committed config has.
- `anyName` needs `enableUnknownRpc: true` (and see the bug in 2.6).

### 2.3 Responses
- Without result: `{"result": {"success": true}}` (:201-202).
- With result: `{"result": {<column>: <value>, ...}}` for the **first row only** (`fetchone`), or `{"result": null}` when there are no rows (:207-208).
- Values are made JSON-safe: datetime/date/time become ISO strings, UUID becomes a string, bytes become UTF-8 text or hex if not decodable (:210-225).
- Error: `{"error": "..."}`. There is no connector timeout.

### 2.4 Config keys
- `serverSideRpc.enableUnknownRpc` (false, :57, :511-512)
- `serverSideRpc.overrideRpcConfig` (false, :58, :517-518)
- `serverSideRpc.methods[]`: `name`, `query`, `args`, `params` (legacy), `result` (false)
- `connection.attributes` is passed to `pyodbc.connect` (:378). There is no explicit `commit()` anywhere, so writes made through RPC depend on `autocommit` (the committed config has `true`).

### 2.5 Changes vs baseline
- **CHANGED: device RPC response.**
  - Baseline: `{"success": true|false}`, or the raw row dict with no wrapper (`8c64fa35^:.../odbc_connector.py:173-178`).
  - Now: `{"result": {"success": true}}` or `{"result": {row}}`/`null`, and failures return `{"error": "<reason>"}`.
- **CHANGED: reserved errors.**
  - Baseline: `{"<method>": "Error during executing reserved RPC <e>"}` and `{"<method>": "RPC params are empty, expected format: set value={value};"}` (old :191-197, :215-217).
  - Now: `{"error": ...}`.
- **CHANGED: reserved params.**
  - Baseline: free order; both `procedure_name` and `query` allowed, with query winning; `with_result` in any case; segments with an extra `=` silently dropped (old :230-255).
  - Now: fixed order regex, the two are mutually exclusive, and `=` is allowed.
- **CHANGED: pyodbc warnings are now errors.** Baseline logged them and still replied with success for reserved RPCs (old :207-210) or `{"success": false}` for device RPCs.
- **NEW:** JSON-safe row conversion; `null` result for no rows (baseline crashed on `row_to_dict(None)`); `"Query returned no result set"`.
- **NEW:** connector RPC is explicitly rejected.
- **CHANGED:** unknown-RPC args now also accept the legacy `params` key (baseline accepted `args` only, old :146). Get/set matching is now case-insensitive (old :183).

### 2.6 Open questions
- **Bug (pre-existing, also at old :535-537).** If `serverSideRpc.methods` is missing or empty, :523-525 replaces the whole `serverSideRpc` dict with `{"methods": {}}`, which drops `enableUnknownRpc`/`overrideRpcConfig`. Any device RPC then fails with `"Failed to process '<m>' RPC request: 'enableUnknownRpc'"` (KeyError at :158). In practice unknown RPCs only work when at least one method is configured.
- Reserved `get` and `set` are identical.
- All reserved args are strings.

---

## 3. SNMP (`thingsboard_gateway/connectors/snmp/`)

### 3.1 Dispatch (`snmp_connector.py:327-340`)
SNMP error texts are **not** prefixed with `"Failed to process ..."`; each message is sent raw (:342-346).

**(a) Connector RPC: not supported.** Error: `"Connector RPC is not supported by SNMP connector"` (:335-336).

**(b) Reserved `get`/`set`** (:361-381). Order of checks:
1. Device lookup by exact `deviceName` in the connector config (:314-317). If absent: `"Device <name> not found"` (:362-364).
2. Empty params: `"No 'params' found in reserved RPC request '<method>'"` (:366-368).
3. Pattern selection is case-insensitive on `set` (:370-371).

From `constants.py:15-22`:
```
RESERVED_GET_RPC_SCHEMA = 'oid=<oid>;[timeout=<seconds>;]'
RESERVED_SET_RPC_SCHEMA = 'oid=<oid>;[type=<type>;][timeout=<seconds>;]value=<value>;'
RESERVED_GET_RPC_PATTERN = (r'^oid=(?P<oid>\.?\d+(?:\.\d+)*)'
                            r'(?:;timeout=(?P<timeout>\d+(?:\.\d+)?))?;?$')
RESERVED_SET_RPC_PATTERN = (r'^oid=(?P<oid>\.?\d+(?:\.\d+)*);'
                            r'(?:type=(?P<type>[A-Za-z0-9]+);)?'
                            r'(?:timeout=(?P<timeout>\d+(?:\.\d+)?);)?'
                            r'value=(?P<value>.+?);?$')
```
- `oid` is numeric dotted with an optional leading `.`. `timeout` is seconds (integer or decimal).
- For set the order is `oid; [type;] [timeout;] value`, and `value` is last. It may contain `;`/`=`.
- No match: `"The requested RPC does not match with the schema: <schema>"` (:373-376).
- **Value typing** (`snmp_downlink_converter.py:25-62, 103-113`). `type` is case-insensitive, default `OCTETSTRING`. Accepted values:
  - `INTEGER`, `INT`
  - `COUNTER`, `COUNTER32`, `COUNTER64`
  - `GAUGE`, `GAUGE32`
  - `TIMETICKS`
  - `OCTETSTRING`, `STRING`, `STR`
  - `IPADDRESS`
- **Conversion errors:** `"Failed to convert RPC value: Cannot convert value '<v>' to type '<TYPE>'"` or `"Failed to convert RPC value: Unsupported SNMP type: <TYPE>"` (:384-387).

**(c) Per-device RPCs** (:348-359)
- Entries come from `devices[].serverSideRpcRequests[]`; the first match wins via `re.search(method_name, requestFilter)` (:353-354). Note the arguments are swapped (see 3.6).
- No match: `"Neither of configured device rpc methods match with <method>"` (:355-357).
- `params` is the value to convert (:359). Entry `mappings` are resolved with `${params...}` (converter :64-101).
- The entry's `method` is any of `get`, `multiget`, `getnext`, `walk`, `multiwalk`, `set`, `multiset`, `bulkget`, `bulkwalk`, `table`, `bulktable` (:186-251).

**(d) Timeouts and other errors**
- The wait is `min(float(timeout from params/entry, default 5), float(rpc_request.timeout))` (:392).
- `"Timeout (<t>s) waiting for RPC <method> response from device <deviceName>"` (:399-402); `<t>` is a float, e.g. `5.0`.
- `"Timeout exception on connection to device <deviceName>"` (:403-405), raised by the puresnmp client timeout, which is device `timeout`, default 6 (:279).
- Any other exception: `"Error processing RPC request <str(rpc_request)>: <e>"` (:339-340). This embeds `"Reserved RPC: id=..., method_name=..., device_name=..., params=..."` (`rpc_request.py:166-167`).

### 3.2 Examples
```json
{"method": "get", "params": "oid=1.3.6.1.2.1.1.5.0;"}
{"method": "get", "params": "oid=.1.3.6.1.2.1.1.3.0;timeout=2.5;"}
{"method": "set", "params": "oid=1.3.6.1.2.1.1.5.0;value=router-01;"}
{"method": "set", "params": "oid=1.3.6.1.4.1.2021.8.1.101.1;type=INTEGER;timeout=3;value=42;"}
{"method": "getData"}
{"method": "setData", "params": "new description"}
```
`getData` and `setData` come from the committed `snmp.json` (lines 91-110).

### 3.3 Responses
- Success: `{"result": "<string>"}`. The result is always a string: bytes are decoded as UTF-8, everything else goes through `str()` (:407, :410-412).
- `set` returns the value echoed by the agent (puresnmp `PyWrapper.set`).
- Error: `{"error": "<raw message>"}`.

### 3.4 Config keys
- Device: `deviceName`, `ip`, `port` (161), `timeout` (6, SNMP client timeout), `community`, `version` (`v2c`) (:275-282). `converter` replaces **both** the uplink and downlink converter (:256-262).
- `serverSideRpcRequests[]`:
  - `requestFilter`, `method`, `oid`
  - `type` (default OCTETSTRING)
  - `mappings`
  - `timeout` (default 5)
  - `scalarOid`, `repeatingOid`, `maxListSize` (1), `bulkSize` (10)

### 3.5 Changes vs baseline
- **REMOVED / CHANGED: the reserved format.** The baseline built the request config from the params string and read `rpc_config["method"]` (`8c64fa35^:.../snmp_connector.py:351, 362`), so params effectively had to include `method=get|set`. The new regex starts with `oid=`, so `method=...` now causes a schema mismatch. Key order is now fixed, and values may contain `;`/`=` (baseline split on `;`/`=`, old :339-346).
- **CHANGED: replies are always sent.**
  - Device not found and no-matching-method are now error replies; baseline only logged and sent no reply (old :313-315, :326-327).
  - Error shape: `{"error": "<text>"}`. Baseline was `{"error": "<repr(e)>", "success": false}` (old :330-332).
- **CHANGED: timeout handling.** It is now float, capped by the request timeout, and produces dedicated messages. Baseline used `int(...)` and a generic error (old :365).
- **CHANGED:** get/set are case-insensitive (old :335). Connector RPC is explicitly rejected. The success shape `{"result": "<str>"}` is unchanged.

### 3.6 Open questions
- **Swapped regex (pre-existing, old :322-323).** The RPC method name is used as the pattern and `requestFilter` as the string. For example, method `set` matches `requestFilter` `setData`. Attribute updates have the same issue (:293).
- **Shipped example is broken.** The committed `snmp.json` entry `multiSetData` (line 98) has no `mappings`, so it always fails with `"Error processing RPC request ...: 'mappings'"` (:221-223). This is pre-existing.
- **Repr strings, not JSON.** Results of `walk`, `multiget` and similar methods are Python `str(dict)` reprs.
- **Uppercase `method` in config.** The RPC path does not lowercase the entry `method` (the polling path does, :161). `"GET"` therefore logs "Not found" and returns a **success** with `{"result": "None"}` (:249-251, :407).
- **Missing prefix.** Error texts lack the `"Failed to process '<method>' RPC request:"` prefix used by FTP/ODBC/OCPP.
- **Timeouts above 5 s.** A param or config `timeout` above 5 s has no effect unless the incoming message carries a larger top-level `timeout`.

---

## 4. OCPP (`thingsboard_gateway/connectors/ocpp/`)

### 4.1 Dispatch (`ocpp_connector.py:334-357`)
- **Charge point lookup.** The charge point is looked up by name: the device name assigned by the uplink converter at BootNotification (`charge_point.py:91`; `ocpp_connector.py:306-309`). If absent: `"Charge Point <name> is not connected"` (:359-364).
- **Call execution.** The call runs with `charge_point.call(request, suppress=False)` on the connector loop with `timeout = min(float(timeout), float(rpc_request.timeout))` (:351, :414-417).

**(a) Connector RPC: not supported.** Error: `"Connector RPC is not supported by OCPP connector"` (:346-347).

**(b) Reserved `get` → GetVariables, `set` → SetVariables** (:387-412; case-insensitive on `set`). From `constants.py:15-31`:
```
RESERVED_GET_RPC_SCHEMA = ('component=<component>;[componentInstance=<instance>;][evseId=<id>;]'
                           'variable=<variable>;[variableInstance=<instance>;][timeout=<seconds>;]')
RESERVED_SET_RPC_SCHEMA = ('component=<component>;[componentInstance=<instance>;][evseId=<id>;]'
                           'variable=<variable>;[variableInstance=<instance>;][timeout=<seconds>;]value=<value>;')
RESERVED_GET_RPC_PATTERN = (r'^component=(?P<component>[^;]+);'
                            r'(?:componentInstance=(?P<componentInstance>[^;]+);)?'
                            r'(?:evseId=(?P<evseId>\d+);)?'
                            r'variable=(?P<variable>[^;]+)'
                            r'(?:;variableInstance=(?P<variableInstance>[^;]+))?'
                            r'(?:;timeout=(?P<timeout>\d+(?:\.\d+)?))?;?$')
RESERVED_SET_RPC_PATTERN = (r'^component=(?P<component>[^;]+);'
                            r'(?:componentInstance=(?P<componentInstance>[^;]+);)?'
                            r'(?:evseId=(?P<evseId>\d+);)?'
                            r'variable=(?P<variable>[^;]+);'
                            r'(?:variableInstance=(?P<variableInstance>[^;]+);)?'
                            r'(?:timeout=(?P<timeout>\d+(?:\.\d+)?);)?'
                            r'value=(?P<value>.+?);?$')
```
- The order is fixed. `evseId` is digits only and becomes `component.evse.id` as an int (:457-458).
- `componentInstance` and `variableInstance` become `instance` (:452-464).
- For set, `value` is last, is sent as the string `attribute_value`, and may contain `;`/`=` (:400-405).
- No `attributeType` is sent.
- `timeout` defaults to 5 (:412).
- Errors: `"No 'params' found in reserved RPC request"` (:388-389); `"The requested RPC does not match with the schema: <schema>"` (:393-396).

**(c) Per-device RPCs** (:366-385)
- Entries come from `chargePoints[].serverSideRpc[]`; the first entry with `methodRPC == method` (exact) is used (:367-368).
- Required `valueExpression`, otherwise `"'valueExpression' is not configured for this RPC"` (:372-374).
- Each `${tag}` is resolved against `{'id','method','params'}`; dotted paths such as `${params.type}` work through JSONPath. The **JSON-encoded** value is substituted with `dumps`, so strings get quotes (:376-382).
- **Without `action`:** sends `DataTransfer(vendor_id="1", data=<string>)` (:428-429).
- **With `action`:** the payload must be valid JSON (`"Invalid JSON payload for action '<action>': <e>"`) and a JSON object (`"Payload for action '<action>' must be a JSON object"`) (:431-437). `action` must name a dataclass in `ocpp.v21.call` (`"Unknown OCPP action '<action>'"`). The payload's top-level keys must be the Python **snake_case** field names, otherwise `"Invalid payload fields for OCPP action '<action>': <e>"` (:441-450).
- `timeout` comes from the entry, default 5 (:385).

**(d) Errors** (wrapped as `"Failed to process '<method>' RPC request: <e>"`, :353-355)
- No config match: `"Neither of configured device rpc methods match"` (:369-370).
- `"Timeout (<t>s) waiting for <Action> response from Charge Point <name> (previous call to the Charge Point may still be in progress)"` (:418-420).
- `"Charge Point <name> returned an error on <Action>: <OCPPError>"` (:421-422).

### 4.2 Examples
```json
{"method": "get", "params": "component=OCPPCommCtrlr;variable=HeartbeatInterval;"}
{"method": "set", "params": "component=OCPPCommCtrlr;variable=HeartbeatInterval;value=30;"}
{"method": "get", "params": "component=Controller;componentInstance=main;evseId=1;variable=Temperature;variableInstance=max;timeout=4;"}
{"method": "set", "params": "component=Controller;componentInstance=main;evseId=1;variable=Temperature;variableInstance=max;timeout=4;value=55;"}
{"method": "rpc1", "params": {"key": "value"}}
{"method": "reset", "params": {"type": "Immediate"}}
```
- The third and fourth examples use illustrative names.
- `rpc1` uses the committed config (`valueExpression` `${params}`). It sends `DataTransfer` with `data='{"key": "value"}'`.
- `reset` assumes the entry `{"methodRPC":"reset","action":"Reset","valueExpression":"${params}"}`.

### 4.3 Responses
- The result is the OCPP CallResult converted with `asdict` (:424). Top-level keys are dataclass fields, and absent optional fields are `null`. Nested keys are whatever the charge point sent, converted to snake_case by the ocpp library (`camel_to_snake_case`).
- Get, illustrative:
  ```json
  {"result": {"get_variable_result": [{"attribute_status": "Accepted", "attribute_value": "60", "component": {"name": "OCPPCommCtrlr"}, "variable": {"name": "HeartbeatInterval"}}], "custom_data": null}}
  ```
  Set has the same shape with `set_variable_result`.
- DataTransfer: `{"result": {"status": "Accepted", "custom_data": null, "data": null, "status_info": null}}`.
- Reset: `{"result": {"status": "...", "custom_data": null, "status_info": null}}`.
- Error: `{"error": "..."}`.

### 4.4 Config keys
- `chargePoints[].serverSideRpc[]`: `methodRPC`, `valueExpression` (required), `action` (optional; default DataTransfer), `timeout` (5).
- `withResponse` is **no longer read**. The committed `ocpp.json` line 60 still contains it, and it is ignored.

### 4.5 Changes vs baseline
- **NEW: `action`** for per-device RPCs, which sends any OCPP 2.1 CSMS→CP action (8c64fa35 plus the validation added in a127a79a).
- **REMOVED: `withResponse`** (a127a79a; baseline `8c64fa35^:.../ocpp_connector.py:370`). A reply is always sent now.
- **CHANGED: result shape.** It is now a JSON object. Baseline sent `{"result": str(result)}`, a Python repr, or `"None"` on timeout or CallError (old :371, :413, :423, :295-303).
- **CHANGED: failures reported as errors.** Timeouts and charge-point CallErrors now produce error replies (`suppress=False`).
  - Charge point not connected: now an error reply; baseline only logged (old :333-336).
  - Missing `valueExpression`: now an error reply; baseline was silent (old :352-353).
  - Reserved RPC missing component/variable: now an error reply; baseline only logged a warning (old :431-434).
- **CHANGED: reserved params.**
  - Baseline: free order; values containing `=` were dropped; a non-numeric `evseId` raised an exception that was only logged (old :374-388).
  - Now: fixed-order regex and `\d+` for `evseId`.
  - Get/set are now case-insensitive (old :427).
- **CHANGED: matching.** Only the first matching `methodRPC` entry runs; baseline ran all of them (old :345-347). Reserved get/set no longer also falls through to the `serverSideRpc` loop.
- **NEW:** connector RPC is explicitly rejected.

### 4.6 Open questions
- **Misattributed errors.** Local JSON-schema validation failures, on the request or the response, raise `OCPPError` and are reported as `"Charge Point <name> returned an error on <Action>: ..."` (:421-422; `ocpp/messages.py` `validate_payload`). The text is misleading.
- **Unresolved `${tag}` is sent as a literal.** It is substituted as the JSON string of the literal tag (e.g. `"${params.type}"`) instead of raising an error (`expression_instead_none=True`, :378). This is pre-existing.
- **Datatype names accepted as `action`.** The check is "a dataclass in `ocpp.v21.call`", which also accepts imported datatypes (e.g. `ComponentType`). These then fail at the library level.
- **Timeouts above 5 s.** Same cap as SNMP: a configured `timeout` above 5 s has no effect unless the request carries a larger `timeout`. The ocpp library's own response timeout is 30 s (library default, `ChargePoint(..., response_timeout=30)`).

---

## 5. Cross-connector notes for the doc writer
- **Reserved params must be a string.** A JSON object yields a Python `TypeError` text: FTP/ODBC/OCPP inside the `"Failed to process..."` wrapper, SNMP inside `"Error processing RPC request..."`.
- **Per-device method naming.** Names must not be `get`/`set` (any case). They must not start with `<connectorType>_` or `gateway_`, and must not be `getTermInfo`, `sendCommand`, `getCommandStatus` or `terminateCommand` (`rpc_request.py:46, 89-115`).
- **Connector RPC support.** Only FTP supports it (`ftp_read`/`ftp_write`). ODBC, SNMP and OCPP return an explicit error.
