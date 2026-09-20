// vrpatch dashboard: vanilla JS, polling only, zero npm.
// ALL picking coordinates go through PickCoords (pick.js) — display and
// submission share one mapping, so style changes cannot desync them.
"use strict";
let SEL = null;                 // selected case name
let vpDrag = null;              // PickCoords drag controller for the viewport

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
  if (vpDrag) vpDrag.cancel();      // never leave a drag in flight across cases
  SEL = name;
  await refreshCase();
  await refreshCases();
}

async function refreshCase() {
  if (!SEL || (vpDrag && vpDrag.active)) return;   // no image swaps mid-drag
  if (!SEL) return;
  const c = await api("/api/case/" + SEL);
  $("caseName").textContent = c.name;
  $("erpImg").src = c.previews.erp + "&t=" + Date.now();
  $("vpImg").src = c.previews.vp + "&t=" + Date.now();
  $("vpMeta").textContent = `yaw ${c.viewport.yaw}  pitch ${c.viewport.pitch}  fov ${c.viewport.fov}  窗口 ${c.viewport.size}`;
  $("inMeta").textContent = `inner ${c.inner.x},${c.inner.y},${c.inner.w},${c.inner.h}`;
  $("exSt").textContent = c.extracted ? "✓ 已生成 clip.mp4 + 掩膜" : "";
  const verSel = $("verSel");
  verSel.innerHTML = "";
  for (const v of [...c.versions].reverse()) {
    const o = document.createElement("option");
    o.value = v.version;
    const ai = v.ai_clip_exists ? "✓AI" : "无AI";
    o.textContent = `${v.version}（${ai}）`;
    verSel.appendChild(o);
  }
  // keep the user's selection if the version still exists, else latest
  if (![...verSel.options].some(o => o.value === verSel.value) && verSel.options.length)
    verSel.value = c.versions[c.versions.length - 1].version;
  updatePipeline(c);
  $("innerBox").style.display = "none";            // committed: hide the live box
}

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
  const p = PickCoords.point($("erpImg"), ev);
  if (!p) return;                    // preview not loaded yet: ignore click
  await postGeometry("viewport", { fx: p.frac.x, fy: p.frac.y });
}

async function postGeometry(kind, body) {
  try {
    await api(`/api/case/${SEL}/${kind}`, body);
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
