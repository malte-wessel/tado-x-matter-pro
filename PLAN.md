# Tado X Matter Pro – implementation plan

A Home Assistant custom integration (HACS, category _integration_) that controls Tado X radiator
thermostats connected over Matter, room by room: schedules, windows, away modes, manual holds, boost
and timed overrides, plus a local "is it heating" inference. It replaces the usual do-it-yourself
setup of a blueprint, one automation per room, per-room helpers (temperatures, timers, trend and
status sensors) and template macros with one integration and the schedule helpers.
Quality bar and tooling come from `pro-budget`.

## Decisions

| Topic | Decision |
| --- | --- |
| Scope | Python only, no panel; dashboards read plain states and attributes. |
| Structure | One config entry (`single_config_entry`) with house options, one **config subentry per room**. |
| Schedules | HA `schedule` helpers stay the source (native editor; a block may carry `temperature` in its additional data). |
| Manual hold | A change not made by the integration (TRV dial, Tado app, HA on a TRV, the room climate) holds until the next plan change. Rooms with several TRVs sync all of them to the new value. |
| Boost | Default 30 °C for 30 min (service may override both). A layer on top of the override slot; when it ends, whatever is underneath applies. |
| Resume | Clears manual hold, timed override, room-off and boost, and skips the wait after a window closed. An open window still keeps the room off. |
| Away / vacation | House-wide idle sensors. Switching them clears manual holds only; boost and timed overrides run out. |
| Dial turned while a window is open | Respected: the room heats as a manual hold until the next plan change; a new opening switches off again. |
| Windows | Per room: open delay (debounce, 30 s), close delay (5 min), reminder after N min (30, 0 = off). House-wide: outdoor condition (optional sensor, "only below N °C") and notify targets. |
| Room temperature | Optional room sensor per room; fallback is the mean of the TRVs' own temperature sensors. |
| Heating inference | Rule on setpoint − TRV temperature and the TRV temperature trend, with hysteresis, per TRV: one status sensor per thermostat, and the room climate's native `hvac_action` = the most active of its TRVs. Trend from each TRV's own temperature sensor (0.01 °C; the climate attribute is only 0.1 °C), found through the device registry. |
| Storage | `homeassistant.helpers.storage.Store`, key `tado_x_matter_pro`, versioned with migrations. Holds numbers, overrides, window phases, deadlines and TRV bookkeeping. No RestoreEntity. |
| Install | HACS integration, public repo. |
| Language | English names, keys and states everywhere; translations `strings.json` + `translations/{en,de}.json`. Logbook and notification texts (which HA cannot translate) come from `messages.py` by `hass.config.language`. |
| Privacy | The repo is public: no data from a real installation (names, entity ids, places, schedules, coordinates, raw diagnostics or history). Test fixtures are synthetic or anonymized. |
| Minimum HA | 2026.10 (decided 2026-10-27). |
| Python tooling | uv, ruff `ALL` with documented ignores, mypy strict, pytest-homeassistant-custom-component 0.13.370, `import probatio as vol`. |
| Name / domain | Tado X Matter Pro, domain `tado_x_matter_pro`. |

## Facts that shape the design

- HA's Matter climate writes `SystemMode`, then `OccupiedHeatingSetpoint`, so one call can produce
  two state reports. `off` keeps the setpoint attribute. Matter devices can blip to `unavailable`
  for a few seconds.
- An entity keeps the caller's context for 5 s after a service call, so reports within 5 s carry our
  context id. That is the primary "ours" signal; value matching is the fallback.
- `schedule` exposes only the current block's data and `next_event`; the next block's temperature
  needs `schedule.get`. Block edges (including the midnight continuation of a block that runs past
  midnight) fire attribute-only changes; editing a schedule may fire only `state_reported`.
- Only a change of the **plan key** (schedule on/off, block temperature, idle) is a plan change, so
  attribute-only schedule updates do not reset manual holds.
- Subentries: `async_get_supported_subentry_types`, `async_add_entities(..., config_subentry_id=)`;
  update listener → reload together with `async_update_and_abort` (`async_update_reload_and_abort`
  raises when the entry has update listeners).
- Entity services: `service.async_register_platform_entity_service(..., entity_domain="climate")`
  in `async_setup` → area, floor and label targets work.

## Configuration (UI only)

**House** (setup form, later "Configure", in flow sections): idle sensors (input_boolean /
binary_sensor, multiple); frost protection 7 °C; boost temperature 30 °C and duration 30 min;
window reminder: outdoor sensor (optional), "only below °C" (optional), notify targets (multi-select
of the `notify.*` actions found when the form opens, custom values allowed).

