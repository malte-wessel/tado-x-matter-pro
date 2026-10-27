# Migrating from a DIY setup

Many Tado X over Matter setups grow into a collection of parts: a heating blueprint with one
automation per room, per-room helpers for temperatures, timers for the wait after a window closed,
derivative and template sensors to guess whether a radiator heats, and template macros for the
dashboard. Tado X Matter Pro replaces all of that except the schedule helpers. This page describes
a careful way over, one room at a time.

## What maps to what

| DIY part | In Tado X Matter Pro |
| --- | --- |
| Schedule helpers | Kept – pick them in the room settings. Block temperatures in *Additional data* (`temperature: 22`) keep working. |
| Blueprint automation per room | The room (a subentry) |
| `input_number` heating / setback temperature per room | The room's *Comfort temperature* / *Eco temperature* numbers |
| Away / vacation booleans as "idle sensors" | *Away sensors* in the house settings |
| Timer per room for the delay after a window closed | The room's *Back on after* setting; no helper |
| Window handling that reacts to every opening | *Switch off after* (open delay) – short openings are ignored |
| Derivative "trend" helper per thermostat | Built in; `trend` attribute of the status sensor |
| Template "status" sensor per thermostat | The status sensor per thermostat (`heating` / `reached` / `off`) |
| Template macros for "plan", "manual", "next change", "back on at" | The Mode sensor and its attributes |

## Step by step

1. **Install and set up the house** ([Installation](installation.md)). Do not add rooms yet.
2. **Pick one room** – ideally one without special cases.
3. **Note its current values**: heating and setback temperatures, window delay.
4. **Disable the room's old automation** (Settings → Automations → the automation → disable).
   Disable, don't delete – you can go back.
5. **Add the room** in Tado X Matter Pro with the same thermostats, schedule and windows. Set its
   comfort and eco numbers to the noted values.
6. **Watch it for a day or two**: the Mode sensor, the status sensors, and the thermostats'
   history. Open a window, turn a thermostat, switch away on.
7. **Repeat** for the other rooms.
8. **Update dashboards** to the new entities (see [Dashboards](dashboards.md)): plan badges become
   the Mode sensor, "back on at" countdowns become `resume_at`, status icons become the status
   sensors or the room thermostat's action.
9. **Remove the old parts** once nothing uses them: the room automations, the blueprint, the
   temperature helpers, the timers, the trend and status sensors, the template macros. Check each
   helper's *Related* tab first for anything still referring to it.

## Things that behave differently

- **Short openings are ignored.** Doors that are opened to walk through no longer switch the
  heating off and on.
- **Manual changes survive midnight.** A schedule whose block runs through midnight used to restart
  automations that triggered on every schedule update; here only real plan changes end a hold.
- **Rooms with two thermostats follow each other.** Turning one sets both.
- **A dial turn while a window is open heats.** It is taken as a deliberate wish.
- **Holds survive restarts**, and a thermostat changed while Home Assistant was down becomes a hold.
- **Entity ids**: rooms are devices called *Heating* in their area, so ids look like
  `climate.kitchen_heating` – see [Entities](entities.md#entity-ids-and-names).
