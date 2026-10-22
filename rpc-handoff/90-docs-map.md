# Map of RPC documentation in the IoT Gateway docs

All paths are relative to `/home/oleksandr/Thingsboard_remote_work/thingsboard.io`. Line numbers are in the include files, because that is where the content lives.

## 1. How the docs are organised

- **Thin wrappers plus includes.** Each page under `src/content/docs/docs/iot-gateway/**` is an 8-line stub. It only does `import X from '@includes/docs/iot-gateway/<same path>.mdx'` and `<X product={Products.GW}/>`.
- **One include per page.** All content is in `src/content/_includes/docs/iot-gateway/<same path>.mdx`. No gateway include is reused by more than one page, and no other product (CE/PE/Edge) imports them. Only the include file needs editing.
- **One page per connector:** `config/<connector>.mdx` (mqtt, modbus, opc-ua, bacnet, s7, rest, request, ble, can, ftp, knx, odbc, ocpp, snmp, socket, xmpp). The sidebar is defined in `astro.sidebar.ts:3531-3608`.
- **There are two RPC pages, and both are under Features:**
  - `features/reserved-rpc` ("Built-in GET/SET RPC Methods"): reserved get/set for every connector, as tabs.
  - `features/service-rpc-methods` ("Service RPC Methods"): the `gateway_*` commands.
- **Two connector page styles:**
  - Big UI-driven pages (mqtt, modbus, opc-ua, bacnet) follow "Requests mapping → RPC subsection → Usage examples tabs (RPC to Device / Reserved RPCs / …) → Advanced configuration → Device RPC methods table".
  - Smaller config-reference pages (rest, request, ble, can, ftp, knx, odbc, ocpp, snmp, socket, xmpp, s7) have a `Section/Subsection "serverSideRpc"` with a parameter table and JSON.
- **Redirects that depend on current paths/anchors** (`src/data/redirects.ts:310-313`):
  - `how-to-use-gateway-rpc-methods` → `/docs/iot-gateway/features/service-rpc-methods/`
  - `how-to-use-get-set-rpc-methods` → `/docs/iot-gateway/features/reserved-rpc/`
  - `how-to-use-rpc-modbus-connector` → `/docs/iot-gateway/config/modbus/#subsection-rpc-requests`. This one breaks if that Modbus heading is renamed.
- **Adjacent page, outside the gateway tree:** the Gateway MQTT API RPC wire format is in `src/content/_includes/docs/reference/gateway-api/rpc.mdx`. It is imported by the `docs/`, `docs/pe/`, `docs/paas/` and `docs/paas/eu/` `reference/gateway-api/rpc.mdx` pages.
  - Request: `{"device": "Device A", "data": {"id": 1, "method": "toggle_gpio", "params": {"pin": 1}}}`
  - Reply: `{"device": "Device A", "id": 1, "data": {"success": true}}`

## 2. Conventions used in RPC examples

- **Commands as typed in the RPC debug terminal** go in ` ```bash ` blocks, e.g. `get type=16int;...;`, `gateway_ping`, `multiply [3,4]`.
- **Responses** follow a bare `Response:` line, in a ` ```json ` block, usually one line, e.g. `{"result": {"value": 13}}`. A screenshot (`<ImageGallery images={[{src, alt, caption}]} />`) follows the response.
- **Parameter tables** use `| Parameter | Description |` or `| Parameter | Default | Description |`. Advanced tables use JSON paths, e.g. `devices[].serverSideRpc[].method`.
- **Full connector configs** are ` ```json ` blocks. MQTT uses ` ```json maxLines=15 collapsible `.
- **Tabs** come from `@components/Tabs.astro` / `TabItem.astro`, with no `syncKey`. reserved-rpc nests Tabs (S7 → PLC / Logo!).
- **UI walkthroughs** use Starlight `<Steps>`. Inside an indented `<TabItem>`, opc-ua wraps them in explicit `<ol><li>`.
- **Notes** use `<Aside type="note">`.
- **Cross-links** use `<DocLink product={props.product} path="features/reserved-rpc/">the guide</DocLink>`.
- **Recurring boilerplate:** "Also, every telemetry and attribute parameter has built-in GET and SET RPC methods out of the box…" and "The RPC Debug Terminal is used only for example purpose…".
- **Screenshot locations:**
  - `src/assets/images/gateway/get-set-connector-rpc/*`
  - `gateway-rpc-{ping,devices,restart,reboot}.png`
  - `<connector>-connector/examples/rpc-to-device-*.png`, `reserved-rpc-result-*.png`, `rpc-to-connector-*.png`
  - `ftp-rpc-*.png`