**Room subentry** ("Add room", reconfigurable): name (default: area of the first TRV); thermostats
(climate, multiple, required; each TRV in one room only); schedule (required); windows and doors
(binary_sensor, multiple); room temperature sensor (optional); section "Windows": switch off after
30 s open, back on after 5 min closed, remind after 30 min open (0 = no reminder).
Not asked: each TRV's own temperature sensor (same device) and the device area (the TRV's area).

**Not configuration:** comfort and eco temperatures are number entities (dashboard, defaults
21/18); times and block temperatures live in the schedule helpers; overrides are services and buttons.

## Backend modules (`custom_components/tado_x_matter_pro/`)

| File | Responsibility |
| --- | --- |
| `__init__.py` | `async_setup` (entity services), `async_setup_entry` (Store, one `RoomController` per subentry, start after HA started), update listener → reload, `async_remove_entry` deletes the store, `async_migrate_entry`. |
| `config_flow.py` | Config flow, options flow (house), `RoomSubentryFlow` (user + reconfigure). |
| `engine/model.py` | Dataclasses and enums: room config, room state, override, boost, window phase, TRV view, effects. |
| `engine/plan.py` | Priority ladder, plan key, next transitions from the weekly schedule. |
| `engine/window.py` | Debounce state machine. |
| `engine/room.py` | Reducer `step(state, inputs, event, now) -> (state, effects, next_wakeup)`. |
| `engine/external.py` | Classifies TRV reports: ours, intermediate, converged, external. |
| `engine/trend.py` | Exact port of HA's derivative sensor (20 min window, 5 min max sub-interval, °C/h). |
| `engine/inference.py` | heating / reached / off with hysteresis. |
| `controller.py` | `RoomController`: listeners → events → `engine.step` → effects; one wakeup timer; serial event queue; trace ring buffer. |
| `trv.py` | `TrvWriter`: reconcile desired vs. actual, expectation before the call, context ids, retry only on exception or unavailable. |
| `history.py` | Seeds trends from the recorder (last 25 min) in the background. |
| `store.py` | Store subclass with `_async_migrate_func` and minor version. |
| `entity.py`, `climate.py`, `sensor.py`, `number.py`, `button.py`, `binary_sensor.py` | Entities. |
| `services.py`, `services.yaml` | Entity services. |
| `logbook.py`, `messages.py` | Logbook descriptions, EN/DE texts. |
| `alerts.py`, `issues.py`, `diagnostics.py` | Window reminder notifications, repair issues, diagnostics with the trace. |

### Entities (one device per room)

The room device is called "Heating" and sits in the area of the room's first thermostat, because
Home Assistant 2026.10 builds entity ids from area + device + entity (`climate.kitchen_heating`,
`sensor.kitchen_heating_mode`). Without an area the device carries the room's name instead.

| Entity | State / notes |
| --- | --- |
| `climate` | Modes `auto` (plan), `heat` (manual hold), `off` (room off, no expiry); presets none/boost/comfort/eco; `hvac_action` from inference; target = effective target; current = room sensor or TRV mean; step 0.5; `turn_on` → auto. |
| `sensor` Mode (enum) | `schedule, idle, manual, timed, boost, window, waiting, off, frost`; attributes `target, reason, plan_target, next_change, next_target, resume_at, override_until, boost_until` (absolute timestamps). |
| `sensor` Next change | `device_class: timestamp`. (planned) |
| `sensor` Back on (rooms with windows) | `device_class: timestamp`: end of the wait after the windows closed; empty otherwise. ✅ 2026-10-27 |
| `sensor` <TRV> heating (one per thermostat) | Enum `heating, reached, off` from the inference for that one TRV; attribute `trend` (°C/h). Lets rooms with several radiators show which one heats. |
| `number` Comfort temperature, Eco temperature | Store-backed, step 0.5. Comfort applies during schedule blocks, eco outside them and while away. |
| `binary_sensor` Window open, Window open too long | On once a window has been open for the open delay; reminder state. Only for rooms with windows. |
| `button` Boost, Resume schedule | |

### Services (climate entity services)

| Service | Fields |
| --- | --- |
| `boost` | `duration?`, `temperature?` |
| `set_override` | `temperature` or `preset` (comfort/eco); `until` (time, rolls to tomorrow if past) or `duration` or `until_next_change` |
| `extend_block` | `until` → override with a snapshot of the current plan target |
| `resume_schedule` | – |

