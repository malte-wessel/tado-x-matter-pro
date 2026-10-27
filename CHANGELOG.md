# Changelog

## Unreleased

Initial release.

- Rooms as subentries (thermostats, schedule, windows with open and close delay, room sensor); house
  settings (away sensors, frost protection, boost, window reminder).
- Per room: a thermostat (auto / heat / off), a mode sensor, comfort and eco temperatures and a
  window sensor. Rooms follow their schedule and the away sensors, switch off for open windows,
  keep manual changes until the next schedule change and sync rooms with several thermostats.
- Per thermostat a heating status (heating / reached / off), inferred from its temperature and
  trend, since Tado X does not report its valve over Matter; the room thermostat shows it as its
  action.
- Documentation in `docs/`: installation, configuration, how it works, entities, heating status,
  dashboards, automations, migrating, troubleshooting, development.
- The room thermostat stays *off* while frost protection heats a room that was switched off.
- Per room with windows a "Back on" timestamp sensor: when heating resumes after the windows were
  closed, shown by cards as relative time.
- Schedules, away sensors and window contacts that become unavailable keep their last known state,
  so a short drop-out neither ends manual holds nor switches a room between eco and comfort. After
  a restart, inputs that have not come back yet keep the last decision.
- While a hand-turned dial settles, nothing is written to the room's thermostats, so the dial is
  never turned back to the old value.
- The store is written only when something changed, not after every thermostat reading; the
  heating status sensors' `temperature` and `trend` attributes are not recorded.
