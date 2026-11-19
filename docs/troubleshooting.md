# Troubleshooting

## First: what does the room think?

The room's [Mode sensor](entities.md#mode) says which rule decides right now, what the plan target
is, when the schedule switches next, and – after a window – when heating resumes. Most questions
are answered there.

The **logbook** (and each room thermostat's *Activity*) lists what happened to a room: a manual
hold and what it held, a timed override, the room switched off, back to the schedule, switched off
for a window and back on after it, a boost and its end – in English or German, following Home
Assistant's language.

For the reasons behind each decision, turn on debug logging for the integration: Settings → Devices
& services → Tado X Matter Pro → three-dot menu → **Enable debug logging**. The log then shows, per
room, every event (a thermostat changed externally, a hold, a mode change) and the decision that
followed, e.g.

```
Kitchen: climate.kitchen_thermostat changed externally to TrvView(available=True, hvac_mode='heat', setpoint=23.0)
Kitchen: ExternalChange(hvac_mode='heat', temperature=23.0) → Desired(hvac_mode='heat', temperature=23.0, mode=<Mode.MANUAL: 'manual'>, ...)
```

Turn it off again afterwards (**Disable debug logging** downloads the log).

Without debug logging, **diagnostics** show the same for the recent past: Settings → Devices &
services → Tado X Matter Pro → three-dot menu → **Download diagnostics** (all rooms), or the same on
a room's device page (one room). They contain each room's inputs, decision and stored state, every
thermostat's last report and write, and a trace of the last 200 reports, decisions and writes – for
example which report was taken as a manual change and why.

## The room is in *manual* although nobody touched it

Something else changed a thermostat. Usual causes:

- **The tado° app's own schedule** changes the setpoint at its block times. Make the tado°
  schedule flat ([Installation](installation.md#prepare-the-tado-app)).
- **tado°'s open window detection** switched a thermostat off. Switch it off in the app.
- **An automation or a dashboard card** controls the thermostat entities directly. Point it at the
  room thermostat (`climate.<area>_heating`) instead.
- **A change while Home Assistant was restarting** – that is intended: it becomes a hold until the
  next schedule change.

The debug log and the trace in the diagnostics show which thermostat changed and to what.

## The heating does not come back after a window

- Check the Mode sensor: *waiting* means the close delay runs; the room's *Back on* sensor says
  until when.
- *window* means a window or door of the room still reports open. Check every contact of the room –
  a door left ajar counts. A contact that is *unavailable* keeps its last known state, so one that
  dropped out while open keeps the room off until it reports again.
- Lower *Back on after* in the room settings if 5 minutes is too long for you.

## Short openings still switch the heating off

Raise *Switch off after* in the room settings. A front door that stands open while shopping is
carried in may need a minute or more.

## The heating status is missing, unknown or late

- **Missing:** only thermostats with a [heating demand](heating-status.md) entity have one. Add it
  in the room's second step (**Change room**).
- **Unknown:** the demand entity or the thermostat is unavailable – check the demand entity first.
- **Late:** a cloud demand is only as fresh as its integration's polling. The status sensor's
  `demand` attribute shows the value it used.

## A thermostat does not take its setting

A repair issue *… does not take its setting* means the integration sent a thermostat a new setting
and it has not reported it back for 30 minutes. The integration keeps trying: on a schedule first,
then whenever the thermostat reports or reconnects. Usual causes:

- **A weak Thread link** – the thermostat is far from the next router (a mains-powered Thread
  device such as a smart plug, or the border router). Add a router nearby.
- **Low batteries.**
- **The thermostat is unavailable** in Home Assistant – check its Matter device page.

The diagnostics' trace shows each attempt (`write`, `retry`, `gave_up`, `confirmed`).

## Repair issues

Besides *… does not take its setting* (above), the integration raises these under Settings →
System → Repairs:

| Issue | Means | Goes away |
| --- | --- | --- |
| *A window contact of … keeps bouncing* | 10 openings within an hour were shorter than the room's open delay. The room ignored them; the contact or the door probably needs a look. | After an hour without bouncing. |
| *Window contact … is gone while open* | The contact has been unavailable for 30 minutes and last said *open*, so the room stays off. | When it reports again. |
| *… uses entities that are gone* / *The house settings use entities that are gone* | An entity the room (or the house settings) names no longer exists or is disabled – usually renamed. Pick it again with *Change room* (or *Configure*). Checked 5 minutes after a start, and whenever entities are renamed or removed. | When the entity is back. |
| *Something overwrites setpoints in several rooms* | Thermostats in two or more rooms were changed outside the integration within a few seconds – usually the tado° app's schedule, manual-control setting or open window detection ([Prepare the tado° app](installation.md#prepare-the-tado-app)). | With the next restart. |

## The entity ids look odd

New entity ids are built from area + device + name. A room device called *Heating* in the area
*Kitchen* gives `climate.kitchen_heating`. If your thermostats have no area, the device is named
after the room. You can rename any entity id in Home Assistant; the integration does not depend on
them. See [Entities](entities.md#entity-ids-and-names).

## A thermostat is in two rooms

Not possible – the room form refuses it. Remove the thermostat from the other room first.

## Everything is unavailable after a restart

The integration starts deciding once Home Assistant has fully started. If entities stay
unavailable, check the log for errors from `custom_components.tado_x_matter_pro` and whether the
thermostats and schedules themselves are available.

## Reporting a problem

Open an issue at <https://github.com/malte-wessel/tado-x-matter-pro/issues> with the integration
and Home Assistant versions, what you did, what you expected, and the diagnostics or the debug log
lines around it. Diagnostics leave out notification targets but contain your entity ids, which
often name rooms; remove anything personal (names, locations) before posting.