## 3. Gateway-level RPC

### `features/service-rpc-methods.mdx` (229 lines)
- **"Step 1. Set Up the RPC Debug Terminal"** (15-104): a UI walkthrough.
- **"Step 2. Service RPC Methods"** (106-229): "Every command prefixed with `gateway_` is interpreted as a service command…"
  - `### gateway_ping` (111-134): `gateway_ping` → `{"code": 200, "resp": "pong"}`
  - `### gateway_devices` (136-162): → `{"code": 200, "resp": {"Device Number One": "OPC-UA Connector"}}`
  - `### gateway_restart` (164-186): `gateway_restart 60` → `{"success": true}`
  - `### gateway_reboot` (188-213): `gateway_reboot 60` → `{"success": true}`. Note at 192-195: works only when started as a Python module and the user has reboot permissions.
  - `### gateway_remove_provisioned_credentials` (215-229): → `{"code": 200, "resp": "Provisioned credentials file removed successfully."}`
- **Not documented:** `gateway_stats`, `gateway_update`, `gateway_version`, `gateway_latency` and `getCommandStatus` do not appear anywhere in the repo. Yet `remote-configuration.mdx:426` lists the widget commands "Ping, Stats, Devices, Update, Version, Restart, Reboot".
- **Two response shapes:** `{"code":200,"resp":...}` vs `{"success": true}`.

### Pages that link to or describe gateway RPC
- **`features/provisioning.mdx:41-44`** "Resetting Provisioned Credentials" links to `/docs/iot-gateway/features/service-rpc-methods/#gateway_remove_provisioned_credentials`. This anchor depends on the heading text.
- **`features/remote-configuration.mdx`:**
  - 110: Navigation Panel item "**RPC** — gateway RPC sending page".
  - 296: connectors-list table row "RPC | Opens the RPC dashboard for sending commands through the gateway to this connector". This is the UI entry for RPC to connector.
  - `### RPC` (408-432): three widgets.
    - **Service RPC:** "Command | One of the service RPC methods: Ping, Stats, Devices, Update, Version, Restart, Reboot", plus Timeout and Response.
    - **RPC Logs** and **RPC debug terminal**.
- **`features/remote-shell.mdx`** (86 lines): UI-only (enable toggle, open terminal, run `ls`). It has no RPC method names, request/response formats or `getCommandStatus`. `config/general.mdx:93` shows only `"remoteShell": false` in the JSON example, with no parameter-table row.
- **`features/device-renaming.mdx`:**
  - "Device Renaming" (16-32): `{"method": "gateway_device_renamed", "params": {"Old device name": "New device name"}}`
  - "Device Removal" (34-50): `{"method": "gateway_device_deleted", "params": "Removed device name"}`
  - "RPC Timeout" (52-56): 1-day TTL persistent RPC.
- **`features.mdx:18-24`** has the landing cards "Built-in GET/SET RPC Methods" and "Service RPC Methods".

### Custom connector API (`custom/methods-and-datatypes.mdx`)
- **`#### send_rpc_reply`** (26-40): args `device`, `req_id`, `content`, `success_sent`, `wait_for_publish`, `quality_of_service` (`0`), `to_connector_rpc` (`False`, "Set to `True` if the RPC was handled by the connector itself rather than forwarded to a device").
- **Connector interface table** (412): `server_side_rpc_handler(content)`.
- **Converter interface** (432-442): the uplink `config` holds the RPC response config; the downlink converts the RPC request.

