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
- Icons per state for the heating status and the Mode sensor (and icons for the other entities
  and the actions); the German name of the heating status is "… Heizstatus".
- Documentation in `docs/` (including Matter/Thread advice in the installation guide): installation, configuration, how it works, entities, heating status,
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
- Window reminder: once a window has kept a room off for the room's *Remind after* minutes
  (default 30, 0 = off), a *Window open too long* sensor turns on and – once per opening, and only
  below the house's outdoor temperature if set – a notification goes to the house's notify actions
  (English or German). Store 1.5.
- Repair issues for a window contact that keeps bouncing (10 short openings within an hour), a
  window contact gone for 30 minutes while it last said open, and setpoints changed outside the
  integration in two or more rooms within a minute (likely the tado° app).
- Schedule edges and away changes are spread over a random 0–45 seconds per room.
- Boost (`tado_x_matter_pro.boost`, house defaults 30 °C for 30 minutes, a layer that ends on
  resume or a change by hand), timed overrides (`set_override`: a temperature or the comfort/eco
  temperature until a time, for a while, or until the next schedule change), `extend_block` (the
  current plan temperature until a time), and the presets boost / comfort / eco / none on the
  room thermostat. The Mode sensor shows `timed` and `boost`, with `override_until` and
  `boost_until`. Store 1.4 keeps boosts and presets across restarts.
- The Mode sensor's `next_change` and `next_target` say when the room's target changes next by
  itself and to what, from the schedule's blocks (`schedule.get_schedule`): right across midnight,
  with a next block's own temperature, at the end of a hold, a timed override, a boost or the wait
  after a window, and empty while away, off or with a window open. The same as a timestamp
  sensor *Next change* per room, with the target as an attribute.
- Logbook entries (English and German, by Home Assistant's language): manual holds, timed
  overrides, a room switched off, back to the schedule, switched off for a window and back on,
  boost and its end.
- Back to the schedule: the action `tado_x_matter_pro.resume_schedule` (also with area, floor and
  label targets, which reach only the room thermostats), a *Resume schedule* button per room, and a
  house device with *Resume all rooms* and *Rooms off schedule* (the count, with the rooms and their
  modes). They end holds and a room switched off, skip the wait after a window – an open window
  still keeps the room off – and return at once.
- A dial turned back to the previous value right after the integration's write is now a hold.
- Changing a room's comfort or eco temperature ends its manual hold – either number, also the one
  the plan does not use at the moment.
- The store is written only when something changed, not after every thermostat reading; the
  heating status sensors' `demand` attribute is not recorded (the demand entity keeps its own
  history).
