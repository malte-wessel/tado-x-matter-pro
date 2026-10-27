// First-time setup of the dev Home Assistant, idempotent: finishes onboarding with the dev user and
// adds the Tado X Matter Pro config entry, the Dev House schedules and its dashboard, through the
// same REST and websocket endpoints the frontend uses. Node 22, no deps.
const BASE = process.env.HA_URL ?? "http://localhost:8123";
const USERNAME = process.env.HASS_USERNAME ?? "dev";
const PASSWORD = process.env.HASS_PASSWORD ?? "dev";
const CLIENT_ID = `${BASE}/`;

async function call(path, { method = "GET", body, token, form } = {}) {
  const headers = {};
  if (token) headers.authorization = `Bearer ${token}`;
  if (body && !form) headers["content-type"] = "application/json";
  const res = await fetch(BASE + path, {
    method,
    headers,
    body: form ? new URLSearchParams(body) : body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status} ${text.slice(0, 200)}`);
  return text ? JSON.parse(text) : null;
}

async function tokenFromCode(code) {
  const res = await call("/auth/token", {
    method: "POST",
    form: true,
    body: { grant_type: "authorization_code", code, client_id: CLIENT_ID },
  });
  return res.access_token;
}

async function onboard() {
  // Home Assistant removes the onboarding endpoint once onboarding is complete.
  const steps = await call("/api/onboarding").catch((err) => {
    if (String(err.message).includes("404")) return [];
    throw err;
  });
  const pending = new Set(steps.filter((s) => !s.done).map((s) => s.step));
  if (pending.size === 0) return null;
  let token;
  if (pending.has("user")) {
    const res = await call("/api/onboarding/users", {
      method: "POST",
      body: {
        client_id: CLIENT_ID,
        name: USERNAME,
        username: USERNAME,
        password: PASSWORD,
        language: "en",
      },
    });
    token = await tokenFromCode(res.auth_code);
    console.log(`created user ${USERNAME}`);
  } else {
    token = await login();
  }
  if (pending.has("core_config"))
    await call("/api/onboarding/core_config", { method: "POST", token, body: {} });
  if (pending.has("analytics"))
    await call("/api/onboarding/analytics", { method: "POST", token, body: {} });
  if (pending.has("integration")) {
    await call("/api/onboarding/integration", {
      method: "POST",
      token,
      body: { client_id: CLIENT_ID, redirect_uri: CLIENT_ID },
    });
  }
  console.log("onboarding done");
  return token;
}

async function login() {
  const flow = await call("/auth/login_flow", {
    method: "POST",
    body: { client_id: CLIENT_ID, handler: ["homeassistant", null], redirect_uri: CLIENT_ID },
  });
  const res = await call(`/auth/login_flow/${flow.flow_id}`, {
    method: "POST",
    body: { client_id: CLIENT_ID, username: USERNAME, password: PASSWORD },
  });
  if (res.type !== "create_entry")
    throw new Error(`login failed: ${JSON.stringify(res).slice(0, 200)}`);
  return tokenFromCode(res.result);
}

async function ensureConfigEntry(token) {
  const entries = await call("/api/config/config_entries/entry?domain=tado_x_matter_pro", { token });
  if (entries.length) {
    console.log(`Tado X Matter Pro entry: ${entries[0].state}`);
    return;
  }
  const flow = await call("/api/config/config_entries/flow", {
    method: "POST",
    token,
    body: { handler: "tado_x_matter_pro" },
  });
  const done = await call(`/api/config/config_entries/flow/${flow.flow_id}`, {
    method: "POST",
    token,
    body: {},
  });
  console.log(
    `Tado X Matter Pro entry: ${done.type === "create_entry" ? "created" : JSON.stringify(done).slice(0, 120)}`,
  );
}

/** A websocket session: `send(message)` resolves with the result. */
async function connect(token) {
  const ws = new WebSocket(BASE.replace(/^http/, "ws") + "/api/websocket");
  const queue = [];
  const waiters = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (waiters.length) waiters.shift()(m);
    else queue.push(m);
  };
  const next = () =>
    queue.length ? Promise.resolve(queue.shift()) : new Promise((r) => waiters.push(r));
  await new Promise((r) => (ws.onopen = r));
  await next(); // auth_required
  ws.send(JSON.stringify({ type: "auth", access_token: token }));
  await next(); // auth_ok
  let id = 1;
  return {
    async send(message) {
      ws.send(JSON.stringify({ id: id++, ...message }));
      const res = await next();
      if (res.success === false) throw new Error(`${message.type}: ${res.error?.message}`);
      return res.result;
    },
    close: () => ws.close(),
  };
}

// Fictional heating schedules of the Dev House (storage helpers, so they are editable in the UI).
// A block's `data.temperature` overrides the room's heating temperature for that block.
const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"];
const WEEKEND = ["saturday", "sunday"];
const ALL_DAYS = [...WEEKDAYS, ...WEEKEND];
const block = (from, to, temperature) =>
  temperature === undefined ? { from, to } : { from, to, data: { temperature } };
const days = (spec) => Object.fromEntries(spec.flatMap(([list, blocks]) => list.map((d) => [d, blocks])));
const SCHEDULES = [
  {
    name: "Heating Ground Floor",
    ...days([
      [WEEKDAYS, [block("06:30:00", "08:30:00"), block("16:00:00", "22:00:00")]],
      [WEEKEND, [block("08:00:00", "22:30:00")]],
    ]),
  },
  {
    name: "Heating Bathroom",
    ...days([[ALL_DAYS, [block("06:00:00", "07:30:00", 23), block("19:00:00", "22:00:00")]]]),
  },
  {
    name: "Heating Bedrooms",
    ...days([[ALL_DAYS, [block("00:00:00", "06:30:00"), block("20:30:00", "24:00:00")]]]),
  },
  {
    name: "Heating Office",
    ...days([
      [WEEKDAYS, [block("08:00:00", "17:00:00")]],
      [WEEKEND, []],
    ]),
  },
  {
    name: "Heating Upstairs Hallway",
    ...days([[ALL_DAYS, [block("06:30:00", "08:30:00"), block("17:30:00", "22:00:00")]]]),
  },
];

async function ensureSchedules(c) {
  const existing = new Set((await c.send({ type: "schedule/list" })).map((s) => s.name));
  let added = 0;
  for (const schedule of SCHEDULES) {
    if (existing.has(schedule.name)) continue;
    await c.send({ type: "schedule/create", icon: "mdi:radiator", ...schedule });
    added += 1;
  }
  console.log(`schedules: ${added} created, ${SCHEDULES.length - added} already present`);
}

// The Dev House dashboard: the house controls, then one section per floor with every room's
// thermostats, contacts (tap toggles them) and room sensor.
const FLOORS = [
  {
    name: "Ground Floor",
    rooms: [
      ["Living Room", ["living_room_thermostat"], ["living_room_terrace_door"], "living_room_temperature"],
      ["Kitchen", ["kitchen_thermostat"], ["kitchen_window"], "kitchen_temperature"],
      ["Hallway", ["hallway_thermostat"], ["front_door"], null],
      ["Toilet", ["toilet_thermostat"], ["toilet_window"], "toilet_temperature"],
    ],
  },
  {
    name: "First Floor",
    rooms: [
      ["Bedroom", ["bedroom_thermostat"], ["bedroom_window_left", "bedroom_window_right"], null],
      ["Kids Room", ["kids_room_thermostat"], ["kids_room_window"], null],
      ["Bathroom", ["bathroom_thermostat", "bathroom_thermostat_tub"], ["bathroom_window"], "bathroom_temperature"],
      ["Upstairs Hallway", ["upstairs_hallway_thermostat"], ["upstairs_hallway_window"], "upstairs_hallway_temperature"],
    ],
  },
  {
    name: "Attic",
    rooms: [
      ["Office", ["office_thermostat_front", "smart_radiator_thermostat_x"], ["office_window_front", "office_window_back"], "office_temperature"],
    ],
  },
];

const thermostatTile = (id) => ({
  type: "tile",
  entity: `climate.${id}`,
  grid_options: { columns: 12 },
  features: [{ type: "target-temperature" }, { type: "climate-hvac-modes", hvac_modes: ["off", "heat"] }],
  features_position: "bottom",
});
const contactTile = (id) => ({
  type: "tile",
  entity: `binary_sensor.${id}`,
  tap_action: {
    action: "perform-action",
    perform_action: "dev_house.set_window",
    target: { entity_id: `binary_sensor.${id}` },
  },
});

function dashboardConfig() {
  const house = {
    type: "grid",
    cards: [
      { type: "heading", heading: "House", icon: "mdi:home-thermometer" },
      { type: "tile", entity: "sensor.outdoor_temperature", name: "Outdoor" },
      { type: "tile", entity: "input_boolean.away_mode" },
      { type: "tile", entity: "input_boolean.vacation_mode" },
      { type: "heading", heading: "Schedules", heading_style: "subtitle" },
      ...SCHEDULES.map((s) => ({
        type: "tile",
        entity: `schedule.${s.name.toLowerCase().replaceAll(" ", "_")}`,
      })),
      {
        type: "markdown",
        content:
          "Tap a window or door to open or close it. Developer tools → Actions has `dev_house.turn_dial` " +
          "(a change at the thermostat itself), `dev_house.drop_connection`, " +
          "`dev_house.set_air_temperature` and `dev_house.set_outdoor_temperature`.",
      },
    ],
  };
  const floors = FLOORS.map((floor) => ({
    type: "grid",
    cards: [
      { type: "heading", heading: floor.name },
      ...floor.rooms.flatMap(([room, trvs, contacts, sensor]) => [
        { type: "heading", heading: room, heading_style: "subtitle" },
        ...trvs.map(thermostatTile),
        ...contacts.map(contactTile),
        ...(sensor ? [{ type: "tile", entity: `sensor.${sensor}`, name: "Room" }] : []),
      ]),
    ],
  }));
  return {
    title: "Dev House",
    views: [{ title: "House", path: "house", type: "sections", max_columns: 4, sections: [house, ...floors] }],
  };
}

async function ensureDashboard(c) {
  const dashboards = await c.send({ type: "lovelace/dashboards/list" });
  if (!dashboards.some((d) => d.url_path === "dev-house")) {
    await c.send({
      type: "lovelace/dashboards/create",
      url_path: "dev-house",
      title: "Dev House",
      icon: "mdi:home-thermometer",
      show_in_sidebar: true,
      require_admin: false,
      mode: "storage",
    });
  }
  // Always rewritten, so changes here reach existing dev instances.
  await c.send({ type: "lovelace/config/save", url_path: "dev-house", config: dashboardConfig() });
  console.log("dashboard: Dev House saved");
}

async function main() {
  const onboarded = await onboard();
  const token = onboarded ?? (await login());
  await ensureConfigEntry(token);
  const session = await connect(token);
  await ensureSchedules(session);
  await ensureDashboard(session);
  session.close();
}

// Home Assistant answers the API before every component is ready; retry a few times on start.
for (let attempt = 1; ; attempt++) {
  try {
    await main();
    break;
  } catch (err) {
    if (attempt >= 10) throw err;
    console.log(`not ready yet (${err.message.slice(0, 80)}), retrying…`);
    await new Promise((r) => setTimeout(r, 3000));
  }
}
console.log(`ready: ${BASE}  (user ${USERNAME} / ${PASSWORD})`);
