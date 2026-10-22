# Gateway-level RPC spec (HEAD e4e27ef2, range 8c64fa35^..HEAD)

**Abbreviations:**
- `svc` = `thingsboard_gateway/gateway/tb_gateway_service.py` (HEAD lines)
- `req` = `thingsboard_gateway/gateway/entities/rpc_request.py`
- `resp` = `thingsboard_gateway/gateway/entities/rpc_response.py`
- `old svc` = svc at `8c64fa35^`

`__send_rpc_reply` / `send_rpc_reply` did not change in the range (HEAD svc:1815-1868 is byte-identical to old svc:1795-1848). Findings come from reading code only; nothing was run.

---

## 0. Entry points (unchanged)

- svc:792-798 registers `_rpc_request_handler` for two topics:
  - `v1/gateway/rpc`: child-device RPC.
  - `v1/devices/me/rpc/request/+`: RPC sent to the gateway device itself.
- tb-mqtt-client 1.13.14 (requirements.txt:18) calls the handler differently for each topic:
  - **Gateway device:** `handler(request_id, content)`. `request_id` is the topic suffix as a str. `content = {"method":…, "params":…}` (`tb_mqtt_client/tb_device_mqtt.py:714-719`).
  - **Child device:** `handler(self, content)`. **The first argument is the MQTT client object, not an id.** `content = {"device":…, "data":{"id","method","params"}}` (`tb_mqtt_client/tb_gateway_mqtt.py:163-166`).

## 1. Classification and routing

`create_rpc_request_from_dict(content, gateway_or_connector_req_id)` is at req:28-43.

**Normalisation (req:63-73).**
- If `content` has no `"data"` key, it is rewritten to `{"data": {"params": content["params"], "method": content["method"]}}`.
- `id` and every other key are dropped.
- A missing `"params"` raises KeyError, and no reply is sent.

**Type detection.** Checked in this order (req:76-86):

1. **GATEWAY** (req:89-98). Either condition is enough:
   - `data.method` is in `RESERVED_RPC_NAMES = ('getTermInfo', 'sendCommand', 'getCommandStatus', 'terminateCommand')` (req:46).
   - `data.method.split('_')[0] == 'gateway'`.
   - Case-sensitive.
2. **CONNECTOR** (req:101-107).
   - `data.method.split('_')[0]` must be one of the `DEFAULT_CONNECTORS` keys: `mqtt, modbus, opcua, ble, request, can, bacnet, odbc, rest, snmp, ftp, socket, xmpp, ocpp, knx, s7` (constants.py:129-146).
   - Case-sensitive.
3. **RESERVED** (req:110-115). The code is `rpc_method == 'get' or rpc_method == 'set' and <has device>`, after `.lower()`.
   - Python evaluates this as `get` OR (`set` AND device). So `get` matches even without a device.
   - No regex or schema is applied here.
4. **DEVICE** (req:118-119): the top-level `"device"` key is not None.
5. **Anything else:** `ValueError(f"Unknown RPC type for content: {content}")` (req:86).

**Request objects.** All share these fields (req:57-60):
- `id = data.id`
- `timeout = content.get('timeout', RPC_DEFAULT_TIMEOUT)`. This is a **top-level** key; the default is 5 s (constants.py:115).
- `params = data.params` (raw).

| Class | Fields |
|---|---|
| `GatewayRPCRequest` (req:122-130) | `id = gateway_or_connector_req_id`; `method_name = method.replace("gateway_", "")` (every occurrence is removed) |
| `ConnectorRPCRequest` (req:133-145) | `id = gateway_or_connector_req_id`; `connector_type, method_name = method.split('_', 1)`; `value = params.get('value')`; `device_name = params.get('deviceName')` |
| `DeviceRPCRequest` (req:148-156) | `method_name = data.method`; `device_name = content["device"]` |
| `ReservedRPCRequest` (req:159-167) | Same fields as Device. `method_name` keeps its original case |

**Routing** (svc:1638-1664).

- **DEVICE / RESERVED** go into a queue. The worker is at svc:1684-1720:
  - If `monotonic()-received > rpc_request.timeout`, it replies `{"error":"Request timeout", "code": 408}` (svc:1688-1693).
  - It maps the renamed device name back to the original name (svc:1695-1697).
  - A device that is not connected yet is re-queued (svc:1700-1702).
  - If the device's connector is None, it replies with the plain string `f"Received RPC {rpc_request} but connector for the device {rpc_request.device_name} not found."` (svc:1704-1711).
  - Otherwise it calls `response = connector.server_side_rpc_handler(rpc_request)`. If the response is not None, it sends `send_rpc_reply(response.device_name, response.id, dumps(response.message))` (svc:1713-1718). If it is None, the gateway sends nothing and the connector is responsible for replying.
