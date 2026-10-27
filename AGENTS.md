# Tado X Matter Pro – guide for coding agents

A Home Assistant custom integration (HACS category _integration_) that controls Tado X thermostats
connected over Matter, room by room. Python only. Read this file first; `PLAN.md` holds the design,
the decisions and the phases.

## Map

| Path | What it is |
| --- | --- |
| `custom_components/tado_x_matter_pro/` | The integration. `manifest.json` carries the version. |
| `custom_components/tado_x_matter_pro/engine/` | **The heating logic as pure Python**: plan ladder, window state machine, overrides, external-change classification, trend and inference. No `homeassistant` imports. |
| `custom_components/tado_x_matter_pro/strings.json` | Backend strings (config flow, entities, services); `translations/{en,de}.json` are the shipped copies. |
| `tests/python/` | pytest with `pytest-homeassistant-custom-component`: a real HA core, no browser. `tests/python/engine/` tests the engine without HA. |
| `tests/fixtures/` | Exported real history for the replay tests, storage fixtures. |
| `scripts/check.sh` | Definition of done: ruff, format check, mypy, pytest. `--fix` formats first. |
| `test/ha/custom_components/dev_house/` | The Dev House: a fictional house with simulated Tado X-like thermostats, windows and a thermal model, mounted only into the dev HA. Services: `set_window`, `turn_dial` (a change at the device, no context), `drop_connection`, `set_air_temperature`, `set_outdoor_temperature`. |
| `test/ha/`, `scripts/ha.sh`, `scripts/ha-setup.mjs` | A real Home Assistant (official image, `HA_VERSION` in `test/ha/.env`) with the integration mounted. The setup script (Node 22, no deps) finishes onboarding with the dev user, adds the config entry, the Dev House schedules and its dashboard. `scripts/ha.sh reset` wipes its config volume. |

## Rules that are not obvious from the code

1. **Decisions live in the engine.** `engine/` decides what a room should do; the Home Assistant
   side (`controller.py`, `trv.py`, entities) only collects inputs, runs `engine.step` and carries out
   its effects. Never decide heating behaviour in an entity or a listener. The engine takes an explicit
   `now` (aware UTC); it never reads the clock.
2. **The integration writes a TRV only when it deviates** from the desired state. A reload or restart
   with nothing changed must not write anything.
3. **Our own writes are recognised by context id first**, by expected value second
   (`engine/external.py`). Anything else that changes mode or setpoint is a manual hold.
4. **State that must survive restarts lives in the Store** (`store.py`), keyed by subentry id, not in
   RestoreEntity. Changing a stored shape: additive → bump `STORAGE_MINOR_VERSION` and fill the keys
   in `_async_migrate_func`; breaking → bump `STORAGE_VERSION` and convert. Add a fixture under
   `tests/fixtures/storage/` and a load test.
5. **Strings go through `strings.json`** and the translation files (en is the source, de second).
   Logbook and notification texts cannot be translated by Home Assistant; they come from
   `messages.py` by `hass.config.language`. Log messages and config errors stay English.
6. **Python style is ruff `ALL`** with the ignores in `pyproject.toml` (HA style: runtime imports, no
   copyright headers) and mypy strict. Every module starts with a one-line docstring.
7. **Tests describe behaviour.** HA tests drive the real config entry (`MockConfigEntry`,
   `hass.config_entries.async_setup`) and assert on HA state and on the service calls the fake TRVs
   received, not on internals. Time moves with `freezer` + `async_fire_time_changed`.
8. **Schemas use probatio** (`import probatio as vol`), Home Assistant's validation library since
   2026.10. Service data is compared by value, never identity (HA hands enums as plain strings).
9. **Minimum HA is 2026.10** (`hacs.json`). Dev HA (`test/ha/.env`) and pytest
   (`pytest-homeassistant-custom-component`) run the same version. Before using an HA API, check it
   exists in 2026.10 or raise the minimum with a changelog note.
10. **Versions agree**: `manifest.json` and `pyproject.toml`; the release workflow checks the tag
    against both. A tag with `-beta.N` becomes a pre-release in HACS.

## Definition of done

```sh
scripts/check.sh   # ruff check + ruff format --check + mypy + pytest
```

Then update `CHANGELOG.md`, and tick the phase in `PLAN.md` with the date and what actually happened.

## Conventions

- **The repository is public.** Never commit anything from a real installation: names of people,
  rooms or places, entity ids, device names or serials, schedules, coordinates, raw diagnostics or
  history. Fixtures are synthetic or anonymized; the dev HA uses the fictional Dev House.
- English for docs, comments, names, keys and states, and commit messages. Commit messages: imperative subject, body explains why.
- Temperatures are floats in °C, rounded to 0.5 before they are written to a TRV.
- Times are aware datetimes in UTC inside the engine and the store (ISO strings in storage); local time
  only when parsing user input (`until`) and when rendering texts.
- Entity unique ids are `<subentry_id>_<key>`; one device per room with identifier `(DOMAIN, subentry_id)`.
- Removing the integration deletes the store; removing a room drops its part of the store.
