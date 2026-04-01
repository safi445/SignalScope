const $ = (id) => document.getElementById(id);

const radar = $("radar");
const ctx = radar.getContext("2d");

const chart = $("rssiChart");
const cctx = chart.getContext("2d");

const trail = $("trail");
const tctx = trail.getContext("2d");

let selectedKey = null; // `${signal_type}:${device_id}`
let selectedHistory = [];
let lastSnapshot = [];
let lastDevices = [];

// Smooth radar state (per device).
const blips = new Map(); // key -> {x,y,tx,ty,r,c,cat,ttl}

function dpr() {
  return Math.max(1, Math.floor(window.devicePixelRatio || 1));
}

function fitCanvasToCss(canvas, context) {
  const r = canvas.getBoundingClientRect();
  const D = dpr();
  const w = Math.max(1, Math.floor(r.width * D));
  const h = Math.max(1, Math.floor(r.height * D));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  context.setTransform(D, 0, 0, D, 0, 0);
  return { cssW: r.width, cssH: r.height };
}

function colorForCategory(cat) {
  if (cat === "Suspicious") return "#ff4d4d";
  if (cat === "Interesting") return "#f5c542";
  return "#35d07f";
}

function setStatus(ok, text) {
  $("statusText").textContent = text;
  $("statusDot").style.background = ok ? "#35d07f" : "#f5c542";
}

function rssiToRadius(rssi) {
  // Map [-90..-30] -> [1..0] then scale to radar radius.
  const v = (Math.max(-90, Math.min(-30, rssi ?? -90)) + 90) / 60; // 0..1
  const t = 1 - v; // 1..0
  return t;
}

function hashAngle(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 0xffffffff * Math.PI * 2;
}

function drawRadarFrame(devices) {
  const { cssW, cssH } = fitCanvasToCss(radar, ctx);
  const w = cssW;
  const h = cssH;
  ctx.clearRect(0, 0, w, h);

  // Background
  ctx.fillStyle = "rgba(11,16,32,0.55)";
  ctx.fillRect(0, 0, w, h);

  const cx = w / 2;
  const cy = h / 2;
  const R = Math.min(w, h) * 0.44;

  // Rings
  ctx.strokeStyle = "rgba(159,176,208,0.18)";
  ctx.lineWidth = 1;
  for (let i = 1; i <= 4; i++) {
    ctx.beginPath();
    ctx.arc(cx, cy, (R * i) / 4, 0, Math.PI * 2);
    ctx.stroke();
  }

  // Crosshair
  ctx.beginPath();
  ctx.moveTo(cx - R, cy);
  ctx.lineTo(cx + R, cy);
  ctx.moveTo(cx, cy - R);
  ctx.lineTo(cx, cy + R);
  ctx.stroke();

  // Sweep
  const t = Date.now() / 1000;
  const ang = (t % 3.2) / 3.2 * Math.PI * 2;
  const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, R);
  grad.addColorStop(0, "rgba(53,208,127,0.04)");
  grad.addColorStop(1, "rgba(53,208,127,0.0)");
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.arc(cx, cy, R, ang - 0.25, ang + 0.02);
  ctx.closePath();
  ctx.fill();

  // Update targets + smooth positions.
  const now = Date.now();
  const present = new Set();

  for (const d of devices) {
    const key = `${d.signal_type}:${d.device_id}`;
    present.add(key);

    const baseAng = hashAngle(key);
    const a = baseAng + Math.sin(t * 1.2 + baseAng) * 0.04;
    const rr = rssiToRadius(d.last_rssi);
    const rad = rr * R;
    const tx = cx + Math.cos(a) * rad;
    const ty = cy + Math.sin(a) * rad;
    const c = colorForCategory(d.category);

    const b = blips.get(key) || { x: tx, y: ty, tx, ty, c, cat: d.category, ttl: 0 };
    b.tx = tx;
    b.ty = ty;
    b.c = c;
    b.cat = d.category;
    b.ttl = now + 4500; // keep fading for 4.5s after last seen
    blips.set(key, b);
  }

  // Lerp + draw (with fade-out for stale blips).
  for (const [key, b] of blips.entries()) {
    const alive = b.ttl - now;
    if (alive <= 0) {
      blips.delete(key);
      continue;
    }
    const k = 0.12; // smoothing factor per frame
    b.x += (b.tx - b.x) * k;
    b.y += (b.ty - b.y) * k;

    const alpha = Math.min(1, Math.max(0.15, alive / 4500));
    ctx.fillStyle = b.c.replace(")", `,${alpha})`).replace("rgb", "rgba");
    ctx.beginPath();
    ctx.arc(b.x, b.y, b.cat === "Suspicious" ? 5 : 4, 0, Math.PI * 2);
    ctx.fill();

    // Glow
    ctx.fillStyle = b.c.replace(")", `,${0.12 * alpha})`).replace("rgb", "rgba");
    ctx.beginPath();
    ctx.arc(b.x, b.y, 13, 0, Math.PI * 2);
    ctx.fill();
  }
}

