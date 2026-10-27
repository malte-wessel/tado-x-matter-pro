# Tado X Matter Pro

[![Validate](https://github.com/malte-wessel/tado-x-matter-pro/actions/workflows/validate.yml/badge.svg)](https://github.com/malte-wessel/tado-x-matter-pro/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![License](https://img.shields.io/github/license/malte-wessel/tado-x-matter-pro)](LICENSE)

Room-by-room heating control for Tado X radiator thermostats connected to Home Assistant over Matter.

Over Matter, Tado X thermostats are plain thermostats: a mode, a setpoint, a temperature. Schedules,
windows, away modes – and even whether a radiator is heating – have to happen in Home Assistant.
Tado X Matter Pro does that in one integration: you add a room, pick its thermostats, schedule and
window contacts, and get a room thermostat that follows the plan, pauses for open windows,
remembers manual changes, and shows which radiator is heating.

> **Status: pre-release.** Room control and the heating status work. Boost, timed overrides, the
> window reminder and repair issues are planned. Not affiliated with tado°.

## Features

- **Rooms** with any number of thermostats, set up in the UI: schedule, windows and doors, an
  optional room sensor.
- **Schedules** from Home Assistant's schedule helpers; a block can carry its own temperature.
  Comfort and eco temperature per room, changeable on the dashboard.
- **Away and vacation:** any switches or sensors you choose put every room on its eco temperature.
- **Windows and doors** switch a room off after a short delay – a door opened to walk through
  changes nothing – and back on a few minutes after closing.
- **Manual changes** at the thermostat, in the tado° app or in Home Assistant are held until the
  next schedule change; rooms with several thermostats follow. Holds survive restarts.
- **Is it heating?** Tado X does not report its valve over Matter; the integration infers it per
  thermostat from the temperature trend and shows it as the room thermostat's action.
- **Frost protection** for rooms that are off or have a window open.
- **Explains itself:** a mode sensor per room says what decides right now, when the schedule
  changes next, and when heating resumes after a window.

## Documentation

| | |
| --- | --- |
| [Installation](docs/installation.md) | Requirements, tado° app settings, HACS |
| [Configuration](docs/configuration.md) | House settings and rooms, field by field |
| [How it works](docs/how-it-works.md) | Priorities, schedule, windows, manual changes, frost, restarts |
| [Entities](docs/entities.md) | What each room creates, states and attributes |
| [Heating status](docs/heating-status.md) | How "heating" is inferred, and its limits |
| [Dashboards](docs/dashboards.md) · [Automations](docs/automations.md) | Examples |
| [Migrating from a DIY setup](docs/migrating.md) | From blueprint and helpers, room by room |
| [Troubleshooting](docs/troubleshooting.md) | Common surprises, debug logging |
| [Development](docs/development.md) | Dev container with a simulated house, tests, code layout |

## Quick start

1. Requirements: Home Assistant 2026.10+, Tado X thermostats added over Matter, a schedule helper.
2. In the tado° app: a flat schedule, manual changes "until you cancel", open window detection off.
3. HACS → Custom repositories → `https://github.com/malte-wessel/tado-x-matter-pro` (Integration) →
   download **Tado X Matter Pro** → restart.
4. Settings → Devices & services → Add integration → *Tado X Matter Pro*, then **Add room**.

## Development

```sh
uv sync            # Python venv with Home Assistant and the test harness
scripts/check.sh   # everything CI runs: ruff, mypy, pytest
scripts/ha.sh      # a real Home Assistant with the simulated Dev House: http://localhost:8123, dev / dev
```

See [Development](docs/development.md), [AGENTS.md](AGENTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
