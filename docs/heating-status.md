# Heating status

Over Matter a Tado X thermostat reports its mode, its setpoint and its temperature – but not its
valve position and not how much it heats. So Home Assistant cannot tell on its own whether a
radiator is heating. Tado X Matter Pro shows a heating status only for thermostats where you
give it an entity that knows: a **heating demand** entity.

## Heating demand entities

Per thermostat, in the room's second step (**Heating demand**), you can pick one entity:

- **A percentage** (`sensor`), for example the heating power a cloud integration such as Tado
  Hijack (HACS) reads from tado°. The thermostat counts as heating from the **heating demand
  threshold** of the house settings on (default 3 %).
- **An on/off value** (`binary_sensor`): on = heating. For example a *Threshold* helper on a
  temperature sensor at the radiator's supply pipe – the pipe is hot exactly while water flows.

Thermostats without a demand entity have no status sensor. The integration itself never talks to
the tado° cloud; it only reads the entity you picked.

Why not guess it from the thermostat's temperature? A valve that opens fully makes the reading
rise quickly, but a valve held partly open for hours – the usual case while a room keeps its
temperature – barely moves it. A guessed status was wrong too often to be useful.

## The status

| Thermostat | Demand | Status |
| --- | --- | --- |
| off | anything | `off` – a cloud value may still show the last demand for a while |
| heat | % ≥ threshold, or on | `heating` |
| heat | % < threshold, or off | `reached` |
| heat | unavailable, unknown or not a number | unknown |
| unavailable | anything | unknown |

The status sensor (`sensor.<area>_heating_<thermostat>_heating`) carries the demand as an attribute.
It is not recorded twice: the demand entity keeps its own history.

## The room's action

The room thermostat's `hvac_action` combines its thermostats:

- `off` when all of them are off,
- `heating` as soon as one of them heats,
- `idle` when all have a status and none heats,
- empty otherwise – for example when a thermostat without a demand entity might be heating.

So a room without any demand entity shows `off` while it is off, and no action otherwise.

## Things to know

- **A cloud value lags.** A cloud integration polls every few minutes – longer when its request
  budget runs low – so the status follows the valve with that delay.
- **The threshold** filters tiny demands that do not warm the radiator noticeably. Change it in the
  house settings; the integration reloads.