`climate.set_temperature` = manual hold; `set_hvac_mode` auto = resume (without skipping the wait),
heat = hold at the current target, off = room off; `set_preset_mode` boost/comfort/eco/none.

## Room state machine

**Ladder** (first match wins; targets rounded to 0.5):

1. Window OPEN or WAITING → off, unless the manual hold was made during this opening (`window_ack`).
2. Boost → heat at the boost temperature.
3. Override slot → its target (absolute, off, or a snapshot of the plan).
4. Plan: idle or schedule off → idle temperature; block `temperature` → that; else heating temperature.
5. Frost: heat targets ≥ frost; if the output is off and the room is below frost → heat at frost
   until frost + 1 (mode `frost`).

**Window:** CLOSED →(any open)→ OPENING (open delay; closing before = bounce, counted) → OPEN (TRVs
off, logbook, reminder after N min) →(all closed)→ WAITING (close delay) → CLOSED. WAITING →(open)→
OPEN directly. Resume or the deadline end WAITING. An external change in WAITING → CLOSED and manual
hold; in OPEN → manual hold with `window_ack`; a new OPENING → OPEN clears `window_ack`.

**What clears what:**

| Trigger | Manual hold | Timed / extend | Room off | Boost | Wait |
| --- | --- | --- | --- | --- | --- |
| Plan key change | clear | keep | keep | keep | – |
| Idle on / off | clear | keep | keep | keep | – |
| Number change affecting the active plan base | clear | keep | keep | keep | – |
| Expiry | – | clear | – | clear | → CLOSED |
| Resume | clear | clear | clear | clear | → CLOSED |
| External TRV change | replace (sync siblings) | replace | replace | clear | see window |

**Restart:** load the store, wait for HA started, rebuild inputs; a changed plan key is a plan
change; expired deadlines apply; persisted OPEN/WAITING with a window still open → OPEN, WAITING past
its deadline → CLOSED, CLOSED but open now → OPENING. A TRV that differs from `last_commanded` → manual
hold (first install: apply the plan). Reconcile writes only on deviation, so reloads cause no writes.

**External changes:** per TRV an expectation `{prev, want, ctx_ids, issued_at, returned_at}` is
registered before the blocking service call. Each report that changes mode or setpoint is (1) ours
when it carries our context id, (2) intermediate within a 30 s settle window on the prev → want path,
(3) converged when it equals the desired value ±0.05, (4) otherwise external, coalesced over 4 s (dial
bursts). Unavailable → available with a deviation is drift and re-applied. Setpoint-only reports
while off are ignored. Counters and a trace go to diagnostics.

**Issues (Repairs):** TRV unavailable > 30 min; window sensor chatter (bounces per hour); Tado app
likely overwriting setpoints (external changes in ≥ 2 rooms within 60 s).

## Repository layout

```
custom_components/tado_x_matter_pro/   the integration (engine/ is pure Python)
tests/python/                          pytest against a real HA core; tests/python/engine/ without HA
tests/fixtures/                        synthetic / anonymized history and storage fixtures
scripts/check.sh                       ruff, mypy, pytest (what CI runs)
scripts/ha.sh, scripts/ha-setup.mjs    dev Home Assistant in Docker (Node 22 for the setup script)
test/ha/                               its configuration.yaml, .env and the Dev House simulator
```

## Dev House

`test/ha/custom_components/dev_house` is mounted only into the dev Home Assistant: a fictional house
(3 floors, 9 rooms, 11 thermostats, 11 window and door contacts, room sensors, an outdoor sensor)
whose thermostats behave like Tado X over Matter (`off`/`heat`, mode and setpoint reported
separately after a delay, a 0.01 °C temperature sensor on the same device) on top of a simple
thermal model. Services simulate a dial turn without context, windows, a connection drop and room
or outdoor temperatures; `speed` in `configuration.yaml` makes the rooms warm and cool faster. The
setup script adds schedules, the away/vacation switches and a "Dev House" dashboard.

## Phases

Each phase ends green on `scripts/check.sh` and with a changelog line; nothing ships before 0.1.0-beta.1.

0. **Scaffold.** ✅ done 2026-10-27. Repo from pro-budget's Python tooling (CI: hassfest, HACS — which
   needs repository topics and brand icons —, python), PLAN.md, AGENTS.md, empty config flow,
   the Dev House for the dev Home Assistant.
