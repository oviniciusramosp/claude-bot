---
title: HomeBridge Control & Configuration
description: Control and configure HomeBridge at localhost:8581 — Samsung ACs (SmartThings), Mi Aqara, Tuya platforms. Includes auth, API patterns, device map, and preference context.
type: skill
created: 2026-04-20
updated: 2026-04-20
tags: [skill, homebridge, smarthome, smartthings, tuya, aqara]
---

## HomeBridge Setup

- **UI:** http://localhost:8581 (also accessible at http://192.168.68.125:8581 on LAN)
- **Auth:** `username: admin-viniciusramos` / `password: Qekver-zubcuh-3sevsu`
- **Restart:** `brew services restart homebridge`
- **Config file:** `~/.homebridge/config.json`
- **Logs:** `~/.homebridge/homebridge.log` or via UI → Logs tab

## Platforms

### SmartThings (primary)
- Plugin npm: `homebridge-smartthings-oauth` (aziz66/homebridge-smartthings, v1.0.58) — migrated 2026-04-20
- Platform key no config: `HomeBridgeSmartThings` (unchanged)
- Auth: OAuth (not PAT) — credentials in `vault/.env`: `SMARTTHINGS_OAUTH_CLIENT_ID` / `SMARTTHINGS_OAUTH_CLIENT_SECRET`
- OAuth app id: `62e797dd-c03d-4443-8434-c2c31a4d5391` (appName: homebridge-smartthings-vr)
- OAuth wizard: HomeBridge UI → Plugins → "Homebridge Smartthings oAuth Plugin" → ⚙️ Settings → "Open OAuth Setup Wizard"
- Ignored devices: `iPhone`, `TV`, `[TV] Quarto`
- AC-specific options: `ExposeHumiditySensorForAirConditioners: true`, `OptionalModeForAirConditioners: "WindFree"`
- Poll intervals: switches/lights = 60s, sensors = 60s, garage = 40 polls max

### Mi Aqara
- Child bridge: `0E:B1:01:23:51:D8` port 55863 (Homebridge Mi Aqara)
- Devices: sensors (not yet surfaced in dashboard)

### Tuya
- Child bridge: `0E:EC:B6:36:7B:83` port 39454 (Homebridge Tuya Platform)
- Account: viniciusarthur.rp@gmail.com / tuyaSmart app, country code 55 (BR)
- Devices: not yet surfaced

## Known Devices

### Office AC (SmartThings — Samsung)
- Location: escritório (office)
- `aid=5` on main bridge `0E:A6:B2:E7:C9:38`
- **Primary control:** Thermostat service (iid=8) — use `TargetHeatingCoolingState` (0=off, 1=heat, 2=cool, 3=auto) and `TargetTemperature`

| Service | Type | iid | uniqueId prefix |
|---------|------|-----|----------|
| Thermostat | Thermostat | 8 | ef347ba8... |
| Fan | FanV2 | 15 | 69460d69... |
| FilterMaintenance | FilterMaintenance | 20 | 5c5c08d4... |
| WindFree Switch | Switch | 23 | 927c8b3b... |
| WindFree (new) | Switch | — | 24454451... |
| Display Light | Switch | — | 8fdbe35b... |

### AC (SmartThings — Samsung)
- Location: unknown (name is just "AC") — clarify with user
- `aid=7` on main bridge `0E:A6:B2:E7:C9:38`
- **Primary control:** same pattern as Office AC

| Service | Type | iid | uniqueId prefix |
|---------|------|-----|----------|
| Thermostat | Thermostat | 8 | 98a13f35... |
| Fan | FanV2 | 15 | 814391f2... |
| FilterMaintenance | FilterMaintenance | 20 | d8cf0c42... |
| WindFree Switch | Switch | 23 | 906b3e11... |
| WindFree (new) | Switch | — | 7cb65e03... |
| Display Light | Switch | — | 4f307b1b... |

