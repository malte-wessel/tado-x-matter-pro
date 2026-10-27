# Configuration

Everything is set up in the Home Assistant UI; there is no YAML. The integration has two levels:

- **House settings** – once, for all rooms. Shown when you add the integration, changed later with
  **Configure** on the integration page.
- **Rooms** – one per room, added with **Add room** on the integration page and changed with the
  room's **Reconfigure**.

What is *not* configuration: the comfort and eco temperatures are entities you change on your
dashboard ([Entities](entities.md#numbers)), the times live in the schedule helpers, and holds are
made with the room thermostat.

## House settings

| Field | Default | Meaning |
| --- | --- | --- |
| **Away sensors** | none | `input_boolean` or `binary_sensor` entities. While **any** of them is on, every room uses its eco temperature, whatever the schedule says. Typical: an away switch and a vacation switch. |
| **Frost protection** | 7 °C | No room is heated to less than this, and a room that is switched off or has a window open is heated to this when its temperature drops below it. See [frost protection](how-it-works.md#frost-protection). |

Section **Boost** (collapsed) – *planned, stored but not used yet*

| Field | Default | Meaning |
| --- | --- | --- |
| Temperature | 30 °C | What boost will heat to (30 °C opens the valve fully). |
| Duration | 30 min | How long a boost will last. |

Section **Window reminder** (collapsed) – *planned, stored but not used yet*

| Field | Default | Meaning |
| --- | --- | --- |
| Outdoor temperature | none | A temperature sensor outside. |
| Only below | empty | Remind only when it is colder than this outside; empty means always. Needs the outdoor sensor. |
| Notify | none | Notification actions to send the reminder with, for example `notify.mobile_app_phone`. The list offers every `notify.*` action Home Assistant has; you can also type one. |

The minutes after which a reminder is sent are set per room (below), so a bathroom window that is
always tilted can be left out.

Changing the house settings reloads the integration. Rooms keep their state.

## Rooms

### Fields

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| **Name** | no | area of the first thermostat, else its name | The room's title on the integration page. |
| **Thermostats** | yes | – | All radiator thermostats of the room. A thermostat can belong to only one room. All thermostats of a room always get the same target. |
| **Schedule** | yes | – | A schedule helper. During its blocks the room is heated to its comfort temperature, or to the block's own temperature. |
| **Windows and doors** | no | none | Contacts (`binary_sensor`, on = open). While one is open long enough, the room's thermostats are switched off. |
| **Room temperature** | no | none | A temperature sensor in the room, shown as the room's current temperature and used for frost protection. Without it, the mean of the thermostats' own readings is used – which reads high, because the thermostats sit at the radiator. |

Section **Windows** (collapsed)

| Field | Default | Meaning |
| --- | --- | --- |
| **Switch off after** | 30 s | How long a window must be open before the room is switched off. Shorter openings are ignored entirely – a door opened to walk through, a contact that bounces. Set 0 to switch off at once. |
| **Back on after** | 5 min | How long to wait after the last window closed before heating again. A window opened again during the wait switches the room off at once. |
| **Remind after** | 30 min | *Planned:* send the window reminder after this long; 0 = never for this room. |

### Schedules

A schedule helper has blocks per weekday. For the integration:

- **Inside a block** the room is heated to its **comfort temperature**.
- **Outside every block** it is kept at its **eco temperature**.
- **A block's own temperature:** in the schedule editor, open a block and enter in *Additional data*

  ```yaml
  temperature: 22.5
  ```

  During that block the room is heated to 22.5 °C instead of its comfort temperature. Blocks
  without it use the comfort temperature. This lets one schedule carry a warm morning and a normal
  evening.

Several rooms can share one schedule, for example all rooms of a floor. Each room still has its own
comfort and eco temperature; a block's own temperature applies to every room using that schedule.

A block that runs through midnight (e.g. 20:30–24:00 followed by 00:00–06:30) counts as one block
for manual holds: crossing midnight does not end a hold, as long as both blocks have the same
temperature.

### Adding a room

1. Settings → Devices & services → **Tado X Matter Pro** → **Add room**.
2. Pick the thermostats first – the name can stay empty and is then taken from their area.
3. Pick the schedule, the windows and doors, and the room sensor if there is one.
4. Open **Windows** to change the delays if you like.

The room starts at once: its thermostats are set to what the plan says right now. From then on,
changes made at a thermostat are respected (see [How it works](how-it-works.md#manual-changes)).

### Changing a room

The room's three-dot menu → **Reconfigure** shows the same form with the current values. Saving
reloads the integration; the room keeps its comfort and eco temperatures, holds and window state.
Removing all windows from a room also removes its *Window open* entity.

### Errors

| Message | Meaning |
| --- | --- |
| *Pick at least one thermostat.* | The thermostat list is empty. |
| *A thermostat already belongs to another room.* | One of the chosen thermostats is used by another room. Remove it there first. |
