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
can be used too.

Optional: a [heating demand](heating-status.md) entity per thermostat, if you want to see which
radiator heats – Tado X does not report it over Matter.

## Prepare the tado° app

Matter gives Home Assistant control over the setpoint, but tado°'s own cloud features keep running
and would fight with the integration. In the tado° app, for every room with a Tado X thermostat:

1. **Schedule:** make it flat – one block for the whole day, every day, at one temperature. tado°
   would otherwise change the setpoint at its own block times; the integration treats such changes
   as manual changes and holds them.
2. **Manual control:** set changes to last "until you cancel" (not "until the next block" or a
   timer), so tado° never undoes a setpoint on its own. Changes coming from a smart home count as
   manual control for tado°, so this setting decides how long the integration's setpoints last.
3. **Open window detection:** switch it off. It would switch the thermostat off on its own; the
   integration does window handling with your contacts instead.

After these settings, every setpoint change comes either from the integration, from someone turning
the thermostat, or from someone using the tado° app – and the integration can tell its own writes
from the other two. If tado° still overwrites setpoints, a repair issue says so
([Troubleshooting](troubleshooting.md#repair-issues)).

## Matter and Thread

The thermostats talk Thread, a low-power mesh. How reliable the heating is depends on that mesh
more than on anything else:

- **Pair in the tado° app first, then share** the thermostat with Home Assistant (in the tado°
  app: the device's settings → *Pair device* / *Device linking*, then add the code in Home
  Assistant). Pairing the other way round is refused by the tado° app.
- **A Thread border router reachable from Home Assistant** – Home Assistant's own (OpenThread
  Border Router with a Thread radio) or a compatible one from another vendor. For tado°'s firmware
  updates and cloud features the thermostats need internet access through it (NAT64; Home
  Assistant's OpenThread Border Router app has it as an option).
- **Routers near every thermostat:** battery thermostats don't route; mains-powered Thread devices
  (smart plugs, the border router itself) do. A thermostat far from the nearest router drops out
  – it shows *unavailable*, takes setpoints late, or not at all.

The integration copes with drop-outs: it confirms every write and sends it again, sends nothing to
a thermostat that is unavailable but catches up when it returns, and recognises old writes the
Matter server delivers late. A thermostat that has not taken its setting for 30 minutes raises a
repair issue – a sign that it needs a router nearby.

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
  entities, repair issues and stored state are removed.
- **The integration:** Settings → Devices & services → Tado X Matter Pro → three-dot menu →
  *Delete*. All devices, entities, repair issues and the stored state
  (`.storage/tado_x_matter_pro`) go. Home Assistant backups made before still contain it. The
  history and logbook entries stay in the recorder like any integration's.

In both cases nothing is written to the thermostats on the way out: they keep their last setpoint
and mode. A room that was off for an open window stays off – set its thermostats yourself, or hand
them back to the tado° app.

**Updates** keep the stored state: older versions of it are migrated. A downgrade to an older
version of the integration keeps working if only details were added since; if the stored state
comes from a newer major version, the integration does not load and says so, rather than misread
it.
