# Heating status

Over Matter a Tado X thermostat reports its mode, its setpoint and its own temperature – but not its
valve position and not whether it is heating. Home Assistant's thermostat cards therefore can't show
"heating" for it. Tado X Matter Pro infers it.

## The idea

While the radiator is cold, a Tado X reading behaves much like a room temperature (in recordings
it was 0.5–1 °C below a room sensor in the same room). Once hot water reaches the radiator, the
thermostat warms with it: its reading **rises quickly** – several degrees per hour within minutes –,
overshoots the setpoint, and **falls** back slowly after the valve has closed. A setpoint only a
little above the reading opens the valve only a little; the reading then barely moves.

So two numbers tell a lot:

- **d** = setpoint − reading, rounded to 0.1 °C. Positive: the thermostat is below its setpoint.
- **t** = the trend of the reading in °C per hour over the last 10 minutes.

## The rule

| Previous status | Becomes *reached* when | Otherwise |
| --- | --- | --- |
| heating | t ≤ −0.5 (cooling down: the valve closed), **or** d ≤ −0.4 and t < 0.2 (clearly above the setpoint, no longer rising), **or** d ≤ −1.0 and t < 0.8 (far above, e.g. right after the setpoint was lowered) | stays *heating* |

| Previous status | Becomes *heating* when | Otherwise |
| --- | --- | --- |
| reached / off / none | d > −0.1 and t > −0.3 (at or below the setpoint and not cooling), **or** t ≥ 0.8 and d > −1.5 (the radiator is clearly warming, even slightly above the setpoint) | *reached* |

A thermostat that is off is always *off*. The rule looks at the previous status (hysteresis), so a
reading that hovers around a threshold does not make the status flicker.

The thresholds were tuned on several days of recorded data from Tado X thermostats, and replay tests
on anonymized recordings check the status against them (start, end, no short blips): the simpler
"reading below setpoint" is wrong most of the time, because the reading at the radiator is above
the setpoint for most of the time the valve is open, and still rising fast for part of it.

## The trend

- **Source:** the temperature sensor on the thermostat's own device (Tado X: 0.01 °C resolution),
  found automatically. If a thermostat has none, its climate entity's reading (0.1 °C) is used,
  which makes the trend coarser.
- **Calculation:** exactly like Home Assistant's *Derivative* helper with a 10-minute time window, a
  5-minute max sub-interval, per hour, 2 decimals; a test compares both. Derivative helpers you set
  up with a longer window show smoother, later values.
- **Why 10 minutes:** Tado X reports its reading every minute while it changes, practically without
  noise. Replayed on recorded history, a 20-minute window kept *heating* about 11 minutes past the
  reading's peak, 10 minutes about 5. A 5-minute window ended sooner still, but turned bumps of a few
  hundredths of a degree into short false *heating*.
- **After a restart** the trend is rebuilt from the recorder's last 25 minutes, so the status is
  right immediately instead of after 10 minutes. Without the recorder the trend starts empty and
  counts as 0 until readings come in.

The trend and the reading are attributes of each [status sensor](entities.md#heating-status-per-thermostat).

## Where you see it

- **Per thermostat:** `sensor.<area>_heating_<thermostat>_heating` – *heating*, *reached*, *off*
  (German: *Heizt*, *Erreicht*, *Aus*).
- **Per room:** the room thermostat's action (`hvac_action`): *heating* as soon as one thermostat of
  the room heats, *idle* once all have reached their setpoint, *off* while they are off. Home
  Assistant's thermostat and tile cards show it.

## Limits

It is an inference, not a measurement. Expect:

- **It shows heat arriving, not the request.** *Heating* starts when the reading turns upwards –
  about 5 minutes after it does. If the setpoint goes up while the radiator is still cooling from
  before, hot water can take a quarter of an hour to arrive, and the status stays *reached* until
  then. *Heating* ends about 5 minutes after the reading peaks.
- **A setpoint just above the reading** shows *heating* for as long as it stays above, although the
  radiator may barely warm: the valve is probably open a little, but the reading cannot tell.
- **Thermostats already at their setpoint:** a hallway radiator whose thermostat reads the setpoint
  when a block starts may barely open. It then shows *reached* most of the time – which is what it
  is doing.
- **Short pulses:** while holding a temperature, Tado X opens the valve briefly from time to time.
  Short pulses may not show up at all, longer ones as short *heating* periods.
- **Sun, ovens, people:** anything that warms the thermostat quickly looks like heating for a while.
- **Other thermostats:** the thresholds fit Tado X at the radiator. Thermostats that report a room
  temperature instead of their own reading at the valve will be judged wrongly.

If you need the true valve state, a temperature sensor on the radiator's return pipe is the reliable
way; the inference is meant for "is this room being heated right now" at a glance and for history.
