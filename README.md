# Rainforest Eagle (custom override)

A private copy of Home Assistant's built-in
[`rainforest_eagle`](https://github.com/home-assistant/core/tree/dev/homeassistant/components/rainforest_eagle)
integration, used to carry a short-term workaround for an EAGLE-3 firmware bug
until Rainforest Automation ships a firmware fix.

## The workaround

EAGLE-3 firmware answers HTTP API calls on port 80 with a `301` redirect to
`https://192.168.7.1/...`, which is unreachable, so setup and polling fail.
This copy skips HTTP and talks to `https://<eagle-ip>/cgi-bin/post_manager`
directly, with certificate verification disabled because the EAGLE uses a
self-signed certificate (see `hub.py`). EAGLE-100 devices are unaffected.

It uses the **same domain** (`rainforest_eagle`), so it transparently replaces
the built-in integration. Existing config entries, devices, entities and
history keep working — no reconfiguration needed.

Requires Home Assistant 2025.2 or newer.

## Install

### Option A: HACS (recommended, easy updates)

1. Push this folder to a GitHub repository (private is fine if HACS has a
   GitHub token with access to it).
2. In Home Assistant: **HACS → ⋮ → Custom repositories**, add the repo URL with
   category **Integration**.
3. Find **Rainforest Eagle (custom)** in HACS, click **Download**.
4. Restart Home Assistant.

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
services → Rainforest Eagle** the integration now shows a "custom integration"
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
  Changes from upstream: `probatio` replaced with `voluptuous` for
  compatibility with released Home Assistant versions, `version` added to the
  manifest, `translations/en.json` generated from `strings.json`, and the
  HTTPS workaround in `hub.py` (used by `data.py` and `coordinator.py`).
- Because this overrides a core integration, upstream fixes to
  `rainforest_eagle` will not reach you while it is installed. Remove it once
  it is no longer needed.
