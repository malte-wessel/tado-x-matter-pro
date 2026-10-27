# Automations

The room thermostat is a regular `climate` entity, so rooms are controlled with the standard
climate actions. The examples use a room in the area *Kitchen*; adapt the entity ids.

You do not need automations for schedules, away mode, windows or frost protection – the integration
does those. Automations are for everything around it.

## Away mode from presence

The integration only needs a switch that is on while nobody is home; set it from your presence
detection and add it under **Away sensors** in the house settings.

```yaml
alias: Away when everyone has left
triggers:
  - trigger: state
    entity_id: zone.home
    to: "0"
    for: { minutes: 15 }
  - trigger: state
    entity_id: zone.home
    from: "0"
actions:
  - if:
      - condition: state
        entity_id: zone.home
        state: "0"
    then:
      - action: input_boolean.turn_on
        target:
          entity_id: input_boolean.away
    else:
      - action: input_boolean.turn_off
        target:
          entity_id: input_boolean.away
mode: restart
```

Switching away on or off ends manual holds in every room; rooms switched off stay off.

## Guests: hold a temperature in one room

A hold lasts until the next schedule change. For an evening with guests in the living room:

```yaml
action: climate.set_temperature
target:
  entity_id: climate.living_room_heating
data:
  temperature: 22.5
```

## Back to the plan

```yaml
action: climate.set_hvac_mode
target:
  entity_id: climate.living_room_heating
data:
  hvac_mode: auto
```

`climate.turn_on` does the same. Targets can be areas or floors:

```yaml
action: climate.set_hvac_mode
target:
  floor_id: first_floor
data:
  hvac_mode: auto
```

Careful: targeting an area also reaches the thermostats themselves if they are in that area. Use
`entity_id` targets with the room thermostats, or put a label on the room thermostats and target the
label, to be sure.

## Switch a room off for a while

Off lasts until the room is set back to *auto* – also across schedule changes. For example, the
guest room while it is not used:

```yaml
action: climate.turn_off
target:
  entity_id: climate.guest_room_heating
```

Frost protection still applies.

## Tell me when a window has paused the heating for long

Until the integration's own window reminder is available:

```yaml
alias: Kitchen window open for 30 minutes
triggers:
  - trigger: state
    entity_id: binary_sensor.kitchen_heating_window_open
    to: "on"
    for: { minutes: 30 }
conditions:
  - condition: numeric_state
    entity_id: sensor.outdoor_temperature
    below: 15
actions:
  - action: notify.mobile_app_phone
    data:
      title: Window open
      message: The kitchen window has been open for 30 minutes.
```

## Heating hours per radiator

The status sensors make heating time countable with the *History stats* helper (Settings → Devices
& services → Helpers → Create helper → History stats):

- Entity: `sensor.kitchen_heating_thermostat_kitchen_heating`
- State: `heating`
- Type: time
- Start: `{{ today_at() }}`, End: `{{ now() }}`

The helper then shows how many hours that radiator heated today; a *Utility meter* on top gives
days, weeks and months.

## React when a room starts heating

```yaml
triggers:
  - trigger: state
    entity_id: climate.kitchen_heating
    attribute: hvac_action
    to: heating
```
