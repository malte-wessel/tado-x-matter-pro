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
