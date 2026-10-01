# Rainforest Eagle (Custom EAGLE-3 HTTPS Workaround)

A private copy of Home Assistant's built-in
[`rainforest_eagle`](https://github.com/home-assistant/core/tree/dev/homeassistant/components/rainforest_eagle)
integration, used to carry a short-term workaround for an EAGLE-3 firmware bug
until Rainforest Automation ships a firmware fix.

## The bug and the fix

### Symptom

On affected EAGLE-3 units, the local API on port 80 never answers. Every
`POST http://<eagle-ip>/cgi-bin/post_manager` gets:

```
HTTP/1.1 301 Moved Permanently
Location: https://192.168.7.1/cgi-bin/post_manager
```

`192.168.7.1` is not on your LAN, so the redirect times out. Rainforest
Automation confirmed this is a firmware bug that happens whether or not
credentials are sent, and is tracking a firmware fix.

The built-in integration uses the [`aioeagle`](https://pypi.org/project/aioeagle/)
library, whose `EagleHub.make_request()` hard-codes
`http://{host}/cgi-bin/post_manager`. So both the config-flow device
detection (`data.async_get_type`) and the 30-second polling
(`coordinator._async_update_data_200`) fail.

### Fix

The same API works over HTTPS on the EAGLE's real LAN IP. The device uses a
self-signed certificate, so certificate verification has to be off. This is
Rainforest's recommended workaround.

The new `hub.py` adds:

- **`EagleHubHttps`**: a subclass of `aioeagle.EagleHub` that overrides only
  `make_request()`. It behaves the same as the original (Basic auth header,
  one request per second, `401` → `BadAuth`, XML parsing), except the URL
  is `https://`.
- **`create_hub()`**: builds an `EagleHubHttps` using Home Assistant's shared
  `aiohttp` session created with `verify_ssl=False`.

`data.py` and `coordinator.py` call `create_hub()` instead of creating an
`aioeagle.EagleHub` directly. Nothing else in how the integration behaves has
changed. Sensors, unique IDs and config entry data are the same, so removing
this override later lets the built-in integration take over the same entities.
EAGLE-100 devices use a separate code path (`eagle100`) and are unaffected.

**Security note:** turning off certificate verification is limited to requests
to the EAGLE on your LAN. Requests are still encrypted, but the device's
identity isn't checked.

## Changes from upstream

Compared with
[`homeassistant/components/rainforest_eagle`](https://github.com/home-assistant/core/tree/dev/homeassistant/components/rainforest_eagle)
on `dev`:

| File | Change | Why |
|---|---|---|
| `hub.py` | **New** | HTTPS hub (the fix) |
| `data.py` | Modified | Use `create_hub()` for device detection |
| `coordinator.py` | Modified | Use `create_hub()` for polling |
| `config_flow.py` | Modified | `probatio` → `voluptuous`; `probatio` is only on Core `dev` and isn't in released Home Assistant versions. Also aborts with "Device is already configured" if you add an EAGLE that already has an entry (upstream silently replaces it, which Home Assistant now warns about) |
| `manifest.json` | Modified | Custom name, `version` (required for custom integrations), links, codeowner |
| `translations/en.json` | **New** | Custom integrations don't get translations built from `strings.json`, so this is generated with the `[%key:common::...]` references resolved |
| `__init__.py`, `const.py`, `diagnostics.py`, `sensor.py`, `strings.json` | Unchanged | |

### `hub.py` (new)

```python
"""EAGLE-200/EAGLE-3 hub that talks HTTPS directly."""

import asyncio
import logging
from time import time

import aioeagle
import xmltodict

from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

_LOGGER = logging.getLogger(__name__)


class EagleHubHttps(aioeagle.EagleHub):
    """EagleHub using HTTPS.

    EAGLE-3 firmware redirects HTTP API calls to an unreachable 192.168.7.1,
    so go straight to HTTPS. The device uses a self-signed certificate.
    """

    async def make_request(self, command_xml: str):
        """Make a request."""
        wait_time = self.next_request - time()
        if wait_time > 0:
            await asyncio.sleep(wait_time)

        url = f"https://{self.host}/cgi-bin/post_manager"
        _LOGGER.debug("Sending to %s: %s", url, command_xml)

        async with self.session.post(
            url,
            headers={"Authorization": self.auth_header, "content-type": "text/xml"},
            data=command_xml,
        ) as response:
            self.next_request = time() + 1

            if response.status == 401:
                raise aioeagle.BadAuth

            text = await response.text()
            return xmltodict.parse(text, dict_constructor=dict)


def create_hub(
    hass: HomeAssistant, cloud_id: str, install_code: str, host: str
) -> EagleHubHttps:
    """Create a hub using a session that accepts the self-signed certificate."""
    return EagleHubHttps(
        aiohttp_client.async_get_clientsession(hass, verify_ssl=False),
        cloud_id,
        install_code,
        host=host,
    )
```

### `data.py`

```diff
--- a/homeassistant/components/rainforest_eagle/data.py
+++ b/custom_components/rainforest_eagle/data.py
@@ -9,9 +9,9 @@
 from requests.exceptions import ConnectionError as ConnectError, HTTPError, Timeout
 
 from homeassistant.exceptions import HomeAssistantError
-from homeassistant.helpers import aiohttp_client
 
 from .const import TYPE_EAGLE_100, TYPE_EAGLE_200
+from .hub import create_hub
 
 _LOGGER = logging.getLogger(__name__)
 
@@ -32,9 +32,7 @@
 
 async def async_get_type(hass, cloud_id, install_code, host):
     """Try API call 'get_network_info' to see if target is Eagle-100 or Eagle-200."""
-    hub = aioeagle.EagleHub(
-        aiohttp_client.async_get_clientsession(hass), cloud_id, install_code, host=host
-    )
+    hub = create_hub(hass, cloud_id, install_code, host)
 
     try:
         async with asyncio.timeout(30):
```

### `coordinator.py`

```diff
--- a/homeassistant/components/rainforest_eagle/coordinator.py
+++ b/custom_components/rainforest_eagle/coordinator.py
@@ -10,7 +10,6 @@
 from homeassistant.config_entries import ConfigEntry
 from homeassistant.const import CONF_HOST, CONF_TYPE
 from homeassistant.core import HomeAssistant
-from homeassistant.helpers import aiohttp_client
 from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
 
 from .const import (
@@ -20,6 +19,7 @@
     TYPE_EAGLE_100,
 )
 from .data import UPDATE_100_ERRORS
+from .hub import create_hub
 
 type RainforestEagleConfigEntry = ConfigEntry[EagleDataCoordinator]
 
@@ -74,11 +74,11 @@
     async def _async_update_data_200(self):
         """Get the latest data from the Eagle-200 device."""
         if (eagle200_meter := self.eagle200_meter) is None:
-            hub = aioeagle.EagleHub(
-                aiohttp_client.async_get_clientsession(self.hass),
+            hub = create_hub(
+                self.hass,
                 self.cloud_id,
                 self.config_entry.data[CONF_INSTALL_CODE],
-                host=self.config_entry.data[CONF_HOST],
+                self.config_entry.data[CONF_HOST],
             )
             eagle200_meter = aioeagle.ElectricMeter.create_instance(
                 hub, self.hardware_address
```

### `config_flow.py`

```diff
--- a/homeassistant/components/rainforest_eagle/config_flow.py
+++ b/custom_components/rainforest_eagle/config_flow.py
@@ -3,7 +3,7 @@
 import logging
 from typing import Any, override
 
-import probatio
+import voluptuous as vol
 
 from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
 from homeassistant.const import CONF_HOST, CONF_TYPE
@@ -21,17 +21,15 @@
 _LOGGER = logging.getLogger(__name__)
 
 
-def create_schema(user_input: dict[str, Any] | None) -> probatio.Schema:
+def create_schema(user_input: dict[str, Any] | None) -> vol.Schema:
     """Create user schema with passed in defaults if available."""
     if user_input is None:
         user_input = {}
-    return probatio.Schema(
+    return vol.Schema(
         {
-            probatio.Required(CONF_HOST, default=user_input.get(CONF_HOST)): str,
-            probatio.Required(
-                CONF_CLOUD_ID, default=user_input.get(CONF_CLOUD_ID)
-            ): str,
-            probatio.Required(
+            vol.Required(CONF_HOST, default=user_input.get(CONF_HOST)): str,
+            vol.Required(CONF_CLOUD_ID, default=user_input.get(CONF_CLOUD_ID)): str,
+            vol.Required(
                 CONF_INSTALL_CODE, default=user_input.get(CONF_INSTALL_CODE)
             ): str,
         }
@@ -54,6 +52,7 @@
             )
 
         await self.async_set_unique_id(user_input[CONF_CLOUD_ID])
+        self._abort_if_unique_id_configured()
         errors = {}
 
         try:
```

### `manifest.json`

```diff
--- a/homeassistant/components/rainforest_eagle/manifest.json
+++ b/custom_components/rainforest_eagle/manifest.json
@@ -1,16 +1,26 @@
 {
   "domain": "rainforest_eagle",
-  "name": "Rainforest Eagle",
-  "codeowners": ["@gtdiehl", "@jcalbert", "@hastarin"],
+  "name": "Rainforest Eagle (Custom EAGLE-3 HTTPS Workaround)",
+  "codeowners": [
+    "@abirismyname"
+  ],
   "config_flow": true,
   "dhcp": [
     {
       "macaddress": "D8D5B9*"
     }
   ],
-  "documentation": "https://www.home-assistant.io/integrations/rainforest_eagle",
+  "documentation": "https://github.com/shundor/rainforest_eagle_custom",
   "integration_type": "device",
   "iot_class": "local_polling",
-  "loggers": ["aioeagle", "eagle100"],
-  "requirements": ["aioeagle==1.1.1", "eagle100==0.1.1"]
+  "loggers": [
+    "aioeagle",
+    "eagle100"
+  ],
+  "requirements": [
+    "aioeagle==1.1.1",
+    "eagle100==0.1.1"
+  ],
+  "version": "1.1.2",
+  "issue_tracker": "https://github.com/shundor/rainforest_eagle_custom/issues"
 }
```

## How it installs

It uses the **same domain** (`rainforest_eagle`), so it transparently replaces
the built-in integration. Existing config entries, devices, entities and
history keep working — no reconfiguration needed.

Requires Home Assistant 2025.2 or newer.

## Install

### Option A: HACS (recommended, easy updates)

1. In Home Assistant: **HACS → ⋮ → Custom repositories**, add
   `https://github.com/shundor/rainforest_eagle_custom` with category
   **Integration** (HACS's GitHub token needs read access to this private repo).
2. Find **Rainforest Eagle (Custom EAGLE-3 HTTPS Workaround)** in HACS, click **Download**.
3. Restart Home Assistant.

### Option B: Manual copy

1. Copy `custom_components/rainforest_eagle/` into your Home Assistant config
   directory so you end up with:

   ```
   <config>/custom_components/rainforest_eagle/__init__.py
   <config>/custom_components/rainforest_eagle/manifest.json
   ...
   ```

   Ways to get it there: the **Samba share**, **Studio Code Server** or
   **File editor** add-ons, or `scp`:

   ```bash
   scp -r custom_components/rainforest_eagle \
     root@homeassistant.local:/config/custom_components/
   ```

2. Restart Home Assistant (**Settings → System → ⋮ → Restart**).

## Verify it is active

After restart, the log contains:

```
WARNING ... We found a custom integration rainforest_eagle which has not been
tested by Home Assistant. ...
```

This is expected and confirms the override loaded. In **Settings → Devices &
services** the integration now shows a "custom integration"
badge.

For more detail, add to `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.rainforest_eagle: debug
    aioeagle: debug
```

## Updating

Bump `version` in `custom_components/rainforest_eagle/manifest.json`, then
either publish a new release/commit for HACS or re-copy the folder, and
restart.

## Removing (once the firmware fix is out)

1. Delete `<config>/custom_components/rainforest_eagle/` (or remove it in
   HACS).
2. Restart Home Assistant. The built-in integration takes over again with the
   same config entry and entities.

## Notes

- Derived from Home Assistant Core (Apache License 2.0, see `LICENSE.md`).
  See [Changes from upstream](#changes-from-upstream).
- Because this overrides a core integration, upstream fixes to
  `rainforest_eagle` will not reach you while it is installed. Remove it once
  it is no longer needed.