- **CONNECTOR** goes to `_process_rpc_to_connector` (svc:1666-1675):
  - `find_connectors_by_type` (svc:1677-1682) matches on `connector.get_type()`, which is the connector's `"type"` from tb_gateway.json.
  - **Only the first matching connector is called** (the code is `for … : return`).
  - `params.connectorId` is not used anywhere in routing.
  - The reply is sent with `to_connector_rpc=True` (svc:1658-1662).
- **GATEWAY** goes to `_process_rpc_to_gateway` (svc:1722-1756).
- The `else` branch at svc:1654-1656 (`{"error":"Unknown RPC type", "code": 400}`) can never run, because `get_rpc_type` raises first.
- Any exception is logged as `"Error while processing RPC request"` and **no reply is sent** (svc:1663-1664).

**Reserved get/set schemas are not shared.** Each connector has its own constants and regex in `connectors/<type>/constants.py`.
- The usual error string is `"The requested RPC does not match with the schema: {expected_schema}"`. It appears in bacnet_connector.py:990, ble:331, can:223, ftp:487, ocpp:396, odbc:183, request:183, rest:324, s7:396/408 and snmp:376.
- A variant is `"The requested RPC either does not match with the schema {expected_schema} or incorrect value/values provided"`, in modbus_connector.py:598, mqtt_connector.py:1089 and socket_connector.py:460.

## 2. Shared response model and wire shapes

**`RPCResponse`** (resp:16-34):
- Constructor: `(rpc_id, to_connector_rpc=False, device=None)`. `_message` defaults to `''`.
- `set_message(m)` produces `{'result': m}`.
- `set_error_msg(e)` produces `{'error': e}`.
- `set_gateway_rpc_msg(m)` stores `m` unchanged.
- The `to_connector_rpc` attribute is assigned at svc:1651 but never read.

**Connector contract** (connector.py:67-69):
- `server_side_rpc_handler(self, rpc_request: DeviceRPCRequest | ReservedRPCRequest | ConnectorRPCRequest) -> RPCResponse`. Returning None means the connector replies on its own.
- Every built-in connector builds `RPCResponse(rpc_request.id, device=rpc_request.device_name)`.

**`__send_rpc_reply`** (svc:1828-1866):
- A str `content` is passed through `json.loads`.
- The `'result'` unwrapping at svc:1849-1850 (commented "For get/set service RPCs") only applies when `success_sent` is not None. The new flows never pass `success_sent`; the only caller that does is `cancel_rpc_request`, svc:1875, with `success_sent=False`.
- **So ThingsBoard receives `{"result": X}` as-is.**
- Device names are mapped back to their renamed ThingsBoard names (svc:1831-1832).

| Case | Topic | Payload |
|---|---|---|
| Device/reserved OK | `v1/gateway/rpc` | `{"device":"<name>","id":<id>,"data":{"result":X}}` |
| Device/reserved error | `v1/gateway/rpc` | `"data":{"error":"<msg>"}` |
| Device timeout | `v1/gateway/rpc` | `"data":{"error":"Request timeout","code":408}` |
| Device has no connector | `v1/gateway/rpc` | `"data":"Received RPC … not found."` (plain string) |
| Connector RPC OK / error | `v1/devices/me/rpc/response/<id>` | `{"result":X}` / `{"error":"<msg>"}` |
| Gateway RPC | `v1/devices/me/rpc/response/<id>` | The method's raw return value |
| Gateway method not found | `v1/devices/me/rpc/response/<id>` | `{"error":"Method not found"}` |
| MQTT 2-way cancelled (svc:1872-1877) | Either topic | `{"success": false}` |

**Timeout and withResponse:**
- At the gateway level, timeout is only used to bound how long a device-queue request waits (svc:1688).
- Connectors reuse `rpc_request.timeout` as their own operation timeout: ble:304, knx:352, modbus:564/606/658, ocpp:351, opcua:1438/1496/1543, snmp:392.
- There is no `withResponse` or one-way handling at the gateway layer. It exists only in request_connector.py.

**NEW helper:** `TBUtility.replace_params_tags_from_rpc_request(text, rpc_request)` (tb_utility.py:190-193).
- It wraps `{'data': rpc_request.params}` and calls `replace_params_tags` (tb_utility.py:180-188) to substitute `${…}` tags.
- Only MQTT uses it (mqtt_connector.py:951, 990).