### `custom/serial-connector.mdx`
- Data-flow diagram at 15.
- Config at 73-86: `"serverSideRpc": [{"method": "setValue", "type": "int", "withResponse": true, "responseType": "string", "responseUntilDelimiter": "\r", "responseTimeoutSec": 5}, ...]`.
- Field table at 115.
- `handle_rpc_request` code at 249-289.
- `server_side_rpc_handler` code at 498-519: reads `content["data"]["method"/"id"/"params"]` and calls `self.__gateway.send_rpc_reply(device=..., req_id=..., content=result, wait_for_publish=True, quality_of_service=1)`.
- Method reference at 780 and 789-790.

## 4. Reserved GET/SET hub: `features/reserved-rpc.mdx` (926 lines, one `<TabItem>` per connector)

| Tab | Lines | Request strings (exact) | Responses shown |
|---|---|---|---|
| OPC-UA | 12-86 | `get ns=3;i=1001;` · `set ns=3;i=1001; value=23;` · `set ns=3;i=1008; value=T3000;` | `{"result": 25.34}`, `{"success": "true", "code": 200}` |
| Modbus | 88-179 | `get type=<type>;functionCode=<functionCode>;objectsCount=<objectsCount>;address=<address>;` · `set ...;address=<address>;value=<value>;` · e.g. `set type=16int;functionCode=6;objectsCount=1;address=2;value=80;` | `{"result": {"value": 13}}`, `{"result": {"value": "80"}}`, `{"result": {"value": 80}}` |
| MQTT | 181-250 | `get requestTopicExpression=<requestTopic>;responseTopicExpression=<responseTopic>;value=<value>;` · `set requestTopicExpression=<requestTopic>;value=<value>;` | none (screenshots only) |
| BACnet | 252-345 | `get objectType=<objectType>;objectId=<objectId>;propertyId=<propertyId>;` · `set ...;priority=<priority>;value=<value>;` (relinquish if `value` is omitted) | `{"result": "30.5"}`, `{"result": "{\"status\":\"ok\"}"}` |
| S7 → PLC | 352-466 | `get type=data;dbNumber=<dbNumber>;start=<start>;dataType=<dataType>;size=<size>;bit=<bit>;` · `get type=tag;tag=<tag>;` · `set type=data;...;value=<value>;` · `set type=tag;tag=DB1.DBD104:REAL;value=12345;` | `{"result": true}`, `{"result":"Successfully wrote value bytearray(b'\\x00') to device S7 PLC for RPC method set"}` |
| S7 → Logo! | 468-533 | `get type=vm;vmAddress=<vmAddress>;` · `set type=vm;vmAddress=<vmAddress>;value=<value>;` | `{"result":12}`, `{"result":"Successfully wrote value 35 to device S7_LOGO for RPC method set"}` |
| REST | 537-624 | `get requestUrlExpression=<url>;value=<value>;` · `set requestUrlExpression=<url>;value=<value>;HTTPMethod=<method>;` | `{"result": {"light-level": 30}}`, `{"result": {"status": "ok"}}` |
| Request | 626-712 | `get requestUrlExpression=<path>;` · `set requestUrlExpression=<path>;value=<value>;httpMethod=<method>;` | `{"result": "{\"light-level\":30}"}`, `{"result": "{\"status\":\"ok\"}"}`, `{"result": {"light-level": 80}}` |
| FTP | 714-799 | `get filePath=<filePath>;` · `set filePath=<filePath>;value=<value>;` | `{"result": 30}`, `{"result": "{\"success\": true}"}` |
| OCPP | 801-882 | `get component=<component>;variable=<variable>` · `set component=<component>;variable=<variable>;value=<value>` (no trailing `;`). Optional params: `componentInstance`, `variableInstance`, `evseId`, `timeout` (default 5) | none. Notes that Rejected / UnknownComponent / UnknownVariable are possible |
| Socket | 884-925 | SET only: `set address=<address>;port=<port>;value=<value>;` | `{"result": "ok"}` |

