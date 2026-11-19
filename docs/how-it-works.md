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
| 2 | A boost runs | heat at the boost temperature | `boost` |
| 3 | The room is switched off with its room thermostat | off | `off` |
| 4 | A timed override runs (*set override* until a time or for a while, *extend block*) | heat at its temperature | `timed` |
| 5 | A manual change is being held | heat at that temperature | `manual` |
| 6 | An away sensor is on, or no schedule block is active | heat at the eco temperature | `idle` |
| 7 | A schedule block with its own `temperature` is active | heat at that temperature | `schedule` |
| 8 | A schedule block is active | heat at the comfort temperature | `schedule` |
| – | **Frost protection** applies on top of all of these | heat at least at the frost temperature | `frost` when it overrides *off* |

Two exceptions to the order:

- A manual change made **while a window is open** wins over the window (see
  [Windows](#a-dial-turned-while-the-window-is-open)).
- **Frost protection** can switch a room on that rules 1 or 3 switched off.

Targets are rounded to the thermostats' 0.5 °C step before they are written.

## The plan: schedule, comfort, eco, away

The *plan* is what the room should do without anyone interfering: the comfort temperature (or the
block's own temperature) during schedule blocks, the eco temperature outside them and whenever an
away sensor is on.

A **plan change** happens when any of these change:

- a schedule block starts or ends,
- the active block's own temperature is different from the previous one,
- an away sensor switches on or off (more precisely: "any away sensor on" changes),
- the room's comfort or eco temperature changes – either one, also the one the plan does not use
  right now: touching the heating settings means "follow the plan".

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
  waits until the reports have stopped for 4 seconds and takes the last value. Meanwhile it writes
  nothing to the room's thermostats, so the dial is never turned back to the old value.
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
| Comfort or eco temperature changed | ends |
| Room thermostat set to *auto* | ends |
| Another manual change | replaced by the new one |
| Restart, reload, changing the room | kept |
| Window opens | kept – the window still switches the room off, and when it is closed the hold applies again |

## The room thermostat

Each room has a thermostat entity of its own (`climate.<area>_heating`) that controls the room as a
whole:

| You do | Effect |
| --- | --- |
| Set a temperature | A hold at that temperature until the next plan change (mode *heat*). |
| Mode **heat** | A hold at the current target until the next plan change. |
| Mode **auto** / turn on | Back to the plan: any hold or "room off" ends. |
| Mode **off** / turn off | The room is switched off **until you set it to auto or heat again** – plan changes do not switch it back on. A change at a thermostat (dial, tado° app) also ends it: it becomes a hold until the next plan change, and then the plan applies. Frost protection still applies. |

Its *current temperature* is the room sensor (or the thermostats' mean). Its *action* is *off*
while all thermostats are off; whether it heats is known only from
[heating demand entities](heating-status.md).

## Boost, timed overrides, presets

- **Boost** (`tado_x_matter_pro.boost`, or the room thermostat's preset *boost*) heats at the boost
  temperature for the boost duration – both from the house settings unless the action gives them.
  It is a layer on top: when it ends, whatever applied underneath applies again. Schedule changes
  don't end it; *resume*, a change by hand (dial, app, room thermostat) and the preset *none* do.
- **Set override** (`tado_x_matter_pro.set_override`) heats at a temperature – or at the room's
  comfort or eco temperature as it is now – **until a time** (today, or tomorrow if that time has
  passed), **for a while**, or – the default – **until the next plan change**, which is a hold like
  a temperature set by hand. One with an end time survives schedule changes (mode `timed`).
- **Extend block** (`tado_x_matter_pro.extend_block`) keeps the plan's current temperature until a
  time, whatever the schedule says – for example comfort an hour longer tonight.
- **Presets** of the room thermostat: *comfort* and *eco* hold that temperature until the next
  plan change; *boost* boosts; *none* ends a boost and a preset's hold.

## Back to the schedule

The action `tado_x_matter_pro.resume_schedule` (targets: room thermostats, or areas, floors and
labels – they reach only the room thermostats), a room's *Resume schedule* button, and the house's
*Resume all rooms* button all do the same:

- a manual hold ends, and a room that was switched off follows its plan again,
- the wait after a window closed is skipped: the plan applies at once,
- a window that is open right now still keeps the room off; when it closes, the plan applies after
  the close delay – not a setting from before.

They return at once; the thermostats are written in the background, so a thermostat that does not
answer never holds up other rooms or a second tap. Mode **auto** on the room thermostat also ends
holds, but keeps the wait after a window.

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

### Reminder

If the room's *Remind after* is not 0 (default 30 minutes), a window that has kept the room off that
long turns on *Window open too long* and – once per opening – sends a notification to the house's
*Notify* actions (title *Window open*, "Kitchen: a window has been open for 30 minutes."; German if
Home Assistant is). With an outdoor sensor and *Only below* set, the notification waits until it is
colder outside than that.

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

## Sensors and schedules that drop out

A schedule, away sensor or window contact that becomes *unavailable* or *unknown* keeps its last
known state: a short drop-out is neither a plan change (holds stay) nor a window event.

After a restart, an input that has not reported yet keeps the room's last decision for up to
5 minutes – away stays on, and a room that was off for an open window stays off. An input that is
still unknown after that counts as *off* (closed, not away, no block), so a deleted helper does not
keep a room in eco for good.

## Getting the setting to the thermostat

Tado X thermostats talk over Thread, and Thread links drop out. So every write is checked:

- **Confirmed or sent again.** A write counts once the thermostat reports the new value. Until
  then it is sent again: a setpoint after 1, 3 and 10 minutes, *off* after 30 seconds and
  2 minutes. Each thermostat has its own sender, so one that does not answer never delays the
  other thermostats of the room, other rooms, or the room thermostat's actions.
- **Unavailable thermostats** are not written – Home Assistant would drop the call. When one comes
  back, it gets what it should have. If it comes back with a value that is neither what it had
  before nor anything the integration sent, someone turned it in the meantime: that becomes a hold.
- **Late deliveries.** The Matter server can hold a write for a node it cannot reach and deliver it
  minutes later, after newer ones. A value the integration sent in the last 20 minutes that shows up
  late is recognised as its own: the current setting is sent again, and no hold starts.
- **Schedule edges and away changes are spread:** each room waits a random 0–45 seconds before it
  writes, so a house full of valves does not transmit in the same second. Windows, your own changes
  and the room's numbers are written at once.
- **A thermostat that has not confirmed a setting for 30 minutes** raises a repair issue
  (Settings → System → Repairs). It goes away when the thermostat confirms.

## Restarts and reloads

The integration stores, per room: comfort and eco temperature, the current hold, the window phase
with its deadline, and each thermostat's last known mode and setpoint. After a restart:

- deadlines that passed while Home Assistant was down take effect at once,
- a plan change that happened meanwhile (a block ended at night) ends a hold as usual,
- a window that was open before keeps the room off; one that was opened while Home Assistant was
  down starts its open delay,
- a thermostat that was changed meanwhile becomes a hold (also one the integration never had to
  write: each thermostat's state is noted when the room starts),
- nothing is written to thermostats that are already right.

The integration starts deciding once Home Assistant has finished starting, so that thermostats,
schedules and sensors of other integrations exist. Until then its entities are unavailable.
