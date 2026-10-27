# How it works

Every room is decided on its own. Whenever something relevant changes – the schedule, an away
sensor, a window, a thermostat, a temperature you set – the integration works out what the room's
thermostats should do and writes them **only if they differ** from that. A thermostat already at
the right setpoint is never written again, so reloads and restarts cause no traffic.

The room's [Mode sensor](entities.md#mode) always tells you which rule is deciding right now.

## What decides the temperature

The first rule that applies wins:

| # | Rule | Thermostats | Mode |
| --- | --- | --- | --- |
| 1 | A window is open (after the open delay), or the wait after closing runs | off | `window` / `waiting` |
| 2 | The room is switched off with its room thermostat | off | `off` |
| 3 | A manual change is being held | heat at that temperature | `manual` |
| 4 | An away sensor is on, or no schedule block is active | heat at the eco temperature | `idle` |
| 5 | A schedule block with its own `temperature` is active | heat at that temperature | `schedule` |
| 6 | A schedule block is active | heat at the comfort temperature | `schedule` |
| – | **Frost protection** applies on top of all of these | heat at least at the frost temperature | `frost` when it overrides *off* |

Two exceptions to the order:

- A manual change made **while a window is open** wins over the window (see
  [Windows](#a-dial-turned-while-the-window-is-open)).
- **Frost protection** can switch a room on that rules 1 or 2 switched off.

Targets are rounded to the thermostats' 0.5 °C step before they are written.

## The plan: schedule, comfort, eco, away

The *plan* is what the room should do without anyone interfering: the comfort temperature (or the
block's own temperature) during schedule blocks, the eco temperature outside them and whenever an
away sensor is on.

A **plan change** happens when any of these change:

- a schedule block starts or ends,
- the active block's own temperature is different from the previous one,
- an away sensor switches on or off (more precisely: "any away sensor on" changes),
- the temperature the plan currently uses changes – for example you move the comfort temperature
  while a block is active. Moving the eco temperature during a block is not a plan change for that
  room, because the block does not use it.

Plan changes matter because they end manual holds (below). A schedule entity also updates its
*next event* attribute at block boundaries and when you edit it; that alone is not a plan change.

## Manual changes

Anything that changes a thermostat's mode or setpoint and is **not** the integration counts as a
manual change:

- someone turns the thermostat,
- someone changes it in the tado° app,
- someone changes the thermostat entity itself in Home Assistant (a card, an automation),
- someone sets a temperature on the **room thermostat** (`climate.<area>_heating`).

A manual change becomes a **hold**: the room keeps that temperature (or stays off, if the
thermostat was switched off) **until the next plan change**. Then the plan takes over again.

Details:

- **Rooms with several thermostats follow:** turning one radiator to 23 °C sets the room to 23 °C,
  so the integration writes 23 °C to the other thermostats of the room too.
- **Turning the dial:** a dial reports every half degree while it is being turned. The integration
  waits until the reports have stopped for 4 seconds and takes the last value.
- **Recognising its own writes:** when the integration writes a thermostat, the thermostat's reports
  in the next seconds carry the integration's own context and are not mistaken for manual changes.
  Matter reports mode and setpoint separately; values on the way from the old to the new setting
  within 30 seconds of a write are also recognised as its own.
- **Changes while Home Assistant was down:** the integration remembers each thermostat's last known
  mode and setpoint. If a thermostat differs after a restart, someone changed it in the meantime,
  and that becomes a hold.

What ends a hold:

| Event | Hold |
| --- | --- |
| Schedule block starts or ends | ends |
| Away sensor on or off | ends |
| The temperature the plan uses changes | ends |
| Room thermostat set to *auto* | ends |
| Another manual change | replaced by the new one |
| Restart, reload, reconfigure | kept |
| Window opens | kept – the window still switches the room off, and when it is closed the hold applies again |

## The room thermostat

Each room has a thermostat entity of its own (`climate.<area>_heating`) that controls the room as a
whole:

| You do | Effect |
| --- | --- |
| Set a temperature | A hold at that temperature until the next plan change (mode *heat*). |
| Mode **heat** | A hold at the current target until the next plan change. |
| Mode **auto** / turn on | Back to the plan: any hold or "room off" ends. |
| Mode **off** / turn off | The room is switched off **until you set it to auto or heat again** – plan changes do not switch it back on. Frost protection still applies. |

Its *current temperature* is the room sensor (or the thermostats' mean), and its *action* is the
[heating status](heating-status.md): *heating* while any thermostat of the room heats, *idle* once
all have reached their setpoint, *off* while they are off.

## Windows

Each room has an **open delay** (default 30 s) and a **close delay** (default 5 min):

```
window      ─closed─┐ open ┌────────────closed──────────────────────
                    └──────┘
                     < 30 s: nothing happens

window      ─closed─┐        open         ┌──────closed───────────────
                    └─────────────────────┘
mode         schedule  │ window           │ waiting (5 min)  │ schedule
                      30 s                close              +5 min
thermostats  heat      │ off                                 │ heat (plan or hold)
```

- An opening shorter than the open delay is **ignored**: nothing is written, the mode stays as it
  was. This keeps doors that are opened to walk through – and contacts that bounce – from switching
  the heating off and on.
- After the open delay all thermostats of the room are switched off (mode `window`, the room's
  *Window open* entity turns on).
- When **all** windows and doors of the room are closed again, the close delay runs (mode
  `waiting`); the room's *Back on* sensor says when heating resumes.
- A window opened again during the wait switches off **at once**, without a new open delay.
- When the wait is over, the room returns to whatever applies then – the plan, or a hold that was
  made before the window opened. If the plan changed while the window was open, the new plan
  applies.

A contact that becomes *unavailable* keeps its last known state.

### A dial turned while the window is open

If someone turns a thermostat up while the room is off because of a window, that is taken as a
deliberate wish: the room heats at that temperature despite the open window (mode `manual`). It
stays like that until the next plan change, or until a window of the room is opened again after
all were closed.

Turning a thermostat during the wait after closing ends the wait: the hold applies at once.

## Away and vacation

The away sensors of the house settings are combined: while **any** of them is on, every room is in
mode `idle` at its eco temperature. Switching away on or off is a plan change, so it ends manual
holds in every room. A room switched **off** stays off.

## Frost protection

The frost temperature (house setting, default 7 °C) is a floor:

- No room is ever heated to less than it – an eco temperature of 5 °C is raised to 7 °C.
- A room that is off – because of a window or because you switched it off – is heated to the frost
  temperature when its temperature falls below it (mode `frost`), and switched off again once it is
  1 °C above it.

The room's temperature is the room sensor, or the thermostats' mean without one. The thermostats'
own readings are higher than the room near the window; a room sensor makes frost protection more
reliable.

## Thermostats that drop out

A thermostat that is *unavailable* is not written. When it comes back, it is compared with what it
should do and written if it differs – a value it had when it reconnected is not treated as a manual
change.

## Restarts and reloads

The integration stores, per room: comfort and eco temperature, the current hold, the window phase
with its deadline, each thermostat's last known mode and setpoint, and the last heating status.
After a restart:

- deadlines that passed while Home Assistant was down take effect at once,
- a plan change that happened meanwhile (a block ended at night) ends a hold as usual,
- a window that was open before keeps the room off; one that was opened while Home Assistant was
  down starts its open delay,
- a thermostat that was changed meanwhile becomes a hold,
- nothing is written to thermostats that are already right.

The integration starts deciding once Home Assistant has finished starting, so that thermostats,
schedules and sensors of other integrations exist. Until then its entities are unavailable.