There are no tabs for KNX, BLE, CAN, ODBC, SNMP or XMPP. Note that `knx.mdx:354` claims a built-in `set` exists.

## 5. Per connector

### Modbus (`config/modbus.mdx`)
- **Enum mapping** (326-392):
  - Line 334: "Uplink `RPC to Device` calls can use enum mapping".
  - The RPC example at 373-387 uses `"method": "getStatus"`, but every other Modbus RPC config uses `"tag"`.
- **`### Requests mapping`** (1059-1075): lists "Reserved GET/SET methods" and "Configurable RPC methods to device".
- **`#### Subsection "RPC requests"`** (1140-1203): fields Method name / Type / Function code / Objects count / Address. This is the redirect target anchor.
- **`#### Usage examples`** (1205):
  - **"RPC to Device"** tab (1373-1520): the command is `getTemperature`; the response is a screenshot only. Config: `"rpc": [{"tag": "getTemperature","type": "16int","address": 0,"objectsCount": 1,"functionCode": 3}]`.
  - **"Reserved RPCs"** tab (1521-1668):
    - `get type=bits;functionCode=1;objectsCount=1;address=1;` → `{"result":{"value":false}}`
    - `set type=bits;functionCode=5;objectsCount=1;address=1;value=1;` → `{"result":{"value":"1"}}`
    - `get type=bits;functionCode=3;objectsCount=1;address=1;` → `{"result":{"value":true}}`. This read-back uses FC3 on a coil, which looks like a docs bug.
- **`##### Device RPC methods`** (1869-1894): the table path prefix is `server.slaves[].rpc[]` although this is the master section. Fields: tag, type, functionCode, objectsCount, address, timeout (5 s), bitTargetType.
- **Slave `##### RPC methods`** (2340-2373): `slave.values[].<register_type>.rpc[]`. Its table descriptions are copy-pasted from attribute updates.

### S7 (`config/s7.mdx`)
- **Full config `serverSideRpc`:** PLC at 119-140 (`getRelay`/`setRelay`, `requestType` read/write, `type: data`); Logo at 176-189 (`setLight`/`getLight`, `type: vm`).
- **`## Requests mapping`** (423-432).
- **`### RPC methods`** (529-651):
  - Lines 532-536 list three approaches: "Configurable RPC to device", "Reserved GET/SET RPCs" (links to the hub), and "**Connector RPC** - ad-hoc requests sent directly to the S7 connector…". Connector RPC has no section or example anywhere.
  - Tabs "Siemens PLCs" (543-617: data and tag tables plus JSON, `set_light`/`get_light`) and "Siemens Logo" (619-649: `vmAddress`).
- **No reserved examples on this page.** They exist only in the hub.

### BACnet (`config/bacnet.mdx`)
- **`## Requests mapping`** (707-721).
- **`### RPC methods`** (782-841): Method, Request Type `writeProperty`/`readProperty`, Object ID, Object Type, Property ID, Request Timeout.
- **"RPC to Device"** tab (996-1133): the command is `getTemperature`. Config `{"method": "getTemperature","objectType": "analogValue","objectId": 1,"propertyId": "presentValue","timeout": 5000,"requestType": "readProperty"}`.
- **"Reserved RPCs"** tab (1134-1265):
  - `get objectType=binaryInput;objectId=1;propertyId=presentValue;` → `{"result": {"value":  "inactive"}}`
  - `set objectType=binaryInput;objectId=1;propertyId=presentValue;value=1;` → `{"result": {"value": 1}}`
  - The response shapes conflict with the hub (`{"result": "30.5"}`).
- **`#### Device RPC methods`** (1508-1536): includes `priority` (1-16) and `timeout` (default 5000).

### MQTT (`config/mqtt.mdx`)
- **`## Requests mapping`** (1291-1320): Reserved GET/SET, Configurable, "One Way and Two Way RPC methods".
- **`### Server side RPC commands`** (1556-1652): Request type, Device name filter, Method filter, Request topic expression, Value expression, Response topic expression, Response topic QoS, Response timeout.
- **"Reserved RPCs"** tab (2433-2586), screenshots only:
  - Two-way get: `get requestTopicExpression=data/get_light_level;responseTopicExpression=data/response;value=${params};`
  - One-way get: `get requestTopicExpression=data/get_light_level;value=${params};`
  - Set: `set requestTopicExpression=data/set_light_level;value=90;`
