# RPC spec: MQTT, REST and REQUEST connectors (HEAD e4e27ef2, compared with `8c64fa35^`)

From reading code plus `git show`/`git diff`; nothing was executed. Path abbreviations, all relative to the gateway repo root:
- `C/` = `thingsboard_gateway/connectors/`
- `GW` = `thingsboard_gateway/gateway/tb_gateway_service.py`
- `RQ` = `thingsboard_gateway/gateway/entities/rpc_request.py`
- `TBU` = `thingsboard_gateway/tb_utility/tb_utility.py`
- "old" = `8c64fa35^`

## 0. Shared facts these three connectors depend on (see 10-gateway-core.md)

- **Classification order** (RQ:76-86): gateway, then connector, then reserved, then device.
  - **CONNECTOR:** the part of the method before the first `_` is a key of `DEFAULT_CONNECTORS`, i.e. `mqtt`, `rest`, `request` (RQ:101-107; `gateway/constants.py:129-146`). The `device` field is not checked.
  - `method_name` is the text after the first `_` (RQ:138).
  - **params must be a JSON object.** The constructor calls `params.get('value')` and `params.get('deviceName')` (RQ:141-142). With non-object params the exception is caught at GW:1663-1664 and **no reply is sent**.
  - Only the first connector of that type receives the RPC (GW:1674-1675).
  - **RESERVED:** `method.lower()` is `get` or `set` (RQ:110-115).
- **What ThingsBoard receives.** Connectors return an `RPCResponse` whose message is either `{"result": X}` (`set_message`) or `{"error": "<msg>"}` (`set_error_msg`) (`gateway/entities/rpc_response.py:23-27`).
  - The gateway replies without `success_sent`, so the dict is published unchanged: GW:1855-1856 for sub-devices, GW:1860-1861 for connector RPCs.
  - The `'result'` unwrapping at GW:1849-1850 only applies to the `success_sent` branches.
  - Net effect: success is `{"result": X}`, error is `{"error": "<msg>"}`.
- `RPC_DEFAULT_TIMEOUT = 5` (`gateway/constants.py:115`).

---

## 1. MQTT (`C/mqtt/`)

### 1.1 How RPCs are dispatched

**(a) RPC to connector**
- Method `mqtt_<name>`, sent to the gateway device. The params object itself is used as the RPC config (`mqtt_connector.py:1044-1045`). It takes the same keys as a `serverSideRpc` entry (see 1.4).
- There is no method allowlist. `<name>` is only used for `${methodName}`.
- `params.deviceName` is optional and only feeds `${deviceName}`.
- The call is two-way if params contain both a truthy `responseTopicExpression` and a truthy `responseTimeout` (938-942). Otherwise it is one-way.

**(b) Reserved get/set**
- Regex, verbatim (`C/mqtt/constants.py:17-18`):
  - `GET_PATTERN_REGEX = r'^requestTopicExpression=(?P<requestTopicExpression>.+);responseTopicExpression=(?P<responseTopicExpression>.+);value=(?P<value>.+);$'`
  - `SET_PATTERN_REGEX = r'^requestTopicExpression=(?P<requestTopicExpression>.+);value=(?P<value>.+);$'`
- Schema strings used in the error text (constants.py:15-16):
  - `get requestTopicExpression=<requestTopicExpression>;responseTopicExpression=<responseTopicExpression>;value=<value>;`
  - `set requestTopicExpression=<requestTopicExpression>;value=<value>;`
- **Pattern selection:** the GET pattern is used only if `method_name == 'get'` exactly (case-sensitive, 1083-1086). Any other reserved spelling (`GET`, `Get`, `set`, `SET`) uses the SET pattern.
- **Parsing rules** (1087, `re.match` anchored):
  - params must be a string.
  - Keys are literal and case-sensitive, in fixed order, with no whitespace.
  - All parts are required, including `value` for `get`.
  - The trailing `;` is required.
  - The groups are greedy `.+`, so values may contain `;` and `=`. Extra segments are absorbed into the previous value rather than rejected.
- **After a match** (1094-1098):
  - `value` becomes `valueExpression`.
  - For `get`, `responseTimeout` is set to `RPC_DEFAULT_TIMEOUT*1000` = 5000 ms. It cannot be overridden because the regex has no group for it.
  - `set` has no response topic, so it is always one-way.
