# Tado X Matter Pro

[![Validate](https://github.com/malte-wessel/tado-x-matter-pro/actions/workflows/validate.yml/badge.svg)](https://github.com/malte-wessel/tado-x-matter-pro/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![License](https://img.shields.io/github/license/malte-wessel/tado-x-matter-pro)](LICENSE)

Room-by-room heating control for Tado X radiator thermostats connected to Home Assistant over Matter.

Over Matter, Tado X thermostats are plain thermostats: a mode, a setpoint, a temperature. Everything
else – schedules, windows, away modes, boost – has to happen in Home Assistant. Tado X Matter Pro does
that in one integration: you add a room, pick its thermostats, schedule and window sensors, and get a
room thermostat that follows the plan, reacts to windows and remembers manual changes.

> **Status:** in development, nothing to install yet. See [PLAN.md](PLAN.md).
> Not affiliated with tado°.

## What it will do

- **Schedules** from Home Assistant's schedule helpers; a block can carry its own temperature.
- **Windows and doors**: off after a short delay (so a door that is opened for a second does not
  count), back on a few minutes after closing, with an optional reminder when a window stays open.
- **Away and holiday**: any switch or sensor you choose drops the house to idle temperatures.
- **Manual changes** on the thermostat, in the tado° app or in Home Assistant hold until the next
  schedule change.
- **Boost**, **heat until …**, **eco until …**, **extend the current block** and **back to schedule**,
  as buttons, presets and services that target rooms, areas or floors.
- **Is it heating?** Tado X does not report its valve over Matter; the integration infers it from the
  thermostat's temperature trend and shows it as the room thermostat's action.
- **Explains itself**: a mode sensor with the reason, the next change and when heating resumes, and
  logbook entries for every decision.

## Requirements

- Home Assistant 2026.10 or newer.
- Tado X thermostats added to Home Assistant through Matter.
- In the tado° app: a flat schedule, manual changes "until ended", and open window detection off –
  otherwise tado° overwrites what Home Assistant sets.

## Development

```sh
uv sync            # Python venv with Home Assistant and the test harness
scripts/check.sh   # everything CI runs: ruff, mypy, pytest
scripts/ha.sh      # a real Home Assistant (official image, version from test/ha/.env) with the simulated Dev House: http://localhost:8123, dev / dev
```

[AGENTS.md](AGENTS.md) describes the layout and the rules, [CONTRIBUTING.md](CONTRIBUTING.md) the workflow.

## License

MIT
