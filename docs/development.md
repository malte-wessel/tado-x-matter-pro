# Development

## Set up

```sh
uv sync            # Python 3.14 venv with Home Assistant and its test harness
scripts/check.sh   # what CI runs: ruff, ruff format --check, mypy, pytest
scripts/check.sh --fix   # format and autofix first
```

The definition of done is a green `scripts/check.sh` plus a line in `CHANGELOG.md`.
[AGENTS.md](../AGENTS.md) lists the rules that are not obvious from the code; [PLAN.md](../PLAN.md)
holds the design, the decisions and the phases.

## Code layout

| Path | What it does |
| --- | --- |
| `custom_components/tado_x_matter_pro/engine/` | **The heating logic as pure Python** (no Home Assistant imports, explicit `now`). |
| `engine/model.py` | Room configuration, inputs, persisted state, the desired output. |
| `engine/room.py` | The reducer `step(state, inputs, config, now, event)` → new state, desired output, next wake-up: plan changes, expiries, the window state machine, events, the priority ladder, frost protection. |
| `engine/external.py` | Classifies thermostat reports: ours, intermediate, converged, external. |
| `engine/trend.py` | Port of Home Assistant's derivative sensor. |
| `engine/inference.py` | The heating / reached / off rule. |
| `controller.py` | One room in Home Assistant: reads inputs, runs the engine, writes thermostats that deviate, stores state. |
| `monitor.py` | Per room: finds each thermostat's temperature sensor, keeps the trends, infers the statuses. |
| `store.py` | Persistence with versioned migrations. |
| `config_flow.py` | House settings, options, the room subentry flow. |
| `climate.py`, `sensor.py`, `number.py`, `binary_sensor.py`, `entity.py` | Entities; they only read the controller and call it. |

The rule of thumb: **behaviour goes into the engine**, the Home Assistant side only feeds it and
carries out its effects. Engine tests run without Home Assistant and are fast; they are the place
for every new rule.

## Tests

| Folder / file | Covers |
| --- | --- |
| `tests/python/engine/` | The engine: ladder, windows, holds, frost, the classifier, trend, inference. No Home Assistant. |
| `tests/python/test_config_flow.py` | House form, options, adding and changing rooms. |
| `tests/python/test_room.py` | Rooms in a real Home Assistant core with fake Matter-like thermostats: schedule, away, windows, dial turns, the room thermostat, numbers, reloads, restarts. |
| `tests/python/test_heating_status.py` | Status sensors and the room's action; the trend compared with Home Assistant's own derivative helper over 300 random steps. |

The fake thermostats (`tests/python/conftest.py`) behave like Tado X over Matter: only *off* and
*heat*, mode and setpoint reported separately, a precise temperature sensor on the same device, and
`dial()` to change them without a Home Assistant context. Time moves with `freezer` and
`async_fire_time_changed`.

## The dev Home Assistant and the Dev House

```sh
scripts/ha.sh          # start (or restart) http://localhost:8123, user dev / dev
scripts/ha.sh stop     # stop gracefully and remove the container
scripts/ha.sh reset    # remove the container and its config volume
```

It runs the official Home Assistant image (version in `test/ha/.env`) with the integration mounted
from your working copy; restart it after Python changes. `scripts/ha-setup.mjs` finishes onboarding,
adds the integration with house settings, creates the schedules and the *Dev House* dashboard.

The **Dev House** (`test/ha/custom_components/dev_house`, mounted only into the dev instance) is a
fictional house to try the integration without hardware: 3 floors, 9 rooms, 11 Tado X-like
thermostats (two rooms with two each, one left with its default name), window and door contacts,
room sensors, an outdoor sensor, and *Away* / *Vacation* switches. A small thermal model warms rooms
while valves are open and cools them otherwise; each thermostat shows its true `valve_open`, to
check the heating status against.

Actions of the Dev House (Developer tools → Actions):

| Action | Simulates |
| --- | --- |
| `dev_house.set_window` | Open, close or toggle contacts (the dashboard tiles toggle on tap). |
| `dev_house.turn_dial` | Someone turning a thermostat: half-degree steps without a Home Assistant context. |
| `dev_house.drop_connection` | Thermostats unavailable for a while, like a Matter hiccup. |
| `dev_house.set_air_temperature` | Jump a room's air temperature. |
| `dev_house.set_outdoor_temperature` | Change the outdoor temperature. |

Options in `test/ha/configuration.yaml`: `speed` makes rooms warm and cool faster than real time
(keep 1 to judge the heating status, whose thresholds are per real hour); `report_delay` is how long
a written setpoint takes to be reported back (above 5 s it exercises the fallback that recognises
the integration's own writes by value).

## Privacy

The repository is public. Never commit anything from a real installation – names, entity ids,
places, schedules, coordinates, diagnostics or history. Fixtures are synthetic or anonymized; the
dev instance uses the Dev House.

## Releasing

Versions in `manifest.json` and `pyproject.toml` must agree; a tag `vX.Y.Z` (or `vX.Y.Z-beta.N` for a
pre-release) starts the release workflow, which checks the versions and publishes a GitHub release
that HACS offers.
