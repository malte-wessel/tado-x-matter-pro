# Tado X Matter Pro documentation

Tado X Matter Pro controls Tado X radiator thermostats that are connected to Home Assistant over
Matter, one room at a time. You tell it which thermostats, schedule and window contacts belong to a
room; it keeps the thermostats on the right temperature, switches them off while a window is open,
respects changes made at the thermostat, and tells you whether each radiator is actually heating.

> **Status: pre-release.** Room control and the heating status work and are covered by tests.
> Boost, timed overrides ("heat until …", "eco until …"), the window reminder and repair issues are
> planned; their settings can already be entered but have no effect yet. See
> [What works today](#what-works-today).

## Pages

| Page | What you find there |
| --- | --- |
| [Installation](installation.md) | Requirements, the settings the tado° app needs, installing with HACS or by hand. |
| [Configuration](configuration.md) | House settings, adding and changing rooms, every field and its default. |
| [How it works](how-it-works.md) | What decides a room's temperature, windows, manual changes, away mode, frost protection, restarts. |
| [Entities](entities.md) | Every entity a room creates, its states and attributes, and how the entity ids are formed. |
| [Heating status](heating-status.md) | How the integration tells "heating" from "reached" without valve data, and its limits. |
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
| Windows | Switch off after an open delay, back on after a close delay, short openings ignored | Reminder when a window stays open |
| Manual changes | Held until the next schedule change; rooms with several thermostats follow | – |
| Room thermostat | Auto (plan), heat (hold a temperature), off | Presets boost / comfort / eco |
| Overrides | Hold until the next change, room off until switched back | Boost, heat or eco until a time, extend the current block, back to schedule (skipping the wait after a window) |
| Heating status | Per thermostat heating / reached / off, room thermostat action | – |
| Safety | Frost protection | Repair issues (thermostat unavailable, chattering contacts, tado° overwriting setpoints) |
| Explanations | Mode sensor with reason, next change and "back on at" | Logbook entries, diagnostics |