- **"RPC to Device"** tab (2587-2799):
  - Commands: `echo {"deviceName":"SN-001", "methodName":"echo"}` and `no-reply {"deviceName":"SN-001", "methodName":"no-reply"}`.
  - Topics: `sensor/${deviceName}/request/${methodName}/${requestId}` and the matching `response` topic.
  - Config at 2776-2794 uses `"type": "twoWay"` / `"oneWay"`.
- **`#### Device RPC methods`** (3134-3181): the table does not list the `type` field even though the JSON uses it.

### OPC-UA (`config/opc-ua.mdx`)
- **`## Requests mapping`** (1368-1383): Reserved GET/SET, "**RPC method to connector**", Configurable.
- **`### Subsection "RPC methods"`** (1445-1501): Method name, Arguments.
- **"RPC to Device"** tab (1999-2169): `multiply`, then `multiply [3,4]`. Responses are screenshots. Config `"rpc_methods": [{"method": "multiply","arguments": [{"type": "integer","value": 5},...]}]`.
- **"Reserved RPCs"** tab (2170-2305):
  - `get ns=3;i=1012;` → `{"result":  {"value":  false}}`
  - `set ns=3;i=1012; true` → `{"result":  {"value":  true}}`
  - This conflicts with the hub's `set ... value=23;` syntax and its `{"success": "true", "code": 200}` response. The hub's sample config also uses the old `"path"` key.
- **"Reserved RPCs to foreign nodes"** tab (2306-2442):
  - `get Root\\.Objects\\.DemoDeviceInfo\\.TextMessage;` → `{"result":{"value":"HI"}}`
  - `set Root\\.Objects\\.DemoDeviceInfo\\.TextMessage; New Message` → `{"result":{"value":"New Message"}}`
- **"RPC to Connector"** tab (2443-2579): this is the only full RPC-to-connector walkthrough in the docs. The note says "RPC To Connector will execute the method on every device that has the OPC-UA connector configured". It uses the connector "RPC" icon with Method `set_relay` and Arguments `true`/`false`; responses are screenshots only.
- **`#### Device RPC methods`** (2799-2829): `mapping[].rpc_methods[].method/arguments[].type/value/timeout` (default 5000).

### REST (`config/rest.mdx`)
- **`### Subsection "serverSideRpc"`** (552-609): `deviceNameFilter`, `methodFilter`, `requestUrlExpression`, `responseTimeout`, `HTTPMethod`, `valueExpression`, `timeout`, `tries`, `httpHeaders`, `security.type`. There is a with-reply / without-reply note.
- **Lines 606-609:** "required parameters are `requestUrlExpression`, `responseTimeout`, `HTTPMethod`, and `valueExpression`" for reserved methods. The hub's GET uses only `requestUrlExpression` and `value`.
- **Full config** at 82 (`"serverSideRpc": []`).

### Request (`config/request.mdx`)
- **`## Section "serverSideRpc"`** (398-450): same fields as REST, but spelled **`httpMethod`** (REST uses `HTTPMethod`).
- **Full config** at 115-140.

### Socket (`config/socket.mdx`)
- **`### Subsection "RPC methods"`** (440-510), with Basic/Advanced tabs. Fields: `methodRPC` (`rpcMethod1`), `withResponse`, `methodProcessing` (`write`), `encoding`.
- **Lines 508-510:** reserved `set` "required parameters are `withResponse`, `methodProcessing`, and `encoding`". This contradicts the hub's `set address=...;port=...;value=...;`.

### XMPP (`config/xmpp.mdx`)
- **`### Subsection "serverSideRpc"`** (172-192): `methodRPC`, `withResponse`, `valueExpression`.
- **Full config** at 57-63.
- No reserved RPC is mentioned.