## 3. Gateway-level methods

These are sent to the **gateway device**. Sources:
- Method table: svc:351-360
- Scheduled methods: svc:362-365
- Custom methods: svc:361 and 2377-2404
- Remote shell: tb_remote_shell.py:26-31

**Dispatch** (svc:1729-1754):
1. If the remote shell is enabled and the name is a shell command, the shell function runs. Otherwise the method table is used.
2. If nothing was found and the name is `restart` or `reboot`, the action is scheduled.
3. If nothing was found at all, the reply is `{"error":"Method not found"}`.
4. Arguments depend on `params`:
   - A list is passed as `fn(*params)`.
   - The string `'{}'` or None calls `fn()`.
   - Anything else is passed as `fn(params)`. **This includes a dict `{}`.**

| Request | Behaviour / response |
|---|---|
| `{"method":"gateway_ping","params":{}}` | `{"code":200,"resp":"pong"}` (svc:1758-1761) |
| `{"method":"gateway_devices","params":{}}` | `{"code":200,"resp":{"<device>":"<connectorName>",…}}` (svc:1763-1769) |
| `{"method":"gateway_version","params":{}}` | `{"resp":{"current_version":"…","latest_version":"…"},"code":200}`, or `{"error":str(e),"code":500}` (svc:1783-1789; tb_updater.py:41-43) |
| `{"method":"gateway_update","params":{}}` | `{"resp":<update()>,"code":200}`, or `{"error":…, "code":500}` (svc:1771-1781). `update()` returns `"Congratulations! You have the latest version."` or the result of the package install (tb_updater.py:111-116) |
| `{"method":"gateway_stats","params":null}` (also `[]` or `"{}"`) | `{"eventsProduced":n,"eventsSent":n,"<Conn>EventsProduced":n,"<Conn>EventsSent":n,…}` (svc:1914-1929). The function takes no arguments, so `params:{}` raises TypeError and **no reply** is sent |
| `{"method":"gateway_device_renamed","params":{"<old>":"<new>"}}` | Uses the first item of the dict. Returns `{"success":true}` (svc:757-779) |
| `{"method":"gateway_device_deleted","params":"<deviceName>"}` | Returns `{"success":true}` (svc:719-740) |
| `{"method":"gateway_remove_provisioned_credentials","params":null}` | Deletes `<configDir>/.credentials`. Returns one of: `{"code":200,"resp":"Provisioned credentials file removed successfully."}`, `{"code":500,"error":str(e)}`, `{"code":404,"message":"Provisioned credentials file does not exist."}` (svc:742-755). Takes no arguments, so `params:{}` gets no reply |
| `{"method":"gateway_restart","params":5000}` / `gateway_reboot` | Delay is `int(params)` in **milliseconds**. If `params` cannot be converted, the delay is 1000. There is no minimum (svc:1735-1745). It runs in `_watchers` (svc:513-525). Reboot runs `shutdown -r -t 0`; a return code of 256 logs `"Error on RPC command: 256. Permission denied."`. The response is the string `'Success'`; see bug 2 |
| `{"method":"gateway_<custom>", …}` | Every callable in `/etc/thingsboard-gateway/rpc/*.py` (constants.py:158). The method name is the attribute name with `"__rpc_"` removed (svc:2404). The return value is sent raw |
| `{"method":"getTermInfo","params":{}}` | `{"platform":…,"release":…,"cwd":…}` (tb_remote_shell.py:36-37) |
| `{"method":"sendCommand","params":{"command":"ls -la","cwd":"/tmp"}}` | `{"ok":true\|false,"qos":0}` (39-63). `cwd` is optional |
| `{"method":"getCommandStatus","params":{}}` | `{"data":[{"stdout":"…","stderr":"…"}],"cwd":"…","done":bool,"qos":0}` (65-98) |
| `{"method":"terminateCommand","params":{}}` | `{"ok":true}`, or `{"ok":false,"error":"Process for termination not found."}`, or `{"ok":false,"error":str(e)}` (100-113) |

The four shell methods have no prefix. When `remoteShell` is false they return `{"error":"Method not found"}`.

**Connector RPC** is sent to the gateway device.
- Example: `{"method":"<type>_<method>","params":{"deviceName":"…", "value":…, …}}`.
- `params` **must be a JSON object** (req:141-142).
- The method is split at the first underscore. For example, `opcua_get_value` gives type `opcua` and method `get_value`.

**Device / reserved RPC** is sent to a child device. The gateway receives `{"device":"D","data":{"id":1,"method":"get","params":"<connector schema>"}}`.

