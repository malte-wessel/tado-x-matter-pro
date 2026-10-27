# Installation

## Requirements

- **Home Assistant 2026.10 or newer.** The integration uses config subentries for rooms and the
  entity naming of 2026.10.
- **Tado X thermostats added to Home Assistant over Matter** (Settings → Devices & services →
  Matter). Each thermostat then appears as a `climate` entity with the modes *off* and *heat*,
  plus a temperature sensor and a humidity sensor on the same device.
- **A schedule helper per heating pattern** (Settings → Devices & services → Helpers → Create
  helper → Schedule). Rooms can share a schedule; see [Configuration](configuration.md#schedules).
- Optional: window and door contacts (`binary_sensor`), a room temperature sensor per room, and
  switches or sensors that mean "nobody is home" (for example an `input_boolean` for away and one
  for vacation).

Other thermostats that look the same to Home Assistant (a `climate` entity with *off* and *heat*)
can be used too, but the [heating status](heating-status.md) is tuned for Tado X.

## Prepare the tado° app

Matter gives Home Assistant control over the setpoint, but tado°'s own cloud features keep running
and would fight with the integration. In the tado° app, for every room with a Tado X thermostat:

1. **Schedule:** make it flat – one block for the whole day, every day, at one temperature. tado°
   would otherwise change the setpoint at its own block times; the integration treats such changes
   as manual changes and holds them.
2. **Manual control:** set changes to last "until you cancel" (not "until the next block" or a
   timer), so tado° never undoes a setpoint on its own.
3. **Open window detection:** switch it off. It would switch the thermostat off on its own; the
   integration does window handling with your contacts instead.

After these settings, every setpoint change comes either from the integration, from someone turning
the thermostat, or from someone using the tado° app – and the integration can tell its own writes
from the other two.

## Install with HACS

The integration is not in the HACS default list yet; add it as a custom repository:

1. HACS → three-dot menu → **Custom repositories**.
2. Repository `https://github.com/malte-wessel/tado-x-matter-pro`, type **Integration**.
3. Find **Tado X Matter Pro** in HACS, download it, and restart Home Assistant.

## Install by hand

Copy the folder `custom_components/tado_x_matter_pro` of this repository into the
`custom_components` folder of your Home Assistant configuration (next to `configuration.yaml`) and
restart Home Assistant.

## Add the integration

Settings → Devices & services → **Add integration** → *Tado X Matter Pro*. The first form holds the
house settings; rooms are added afterwards. Continue with [Configuration](configuration.md).

There is only one Tado X Matter Pro entry per Home Assistant; it holds all rooms.

## Removing

- **A room:** on the integration page, open the room's three-dot menu → *Delete*. Its device,
  entities and stored state are removed. The thermostats stay at their last setpoint and mode.
- **The integration:** Settings → Devices & services → Tado X Matter Pro → three-dot menu →
  *Delete*. All rooms and the stored state go; the thermostats keep their last setpoint. Home
  Assistant backups contain the stored state under `.storage/tado_x_matter_pro`.
