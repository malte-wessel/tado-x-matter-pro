# Entities

Every room gets one device with these entities:

| Entity | Example id (room in area *Kitchen*) | Exists |
| --- | --- | --- |
| [Room thermostat](#room-thermostat) | `climate.kitchen_heating` | always |
| [Mode](#mode) | `sensor.kitchen_heating_mode` | always |
| [Next change](#next-change) | `sensor.kitchen_heating_next_change` | always |
| [Comfort temperature](#numbers) | `number.kitchen_heating_comfort_temperature` | always |
| [Eco temperature](#numbers) | `number.kitchen_heating_eco_temperature` | always |
| [Window open](#window-open) | `binary_sensor.kitchen_heating_window_open` | if the room has windows or doors |
| [Window open too long](#window-open-too-long) | `binary_sensor.kitchen_heating_window_open_too_long` | if the room has windows or doors and *Remind after* is not 0 |
| [Back on](#back-on) | `sensor.kitchen_heating_back_on` | if the room has windows or doors |
| [*Thermostat* heating](#heating-status-per-thermostat) | `sensor.kitchen_heating_thermostat_kitchen_heating` | per thermostat with a heating demand entity |
| [Resume schedule](#resume-schedule) | `button.kitchen_heating_resume_schedule` | always |

The house gets one more device, **Heating** (no area), with what concerns all rooms:

| Entity | Id | Meaning |
| --- | --- | --- |
| [Resume all rooms](#the-house) | `button.heating_resume_all_rooms` | Every room back to its schedule. |
| [Rooms off schedule](#the-house) | `sensor.heating_rooms_off_schedule` | How many rooms *Resume all rooms* would change. |

## Entity ids and names

Home Assistant 2026.10 builds new entity ids from **area + device + entity name**. The room's device
is therefore called **Heating** (in German *Heizung*, following Home Assistant's language) and
placed in the area of the room's first thermostat, which gives ids like
`climate.kitchen_heating` and `sensor.kitchen_heating_mode`. If the thermostats have no area, the
device carries the room's name instead (`climate.kitchen`, `sensor.kitchen_mode`).

Entity names, states and attributes are translated (English and German). You can rename entities
and the device in Home Assistant as usual; the integration finds them by their unique ids.

## Room thermostat

`climate.<area>_heating` – the room as one thermostat.

| Property | Value |
| --- | --- |
| State (mode) | `auto` – follows the plan · `heat` – a manual hold · `off` – the room is switched off. A window pausing the room or frost protection heating it does not change this mode; the [Mode sensor](#mode) shows them. |
| `temperature` | The current target. While a window pauses the room: the temperature it will return to (a hold's, or the plan's). Empty when the room is switched off – unless frost protection heats it, then the frost temperature. |
| `current_temperature` | The room sensor; without one, the mean of the thermostats' readings. |
| `hvac_action` | `off` while all thermostats are off; `heating` while any heats, `idle` when all have a status and none heats – only known from [heating demand entities](heating-status.md); empty otherwise. |
| `preset_mode` | `boost` while a boost runs, `comfort` / `eco` while that preset holds, else `none` ([presets](how-it-works.md#boost-timed-overrides-presets)). |
| Range / step | 5–30 °C, 0.5 °C |

What setting it does is described in [How it works](how-it-works.md#the-room-thermostat). It works
with the standard actions `climate.set_temperature`, `climate.set_hvac_mode`, `climate.turn_on` and
`climate.turn_off`, so voice assistants and automations can control rooms like any thermostat.

## Mode

`sensor.<area>_heating_mode` – what decides the room's target right now.

| State | English | German | Meaning |
| --- | --- | --- | --- |
| `schedule` | Schedule | Zeitplan | A schedule block is active. |
| `idle` | Idle | Leerlauf | No block active, or an away sensor is on: eco temperature. |
| `manual` | Manual | Manuell | A manual change is held. |
| `timed` | Timed | Befristet | An override that ends at a time (set override until …, extend block). |
| `boost` | Boost | Boost | A boost runs. |
| `window` | Window | Fenster | A window is open; thermostats are off. |
| `waiting` | Waiting | Wartet | All windows closed, the close delay runs. |
| `off` | Off | Aus | The room is switched off with its room thermostat. |
| `frost` | Frost protection | Frostschutz | The room would be off but is below the frost temperature. |

Attributes:

| Attribute | Meaning |
| --- | --- |
| `target` | The setpoint the thermostats are given; empty while they are off. |
| `plan_target` | What the plan says right now (comfort, block, or eco temperature) – also while a hold or a window overrides it. |
| `next_change` | When the room's target changes next **by itself** (ISO time): a block edge that changes the temperature (a block continuing past midnight at the same temperature is none), the end of a hold at the next plan change, the end of a timed override or a boost, the end of the wait after a window. Empty when nothing would change on its own – while away, while the room is off, while a window is open. |
| `next_target` | The target then – also a next block's own temperature. With `target` and `next_change` a card can show "21 °C → 18 °C at 23:00". |
| `resume_at` | While `waiting`: when heating resumes. |
| `override_until` | When a timed override ends. |
| `boost_until` | When a boost ends. |
| `window` | The window phase: `closed`, `opening` (open, delay running), `open`, `waiting`. |

## Next change

`sensor.<area>_heating_next_change` (device class *timestamp*; German *Nächste Änderung*) – the
Mode sensor's `next_change` as its own entity, so cards show it as relative time (*in 2 hours*).
Attribute `target`: the temperature from then on. Empty while nothing would change by itself.

## Numbers

`number.<area>_heating_comfort_temperature` and `number.<area>_heating_eco_temperature` – the
room's two plan temperatures, 5–30 °C in 0.5 °C steps. Defaults 21 °C and 18 °C.

| Number | Used |
| --- | --- |
| Comfort temperature | During schedule blocks that have no temperature of their own. |
| Eco temperature | Outside schedule blocks and while an away sensor is on. |

Changing a number applies at once and counts as a plan change: it ends a manual hold in that room
– either number, also the one the plan does not use right now. The values are stored by the integration and survive restarts.

## Window open

`binary_sensor.<area>_heating_window_open` (device class *window*) – on while a window or door of
the room has been open for longer than the open delay. Off during short openings and during the wait after closing (see the Mode sensor for that). Only
rooms with windows or doors have it.

## Window open too long

`binary_sensor.<area>_heating_window_open_too_long` (device class *problem*; German *Fenster zu
lange offen*) – on once a window has kept the room off for the room's *Remind after* minutes, until
it is closed. It turns on whatever the outdoor temperature; only the notification waits for the
cold.

## Back on

`sensor.<area>_heating_back_on` (device class *timestamp*; German *Wieder an*) – when heating
resumes after the room's windows and doors were closed: the closing time plus the room's *Back on
after* delay. Set only while that wait runs (Mode *waiting*); empty while a window is still open and
otherwise. Cards show timestamps as relative time, so a tile reads *in 4 minutes*. Only rooms with
windows or doors have it. The same time is the Mode sensor's `resume_at` attribute.

## Resume schedule

`button.<area>_heating_resume_schedule` – the room back to its schedule; the same as the action
`tado_x_matter_pro.resume_schedule` (see [Back to the schedule](how-it-works.md#back-to-the-schedule)).

## The house

- `button.heating_resume_all_rooms` – every room back to its schedule at once.
- `sensor.heating_rooms_off_schedule` – the number of rooms where something other than the plan
  decides: a manual hold or a room switched off (later also boost and timed overrides) – exactly
  the rooms *Resume all rooms* would change. Attribute `rooms`: those rooms by name, each with its
  [mode](#mode), e.g. `{"Kitchen": "manual"}`. A dashboard badge can show the sensor while it is
  above 0 and press the button on tap.

## Heating status per thermostat

`sensor.<area>_heating_<thermostat name>_heating` – one per thermostat of the room, on the room's
device, named after the thermostat (*Thermostat Kitchen heating*, in German *… Heizstatus*).

| State | English | German | Meaning |
| --- | --- | --- | --- |
| `heating` | Heating | Heizt | The demand is at or above the threshold, or on. |
| `reached` | Reached | Erreicht | The thermostat is on, but its demand is below the threshold, or off. |
| `off` | Off | Aus | The thermostat is off. |
| unknown | | | The thermostat or its demand entity is unavailable. |

Attributes:

| Attribute | Meaning |
| --- | --- |
| `thermostat` | The thermostat's entity id. |
| `demand` | The heating demand entity's value: a percentage, or `true`/`false`. Not recorded in the history; the demand entity keeps its own. |

Where the status comes from is explained in [Heating status](heating-status.md).
