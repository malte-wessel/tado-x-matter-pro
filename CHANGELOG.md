# Changelog

## Unreleased

Initial release.

- Rooms as subentries (thermostats, schedule, windows with open and close delay, room sensor); house
  settings (away sensors, frost protection, boost, window reminder).
- Per room: a thermostat (auto / heat / off), a mode sensor, comfort and eco temperatures and a
  window sensor. Rooms follow their schedule and the away sensors, switch off for open windows,
  keep manual changes until the next schedule change and sync rooms with several thermostats.
- Per thermostat an optional heating demand entity – a percentage (e.g. a cloud integration's
  heating power) or an on/off value (e.g. a pipe sensor) – since Tado X does not report its valve
  over Matter. Thermostats with one get a heating status (heating / reached / off, heating from a
  house-wide threshold, default 3 %); the room thermostat shows the most active one as its
  action.
- Documentation in `docs/`: installation, configuration, how it works, entities, heating status,
  dashboards, automations, migrating, troubleshooting, development.
- The room thermostat stays *off* while frost protection heats a room that was switched off.
- Per room with windows a "Back on" timestamp sensor: when heating resumes after the windows were
  closed, shown by cards as relative time.
- Diagnostics for the house and per room: inputs, decision, stored state, the thermostats' last
  reports and writes, and a trace of the last 200 reports, decisions and writes.
- Schedules, away sensors and window contacts that become unavailable keep their last known state,
  so a short drop-out neither ends manual holds nor switches a room between eco and comfort. After
  a restart, inputs that have not reported yet keep the last decision for up to 5 minutes (a room
  off for an open window stays off); after that an unknown input counts as off, so a deleted away
  helper does not keep rooms in eco.
- A thermostat's late report of the integration's own write is recognised as such, so it no longer
  turns into a manual hold after the next restart. Changes made while Home Assistant was down are
  also detected on thermostats the integration never had to write.
- While a hand-turned dial settles, nothing is written to the room's thermostats, so the dial is
  never turned back to the old value.
- While a window pauses a room, its thermostat's target shows what the room returns to – a hold's
  temperature or the plan's; a room switched off shows none.
- Removing a thermostat from a room also removes its status sensor; status sensors are named after
  the thermostat also when it was not set up yet.
- Settings that have no effect yet (boost, window reminder) are marked *planned* in the forms.
- Reliable delivery: every write is confirmed by the thermostat's report or sent again (setpoints
  after 1, 3 and 10 minutes, off after 30 seconds and 2 minutes), one call at a time per
  thermostat, so a thermostat that does not answer never delays others or the room's actions.
  Unavailable thermostats get the setting when they return; a value that appears late and was sent
  by the integration earlier is re-sent instead of becoming a hold, while a thermostat that returns
  with a value nobody sent becomes a hold. A repair issue appears after 30 minutes unconfirmed.
- Schedule edges and away changes are spread over a random 0–45 seconds per room.
- A dial turned back to the previous value right after the integration's write is now a hold.
- Changing a room's comfort or eco temperature ends its manual hold – either number, also the one
  the plan does not use at the moment.
- The store is written only when something changed, not after every thermostat reading; the
  heating status sensors' `demand` attribute is not recorded (the demand entity keeps its own
  history).
