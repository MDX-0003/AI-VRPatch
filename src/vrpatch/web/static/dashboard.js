// vrpatch dashboard: vanilla JS, polling only, zero npm.
// All display and submitted coords derive from one mapping per image
// (getBoundingClientRect), per the js-drag-overlay-coords rule.
"use strict";
let SEL = null;          // selected case name
let drag = null;

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

async function selectCase(name) {
  SEL = name;
  await refreshCase();
  await refreshCases();
}

async function refreshCase() {
  if (!SEL) return;
  const c = await api("/api/case/" + SEL);
  $("caseName").textContent = c.name;
  $("erpImg").src = c.previews.erp + "&t=" + Date.now();
  $("vpImg").src = c.previews.vp + "&t=" + Date.now();
  $("vpMeta").textContent = `yaw ${c.viewport.yaw}  pitch ${c.viewport.pitch}  fov ${c.viewport.fov}  窗口 ${c.viewport.size}`;
  $("inMeta").textContent = `inner ${c.inner.x},${c.inner.y},${c.inner.w},${c.inner.h}`;
  $("exSt").textContent = c.extracted ? "✓ 已生成 clip.mp4 + 掩膜" : "";
  $("aiSt").textContent = c.ai_clip ? (c.ai_clip_exists ? "✓ " + c.ai_clip : "✗ 文件不存在：" + c.ai_clip) : "";
  $("mgSt").textContent = c.merged ? "✓ derived/ 下已有 out 产物" : "";
  $("stExtract").className = "step on";
  $("stAi").className = "step" + (c.extracted ? " on" : "");
  $("stMerge").className = "step" + (c.ai_clip_exists ? " on" : "");
  $("btnMerge").disabled = !c.ai_clip_exists;
}

async function erpClick(ev) {
  if (!SEL) return;
  const r = ev.target.getBoundingClientRect();
  await postGeometry("viewport", { fx: (ev.clientX - r.left) / r.width,
                                   fy: (ev.clientY - r.top) / r.height });
}

// inner drag: display and submit share one pt() mapping
function pt(ev) {
  const img = $("vpImg"), r = img.getBoundingClientRect();
  return { rx: ev.clientX - r.left, ry: ev.clientY - r.top,
           x: (ev.clientX - r.left) / r.width * img.naturalWidth,
           y: (ev.clientY - r.top) / r.height * img.naturalHeight };
}

async function postGeometry(kind, body) {
  try {
    await api(`/api/case/${SEL}/${kind}`, body);
    await refreshCase();
  } catch (e) { alert(e.message); }
}

$("vpImg").addEventListener("mousedown", (e) => {
  if (!SEL) return;
  drag = { a: pt(e) };
  $("innerBox").style.display = "block";
  e.preventDefault();
});
$("vpImg").addEventListener("mousemove", (e) => {
  if (!drag) return;
  const b = pt(e);
  const s = $("innerBox");
  s.style.left = Math.min(drag.a.rx, b.rx) + "px";
  s.style.top = Math.min(drag.a.ry, b.ry) + "px";
  s.style.width = Math.abs(b.rx - drag.a.rx) + "px";
  s.style.height = Math.abs(b.ry - drag.a.ry) + "px";
});
window.addEventListener("mouseup", (e) => {
  if (!drag) return;
  const b = pt(e);
  const w = Math.abs(b.x - drag.a.x), h = Math.abs(b.y - drag.a.y);
  if (w > 2 && h > 2) {
    postGeometry("inner", { x: Math.round(Math.min(drag.a.x, b.x)),
                            y: Math.round(Math.min(drag.a.y, b.y)),
                            w: Math.round(w), h: Math.round(h) });
  } else {
    $("innerBox").style.display = "none";
  }
  drag = null;
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
    await api(`/api/case/${SEL}/merge`, {});
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
  if (SEL && !t.current) refreshCase();
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
      await api(`/api/case/${SEL}/ai-clip`, { path: f });
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