function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return "—";
  }
}

function msToHuman(ms) {
  if (!isFinite(ms) || ms < 0) return "—";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function drawChart(historyRows) {
  const w = chart.width;
  const h = chart.height;
  cctx.clearRect(0, 0, w, h);

  // background
  cctx.fillStyle = "rgba(11,16,32,0.55)";
  cctx.fillRect(0, 0, w, h);

  cctx.strokeStyle = "rgba(159,176,208,0.18)";
  cctx.lineWidth = 1;
  for (let i = 1; i <= 3; i++) {
    const y = (h * i) / 4;
    cctx.beginPath();
    cctx.moveTo(0, y);
    cctx.lineTo(w, y);
    cctx.stroke();
  }

  if (!historyRows || historyRows.length === 0) {
    cctx.fillStyle = "rgba(159,176,208,0.7)";
    cctx.font = "13px ui-sans-serif, system-ui";
    cctx.fillText("Select a device to view RSSI timeline.", 12, 26);
    return;
  }

  // Use oldest->newest
  const pts = [...historyRows].reverse().map((r) => ({ ts: Date.parse(r.ts), rssi: r.rssi }));
  const rssiVals = pts.map((p) => (typeof p.rssi === "number" ? p.rssi : null)).filter((x) => x !== null);
  const minR = rssiVals.length ? Math.min(...rssiVals) : -90;
  const maxR = rssiVals.length ? Math.max(...rssiVals) : -30;
  const lo = Math.min(minR, -90);
  const hi = Math.max(maxR, -30);

  const t0 = pts[0].ts;
  const t1 = pts[pts.length - 1].ts;
  const dt = Math.max(1, t1 - t0);

  const xFor = (t) => ((t - t0) / dt) * (w - 24) + 12;
  const yFor = (r) => {
    const v = (r - lo) / (hi - lo || 1); // 0..1
    return (1 - v) * (h - 24) + 12;
  };

  // line
  cctx.strokeStyle = "rgba(245,197,66,0.9)";
  cctx.lineWidth = 2;
  cctx.beginPath();
  let started = false;
  for (const p of pts) {
    if (typeof p.rssi !== "number") continue;
    const x = xFor(p.ts);
    const y = yFor(p.rssi);
    if (!started) {
      cctx.moveTo(x, y);
      started = true;
    } else {
      cctx.lineTo(x, y);
    }
  }
  cctx.stroke();

  // points
  cctx.fillStyle = "rgba(245,197,66,0.95)";
  for (const p of pts) {
    if (typeof p.rssi !== "number") continue;
    const x = xFor(p.ts);
    const y = yFor(p.rssi);
    cctx.beginPath();
    cctx.arc(x, y, 2.8, 0, Math.PI * 2);
    cctx.fill();
  }

  // labels
  cctx.fillStyle = "rgba(159,176,208,0.85)";
  cctx.font = "12px ui-monospace, Menlo, Consolas, monospace";
  cctx.fillText(`${hi} dBm`, 12, 14);
  cctx.fillText(`${lo} dBm`, 12, h - 6);
}

function drawTrail(historyRows) {
  const w = trail.width;
  const h = trail.height;
  tctx.clearRect(0, 0, w, h);

  // background
  tctx.fillStyle = "rgba(11,16,32,0.55)";
  tctx.fillRect(0, 0, w, h);

  // grid
  tctx.strokeStyle = "rgba(159,176,208,0.14)";
  tctx.lineWidth = 1;
  for (let i = 1; i <= 4; i++) {
    const x = (w * i) / 5;
    tctx.beginPath();
    tctx.moveTo(x, 0);
    tctx.lineTo(x, h);
    tctx.stroke();
  }
  for (let i = 1; i <= 3; i++) {
    const y = (h * i) / 4;
    tctx.beginPath();
    tctx.moveTo(0, y);
    tctx.lineTo(w, y);
    tctx.stroke();
  }

  if (!historyRows || historyRows.length < 6) {
    tctx.fillStyle = "rgba(159,176,208,0.7)";
    tctx.font = "13px ui-sans-serif, system-ui";
    tctx.fillText("Trail needs more samples (keep scanning).", 12, 26);
    return;
  }

  // We generate a relative trail using RSSI deltas as step lengths.
  // This is NOT real location — just a “relative movement” visualization.
  const pts = [...historyRows]
    .reverse()
    .map((r) => ({ ts: Date.parse(r.ts), rssi: r.rssi }))
    .filter((p) => typeof p.rssi === "number");

  if (pts.length < 6) {
    tctx.fillStyle = "rgba(159,176,208,0.7)";
    tctx.font = "13px ui-sans-serif, system-ui";
    tctx.fillText("Trail needs more RSSI points.", 12, 26);
    return;
  }

  let x = w / 2;
  let y = h / 2;
  const path = [{ x, y, rssi: pts[0].rssi }];
  let angle = hashAngle(selectedKey || "trail");

  for (let i = 1; i < pts.length; i++) {
    const dr = Math.max(-20, Math.min(20, pts[i].rssi - pts[i - 1].rssi));
    const step = Math.abs(dr) * 1.6 + 2.0;
    angle += (dr >= 0 ? 0.35 : -0.35) + Math.sin(i * 0.7) * 0.08;
    x += Math.cos(angle) * step;
    y += Math.sin(angle) * step;
    x = Math.max(12, Math.min(w - 12, x));
    y = Math.max(12, Math.min(h - 12, y));
    path.push({ x, y, rssi: pts[i].rssi });
  }

  // path line
  tctx.strokeStyle = "rgba(245,197,66,0.9)";
  tctx.lineWidth = 2;
  tctx.beginPath();
  tctx.moveTo(path[0].x, path[0].y);
  for (const p of path.slice(1)) tctx.lineTo(p.x, p.y);
  tctx.stroke();

  // nodes (fade older)
  for (let i = 0; i < path.length; i++) {
    const p = path[i];
    const a = i / (path.length - 1);
    const alpha = 0.15 + a * 0.85;
    tctx.fillStyle = `rgba(245,197,66,${alpha})`;
    tctx.beginPath();
    tctx.arc(p.x, p.y, i === path.length - 1 ? 5 : 3, 0, Math.PI * 2);
    tctx.fill();
  }

  // labels
  tctx.fillStyle = "rgba(159,176,208,0.85)";
  tctx.font = "12px ui-monospace, Menlo, Consolas, monospace";
  tctx.fillText("Relative trail (RSSI-delta based)", 12, 16);
}

async function selectDevice(d) {
  selectedKey = `${d.signal_type}:${d.device_id}`;
  $("selectedLabel").textContent = selectedKey;
  $("selFirst").textContent = fmtTime(d.first_seen);
  $("selLast").textContent = fmtTime(d.last_seen);
  $("selSeen").textContent = String(d.seen_count);
  $("selPersist").textContent = msToHuman(Date.parse(d.last_seen) - Date.parse(d.first_seen));
  $("selMotion").textContent = "…";

  try {
    const r = await fetch(`/history?device_id=${encodeURIComponent(d.device_id)}&limit=120`, { cache: "no-store" });
    const data = await r.json();
    selectedHistory = data.rows || [];
    drawChart(selectedHistory);
    drawTrail(selectedHistory);
  } catch {
    selectedHistory = [];
    drawChart([]);
    drawTrail([]);
  }

  try {
    const r2 = await fetch(`/device_stats?device_id=${encodeURIComponent(d.device_id)}&minutes=10`, { cache: "no-store" });
    const s = await r2.json();
    const mv = (s.movement || "unknown").toUpperCase();
    const sc = typeof s.movement_score === "number" ? s.movement_score.toFixed(1) : "—";
    $("selMotion").textContent = `${mv} (σ=${sc})`;
  } catch {
    $("selMotion").textContent = "—";
  }
}

function passesFilters(d) {
  const q = ($("q")?.value || "").trim().toLowerCase();
  const onlySusp = $("onlySusp")?.checked;
  const onlyCam = $("onlyCam")?.checked;
  const onlyWifi = $("onlyWifi")?.checked;
  const onlyBle = $("onlyBle")?.checked;

  if (onlySusp && d.suspicion_score < 60) return false;
  if (onlyCam && !(d.tags || []).includes("potential_camera")) return false;
  if (onlyWifi && d.signal_type !== "wifi") return false;
  if (onlyBle && d.signal_type !== "ble") return false;

  if (!q) return true;
  const blob = [
    d.ssid,
    d.name,
    d.vendor,
    d.device_id,
    d.signal_type,
    d.source,
    d.security,
    d.band,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return blob.includes(q);
}

function renderList(devices) {
  $("deviceCount").textContent = String(devices.length);
  const host = $("deviceList");
  host.innerHTML = "";

  const filtered = devices.filter(passesFilters);
  $("deviceCount").textContent = String(filtered.length);

  for (const d of filtered.slice(0, 60)) {
    const row = document.createElement("div");
    row.className = "row";

    const catClass = d.category === "Suspicious" ? "r" : d.category === "Interesting" ? "y" : "g";
    const title = d.ssid || d.name || "(unnamed)";

    const key = `${d.signal_type}:${d.device_id}`;
    if (selectedKey && key === selectedKey) row.classList.add("sel");

    const cam = (d.tags || []).includes("potential_camera");
    const badge = cam ? `<span class="badge cam">POTENTIAL CAMERA</span>` : "";

    row.innerHTML = `
      <div class="rowTop">
        <div>
          <div style="font-weight:650">${escapeHtml(title)} ${badge}</div>
          <div class="id">${escapeHtml(d.signal_type)} · ${escapeHtml(d.device_id)} · ${escapeHtml(d.source ?? "—")}</div>
        </div>
        <div class="tag ${catClass}">${escapeHtml(d.category)} · ${d.suspicion_score}</div>
      </div>
      <div class="small">
        <div>RSSI: <b>${d.last_rssi ?? "—"}</b> dBm</div>
        <div>Seen: <b>${d.seen_count}</b></div>
        <div>Vendor: <b>${escapeHtml(d.vendor ?? "—")}</b></div>
        <div>Band: <b>${escapeHtml(d.band ?? "—")}</b></div>
        <div>Sec: <b>${escapeHtml(d.security ?? "—")}</b></div>
      </div>
    `;
    row.addEventListener("click", () => selectDevice(d));
    host.appendChild(row);
  }
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function tick() {
  try {
    const r = await fetch("/scan", { cache: "no-store" });
    const data = await r.json();
    const ts = data.ts ? new Date(data.ts) : null;
    $("lastScan").textContent = ts ? ts.toLocaleTimeString() : "—";

    setStatus(true, `Live · ${data.device_count} devices`);
    renderList(data.devices || []);
    drawRadar(data.devices || []);
  } catch (e) {
    setStatus(false, "Waiting for server…");
  }
  requestAnimationFrame(() => drawRadar(window.__lastDevices || []));
}

async function poll() {
  try {
    const r = await fetch("/scan", { cache: "no-store" });
    const data = await r.json();
    window.__lastDevices = data.devices || [];
    lastSnapshot = window.__lastDevices;
    lastDevices = window.__lastDevices;
    const ts = data.ts ? new Date(data.ts) : null;
    $("lastScan").textContent = ts ? ts.toLocaleTimeString() : "—";
    setStatus(true, `Live · ${data.device_count} devices`);
    renderList(window.__lastDevices);

    // Auto-select the top device once (first load).
    if (!selectedKey && window.__lastDevices.length) {
      await selectDevice(window.__lastDevices[0]);
    }
  } catch (e) {
    setStatus(false, "Waiting for server…");
  }
}

async function debrief() {
  $("debrief").textContent = "Loading…";
  try {
    const r = await fetch("/debrief?minutes=5", { cache: "no-store" });
    const d = await r.json();
    const lines = [];
    lines.push(`Scan Window: ${d.scan_window_minutes} minutes`);
    lines.push(`Unique Devices (window): ${d.unique_devices_in_window}`);
    lines.push(`Observations (window): ${d.observations_in_window}`);
    lines.push("");
    lines.push(`New Devices: ${d.new_devices.length}`);
    for (const x of d.new_devices.slice(0, 6)) lines.push(`- ${x}`);
    lines.push("");
    lines.push(`Lost Devices: ${d.lost_devices.length}`);
    for (const x of d.lost_devices.slice(0, 6)) lines.push(`- ${x}`);
    lines.push("");
    lines.push(`Suspicious: ${d.suspicious.length}`);
    for (const s of d.suspicious.slice(0, 6)) {
      lines.push(`- ${s.signal_type} ${s.device_id} (${s.last_rssi ?? "—"} dBm) score=${s.suspicion_score}`);
    }
    lines.push("");
    lines.push(`Environment: ${d.environment.density}`);
    $("debrief").textContent = lines.join("\n");
  } catch (e) {
    $("debrief").textContent = "Debrief failed (server not ready).";
  }
}

$("btnDebrief").addEventListener("click", debrief);

function renderEvents(rows) {
  const host = $("events");
  host.innerHTML = "";
  for (const e of (rows || []).slice(0, 40)) {
    const el = document.createElement("div");
    el.className = "ev";
    const sev = (e.severity || "info").toLowerCase();
    const ts = e.ts ? new Date(e.ts).toLocaleTimeString() : "—";
    el.innerHTML = `
      <div class="evTop">
        <div class="sev ${sev}">${escapeHtml(sev.toUpperCase())}</div>
        <div>${escapeHtml(ts)}</div>
      </div>
      <div class="evTitle">${escapeHtml(e.title || e.event_type || "event")}</div>
      <div class="evSmall">${escapeHtml(e.device_key || "")}</div>
    `;
    host.appendChild(el);
  }
}

async function refreshEvents() {
  try {
    const r = await fetch("/events?limit=60", { cache: "no-store" });
    const d = await r.json();
    renderEvents(d.rows || []);
  } catch {
    renderEvents([]);
  }
}

$("btnEvents")?.addEventListener("click", refreshEvents);

// Re-filter on input changes without waiting for next poll.
for (const id of ["q", "onlySusp", "onlyCam", "onlyWifi", "onlyBle"]) {
  const el = $(id);
  if (!el) continue;
  el.addEventListener("input", () => renderList(lastSnapshot));
  el.addEventListener("change", () => renderList(lastSnapshot));
}

function anim() {
  drawRadarFrame(lastDevices);
  requestAnimationFrame(anim);
}

// Poll scan data every ~2.5s; radar animates continuously.
setInterval(poll, 2500);
poll();
requestAnimationFrame(anim);
setInterval(refreshEvents, 5000);
refreshEvents();

// Keep chart updated even when list re-renders.
drawChart([]);
drawTrail([]);