## 4. Config keys

- `thingsboard.remoteShell` (bool). It is false in the default file (tb_gateway.json:5) and read at svc:210, 441-447. It enables the shell methods.
- `handleDeviceRenaming` (default True). The code reads it from the **top level** of the config (svc:758), but the file puts it under `thingsboard` (tb_gateway.json:22). See bug 11.
- `RPC_DEFAULT_TIMEOUT = 5` (constants.py:115) cannot be configured. A request can only override it with a top-level `"timeout"` key (req:59).
- The custom RPC directory `/etc/thingsboard-gateway/rpc` is fixed.
- RPC replies always use QoS 0: `send_rpc_reply` defaults to `quality_of_service=0` (svc:1816). `thingsboard.qos` is not used.
- **Key added in the range: `thingsboard.statistics.enableCustom: false`** (commit f1ee9e6a, tb_gateway.json:10).
  - This is a **statistics setting, not RPC**.
  - The code that reads it already existed (svc:411-423). When the key is absent it is treated as True.
  - The remote configurator's default is True (tb_gateway_remote_configurator.py:49).
- tb_gateway_remote_configurator.py has no RPC changes in the range. The only change there is commit 067ea273, which skips re-creating storage when its config did not change (:389-392).

## 5. Changes compared with `8c64fa35^`

**NEW**
- The request/response entities (req, resp) and the `RPCType` enum (60cdfe3c).
- **Connector API:**
  - `server_side_rpc_handler` now receives a request object instead of the raw dict.
  - It must return `RPCResponse` or None (connector.py:67-69).
  - Custom-connector docs must be updated.
- When a device has no connector, the gateway now replies with a plain string (svc:1706). Before, it only logged (old svc:1700-1703).
- `DummyCustomConnector` (connector.py:72-141, used at svc:909, 913) is a placeholder for any non-grpc connector whose class fails to import. Its RPC handler returns `{"error": f"Custom connector '{name}' is not implemented."}`.
- The helper `replace_params_tags_from_rpc_request`.

**CHANGED**
- **Routing order:**
  - Before: a `"device"` key always meant device RPC (old svc:1640-1642).
  - Now: gateway, then connector, then reserved, then device, whether or not `"device"` is present.
- **Connector RPC selection:**
  - Before: the prefix had to be a type present in `connectors_configs`, custom types included, and **every** connector of that type was called (old svc:1651-1658).
  - Now: the prefix must be one of the 16 built-in types, and **only the first** connector of that type is called.
- **Connector response:**
  - Before: a None result replied `{"success": false}` (old svc:1665-1666).
  - Now: no reply.
- **Method not found:** `{"error":"Method not found","code":404}` (old svc:1729) became `{"error":"Method not found"}`.
- **Unknown prefix with no device** (for example `ping`, `set`):
  - Before: `{"error":"<module> - connector not found in available connectors.","code":404}` (old svc:1661-1664).
  - Now: no reply.
- **Remote shell method while the shell is disabled:** the 404 "connector not found" error became `"Method not found"`.
- **Exceptions inside gateway or connector RPC:**
  - Before: `{"error":"<exc>","code":500}` (old svc:1673-1675).
  - Now: no reply.
- **`"qos"` key in gateway method results:**
  - Before: the key was stripped and used as the reply QoS (old svc:1667-1670).
  - Now: it is sent in the payload. Shell replies now include `"qos":0`.
- **restart/reboot:**
  - Before: `params` was seconds × 1000, with a minimum of 1000 ms, and the reply was `{"success":true}` (old svc:1721-1726).
  - Now: `params` is milliseconds, the default is 1000, there is no minimum, and the reply is `'Success'`.
- **Device RPC errors:**
  - Before: the gateway added `"success":false` to error dicts returned by connectors (old svc:1698-1699), and connectors replied in their own shapes, often `{"result":{"error":…}}` (for example old modbus_connector.py:570).
  - Now: replies are always `{"result":X}` or `{"error":E}`, with no `success` key.
- **Source of the device-queue timeout:**
  - Before: `content["params"]["timeout"]` (old svc:1683).
  - Now: top-level `content["timeout"]`.
  - In both cases the effective default is 5 s.