### CAN (`config/can.mdx`)
- **Device params** (153-159): `enableUnknownRpc`, `overrideRpcConfig`, `serverSideRpc`. The downlink converter note is at 186-187.
- **`#### Subsection "serverSideRpc"`** (352-434): without-parameters mode (`dataInHex`) vs with-parameters mode.
  - Fields: `method`, `response`, `nodeId`, `isExtendedId`, `isFd`, `bitrateSwitch`, `data*`.
  - RPC payload examples: `{"device": "Car", "data": {"method": "setLightLevel", "params": { "value": 70 }}}` and `setSpeed` with `dataExpression`.
- **Full config** at 27 and 79-100.

### BLE (`config/ble.mdx`)
- **`#### Subsection "serverSideRpc"`** (273-291): `methodRPC`, `withResponse`, `characteristicUUID`, `methodProcessing` (`read`/`write`/`notify`).
- **Full config** at 100-106.

### KNX (`config/knx.mdx`)
- **`## Section "serverSideRpc"`** (330-356): `requestType`, `deviceNameFilter`, `method`, `dataType`, `groupAddress`.
- **Lines 354-356** claim a built-in `set`, but the hub has no KNX tab.
- **Full config** at 67-82.

### FTP (`config/ftp.mdx`)
- **`## Section "serverSideRpc"`** (353-425): `deviceNameFilter`, `methodFilter` (`read`/`write`), `valueExpression`.
- **"Read example"** (378-393) and **"Write example"** (395-425) use the "FTP connector RPC page" (connector RPC UI). They are screenshots only, with no text payloads.
- **Full config** at 57-67.

### ODBC (`config/odbc.mdx`)
- **`## Section "serverSideRpc"`** (300-377): `enableUnknownRpc`, `overrideRpcConfig`, `methods` (name-only / config / combining). Method fields: `name`, `query`, `args`, `result`.
- **RPC payload example:** `{"device": "ODBC Device 1", "data": {"method": "procedureOne", "params": {"args": [...]}}}`.
- **Full config** at 59-67.

### SNMP (`config/snmp.mdx`)
- **`### Section "serverSideRpcRequests"`** (143-216): `requestFilter`, `method`, `oid`, plus a with-reply / without-reply note.
- **`### set`** (388-404) and **`### multiset`** (406-465): the RPC form uses a `mappings` array and `${params.temperature}`.
- **Line 481:** `type` is required for set/multiset.
- **Full config** at 47-51.

### OCPP (`config/ocpp.mdx`)
- **`### Subsection "serverSideRpc"`** (302-344): `methodRPC`, `action` (falls back to `DataTransfer` if omitted), `withResponse`, `timeout` (5), `valueExpression`. Examples: `startTransaction`, `clearCache`, `changeAvailability`.
- **Line 309** links to the hub.
- **Full config** at 73-79 (`methodRPC: "rpc1"`); the field table is at 233.

## 6. Inconsistencies already present in the docs (before checking against code)

1. **OPC-UA SET syntax and response shape differ** between the hub and `opc-ua.mdx`.
2. **BACnet response shapes differ** between the hub and `bacnet.mdx`.
3. **Socket and REST "required parameters" text** contradicts the hub's param strings.
4. **`HTTPMethod` (REST) vs `httpMethod` (Request).**
5. **Modbus:**
   - The reserved read-back uses FC3 on a coil.
   - The advanced table prefix is `server.slaves[]` in the master section.
   - The enum RPC example uses `method` instead of `tag`.
6. **MQTT** advanced table is missing `type`.
7. **"Connector RPC" / RPC to connector** is documented only in OPC-UA. S7 mentions it without an example, and FTP shows only screenshots.
8. **Missing service methods:** Stats / Update / Version appear in the UI list but have no method docs. There are no remote-shell RPC command docs.
9. **KNX** claims a reserved `set` but has no hub tab.
10. **Service RPC response shapes** are mixed: `{"code":200,"resp":...}` vs `{"success": true}`.
