# Changelog

## 0.1.0-beta.2 – 2026-11-27

- A thermostat switched back on after a window no longer heats at its old setpoint: the setpoint
  is written while it is still off, then the mode. Retries to a thermostat that already heats send
  only the setpoint, and each call gets its own timeout.

## 0.1.0-beta.1 – 2026-11-19

Initial release.