- **Value typing:** none. The payload is the literal text of `value`, with two substitutions: `${deviceName}` (1001-1003) and `${...}` tags resolved against `{'params': <groupdict>}` (992-1007).
- **Topics:** `${deviceName}`, `${methodName}` (which is `get`/`set`) and `${requestId}` are substituted (943-949, 983-988).

**(c) Device RPCs from config (`serverSideRpc`)**
- The section is read from the top level or from `requestsMapping.serverSideRpc` (291-300).
- Mandatory keys: `deviceNameFilter`, `methodFilter`, `requestTopicExpression`, `valueExpression`. An entry missing any of them is dropped at startup with an error log (175, 307-321).
- **Matching:** the first entry, in config order, where `re.search(deviceNameFilter, device)` and `re.search(methodFilter, method)` both match (1061-1065). This is a partial `search`, not `fullmatch`.
- **Two-way** only if `responseTopicExpression` and `responseTimeout` are both truthy. A `responseTopicExpression` without `responseTimeout` is handled as one-way and logs `2-way RPC without timeout: treating as 1-way` (979-980).
- The `type` key (`twoWay`/`oneWay` in the default config) is **not read**.
- **Two-way flow:**
  1. Subscribe to the resolved response topic with `responseTopicQoS` (default 1) (958).
  2. Wait up to about 1 s for the subscription (961-967).
  3. Register the timeout as now + `responseTimeout` **ms** (954, 970-976).
  4. Publish, then return None (1035).
  5. The first message on exactly that topic is forwarded as `{"result": payload.decode('utf-8').replace("'", '"')}` (697-701, GW:1794-1811).
- **Timeout:** the gateway main loop unsubscribes and replies `{"success": false}` (GW:531-537, 1872-1877, 1834-1858).
- A response topic that also matches a data-mapping `topicFilter` is consumed as telemetry and the RPC times out. The mapping branch `continue`s first (646-662). This is pre-existing.
- **Placeholders:**
  - In topics: `${deviceName}`, `${methodName}`, `${requestId}`. Any remaining `${k}` is resolved by `replace_params_tags` with body = RPC params (TBU:181-194). The working form is therefore `${<key>}`, not `${params.<key>}` (see 1.5).
  - In `valueExpression`: `${deviceName}`, plus `${params}` and `${params.<jsonpath>}` resolved against `{'params': params}`. Each value is replaced with `orjson.dumps(value)` (992-1007), so strings get quotes.

**(d) Errors (exact text)**
- No matching config: `Config not found for {method_name} RPC method and {device_name} device` (1067).
- Reserved with empty params: `No 'params' found in reserved RPC request '{method_name}'` (1077). This one is not logged.
- Reserved with a schema mismatch: `The requested RPC either does not match with the schema {expected_schema} or incorrect value/values provided` (1089).
- Any exception: `Error during handling RPC request: {e}` (1056). Examples:
  - A connector RPC without `requestTopicExpression` gives `...'NoneType' object has no attribute 'replace'`.
  - Dict params on a reserved RPC give the Python TypeError text.
- `Error during publishing to target broker: {e}` (1018) is practically unreachable, because `_publish` catches everything and returns a bool (1103-1111).
- `Invalid RPC type request: {rpc_request}` (1051) is unreachable for the normal types.

### 1.2 Examples (built from the regex and code)

Reserved RPCs and configured RPCs are sent to the sub-device; connector RPCs are sent to the gateway device.

```json
{"method": "get", "params": "requestTopicExpression=sensor/SN-001/request/temp/${requestId};responseTopicExpression=sensor/SN-001/response/temp/${requestId};value=1;"}
```
Publishes `1`, waits up to 5000 ms, and replies `{"result":"<payload>"}`, or `{"success":false}` on timeout.

```json
{"method": "set", "params": "requestTopicExpression=sensor/SN-001/relay/set;value={\"state\":true};"}
```
Publishes `{"state":true}` as-is and replies `{"result":"success"}` immediately.

```json
{"method": "mqtt_sendCommand", "params": {"requestTopicExpression": "devices/${deviceName}/cmd/${methodName}", "valueExpression": "${params.command}", "deviceName": "SN-001", "command": "reboot", "qos": 1}}
```
Topic `devices/SN-001/cmd/sendCommand`, payload `"reboot"` (JSON-encoded), reply `{"result":"success"}`.