**FIXED within the range** (relative to 60cdfe3c)
- **f491aa01:** shell names are classified as gateway RPC again. Gateway method results are sent raw instead of wrapped in `{"result":…}`.
- **bfc44312:** despite its title ("gateway_ping"), it replaced `params.get("secondsToRestart",1000)` with `int(params)`. That is the restart/reboot delay, not ping.
- **838dfdb2:** connector methods with more than one `_` work again (the split became `split('_', 1)`).
- **0aa4bb96:** gateway methods with more than one `_` work again. This covers `gateway_device_renamed`, `gateway_device_deleted` and `gateway_remove_provisioned_credentials`, which were broken from 60cdfe3c until this commit.
- **e9fa3efb:** fixed the indentation of `ConnectorRPCRequest.__str__`.
- **9ad93b25:** the default timeout now comes from gateway constants.

## 6. Open questions and likely bugs (per trace)

1. **"Connector of type X not found" is never sent.**
   - svc:1671 calls `dumps(rpc_request)` on an object, which raises TypeError.
   - Even without that, the returned str has no `.to_connector_rpc` attribute (svc:1651).
   - Result: no reply. The string `{"error":"Connector of type <type> not found","code":404}` (svc:1672) is never delivered.
2. **restart/reboot replies are lost.**
   - `'Success'` goes through `dumps`, then `loads`, then the client's `orjson.loads('Success')` at `tb_device_mqtt.py:1134-1135`, which raises JSONDecodeError. The error is logged at svc:1864-1866.
   - The same happens for any custom method that returns a string that is not valid JSON.
   - The log line says "scheduled in %i seconds" but the delay is in ms.
3. **Child-device RPC whose name matches `gateway_*`, a shell name or `<type>_*`** is run at gateway or connector level instead of on the device.
   - Its id is the client object, so the reply fails (`RPC_RESPONSE_TOPIC + req_id`, tb_device_mqtt.py:871).
   - **With `remoteShell` enabled, a child-device RPC named `sendCommand` runs a shell command on the gateway host.**
4. **The device RPC thread can die.** svc:1719 only catches `(TimeoutError, Empty)`. If any handler raises, or returns something other than `RPCResponse`/None (`response.device_name` is read at svc:1716), the "RPC to devices processing thread" stops and all later device RPCs are dropped. Affected:
   - gRPC connectors (grpc_connector.py:55-58, then `msg['data']` at grpc_downlink_converter.py:110).
   - The shipped `extensions/serial/custom_serial_connector.py:416-421`, which calls `content.get`.
   - Any user custom connector still written against the dict API.
5. **`get` sent to the gateway device itself** becomes RESERVED with no device and no id.
   - It is busy re-queued for 5 s with no wait (svc:1700-1702), then the timeout reply to a None id fails.
   - The operator precedence at req:112 looks unintended.
6. **`set`, `ping` or any other unknown name with no device** raises ValueError and gets no reply. The 400 branch is unreachable.
7. **Gateway methods that take no arguments** (`stats`, `remove_provisioned_credentials`) fail on `params:{}`. Not confirmed from this repo what ThingsBoard sends when params are left empty.
8. **Connector RPC edge cases:**
   - `params` that is not an object raises AttributeError (req:141-142).
   - A method with no `_` (for example `"modbus"`) raises ValueError (req:138).
   - In both cases there is no reply.
9. **Only the first connector of a type is used, and `connectorId` is ignored.** The order is the insertion order of `available_connectors_by_name`.
10. **Timeout is effectively fixed at 5 s.**
    - The gateway-device conversion drops every key except method and params, so connector RPC always uses 5 s.
    - Not checked whether ThingsBoard puts a top-level `"timeout"` in `v1/gateway/rpc` payloads.
11. **`handleDeviceRenaming` is effectively ignored.** It is read from the top level (svc:758), but the file nests it under `thingsboard`, so the value is always True. This predates the range.
12. **`DummyCustomConnector.server_side_rpc_handler` breaks the contract** by returning a dict (connector.py:137-141). For a connector RPC this hits the AttributeError at svc:1651, so there is no reply.
13. **MQTT 2-way replies may go to the wrong topic.** `rpc_with_reply_processing` (svc:1807) picks the topic based on `device_name is None`. A connector RPC that includes `params.deviceName` would get its reply on `v1/gateway/rpc`.
14. **Reserved method case is handled inconsistently.** Detection lower-cases the method, but `method_name` keeps the original case. Connectors compare differently (rest uses `.lower()`; modbus uses `== "get"` at modbus_connector.py:625).
15. **The `'result'` unwrap** at svc:1849-1850 is effectively dead for new flows, so ThingsBoard gets `{"result":X}`. Is that intended? Also, is the extra `"qos":0` in shell replies acceptable to the ThingsBoard widget?
16. **An unset `RPCResponse` message** (`''`) on a connector RPC would hit `orjson.loads('')`, so no reply is sent.
