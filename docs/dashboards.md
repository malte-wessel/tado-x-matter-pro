# Dashboards

The integration's entities work with Home Assistant's built-in cards. The examples use a room in
the area *Kitchen*; replace `kitchen` with your area. All snippets are for the card editor's YAML
mode.

## A room at a glance: tile card

The room thermostat as a tile with the target temperature and the mode buttons. The tile shows the
action (*Heating* / *Idle*) next to the current temperature.

```yaml
type: tile
entity: climate.kitchen_heating
name: Kitchen
features:
  - type: target-temperature
  - type: climate-hvac-modes
    hvac_modes:
      - auto
      - heat
      - "off"
features_position: bottom
```

*auto* is the plan, *heat* holds the current target, *off* switches the room off until *auto* again.

## The big thermostat

```yaml
type: thermostat
entity: climate.kitchen_heating
features:
  - type: climate-hvac-modes
    hvac_modes:
      - auto
      - heat
      - "off"
```

The ring shows the target; the action shows whether the room is heating.

## Why is the room doing this? Mode and next change

A tile for the mode sensor, with the next change underneath:

```yaml
type: tile
entity: sensor.kitchen_heating_mode
state_content:
  - state
  - next_change
```

Or a sentence with a markdown card:

```yaml
type: markdown
content: >-
  {% set m = 'sensor.kitchen_heating_mode' %}
  **{{ states(m) | title }}** · target {{ state_attr(m, 'target') or '–' }} °C
  {% if state_attr(m, 'resume_at') %}
  · back on at {{ as_timestamp(state_attr(m, 'resume_at')) | timestamp_custom('%H:%M') }}
  {% elif state_attr(m, 'next_change') %}
  · {{ state_attr(m, 'next_target') }} °C at
  {{ as_timestamp(state_attr(m, 'next_change')) | timestamp_custom('%H:%M') }}
  {% endif %}
```

Shows for example *Schedule · target 21 °C · 18 °C at 22:00*, or *Waiting · back on at 17:42*.

## Comfort and eco temperature

```yaml
type: entities
title: Kitchen temperatures
entities:
  - entity: number.kitchen_heating_comfort_temperature
    name: Comfort
  - entity: number.kitchen_heating_eco_temperature
    name: Eco
```

## Which radiator is heating

For a room with two thermostats, their status sensors side by side:

```yaml
type: grid
columns: 2
square: false
cards:
  - type: tile
    entity: sensor.bathroom_heating_thermostat_bathroom_heating
    name: Radiator
    state_content:
      - state
      - trend
  - type: tile
    entity: sensor.bathroom_heating_thermostat_bathroom_tub_heating
    name: Tub
    state_content:
      - state
      - trend
```

Over the day, a history graph shows when each radiator heated:

```yaml
type: history-graph
title: Heating today
hours_to_show: 24
entities:
  - entity: sensor.bathroom_heating_thermostat_bathroom_heating
  - entity: sensor.bathroom_heating_thermostat_bathroom_tub_heating
```

The statuses appear as coloured timelines.

## A whole floor

The room thermostats of a floor in one card, with the action shown by each tile:

```yaml
type: grid
columns: 2
square: false
cards:
  - type: tile
    entity: climate.living_room_heating
    features: [{ type: target-temperature }]
  - type: tile
    entity: climate.kitchen_heating
    features: [{ type: target-temperature }]
  - type: tile
    entity: climate.hallway_heating
    features: [{ type: target-temperature }]
  - type: tile
    entity: climate.toilet_heating
    features: [{ type: target-temperature }]
```

## Windows

When the heating comes back after a window: the *Back on* sensor, shown as relative time (*in 4
minutes*), only while the wait runs:

```yaml
type: conditional
conditions:
  - condition: state
    entity: sensor.kitchen_heating_mode
    state: waiting
card:
  type: tile
  entity: sensor.kitchen_heating_back_on
  name: Heating back on
```

Or the mode whenever it is not the plain plan:

```yaml
type: conditional
conditions:
  - condition: state
    entity: sensor.kitchen_heating_mode
    state_not: schedule
  - condition: state
    entity: sensor.kitchen_heating_mode
    state_not: idle
card:
  type: tile
  entity: sensor.kitchen_heating_mode
  state_content: [state, resume_at]
```