```json
{"method": "mqtt_getStatus", "params": {"requestTopicExpression": "gw/status/req/${requestId}", "responseTopicExpression": "gw/status/resp/${requestId}", "responseTimeout": 10000, "valueExpression": "${params.query}", "query": "all"}}
```
This is a two-way connector RPC. Do not add `deviceName` here (see 1.6, item 4).

A configured device RPC against the default `getRelay` entry: `{"method":"getRelay","params":{"pin":1}}` to device `SN-001`, id 42.
- Publishes to `sensor/SN-001/request/getRelay/42` and listens on `sensor/SN-001/response/getRelay/42`.
- The payload produced by `${params}` is currently `"{'pin': 1}"` (see 1.6, item 1).

### 1.3 Response format
- One-way success: `{"result": "success"}` (1026-1027).
- The `{"error": "error"}` branch (1028-1029) is unreachable, because `_publish` returns True/False and never None.
- Two-way: `{"result": "<raw payload string, ' replaced by \">"}`. The payload is **not** parsed as JSON.
- Two-way timeout: `{"success": false}`.
- Errors: `{"error": "<msg from 1.1(d)>"}`.

### 1.4 Config keys read by the RPC code

| key | default | where |
|---|---|---|
| `deviceNameFilter`, `methodFilter` | required (regex `search`) | 175, 1063-1064 |
| `requestTopicExpression` | required | 175, 983 |
| `valueExpression` | required | 175, 992-999 |
| `responseTopicExpression` | none (one-way without it) | 938 |
| `responseTimeout` | none, in ms | 939, 954 |
| `responseTopicQoS` | 1 | 958 |
| `qos` | 0 | 1016 |
| `retain` | False | 1015 |

### 1.5 Changes vs. old
- **CHANGED – reserved params parsing.** Old: split on `;`, each part `key=value`, any order, any keys merged into the config. That let callers pass `responseTimeout`, `qos`, `retain` and `responseTopicQoS`, but values could not contain `=` (old `mqtt_connector.py:1045-1058`). New: strict regex.
  - **REMOVED:** passing those extra keys; `get` timeout is now fixed at 5000 ms.
  - **REMOVED:** two-way `set`. Old code allowed a `set` with `responseTopicExpression`.
