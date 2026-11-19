# Tado X Matter Pro documentation

Tado X Matter Pro controls Tado X radiator thermostats that are connected to Home Assistant over
Matter, one room at a time. You tell it which thermostats, schedule and window contacts belong to a
room; it keeps the thermostats on the right temperature, switches them off while a window is open,
respects changes made at the thermostat, and tells you whether each radiator is actually heating.

> **Status: pre-release.** Everything below works and is covered by tests; it has not yet run in a
> real house for long. See [What works today](#what-works-today).

## Pages

| Page | What you find there |
| --- | --- |
| [Installation](installation.md) | Requirements, the settings the tado° app needs, installing with HACS or by hand. |
| [Configuration](configuration.md) | House settings, adding and changing rooms, every field and its default. |
| [How it works](how-it-works.md) | What decides a room's temperature, windows, manual changes, away mode, frost protection, restarts. |
| [Entities](entities.md) | Every entity a room creates, its states and attributes, and how the entity ids are formed. |
| [Heating status](heating-status.md) | Which radiator heats: heating demand entities per thermostat, the threshold, the room's action. |
| [Dashboards](dashboards.md) | Card examples with Home Assistant's built-in cards. |
| [Automations](automations.md) | Examples: away mode, guests, holds, heating hours. |
| [Migrating from a DIY setup](migrating.md) | Replacing a blueprint/automation/helper setup room by room. |
| [Troubleshooting](troubleshooting.md) | Common surprises and how to find out what the integration decided. |
| [Development](development.md) | The dev container with its simulated house, tests, and how the code is organised. |

## What works today

| Area | Today | Planned |
| --- | --- | --- |
| Rooms | Thermostats, schedule, windows and doors, room sensor; added and changed in the UI | – |
| Plan | Comfort temperature during schedule blocks, a block's own temperature, eco outside blocks and while away | – |
| Windows | Switch off after an open delay, back on after a close delay, short openings ignored, a reminder when a window stays open | – |
| Manual changes | Held until the next schedule change; rooms with several thermostats follow | – |
| Room thermostat | Auto (plan), heat (hold a temperature), off; presets boost / comfort / eco | – |
| Overrides | Hold until the next change, room off until switched back, back to the schedule per room or for all rooms (action and buttons), boost, heat or eco until a time or for a while, extend the current block | – |
| Heating status | Per thermostat heating / reached / off from an optional heating demand entity, room thermostat action | – |
| Safety | Frost protection; every write confirmed or sent again; repair issues for a thermostat that does not take its setting, bouncing window contacts, a contact gone while open, and something overwriting setpoints in several rooms | – |
| Explanations | Mode sensor with target, next change and "back on at"; logbook entries (English, German); diagnostics with a trace | – |