1. **Spikes.** S1 Matter contract test: HA's real Matter integration in pytest (dev dependency
   `matter-python-client`, mocked server) with an anonymized Tado X node fixture; asserts the report
   sequence of `set_temperature(heat, …)` and which reports carry our context. S2 + S3 analysis of
   real TRV history (outside the repo; only the conclusions land here): what dial turns, app changes
   and tado° cloud writes look like, their timing and rounding. S4 subentry UX (add, reconfigure,
   delete removes the device) in the dev HA. Done when the findings are recorded below.
2. **Thin slice through phases 2 and 3.** ✅ done 2026-10-27 (to try the integration in the Dev House
   early): engine (ladder, window state machine with open and close delay, manual hold until the
   next plan change incl. sibling sync, room off, resume, timed-override expiry, frost floor,
   external-change classifier); house form and options with sections; rooms as subentries (add,
   reconfigure, one room per thermostat, name from the area); controller with store, reconcile
   only on deviation, changes while HA was down → manual hold; room thermostat, mode sensor,
   comfort/eco numbers, window sensor. 56 tests (engine + HA with fake Matter-like thermostats).
   Not yet: boost and timed-override services, the 100 % engine coverage gate, a reminder or
   repairs.
3. **Engine (rest).** `engine/*` with table tests for the ladder, the clearing matrix, window timings and the
   external classifier. Done at 100 % branch coverage of `engine/`.
4. **Shell (rest).** Flows, controller, TrvWriter, store, all entities; a fake Matter-like TRV in the
   tests; the real `schedule` component with block data; time travel. Done when every behaviour of
   the ladder is reproduced against HA and a reload makes no writes.
5. **Commands.** Services, presets, buttons, logbook (EN/DE), diagnostics. Tests include area targets.
6. **Inference.** ✅ mostly done 2026-10-27: `engine/trend.py` (derivative port), `engine/inference.py`
   (the tuned rule), `monitor.py` (each thermostat's precise temperature sensor found on its device,
   trends seeded from the recorder, ticks like the derivative's max sub-interval), one status sensor
   per thermostat (heating / reached / off, attributes trend and reading), the room thermostat's
   `hvac_action`. A test compares the trend with Home Assistant's derivative helper over 300 random
   steps (within one rounding unit). Open: the replay against recorded real history.
   Originally: Trend, inference, seeding; the per-TRV status sensors and the room's `hvac_action`. Done when an equivalence test against HA's derivative
   sensor (|Δ| ≤ 0.01) and a replay test on anonymized recorded history agree ≥ 98 %.
7. **Extras.** Frost guard, window reminder and notify, issues. Release 0.1.0-beta.1.
8. **Real-world rollout.** One room first next to the existing setup, then all rooms, then the old
   automations and helpers go. Done after one week without regressions.

## Findings

- Home Assistant 2026.10 prefixes new entity ids with the area (setting `entity_id_parts`, default
  area + parent device + device + entity), so a device named like its area doubles the name
  (`kitchen_kitchen`). Hence the room device's name "Heating".
- The store must be written on unload, not only with the 1 s delayed save: a reload otherwise starts
  from the previous state and overwrites a change the user just made.
- The dev container must be stopped gracefully (`docker stop`) before it is removed, or Home
  Assistant loses registry changes from its last seconds.
- The S1 Matter contract test is postponed (decided 2026-10-27).
- Review 2026-10-27: (1) schedules and idle sensors read as off while unavailable, so a blip ended
  holds or flipped eco/comfort – all inputs now keep their last available state, and inputs not
  known since the start fall back to the stored plan key; (2) any run during the 4 s dial coalesce
  wrote the old target back to the turned thermostat – no writes while an external change is
  pending; (3) every reading rewrote the store (now only on change) and recorded the status
  sensors' trend/reading attributes (now unrecorded).
- Open from that review: retry failed writes with backoff and a timeout; store the last command
  next to the last report so a write in flight at shutdown is not a hold; repair issue for window
  contacts unavailable while open; away vs. vacation temperatures; `zone.home`/`person` as idle
  inputs; window detection from the temperature drop for rooms without contacts; an `away` mode
  separate from `idle`.

## Open questions (defaults in brackets)

- Should the thermostat selector be limited to Matter climates? [No: any climate, so the fake TRVs
  of tests and the dev HA work; the README says what is supported.]
- Chatter threshold for the repair issue. [10 bounces within an hour.]
- How long a TRV may be unavailable before an issue. [30 min.]
