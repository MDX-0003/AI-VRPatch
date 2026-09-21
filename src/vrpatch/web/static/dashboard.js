// vrpatch dashboard: vanilla JS, polling only, zero npm.
// ALL picking coordinates go through PickCoords (pick.js) — display and
// submission share one mapping, so style changes cannot desync them.
"use strict";
let SEL = null;                 // selected case name
let vpDrag = null;              // PickCoords drag controller for the viewport
let CUR = null;                 // last fetched case info (drives media + overlays)
const scrub = { frame: 0, count: 0, fps: 30 };
let vpTimer = null;             // debounce for the per-frame viewport preview

const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const opt = body ? { method: "POST", headers: { "Content-Type": "application/json" },
                       body: JSON.stringify(body) } : {};
  const r = await fetch(path, opt);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.status);
  return j;
}

// ---- cases -----------------------------------------------------------

async function refreshCases() {
  const cases = await api("/api/cases");
  const box = $("cases");
  box.innerHTML = "";
  for (const c of cases) {
    const d = document.createElement("div");
    d.className = "case" + (c.name === SEL ? " sel" : "");
    const st = [c.extracted && "已抠", c.ai_clip_exists && "AI结果", c.merged && "已合并"]
      .filter(Boolean).join("·") || "未处理";
    d.innerHTML = `${c.name}<span class="st">${st}</span>`;
    d.onclick = () => selectCase(c.name);
    box.appendChild(d);
  }
}

async function refreshSources() {
  const s = await api("/api/sources");
  $("srcDir").textContent = "素材库：" + s.dir;
  const sel = $("srcSel");
  sel.innerHTML = "";
  for (const f of s.files) {
    const o = document.createElement("option");
    o.textContent = f; o.value = f;
    sel.appendChild(o);
  }
}

async function createCase() {
  const v = $("srcSel").value;
  if (!v) return alert("素材库 sources/ 里还没有视频，先放一个进去");
  try {
    await api("/api/cases", { video: v });
    await refreshCases();
  } catch (e) { alert(e.message); }
}

// ---- case detail -------------------------------------------------------

function infoSig(c) {
  // what media/preview refreshes depend on — idle polls must not touch them
  return JSON.stringify([c.viewport, c.inner, c.extracted, c.extract_version,
                         c.versions, c.source_frames, c.fps, c.source_url]);
}

async function selectCase(name) {
  if (vpDrag) vpDrag.cancel();      // never leave a drag in flight across cases
  SEL = name;
  await refreshCase();
  await refreshCases();
}

async function refreshCase() {
  if (!SEL || (vpDrag && vpDrag.active)) return;   // no image swaps mid-drag
  const c = await api("/api/case/" + SEL);
  $("caseName").textContent = c.name;
  $("vpMeta").textContent = `yaw ${c.viewport.yaw}  pitch ${c.viewport.pitch}  fov ${c.viewport.fov}  窗口 ${c.viewport.size}`;
  $("inMeta").textContent = `inner ${c.inner.x},${c.inner.y},${c.inner.w},${c.inner.h}`;
  $("exSt").textContent = c.extracted ? "✓ 已生成 clip.mp4 + 掩膜" : "";
  const verSel = $("verSel");
  const keep = verSel.value;               // pollTask rebuilds this list every
  verSel.innerHTML = "";                   // 1.2s — never lose the user's pick
  for (const v of [...c.versions].reverse()) {
    const o = document.createElement("option");
    o.value = v.version;
    const ai = v.ai_clip_exists ? "✓AI" : "无AI";
    o.textContent = `${v.version}（${ai}）`;
    verSel.appendChild(o);
  }
  // restore the selection if the version still exists, else default to latest
  if ([...verSel.options].some(o => o.value === keep))
    verSel.value = keep;
  else if (verSel.options.length)
    verSel.value = c.versions[c.versions.length - 1].version;
  updatePipeline(c);
  $("innerBox").style.display = "none";            // committed: hide the live box
  const changed = !CUR || CUR.name !== c.name || infoSig(CUR) !== infoSig(c);
  CUR = c;
  if (!changed) return;          // idle poll: leave video/overlays/previews alone
  setVideoCase(c);
  drawErpOverlays();
  refreshVp();
}

// ---- ERP video + frame scrubber -----------------------------------------
// The ERP pane is a native <video>: scrubbing decodes in the browser, so
// browsing all frames costs zero server work and zero files. Only the
// viewport pane (reprojection) needs the server, per current frame.

function setVideoCase(c) {
  const v = $("erpVid");
  scrub.count = c.source_frames || 0;
  scrub.fps = c.fps || 30;
  $("frameSlider").max = Math.max(0, scrub.count - 1);
  if (v.dataset.case !== c.name) {       // case switch: reload, reset position
    v.dataset.case = c.name;
    v.src = c.source_url;
    scrub.frame = 0;
    $("frameSlider").value = 0;
    updateFrameLabel();
  } else {
    scrub.frame = Math.min(scrub.frame, Math.max(0, scrub.count - 1));
  }
}

function updateFrameLabel() {
  $("frameLabel").textContent = `${scrub.frame}/${scrub.count}`;
}

