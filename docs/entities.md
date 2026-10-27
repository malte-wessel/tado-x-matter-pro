# Entities

Every room gets one device with these entities:

| Entity | Example id (room in area *Kitchen*) | Exists |
| --- | --- | --- |
| [Room thermostat](#room-thermostat) | `climate.kitchen_heating` | always |
| [Mode](#mode) | `sensor.kitchen_heating_mode` | always |
| [Comfort temperature](#numbers) | `number.kitchen_heating_comfort_temperature` | always |
| [Eco temperature](#numbers) | `number.kitchen_heating_eco_temperature` | always |
| [Window open](#window-open) | `binary_sensor.kitchen_heating_window_open` | if the room has windows or doors |
| [Back on](#back-on) | `sensor.kitchen_heating_back_on` | if the room has windows or doors |
| [*Thermostat* heating](#heating-status-per-thermostat) | `sensor.kitchen_heating_thermostat_kitchen_heating` | one per thermostat |

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
| `temperature` | The current target. While a window pauses the room: the temperature it will return to. Empty when the room is off. |
| `current_temperature` | The room sensor; without one, the mean of the thermostats' readings. |
| `hvac_action` | `heating` while any thermostat heats, `idle` once all reached their setpoint, `off` while they are off ([Heating status](heating-status.md)). |
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
| `window` | Window | Fenster | A window is open; thermostats are off. |
| `waiting` | Waiting | Wartet | All windows closed, the close delay runs. |
| `off` | Off | Aus | The room is switched off with its room thermostat. |
| `frost` | Frost protection | Frostschutz | The room would be off but is below the frost temperature. |

Attributes:

| Attribute | Meaning |
| --- | --- |
| `target` | The setpoint the thermostats are given; empty while they are off. |
| `plan_target` | What the plan says right now (comfort, block, or eco temperature) – also while a hold or a window overrides it. |
| `next_change` | When the schedule switches next (ISO time). |
| `next_target` | The plan's temperature after that switch: the eco temperature when a block ends, the comfort temperature when one starts. A block's own temperature is not known in advance, so a block with its own temperature shows the comfort temperature here. While away: the eco temperature. |
| `resume_at` | While `waiting`: when heating resumes. |
| `override_until` | For overrides that end at a time (planned: boost, heat/eco until). |
| `window` | The window phase: `closed`, `opening` (open, delay running), `open`, `waiting`. |

## Numbers

`number.<area>_heating_comfort_temperature` and `number.<area>_heating_eco_temperature` – the
room's two plan temperatures, 5–30 °C in 0.5 °C steps. Defaults 21 °C and 18 °C.

| Number | Used |
| --- | --- |
| Comfort temperature | During schedule blocks that have no temperature of their own. |
| Eco temperature | Outside schedule blocks and while an away sensor is on. |

Changing a number applies at once. Changing the one the plan currently uses is a plan change and
ends a manual hold in that room. The values are stored by the integration and survive restarts.

## Window open

`binary_sensor.<area>_heating_window_open` (device class *window*) – on while a window or door of
the room has been open for longer than the open delay. Off during short openings and during the wait after closing (see the Mode sensor for that). Only
rooms with windows or doors have it.

## Back on

`sensor.<area>_heating_back_on` (device class *timestamp*; German *Wieder an*) – when heating
resumes after the room's windows and doors were closed: the closing time plus the room's *Back on
after* delay. Set only while that wait runs (Mode *waiting*); empty while a window is still open and
otherwise. Cards show timestamps as relative time, so a tile reads *in 4 minutes*. Only rooms with
windows or doors have it. The same time is the Mode sensor's `resume_at` attribute.

## Heating status per thermostat

`sensor.<area>_heating_<thermostat name>_heating` – one per thermostat of the room, on the room's
device, named after the thermostat (*Thermostat Kitchen heating*, in German *… Heizbetrieb*).

| State | English | German | Meaning |
| --- | --- | --- | --- |
| `heating` | Heating | Heizt | The radiator is being heated. |
| `reached` | Reached | Erreicht | The thermostat is on, but its setpoint is reached; the valve is (mostly) closed. |
| `off` | Off | Aus | The thermostat is off. |

Attributes:

| Attribute | Meaning |
| --- | --- |
| `thermostat` | The thermostat's entity id. |
| `temperature` | The thermostat's own reading (from its precise temperature sensor if it has one). |
| `trend` | How fast that reading changes, in °C per hour, over the last 20 minutes. |

`temperature` and `trend` change with every reading and are not recorded in the history; the
status itself is.

How the status is inferred – and when it can be wrong – is explained in
[Heating status](heating-status.md).