- **REMOVED:** `mqtt_get`/`mqtt_set` addressed to a device as reserved RPCs. Old code stripped the prefix. These are now classified as connector RPCs with string params, so no reply is sent.
- **NEW:** explicit errors for no matching config, empty params and schema mismatch. Old code logged `RPC not handled` (old 1068) or swallowed exceptions, so ThingsBoard timed out.
- **CHANGED:** the one-way ack was `{"success": true}`; it is now `{"result": "success"}`.
- **CHANGED:** the two-way reply was the payload, JSON-parsed when possible (old 690 plus the gateway's `loads`). It is now `{"result": "<string>"}`.
- **CHANGED:** in connector RPCs, `${methodName}` was the full `mqtt_xxx` (old 935/973). It is now `xxx`.
- **FIXED:** two-way connector RPCs. Old reply and timeout handling read `content["device"]` (old GW:1785, 1855), raised KeyError, and never replied.
- **FIXED:** the old gateway also sent an extra `{"success": false}` for every MQTT connector RPC, because the handler returned None (old GW:1665-1666).
- **CHANGED, likely regression:** `${params}` in `valueExpression`. Old code passed `value_type 'params'` and got the raw value, giving JSON like `{"pin":1}` (old 981-985). New code (992-997) uses the default `"string"`, which yields `str(params)`, which is then JSON-encoded again. Results:
  - `{"pin":1}` becomes `"{'pin': 1}"`
  - `1` becomes `"1"`
  - `true` becomes `"True"`

  `${params.<key>}` is unaffected.
- **CHANGED, likely regression:** topic placeholders. Old body was `{"id","method","params"}`, so `${params.<key>}` resolved. New `replace_params_tags_from_rpc_request` (TBU:191-194, added in 24de8483) uses the params as the body. Now `${<key>}` resolves and `${params.<key>}` stays literal.

### 1.6 Open questions
1. The `${params}` and topic `${params.x}` changes in 1.5: intended? The default config uses `"valueExpression": "${params}"`.
2. A one-way RPC reports `success` even when the broker is disconnected: the check is `result is not None` (1026) while `_publish` returns False (1104-1111). The same logic existed in old code (old 1016).
3. The two-way reply is now a string instead of parsed JSON. Is that intended?
4. A connector two-way RPC with `params.deviceName` is replied on the sub-device channel (`to_connector_rpc=False` at GW:1807; GW:1874), so the caller probably never receives it.
5. Reserved method matching is case-insensitive at classification (RQ:111) but case-sensitive at 1083, so `GET` is parsed with the SET schema.
6. The `responseTimeout` check at 1096-1098 is dead code: the regex can never produce that key.
7. The greedy regex silently accepts extra segments.
8. A leftover `${..}` in a topic combined with non-JSON string params raises at `loads` (TBU:122-123).
9. Two-way RPCs whose response topics resolve to the same string collide, because in-flight requests are keyed by topic (GW:543-546). Docs should recommend `${requestId}` in the response topic.

---

## 2. REST (`C/rest/`)

### 2.1 How RPCs are dispatched

**(a) RPC to connector**
- Method `rest_<name>` with object params, used directly as the config (`rest_connector.py:310-311`).
- `requestUrlExpression` and `valueExpression` must be non-None (338-341).
- `params.deviceName` feeds `${deviceName}`.
- Always synchronous: it waits for the HTTP response.

**(b) Reserved get/set**
- Regex, verbatim (`C/rest/constants.py:17-21`):
  - `RESERVED_GET_RPC_PATTERN = (r'^requestUrlExpression=(?P<requestUrlExpression>[^;]+)' r'(;HTTPMethod=(?P<HTTPMethod>[A-Za-z]+))?;?$')`
  - `RESERVED_SET_RPC_PATTERN = (r'^requestUrlExpression=(?P<requestUrlExpression>[^;]+);' r'(HTTPMethod=(?P<HTTPMethod>[A-Za-z]+);)?' r'value=(?P<value>.+?);?$')`
- Schema strings (constants.py:15-16): `requestUrlExpression=<url>;[HTTPMethod=<method>;]` and `requestUrlExpression=<url>;[HTTPMethod=<method>;]value=<value>;`
- **Pattern selection:** `is_set = method_name.lower() == 'set'`; everything else uses the GET pattern. Matching uses `fullmatch` (318-320).
- **Rules:**
  - The URL cannot contain `;` but may contain `=`.
  - `HTTPMethod` is optional, letters only, and the key is case-sensitive.
  - The trailing `;` is optional.
  - `get` does not accept `value`.
  - In `set`, the `;` after the URL is required, `HTTPMethod` must come before `value`, and the value runs to the end, minus one optional trailing `;`.
- **Config built** (356-360): None groups are dropped; `valueExpression` = `value` or `''`.
- **HTTP method default** is `"GET"` for both `get` and `set` (455).
- **Value conversion** (`json_rest_downlink_converter.py:70-77`): `dumps(literal_eval(value))` when the value is a Python literal (e.g. `22.5` stays `22.5`, `{"a": 1}` becomes `{"a": 1}`). Otherwise the raw text is sent (e.g. `on`, or JSON containing `true`).
- Reserved RPCs cannot set headers, so the body is sent with no Content-Type (505-511).

**(c) Device RPCs from config (`requestsMapping.serverSideRpc`)**
- An old top-level `serverSideRpc` is moved there by the adapter (`backward_compatibility_adapter.py:54-62`). Entries are loaded at 403-421.
- **Matching:** the first entry where `fullmatch(deviceNameFilter, device)` and `fullmatch(methodFilter, method)` (349-354).
- Always synchronous.

**Placeholders** (converter 47-68):
- URL: `${restId}` (the RPC id; **not** `${requestId}`), `${methodName}`, `${deviceName}` (URL-quoted), and `${params.<path>}` (via `replace_params_tags`, line 60).
- Body: the same, but `${deviceName}` is raw. `${params}` and `${params.<path>}` are replaced with `str(value)`, then the `literal_eval`/`dumps` step runs.
- A URL without a scheme gets an `http://` prefix (429-432).

**(d) Errors (exact text)**
- No matching config: `Neither of configured device rpc methods match with {method_name}` (333).
- Missing keys: `RPC '{method_name}' requires {', '.join(missing_params)} param(s)` (341).
- Empty params on a reserved RPC: `No 'params' found in reserved RPC request '{method_name}'` (316).
- Schema mismatch: `The requested RPC does not match with the schema: {expected_schema}` (324).
- HTTP/transport errors: `{result['error']}{code}` with `code = " (code: N)"` when present (375-377). Sources:
  - `Timeout (code: 408)` (553-555)
  - the requests exception text (556-558)
  - `<reason> (code: <status>)` for non-2xx (583-584)
- `Cannot form request for RPC {rpc_request}` (372).
- `Error processing RPC request {rpc_request}: {e}` (302).
- `Invalid RPC type request: {rpc_request}` (300).

### 2.2 Examples

```json
{"method": "get", "params": "requestUrlExpression=http://127.0.0.1:5000/device/${deviceName}/temperature;HTTPMethod=GET;"}
```

```json
{"method": "set", "params": "requestUrlExpression=http://127.0.0.1:5000/setpoint;HTTPMethod=POST;value={\"setpoint\": 22.5};"}
```
Body `{"setpoint": 22.5}`, sent without a Content-Type header.

```json
{"method": "rest_setSetpoint", "params": {"requestUrlExpression": "http://127.0.0.1:5000/device/${deviceName}/setpoint", "HTTPMethod": "POST", "valueExpression": "{\"setpoint\": ${params.value}}", "deviceName": "Thermostat 1", "value": 22.5, "httpHeaders": {"Content-Type": "application/json"}, "timeout": 5}}
```

A configured device RPC against the default `echo` entry: `{"method":"echo","params":{"a":1}}` sends a GET to `http://127.0.0.1:5001/<device>` with JSON body `{"a": 1}`.

### 2.3 Response format
- Success: `{"result": <response.json()>}`. If the body is not JSON, `{"result": "<body text>"}` (bytes are decoded as UTF-8, 379-381).
- Error: `{"error": "<msg>"}`.
- No separate RPC timeout exists; the limit is the HTTP `timeout`.

### 2.4 Config keys read by the RPC code

| key | default | where |
|---|---|---|
| `deviceNameFilter`, `methodFilter` | required (`fullmatch`) | 351-352 |
| `requestUrlExpression`, `valueExpression` | required | 338 |
| `HTTPMethod` (alias `httpMethod`) | `"GET"` | 455 |
| `timeout` | 10 s | 451 |
| `allowRedirects` | False | 458 |
| `SSLVerify` | True | 459 |
| `security.type` | `anonymous` | 437-447 |
| `httpHeaders` (dict or JSON string) | `{}` | 464-466 |
| `extension` (custom converter) | none | 407-411 |

- `security.type` values: `basic` uses `username`/`password`; `cert` uses `cert`/`key`.
- Content-Type `multipart/form-data` or `application/json` changes how the body is built (471-497).
- `responseTimeout` and `tries` are **not read**.

### 2.5 Changes vs. old
- **CHANGED – reserved parsing.** Old: split on `;` into `key=value` pairs, any keys, passed straight into the request config (old `rest_connector.py:301-309`). New: the regex accepts only `requestUrlExpression`, `HTTPMethod`, and `value` (set only).
  - **REMOVED:** passing `httpHeaders`, `timeout`, etc., and `value` on `get`.
  - **FIXED:** URLs containing `=`. Old split dropped them.
- **CHANGED – reply shape.** Old was `{"result": <first element>}`, including errors, e.g. `{"result": {"error": "Timeout", "code": 408}}` (old 323, 341). New: `{"error": "Timeout (code: 408)"}`; success is `{"result": ...}`.
- **NEW:** error replies for no matching config, missing keys and schema mismatch. Old code was silent and ThingsBoard timed out.
- **CHANGED – connector RPC.** Old code supported only `rest_get`/`rest_set` with the string format, took the device name from the params string (old 290-294), and replied through the device path. New: `rest_<any>` with object params used as the config.
- **REMOVED:** `rest_get`/`rest_set` addressed to a device.
- **NEW:** `httpMethod` accepted as an alias for `HTTPMethod` (455).
- **FIXED:** the converter now catches `ValueError` (converter line 74). Previously, non-literal bodies such as `on` or JSON with `true` aborted the RPC.
- **FIXED:** byte bodies are decoded before replying.

### 2.6 Open questions
1. A reserved `set` without `HTTPMethod` sends GET. Is that intended?
2. A 2xx JSON body that contains an `error` key is reported as an RPC error (375-377).
3. The `Cannot form request...` message (372) is effectively unreachable. When the request cannot be formed, `json.dumps(request_dict)` at 542 raises on the function object, so the reply becomes `Error processing RPC request ...: Object of type function is not JSON serializable`.
4. The default `rest.json` at HEAD uses `${requestId}`, `responseTimeout` and `tries`, none of which REST reads. `${requestId}` stays literal in the URL.
5. If the converter fails (returns None), the reply is `... 'NoneType' object is not a mapping` (345).

---

## 3. REQUEST (`C/request/`)

### 3.1 How RPCs are dispatched

**(a) RPC to connector**
- Method `request_<name>`, object params, passed through `__build_rpc_config` (`request_connector.py:168-170, 294-311`).
- Defaults from that function:

| key | default |
|---|---|
| `responseTimeout` | 1 |
| `httpMethod` | `"GET"` |
| `requestValueExpression` | `"${params}"` |
| `responseValueExpression` | None |
| `timeout` | 0.5 |
| `tries` | 3 |
| `httpHeaders` | `{"Content-Type": "application/json"}` (a JSON string is accepted) |

- `requestUrlExpression` is required: `requestUrlExpression parameter is required. Please check your RPC params.` (309).
- Always synchronous.

**(b) Reserved get/set**
- Regex, verbatim (`C/request/constants.py:17-21`):
  - `RESERVED_GET_RPC_PATTERN = (r'^requestUrlExpression=(?P<requestUrlExpression>[^;]+)' r'(;httpMethod=(?P<httpMethod>[A-Za-z]+))?;?$')`
  - `RESERVED_SET_RPC_PATTERN = (r'^requestUrlExpression=(?P<requestUrlExpression>[^;]+);' r'(httpMethod=(?P<httpMethod>[A-Za-z]+);)?' r'value=(?P<value>.+?);?$')`
- Schema strings: `requestUrlExpression=<url>;[httpMethod=<method>;]` and `requestUrlExpression=<url>;[httpMethod=<method>;]value=<value>;`
- The key is lowercase `httpMethod`, unlike REST's `HTTPMethod`.
- Same rules as REST: `fullmatch`, `is_set` via `.lower()` (177-179).
- `value` becomes `requestValueExpression`; it is `''` for `get` (288-292). Then the `__build_rpc_config` defaults apply, so the reserved timeouts are 1 s and 0.5 s.

**(c) Device RPCs from config (top-level `serverSideRpc`)** (347-354)
- **Matching:** `fullmatch` on `deviceNameFilter` and `methodFilter` (211-216).
- The raw entry is used, **without** `__build_rpc_config` defaults:
  - `responseTimeout` defaults to 5 (236).
  - `timeout` defaults to 1 (417).
  - `httpMethod` defaults to `"GET"` (419).
  - `httpHeaders` is used as-is (429-430).
  - `allowRedirects` defaults to False (422).
  - `requestValueExpression` is **required**: the converter reads it with `[...]`.

**Common to all three kinds**
- **URL:** relative paths are joined to the connector-level `host` (362-367, 415). `SSLVerify` (connector-level) defaults to False (82). `security` is connector-level and only `basic` is supported (70-73, 92-105).
- **Placeholders** (`json_request_downlink_converter.py:46-67`):
  - `${requestId}`, `${methodName}`, `${deviceName}`. `${deviceName}` is URL-quoted in both the URL **and** the body.
  - `${params.<path>}` in the URL.
  - `${params}` and `${params.<path>}` in the body, followed by the `literal_eval`/`dumps` step (69-76).
- **Execution** (223-286): the HTTP call runs in a thread with `join(responseTimeout)`.
  - Non-2xx is an error.
  - A JSON body has `responseValueExpression` applied (a `${..}` template, or a literal).
  - A non-JSON body is returned as text, and `responseValueExpression` is ignored.

**(d) Errors (exact text)**
- `Neither of configured device rpc methods match with {method_name}` (192)
- `No 'params' found in reserved RPC request '{method_name}'` (175)
- `The requested RPC does not match with the schema: {expected_schema}` (183)
- `Failed to convert RPC request {rpc_request}` (201)
- `Rpc timeout` (245)
- `No response received from RPC execution` (249)
- `{response.reason} (code: {response.status_code})` (253)
- `Thread execution error: {e}` (241)
- `Response parsing error {e}` (284)
- `No values found for responseValueExpression: {response_expression} in RPC response. Please check your configuration.` (274)
- `Error processing RPC request {rpc_request}: {e}` (160)
- `Invalid RPC type request: {rpc_request}` (158)

### 3.2 Examples

```json
{"method": "get", "params": "requestUrlExpression=/api/v1/temperature;httpMethod=GET;"}
```
Empty body; header `Content-Type: application/json`.

```json
{"method": "set", "params": "requestUrlExpression=/api/v1/setpoint;httpMethod=POST;value={\"setpoint\": 22.5};"}
```

```json
{"method": "request_getStatus", "params": {"requestUrlExpression": "/api/v1/status/${deviceName}", "httpMethod": "GET", "requestValueExpression": "", "responseValueExpression": "${status}", "responseTimeout": 3, "timeout": 2, "deviceName": "SN-001"}}
```
For a JSON body `{"status": "ok"}` the reply is `{"result": "ok"}`.

### 3.3 Response format
- Success: `{"result": <JSON body | text | string from responseValueExpression>}` (207-209).
- Error: `{"error": "<msg>"}`.

### 3.4 Config keys read by the RPC code
- `deviceNameFilter`, `methodFilter`, `requestUrlExpression`, `requestValueExpression`, `responseValueExpression`, `responseTimeout` (s), `timeout` (s), `httpMethod`, `httpHeaders`, `allowRedirects`, `converter` (custom class).
- Connector-level: `host`, `SSLVerify`, `security`.
- `tries` is read at 304 but never used.

### 3.5 Changes vs. old
- **CHANGED – reply shape.**
  - Device and reserved RPCs: success was `{"result": {"value": <body>}}`, error `{"result": {"error": "<msg>"}}` (old 252, 255).
  - Connector RPCs: the reply was a list, `[{"success": true, "result": ..., "status": N}]` or `[{"success": false, "error": ..., "status": N}]` (old 216, 226-237).
  - Now every kind replies `{"result": ...}` or `{"error": ...}`.
- **NEW:** a non-2xx HTTP response is an error, `<reason> (code: N)`. Old code treated it as success.
- **CHANGED – reserved parsing.** Old: split on `;`, keys stripped, any keys accepted (`responseTimeout`, `timeout`, `tries`, `httpHeaders`, `responseValueExpression`) (old 319-333). New: only the regex keys; whitespace is no longer tolerated.
  - **REMOVED:** those extra keys.
  - **CHANGED:** `get` used to send the whole params string as the body (default `${params}`); it now sends an empty body.
- **CHANGED – error texts.**
  - No match was `No matching RPC request configuration found for this RPC. Please check your` (old 176).
  - A missing URL was `Please check your RPC params. requestUrlExpression parameter is required for reserved RPCs. Please check your RPC params.` (old 192, 363).
- **CHANGED – classification.** Old: a connector RPC only when no device was given, and only with a single `_` (old `entities/rpc_request.py:42-46`, now deleted). New: `request_<anything>`, device ignored.
- **FIXED:** the converter now catches `ValueError` (converter line 73).

### 3.6 Open questions
1. The default `request.json` `echo` entry has no `requestValueExpression`, so it fails with `Failed to convert RPC request ...`. This was broken before the range too.
2. The `No values found...` error (274) is unreachable because of `expression_instead_none`. An unresolved path returns the expression text literally.
3. With the default timeouts (HTTP 0.5 s < `responseTimeout` 1 s), a slow server produces `No response received from RPC execution` rather than `Rpc timeout`. After `Rpc timeout`, the request thread keeps running.
4. A connector RPC's default `${params}` body sends the entire params object, including `requestUrlExpression` etc., even on GET.
5. `${deviceName}` is URL-quoted inside the body (converter line 56).
6. Reserved key naming is inconsistent: `httpMethod` here, `HTTPMethod` in REST.

---

## 4. Shared issues (also in 10-gateway-core.md)
- **Connector not found** (GW:1666-1672): `dumps(rpc_request)` raises before the `return`, and the return value is a str that then gets `.to_connector_rpc` assigned (GW:1650-1651). Either way, no reply is sent.
- **Method-name collisions:**
  - Sub-device method names starting with `<connectorType>_` (e.g. `request_data`) are routed as connector RPCs (RQ:101-107).
  - Names in `RESERVED_RPC_NAMES` (`sendCommand`, ...) or starting with `gateway_` are routed to the gateway (RQ:46, 89-98).
- **`get` without a device:** RQ:112 parses as `get or (set and device)`, so a `get` with no `device` is classified as RESERVED with `device_name=None`.