## UUID → Service Type Map

```
0000004A-0000-1000-8000-0026BB765291 → Thermostat
000000B7-0000-1000-8000-0026BB765291 → HeaterCooler
00000082-0000-1000-8000-0026BB765291 → FilterMaintenance
00000049-0000-1000-8000-0026BB765291 → Switch (WindFree mode)
```

## API Patterns

### Authenticate (get token)
```bash
TOKEN=$(curl -s -X POST http://localhost:8581/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin-viniciusramos","password":"Qekver-zubcuh-3sevsu"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
```

### List device layout (always works, no live values)
```bash
curl -s http://localhost:8581/api/accessories/layout \
  -H "Authorization: Bearer $TOKEN"
```

### List accessories with live values (requires valid SmartThings token)
```bash
curl -s http://localhost:8581/api/accessories \
  -H "Authorization: Bearer $TOKEN"
```

### Control a device characteristic
```bash
curl -s -X PUT http://localhost:8581/api/accessories/<uniqueId> \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"characteristicType": "<type>", "value": <value>}'
```

Common `characteristicType` values for ACs:
- `Active` → 0 (off) / 1 (on)
- `TargetHeaterCoolerState` → 0 (auto), 1 (heat), 2 (cool)
- `CoolingThresholdTemperature` → number (°C)
- `HeatingThresholdTemperature` → number (°C)
- `RotationSpeed` → 0–100 (fan speed %)
- `On` (Switch service) → true/false (WindFree toggle)

### Restart HomeBridge
```bash
brew services restart homebridge
```

### Get plugin list
```bash
curl -s http://localhost:8581/api/plugins -H "Authorization: Bearer $TOKEN"
```

### Get bridge status
```bash
curl -s http://localhost:8581/api/status/homebridge -H "Authorization: Bearer $TOKEN"
```

## SmartThings Auth (OAuth — post 2026-04-20)

Plugin now uses OAuth. Tokens are managed automatically by `homebridge-smartthings-oauth` (no manual PAT rotation needed). If accessories stop showing up:

1. Open HomeBridge UI → Plugins → "Homebridge Smartthings oAuth Plugin" → ⚙️ → "Open OAuth Setup Wizard"
2. Re-enter Client ID / Secret from `vault/.env` (`SMARTTHINGS_OAUTH_CLIENT_ID` / `SMARTTHINGS_OAUTH_CLIENT_SECRET`)
3. Complete Samsung login and re-authorize
4. Restart HomeBridge if needed

OAuth app was created via SmartThings REST API (`API_ONLY` type, `CONNECTED_SERVICE` classification) on 2026-04-20. The `SMARTTHINGS_TOKEN` (legacy PAT) in vault/.env is kept for reference but no longer used by HomeBridge.

## Preferences

- **WindFree mode:** preferred for passive cooling (quieter); use the Switch service (iid=23 on each AC)
- **AC naming:** "Office AC" = escritório; "AC" = quarto or sala (clarify with user)
- **Dashboard:** Jarvis Dashboard at http://192.168.68.125:4000 → "Casa" tab shows AC cards
  - Backend route: `GET /api/home/devices` (groups by name)
  - Control route: `POST /api/home/devices/:uniqueId/set`
- **Group services by name** when presenting to user — 1 card per physical AC, not per HomeKit service
- **Humidity sensor** is exposed for each AC (from SmartThings platform setting) — useful for monitoring

## Common Tasks

### Check if HomeBridge is running
```bash
brew services list | grep homebridge
curl -s http://localhost:8581/api/status/homebridge -H "Authorization: Bearer $TOKEN" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d)"
```

### Turn off all ACs
Control `Active=0` on each HeaterCooler service (iid=15) for both devices.

### Set temperature
Use `CoolingThresholdTemperature` or `HeatingThresholdTemperature` on the HeaterCooler service.

### Check config
```bash
cat ~/.homebridge/config.json | python3 -m json.tool
```