function gotoFrame(n) {
  scrub.frame = Math.max(0, Math.min(scrub.count - 1, n));
  $("frameSlider").value = scrub.frame;
  updateFrameLabel();
  const v = $("erpVid");
  if (scrub.count > 0 && v.readyState >= 1)
    v.currentTime = scrub.frame / scrub.fps;   // fires 'seeked' -> vp refresh
}

// ERP overlays mirror what render.py used to bake in: a red cross at the
// viewport centre and the rough footprint box (fov fraction x viewport
// aspect). Pure display arithmetic on case fractions — no projection math
// lives client-side.
function drawErpOverlays() {
  if (!CUR) return;
  const v = $("erpVid");
  if (v.readyState < 1) return;
  const r = v.getBoundingClientRect();
  if (r.width === 0) return;
  const vp = CUR.viewport;
  const cx = (0.5 + vp.yaw / 360) * r.width;
  const cy = (0.5 - vp.pitch / 180) * r.height;
  const fw = (vp.fov / 360) * r.width;
  const fh = fw * vp.size[1] / vp.size[0];
  PickCoords.drawOverlay($("vpFoot"), v,
    { x: cx - fw / 2, y: cy - fh / 2, w: fw, h: fh });
  const cross = $("vpCross");
  const ob = (cross.offsetParent || document.body).getBoundingClientRect();
  cross.style.left = (r.left - ob.left + cx) + "px";
  cross.style.top = (r.top - ob.top + cy) + "px";
  cross.style.display = "block";
}

// viewport preview follows the scrub frame (server-side reprojection, ~1s
// uncached on 8K); frame 0 maps to the no-param fast path (startup base)
function refreshVp() {
  if (!CUR) return;
  const f = scrub.frame > 0 ? `&frame=${scrub.frame}` : "";
  $("vpImg").src = `${CUR.previews.vp}${f}&t=${Date.now()}`;
}

function scheduleVpRefresh(delay = 350) {
  clearTimeout(vpTimer);
  vpTimer = setTimeout(() => {
    vpTimer = null;
    if (SEL && !(vpDrag && vpDrag.active)) refreshVp();
  }, delay);
}

{
  const v = $("erpVid");
  v.addEventListener("loadedmetadata", () => {
    if (scrub.frame > 0) v.currentTime = scrub.frame / scrub.fps;
    drawErpOverlays();
  });
  v.addEventListener("seeked", () => {
    if (scrub.count > 0) scrub.frame = Math.round(v.currentTime * scrub.fps);
    $("frameSlider").value = scrub.frame;
    updateFrameLabel();
    scheduleVpRefresh();
  });
  v.addEventListener("timeupdate", () => {
    if (v.paused) return;              // seeks handled by 'seeked'
    scrub.frame = Math.round(v.currentTime * scrub.fps);
    $("frameSlider").value = scrub.frame;
    updateFrameLabel();
  });
  v.addEventListener("play", () => { $("btnPlay").textContent = "⏸"; });
  v.addEventListener("pause", () => {
    $("btnPlay").textContent = "▶";
    scheduleVpRefresh(0);              // settle on the frame where we stopped
  });
  $("btnPlay").onclick = () => {
    if (!v.src) return;
    if (v.paused) v.play(); else v.pause();
  };
  $("btnPrev").onclick = () => gotoFrame(scrub.frame - 1);
  $("btnNext").onclick = () => gotoFrame(scrub.frame + 1);
  $("frameSlider").addEventListener("input",
    (e) => gotoFrame(parseInt(e.target.value, 10)));
}
window.addEventListener("resize", drawErpOverlays);

// pipeline badges reflect the SELECTED extract version
async function updatePipeline(c) {
  if (!c) c = await api("/api/case/" + SEL);
  const v = c.versions.find(v => v.version === $("verSel").value) || c.versions[c.versions.length - 1];
  if (!v) { $("stExtract").className = "step"; $("stAi").className = "step"; $("stMerge").className = "step"; return; }
  $("exSt").textContent = v.extracted ? "✓ 该版本已生成 clip.mp4 + 掩膜" : "";
  $("aiSt").textContent = v.ai_clip ? (v.ai_clip_exists ? "✓ " + v.ai_clip : "✗ 文件不存在：" + v.ai_clip) : "";
  $("aiSt").className = "meta";
  $("stExtract").className = "step on";
  $("stAi").className = "step" + (v.extracted ? " on" : "");
  $("stMerge").className = "step" + (v.ai_clip_exists ? " on" : "");
  $("btnMerge").disabled = !v.ai_clip_exists;
}

// ERP click: viewport centre follows the click, via the single mapping.
async function erpClick(ev) {
  if (!SEL) return;
  const p = PickCoords.point($("erpVid"), ev);
  if (!p) return;                    // video metadata not ready: ignore click
  await postGeometry("viewport", { fx: p.frac.x, fy: p.frac.y });
}

async function postGeometry(kind, body) {
  try {
    await api(`/api/case/${SEL}/${kind}`, body);
    await refreshCase();
  } catch (e) { alert(e.message); }
}

async function resetDraft() {
  if (!SEL) return;
  try {
    // reset target = the version chosen in the dropdown (default: latest)
    await api(`/api/case/${SEL}/reset-draft`, { version: $("verSel").value });
    await refreshCase();
  } catch (e) { alert(e.message); }
}

// inner drag: display and submission are both PickCoords outputs.
// Submission uses frac (0..1 of the preview) — resolution-independent, the
// server converts to viewport pixels.
vpDrag = PickCoords.drag($("vpImg"), {
  onMove(rect) { PickCoords.drawOverlay($("innerBox"), $("vpImg"), rect.css); },
  onCommit(rect) {
    postGeometry("inner", {
      fx: rect.frac.x, fy: rect.frac.y, fw: rect.frac.w, fh: rect.frac.h });
  },
  onCancel() { $("innerBox").style.display = "none"; },
});

// ---- joystick micro-offset ---------------------------------------------
// Hold a direction: nudge every 100ms (0.1° per step). Server owns wrap/clamp;
// meta text updates live from each response; previews refresh once on release.
let joyTimer = null;

async function nudgeOnce(dy, dp) {
  if (!SEL) return null;
  try {
    return await api(`/api/case/${SEL}/nudge`, { dyaw: dy, dpitch: dp });
  } catch { return null; }
}

function updateJoystickMeta(r) {
  if (!r) return;
  $("vpMeta").textContent =
    `yaw ${r.yaw}  pitch ${r.pitch}  （预览松手后刷新）`;
}

document.querySelectorAll(".jb").forEach((btn) => {
  const dy = parseFloat(btn.dataset.dy), dp = parseFloat(btn.dataset.dp);
  // arm/disarm the interval SYNCHRONOUSLY: awaiting the first nudge response
  // before arming left a window where mouseup's stop() ran too early and the
  // interval leaked (yaw/pitch drifting forever after a single click)
  const start = (e) => {
    if (!SEL || joyTimer) return;
    e.preventDefault();
    joyTimer = setInterval(() => nudgeOnce(dy, dp).then(updateJoystickMeta), 100);
    nudgeOnce(dy, dp).then(updateJoystickMeta);
  };
  const stop = () => {
    if (!joyTimer) return;
    clearInterval(joyTimer);
    joyTimer = null;
    if (SEL) refreshCase();          // re-render previews once on release
  };
  btn.addEventListener("mousedown", start);
  btn.addEventListener("mouseup", stop);
  btn.addEventListener("mouseleave", stop);
  btn.addEventListener("touchstart", start, { passive: false });
  btn.addEventListener("touchend", stop);
});

// ---- pipeline ----------------------------------------------------------

async function runExtract() {
  if (!SEL) return;
  await api(`/api/case/${SEL}/extract`, {});
  pollTask();
}

async function runMerge() {
  if (!SEL) return;
  try {
    await api(`/api/case/${SEL}/merge`, { version: $("verSel").value });
    pollTask();
  } catch (e) { alert(e.message); }
}

async function pollTask() {
  const t = await api("/api/task");
  let txt = "";
  if (t.current) {
    txt += `▶ ${t.current.kind} · ${t.current.case} · ${t.current.state}\n`;
    txt += (t.current.tail || []).join("\n");
  } else {
    txt = "（空闲）";
  }
  for (const q of t.queued) txt += `\n… 排队：${q.kind} · ${q.case}`;
  for (const l of t.last) txt += `\n${l.state === "done" ? "✓" : "✗"} ${l.kind} · ${l.case}`;
  $("taskBox").textContent = txt;
  // a finished task may have produced new files → refresh pipeline badges
  if (SEL && !t.current && !joyTimer) refreshCase();
}

// ---- AI clip path browser ----------------------------------------------

let bDir = null;

async function openBrowse() {
  $("browseBox").style.display = "block";
  await browseDir(null);
}

function closeBrowse() { $("browseBox").style.display = "none"; }

async function browseDir(path) {
  const j = await api("/api/browse" + (path ? "?path=" + encodeURIComponent(path) : ""));
  bDir = j.path;
  $("bPath").textContent = j.path;
  const list = $("bList");
  list.innerHTML = "";
  if (j.parent) {
    const d = document.createElement("div");
    d.className = "bitem"; d.textContent = "📁 ..";
    d.onclick = () => browseDir(j.parent);
    list.appendChild(d);
  }
  for (const dname of j.dirs) {
    const d = document.createElement("div");
    d.className = "bitem"; d.textContent = "📁 " + dname;
    d.onclick = () => browseDir(bDir + "\\" + dname);
    list.appendChild(d);
  }
  for (const f of j.files) {
    const d = document.createElement("div");
    d.className = "bitem"; d.textContent = "🎬 " + f;
    d.onclick = async () => {
      await api(`/api/case/${SEL}/ai-clip`, { path: f, version: $("verSel").value });
      closeBrowse();
      await refreshCase();
    };
    list.appendChild(d);
  }
}

// ---- boot ---------------------------------------------------------------

refreshCases(); refreshSources(); refreshCase();
setInterval(refreshCases, 4000);
setInterval(pollTask, 1200);
