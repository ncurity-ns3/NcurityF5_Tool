const COLOR = {
  1: "#67b246",
  2: "#d45b5b",
  3: "#e0c14a",
  4: "#e08a4a",
  5: "#4a90d9",
  6: "#8a6bb0",
  7: "#3aa0a0",
  8: "#c76b9a",
  16: "#8a6bb0",
};

let MODEL = null;
let SELECTED = null;
let SELECTED_PROFILE = null;
const GRAPHS = {};
const SCROLL_BY_POLICY = {};
let ZOOM = 1;
let BASE_SIZE = { w: 800, h: 400 };
const ZOOM_MIN = 0.25;
const ZOOM_MAX = 2.5;
let zoomHudTimer = 0;

const svg = document.getElementById("canvas");
const macroStack = document.getElementById("macro-stack");
const canvasScene = document.getElementById("canvas-scene");
const canvasScaler = document.getElementById("canvas-scaler");
const profileList = document.getElementById("profile-list");
const statusEl = document.getElementById("status");
const filterEl = document.getElementById("filter");
const sourceLabel = document.getElementById("source-label");
const detail = document.getElementById("detail");
const detailBody = document.getElementById("detail-body");

const dropzone = document.getElementById("dropzone");
const canvasWrap = document.getElementById("canvas-wrap");

document.getElementById("file").addEventListener("change", (ev) => {
  const file = ev.target.files[0];
  if (file) uploadFile(file);
  ev.target.value = "";
});

function keepDrop(e) {
  e.preventDefault();
  e.stopPropagation();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
}

["dragenter", "dragover", "dragleave"].forEach((evt) => {
  window.addEventListener(evt, keepDrop);
});
window.addEventListener("drop", (e) => {
  keepDrop(e);
  const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (file) uploadFile(file);
});

function setProgress(widthPct, text, pulsing) {
  const bar = document.getElementById("bar");
  const label = document.getElementById("progress-label");
  if (bar) {
    bar.classList.toggle("pulse", !!pulsing);
    if (!pulsing && widthPct != null) bar.style.width = widthPct + "%";
  }
  if (label) label.textContent = text;
  statusEl.textContent = text;
}

function uploadErrorFromXhr(xhr, parsed) {
  if (parsed && parsed.error) return parsed.error;
  if (xhr.status === 413) return "파일이 너무 큽니다. 16GB 이하 qkview/UCS를 올려 주세요.";
  if (!xhr.responseText) return `서버가 빈 응답을 보냈습니다. (HTTP ${xhr.status || 0})`;
  return "서버 응답을 해석하지 못했습니다.";
}

function resetViewerForLoad() {
  Object.keys(SCROLL_BY_POLICY).forEach((key) => delete SCROLL_BY_POLICY[key]);
  Object.keys(GRAPHS).forEach((key) => delete GRAPHS[key]);
  SELECTED = null;
  SELECTED_PROFILE = null;
  ZOOM = 1;
  if (canvasWrap) {
    canvasWrap.scrollLeft = 0;
    canvasWrap.scrollTop = 0;
  }
  if (svg) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
  }
  if (macroStack) {
    macroStack.innerHTML = "";
    macroStack.classList.remove("has-macros");
  }
  hideDetail();
  applyZoom();
}

function uploadFile(file) {
  resetViewerForLoad();
  statusEl.textContent = `${file.name} 업로드 중…`;
  dropzone.classList.remove("hidden");
  dropzone.innerHTML = `<strong>${escapeHtml(file.name)}</strong><span id="progress-label">파일을 준비하는 중…</span><div class="progress"><i id="bar"></i></div>`;
  const body = new FormData();
  body.append("file", file);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload");
  xhr.timeout = 0;
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) {
      setProgress(null, `${file.name} 업로드 중…`, true);
      return;
    }
    const pct = Math.round((e.loaded / e.total) * 100);
    setProgress(pct, `업로드 ${pct}% (${file.name})`, false);
  };
  xhr.upload.onload = () => {
    setProgress(100, "업로드 완료. UCS/qkview에서 설정을 추출하고 분석하는 중…", true);
  };
  xhr.onload = async () => {
    let data = {};
    try {
      data = JSON.parse(xhr.responseText || "{}");
    } catch (err) {
      data = { error: uploadErrorFromXhr(xhr, null) };
    }
    if (xhr.status >= 400) {
      statusEl.textContent = uploadErrorFromXhr(xhr, data);
      resetDropzone();
      return;
    }
    setProgress(100, `분석 완료. 흐름도를 그리는 중… (${(data.files || []).join(", ") || file.name})`, true);
    await loadModel();
  };
  xhr.onerror = () => {
    statusEl.textContent = "업로드 네트워크 오류";
    resetDropzone();
  };
  xhr.ontimeout = () => {
    statusEl.textContent = "업로드 시간이 초과되었습니다.";
    resetDropzone();
  };
  xhr.send(body);
}

function resetDropzone() {
  dropzone.classList.remove("hidden");
  dropzone.innerHTML = "<strong>qkview 파일을 여기에 놓으세요</strong><span>또는 위 버튼으로 .qkview / .ucs / bigip.conf 선택</span>";
}

filterEl.addEventListener("input", () => renderLists());
document.getElementById("detail-close").addEventListener("click", () => {
  hideDetail();
});
document.getElementById("upload-form").addEventListener("submit", (e) => e.preventDefault());

function graphByName(name) {
  if (!name) return null;
  if (GRAPHS[name]) return GRAPHS[name];
  return (MODEL && MODEL.policies ? MODEL.policies.find((p) => p.name === name) : null) || null;
}

function rememberPolicies(policies) {
  (policies || []).forEach((policy) => {
    if (!policy || !policy.name) return;
    const idx = (MODEL.policies || []).findIndex((item) => item.name === policy.name);
    if (idx >= 0) MODEL.policies[idx] = policy;
    else (MODEL.policies ||= []).push(policy);
    if (Array.isArray(policy.nodes)) GRAPHS[policy.name] = policy;
  });
}

function ensureGraphs(name) {
  if (!name) return null;
  if (GRAPHS[name] && Array.isArray(GRAPHS[name].nodes)) return GRAPHS[name];
  const fromModel = (MODEL && MODEL.policies ? MODEL.policies.find((p) => p.name === name) : null) || null;
  if (fromModel && Array.isArray(fromModel.nodes)) {
    GRAPHS[name] = fromModel;
    return fromModel;
  }
  return fromModel;
}

async function fetchPolicyBundle(name) {
  const res = await fetch(`/api/policy?name=${encodeURIComponent(name)}`);
  if (!res.ok) return null;
  const data = await res.json();
  MODEL.objects = Object.assign(MODEL.objects || {}, data.objects || {});
  rememberPolicies(data.policies || []);
  return GRAPHS[name] || null;
}

async function prefetchGraphs() {
  try {
    const res = await fetch("/api/graphs");
    if (!res.ok) return;
    const data = await res.json();
    MODEL.objects = Object.assign(MODEL.objects || {}, data.objects || {});
    rememberPolicies(data.policies || []);
  } catch (_err) {
    /* first policy is already on screen */
  }
}

async function loadModel() {
  const res = await fetch("/api/model");
  if (!res.ok) {
    statusEl.textContent = "qkview를 올리면 Access Policy 흐름도가 생성됩니다.";
    resetDropzone();
    return;
  }
  MODEL = await res.json();
  Object.keys(SCROLL_BY_POLICY).forEach((key) => delete SCROLL_BY_POLICY[key]);
  Object.keys(GRAPHS).forEach((key) => delete GRAPHS[key]);
  rememberPolicies(MODEL.policies || []);
  SELECTED = null;
  SELECTED_PROFILE = null;
  ZOOM = 1;
  if (canvasWrap) {
    canvasWrap.scrollLeft = 0;
    canvasWrap.scrollTop = 0;
  }
  sourceLabel.textContent = MODEL.source || "";
  const s = MODEL.summary;
  const files = (MODEL.extracted_files || []).join(", ");
  statusEl.textContent = `${MODEL.source || ""} · ${files ? files + " · " : ""}프로필 ${s.profiles} · 정책 ${s.policies} · 매크로 ${s.macros} · 아이템 ${s.items}`;
  renderLists();
  const withVs = (MODEL.profiles || []).find((p) => (p.virtuals || []).length);
  const first = MODEL.preferred_policy
    || withVs?.access_policy
    || withVs?.name
    || (MODEL.policies || []).find((p) => p.name && p.name.endsWith("/AP_CSH_Modern") && p.type !== "macro")?.name
    || (MODEL.policies || []).find((p) => p.type !== "macro")?.name;
  if (first) await selectPolicy(first);
  dropzone.classList.add("hidden");
  prefetchGraphs();
}

function uniqueByName(items, keyFn) {
  const seen = new Set();
  return items.filter((item) => {
    const key = keyFn(item);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function renderLists() {
  if (!MODEL) return;
  const q = filterEl.value.trim().toLowerCase();
  const profiles = uniqueByName(MODEL.profiles || [], (p) => p.name || p.access_policy);
  const allPolicies = uniqueByName(MODEL.policies || [], (p) => p.name);

  profileList.innerHTML = "";
  profiles
    .filter((p) => !q || p.name.toLowerCase().includes(q) || (p.access_policy || "").toLowerCase().includes(q))
    .forEach((p) => {
      const li = document.createElement("li");
      if (isSelectedProfile(p)) li.classList.add("active");
      li.innerHTML = `${escapeHtml(profileListLabel(p))}<span class="meta">${escapeHtml(p.access_policy || "")}</span>`;
      li.addEventListener("click", () => {
        const sel = window.getSelection && window.getSelection();
        if (sel && String(sel) && li.contains(sel.anchorNode)) return;
        selectPolicy(p.access_policy || p.name);
      });
      profileList.appendChild(li);
    });

  if (!profiles.length) {
    allPolicies
      .filter((p) => p.type !== "macro")
      .filter((p) => !q || p.name.toLowerCase().includes(q) || p.caption.toLowerCase().includes(q))
      .forEach((p) => {
        const li = document.createElement("li");
        if (SELECTED === p.name) li.classList.add("active");
        li.textContent = p.caption;
        li.addEventListener("click", () => {
          const sel = window.getSelection && window.getSelection();
          if (sel && String(sel) && li.contains(sel.anchorNode)) return;
          selectPolicy(p.name);
        });
        profileList.appendChild(li);
      });
  }
}

function lastPathSegment(value) {
  return String(value || "").split("/").filter(Boolean).pop() || "";
}

function profileListLabel(profile) {
  return lastPathSegment(profile.name) || lastPathSegment(profile.access_policy);
}

function isSelectedProfile(profile) {
  const keys = [SELECTED_PROFILE, SELECTED].filter(Boolean);
  return keys.some((key) => (
    key === profile.access_policy
    || key === profile.name
    || lastPathSegment(key) === lastPathSegment(profile.access_policy)
    || lastPathSegment(key) === lastPathSegment(profile.name)
  ));
}

async function selectPolicy(name) {
  saveCanvasScroll();
  SELECTED = name;
  const stub = (MODEL.policies || []).find((p) => p.name === name);
  if (stub && stub.type !== "macro") SELECTED_PROFILE = name;
  renderLists();
  let policy = ensureGraphs(name);
  if (!policy || !Array.isArray(policy.nodes)) policy = await fetchPolicyBundle(name);
  if (!policy || !Array.isArray(policy.nodes)) {
    statusEl.textContent = `정책을 찾을 수 없습니다: ${name}`;
    return;
  }
  if (canvasWrap && !SCROLL_BY_POLICY[name]) {
    canvasWrap.scrollLeft = 0;
    canvasWrap.scrollTop = 0;
  }
  draw(policy, collectMacros(policy));
  restoreCanvasScroll();
  showPolicyOverview(policy);
}

function saveCanvasScroll() {
  if (!canvasWrap || !SELECTED) return;
  SCROLL_BY_POLICY[SELECTED] = { left: canvasWrap.scrollLeft, top: canvasWrap.scrollTop, zoom: ZOOM };
}

function restoreCanvasScroll() {
  if (!canvasWrap) return;
  const pos = (SELECTED && SCROLL_BY_POLICY[SELECTED]) || { left: 0, top: 0, zoom: 1 };
  ZOOM = pos.zoom || 1;
  applyZoom();
  canvasWrap.scrollLeft = pos.left;
  canvasWrap.scrollTop = pos.top;
  requestAnimationFrame(() => {
    canvasWrap.scrollLeft = pos.left;
    canvasWrap.scrollTop = pos.top;
  });
}

function clampZoom(value) {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, value));
}

function measureContent() {
  let w = BASE_SIZE.w;
  let h = BASE_SIZE.h;
  if (macroStack && macroStack.classList.contains("has-macros")) {
    macroStack.querySelectorAll(".macro-block.open svg").forEach((el) => {
      w = Math.max(w, Number(el.getAttribute("width")) || 0);
    });
    h += macroStack.offsetHeight || 0;
  }
  return { w: Math.max(1, w), h: Math.max(1, h) };
}

function viewportSize() {
  if (!canvasWrap) return { w: 1, h: 1 };
  return {
    w: Math.max(1, canvasWrap.clientWidth || 1),
    h: Math.max(1, canvasWrap.clientHeight || 1),
  };
}

function applyZoom() {
  if (!svg) return;
  svg.setAttribute("width", String(BASE_SIZE.w));
  svg.setAttribute("height", String(BASE_SIZE.h));
  const content = measureContent();
  const view = viewportSize();
  const sceneW = Math.max(content.w, view.w / ZOOM);
  const sceneH = Math.max(content.h, view.h / ZOOM);
  if (canvasScene) {
    canvasScene.style.width = `${sceneW}px`;
    canvasScene.style.height = `${sceneH}px`;
    canvasScene.style.transform = `scale(${ZOOM})`;
  }
  if (canvasScaler) {
    canvasScaler.style.width = `${sceneW * ZOOM}px`;
    canvasScaler.style.height = `${sceneH * ZOOM}px`;
  }
  const pct = document.getElementById("zoom-pct");
  if (pct) pct.textContent = `${Math.round(ZOOM * 100)}%`;
}

function scheduleFit() {
  requestAnimationFrame(() => applyZoom());
}

function showZoomHud() {
  const hud = document.getElementById("zoom-hud");
  if (!hud) return;
  hud.classList.add("visible");
  hud.setAttribute("aria-hidden", "false");
  clearTimeout(zoomHudTimer);
  zoomHudTimer = window.setTimeout(() => {
    if (hud.matches(":hover")) return;
    hud.classList.remove("visible");
    hud.setAttribute("aria-hidden", "true");
  }, 2500);
}

function setZoom(next, clientX, clientY, showHud) {
  const prev = ZOOM;
  ZOOM = clampZoom(next);
  const rect = canvasWrap.getBoundingClientRect();
  const cx = clientX == null ? rect.left + rect.width / 2 : clientX;
  const cy = clientY == null ? rect.top + rect.height / 2 : clientY;
  const sx = canvasWrap.scrollLeft + (cx - rect.left);
  const sy = canvasWrap.scrollTop + (cy - rect.top);
  applyZoom();
  if (ZOOM !== prev) {
    const factor = ZOOM / prev;
    canvasWrap.scrollLeft = sx * factor - (cx - rect.left);
    canvasWrap.scrollTop = sy * factor - (cy - rect.top);
  }
  if (showHud !== false) showZoomHud();
}

function zoomBy(factor, clientX, clientY) {
  setZoom(ZOOM * factor, clientX, clientY);
}

function zoomFit() {
  if (!canvasWrap) return;
  const rect = canvasWrap.getBoundingClientRect();
  if (BASE_SIZE.w < 1 || BASE_SIZE.h < 1) return;
  const next = Math.min(rect.width / BASE_SIZE.w, rect.height / BASE_SIZE.h) * 0.96;
  setZoom(next);
  canvasWrap.scrollLeft = 0;
  canvasWrap.scrollTop = 0;
}

function initZoom() {
  const hud = document.getElementById("zoom-hud");
  const zoomIn = document.getElementById("zoom-in");
  const zoomOut = document.getElementById("zoom-out");
  const zoomReset = document.getElementById("zoom-reset");
  if (zoomIn) zoomIn.addEventListener("click", () => zoomBy(1.2));
  if (zoomOut) zoomOut.addEventListener("click", () => zoomBy(1 / 1.2));
  if (zoomReset) zoomReset.addEventListener("click", () => setZoom(1));
  if (hud) {
    hud.addEventListener("mouseenter", () => clearTimeout(zoomHudTimer));
    hud.addEventListener("mouseleave", () => showZoomHud());
  }
  const onCtrlWheel = (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    const main = document.querySelector(".main");
    if (main && !main.contains(event.target) && event.target !== hud && !hud?.contains(event.target)) return;
    event.preventDefault();
    event.stopPropagation();
    zoomBy(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX, event.clientY);
  };
  window.addEventListener("wheel", onCtrlWheel, { passive: false, capture: true });
  canvasWrap.addEventListener("wheel", onCtrlWheel, { passive: false });
  window.addEventListener("keydown", (event) => {
    if (event.target && /^(INPUT|TEXTAREA)$/.test(event.target.tagName)) return;
    if ((event.ctrlKey || event.metaKey) && (event.key === "+" || event.key === "=")) {
      event.preventDefault();
      zoomBy(1.2);
    } else if ((event.ctrlKey || event.metaKey) && (event.key === "-" || event.key === "_")) {
      event.preventDefault();
      zoomBy(1 / 1.2);
    } else if ((event.ctrlKey || event.metaKey) && event.key === "0") {
      event.preventDefault();
      setZoom(1);
    }
  });
}

function collectMacroNames(policy, seen) {
  const names = [];
  (policy.macros || []).forEach((n) => names.push(n));
  (policy.nodes || []).forEach((n) => {
    if (n.macro) names.push(n.macro);
  });
  names.forEach((name) => {
    if (!name || seen.has(name)) return;
    seen.add(name);
    const nested = graphByName(name);
    if (nested) collectMacroNames(nested, seen);
  });
  return seen;
}

function collectMacros(policy) {
  return Array.from(collectMacroNames(policy, new Set()))
    .map((n) => graphByName(n))
    .filter(Boolean);
}

function addGraphDefs(target, prefix) {
  const defs = svgEl("defs", {});
  const markerId = `${prefix}-arrow`;
  const hatchId = `${prefix}-hatch`;
  const marker = svgEl("marker", {
    id: markerId,
    viewBox: "0 0 10 10",
    refX: 9,
    refY: 5,
    markerWidth: 7,
    markerHeight: 7,
    orient: "auto-start-reverse",
  });
  marker.appendChild(svgEl("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: "#6a7684" }));
  defs.appendChild(marker);
  const hatch = svgEl("pattern", {
    id: hatchId,
    width: "8",
    height: "8",
    patternUnits: "userSpaceOnUse",
  });
  hatch.appendChild(svgEl("rect", { width: "8", height: "8", fill: "#ffffff" }));
  hatch.appendChild(
    svgEl("path", {
      d: "M -2 6 L 6 -2 M 0 10 L 10 0 M 2 14 L 14 2",
      stroke: "#c9d2da",
      "stroke-width": "1.15",
    })
  );
  defs.appendChild(hatch);
  target.appendChild(defs);
  return { markerId, hatchId };
}

function paintGraph(target, graph, markerId, hatchId, opts) {
  const laid = layoutGraph(graph);
  const top = opts && opts.top != null ? opts.top : 28;
  const inner = svgEl("g", { transform: `translate(24, ${top})` });
  const nodeLayer = svgEl("g", { class: "node-layer" });
  const edgeLayer = svgEl("g", { class: "edge-layer" });
  laid.nodes.forEach((n) => nodeLayer.appendChild(drawNode(n, graph, hatchId)));
  laid.edges.forEach((e) => edgeLayer.appendChild(drawEdge(e, markerId)));
  inner.appendChild(nodeLayer);
  inner.appendChild(edgeLayer);
  target.appendChild(inner);
  return { width: laid.width + 80, height: laid.height + top + 20 };
}

function drawMacroStack(macros) {
  if (!macroStack) return;
  macroStack.innerHTML = "";
  if (!macros.length) {
    macroStack.classList.remove("has-macros");
    return;
  }
  macroStack.classList.add("has-macros");
  const split = document.createElement("div");
  split.className = "macro-split";
  split.setAttribute("aria-hidden", "true");
  macroStack.appendChild(split);
  macros.forEach((macro) => {
    const block = document.createElement("div");
    block.className = "macro-block";
    block.dataset.macroId = macro.name;
    const bar = document.createElement("button");
    bar.type = "button";
    bar.className = "macro-bar";
    bar.innerHTML = `<span class="macro-twist">▸</span><span>Macro: ${escapeHtml(macro.caption)}</span>`;
    const body = document.createElement("div");
    body.className = "macro-body";
    body.appendChild(svgEl("svg", { class: "macro-svg" }));
    bar.addEventListener("click", () => toggleMacroBlock(block));
    block.appendChild(bar);
    block.appendChild(body);
    macroStack.appendChild(block);
  });
}

function ensureMacroDrawn(block) {
  const macro = graphByName(block.dataset.macroId);
  if (!macro) return;
  const macroSvg = block.querySelector("svg");
  if (!macroSvg || macroSvg.childNodes.length) return;
  const prefix = `m${String(macro.name).replace(/[^a-zA-Z0-9_-]/g, "_")}`;
  const ids = addGraphDefs(macroSvg, prefix);
  const size = paintGraph(macroSvg, macro, ids.markerId, ids.hatchId, { top: 16 });
  macroSvg.setAttribute("width", String(size.width));
  macroSvg.setAttribute("height", String(size.height));
}

function toggleMacroBlock(block, forceOpen) {
  const open = forceOpen === true ? true : !block.classList.contains("open");
  block.classList.toggle("open", open);
  if (open) ensureMacroDrawn(block);
  applyZoom();
}

function openMacroAndScroll(macroName) {
  if (!macroName || !macroStack) return false;
  const want = String(macroName);
  const block = [...macroStack.querySelectorAll(".macro-block")].find((el) => {
    const id = el.dataset.macroId || "";
    return id === want || id.endsWith(`/${lastPathSegment(want)}`) || lastPathSegment(id) === lastPathSegment(want);
  });
  if (!block) return false;
  toggleMacroBlock(block, true);
  block.classList.add("flash");
  window.setTimeout(() => block.classList.remove("flash"), 1400);
  requestAnimationFrame(() => {
    const wrapRect = canvasWrap.getBoundingClientRect();
    const blockRect = block.getBoundingClientRect();
    canvasWrap.scrollTo({
      top: canvasWrap.scrollTop + (blockRect.top - wrapRect.top) - 8,
      behavior: "smooth",
    });
  });
  return true;
}

function draw(policy, macros) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const ids = addGraphDefs(svg, "main");
  const title = svgEl("text", { x: "24", y: "22", fill: "#0260EA", "font-size": "16", "font-weight": "700" });
  title.textContent = policy.caption + (policy.type === "macro" ? "  (Macro)" : "");
  svg.appendChild(title);
  const size = paintGraph(svg, policy, ids.markerId, ids.hatchId);
  BASE_SIZE = { w: Math.max(1, size.width), h: Math.max(1, size.height) };
  svg.setAttribute("width", String(BASE_SIZE.w));
  svg.setAttribute("height", String(BASE_SIZE.h));
  drawMacroStack(policy.type === "macro" ? macros.filter((m) => m.name !== policy.name) : macros);
  applyZoom();
}

function charWidth(ch, fontSize) {
  if (ch === " ") return fontSize * 0.32;
  if (/[\u1100-\uD7AF\u3000-\u9FFF]/.test(ch)) return fontSize * 0.95;
  return fontSize * 0.58;
}

function wrapLines(text, maxWidth, fontSize) {
  const raw = String(text || "").trim();
  if (!raw) return [""];
  const parts = raw.split(/([_\-\/\s])/);
  const lines = [];
  let current = "";
  let width = 0;
  const measure = (s) => [...s].reduce((sum, ch) => sum + charWidth(ch, fontSize), 0);
  const flush = () => {
    const trimmed = current.replace(/\s+$/, "");
    if (trimmed) lines.push(trimmed);
    current = "";
    width = 0;
  };
  parts.forEach((token) => {
    if (!token) return;
    const tw = measure(token);
    if (current && width + tw > maxWidth) flush();
    if (tw <= maxWidth) {
      current += token;
      width += tw;
      return;
    }
    [...token].forEach((ch) => {
      const cw = charWidth(ch, fontSize);
      if (current && width + cw > maxWidth) flush();
      current += ch;
      width += cw;
    });
  });
  flush();
  return lines.length ? lines : [raw];
}

function wrapLabel(cx, cy, maxWidth, value, fill, size, weight, maxLines) {
  const lines = wrapLines(value, maxWidth, size).slice(0, maxLines || 4);
  const lh = size + 4;
  const blockH = lines.length * lh;
  const g = svgEl("g", {});
  lines.forEach((line, i) => {
    const y = cy - blockH / 2 + lh / 2 + i * lh;
    const t = svgEl("text", {
      x: String(cx),
      y: String(y),
      fill,
      "font-size": String(size),
      "text-anchor": "middle",
      "dominant-baseline": "middle",
      "alignment-baseline": "middle",
      "font-weight": String(weight || 600),
    });
    t.textContent = line;
    g.appendChild(t);
  });
  return g;
}

function drawNode(n, graph, hatchId) {
  const x = n.x - n.width / 2;
  const y = n.y - n.height / 2;
  const wrap = svgEl("g", { class: "vpe-node", transform: `translate(${x}, ${y})`, style: "cursor:pointer" });
  wrap.addEventListener("click", () => {
    if (n.kind === "macro") openMacroAndScroll(n.macro || n.id);
    showDetail(n, graph);
  });
  const color = COLOR[n.color] || COLOR[1];
  const cx = n.width / 2;
  const cy = n.height / 2;
  if (n.kind === "start" || n.kind === "entry") {
    wrap.appendChild(svgEl("rect", { width: n.width, height: n.height, rx: 14, ry: 14, fill: color, stroke: "#3d7a2c" }));
    wrap.appendChild(wrapLabel(cx, cy, n.width - 12, n.caption, "#fff", 11, 700, 2));
    return wrap;
  }
  if (n.kind.startsWith("ending") || n.kind === "terminal") {
    wrap.appendChild(svgEl("rect", { width: n.width, height: n.height, rx: 8, ry: 8, fill: color, stroke: "#3335", "stroke-width": 0.6 }));
    wrap.appendChild(wrapLabel(cx, cy, n.width - 10, n.caption, "#fff", 11, 700, 2));
    return wrap;
  }
  if (n.kind === "macro") {
    wrap.classList.add("vpe-macro");
    wrap.appendChild(svgEl("rect", { width: n.width, height: n.height, fill: "#fff", stroke: "#4b5d6e", "stroke-width": 1.4 }));
    const inset = Math.max(4, Math.min(7, n.width * 0.06));
    wrap.appendChild(
      svgEl("rect", {
        x: String(inset),
        y: String(inset),
        width: n.width - inset * 2,
        height: n.height - inset * 2,
        fill: hatchId ? `url(#${hatchId})` : "#fff",
        stroke: "#4b5d6e",
        "stroke-width": 1.1,
      })
    );
    wrap.appendChild(wrapLabel(cx, cy, n.width - inset * 2 - 10, n.caption, "#1d2a38", 12, 700, 4));
    return wrap;
  }
  wrap.appendChild(
    svgEl("rect", {
      width: n.width,
      height: n.height,
      fill: "#fff",
      stroke: "#5c6b7a",
      "stroke-width": 1.2,
    })
  );
  wrap.appendChild(wrapLabel(cx, cy, n.width - 12, n.caption, "#1d2a38", 12, 700, 4));
  return wrap;
}

function drawEdge(e, markerId) {
  const pts = e.points || [];
  const d = pts.map((p, i) => `${i ? "L" : "M"} ${p.x} ${p.y}`).join(" ");
  const g = svgEl("g", { class: "edge-layer" });
  g.appendChild(svgEl("path", { d, class: "edge-halo" }));
  g.appendChild(svgEl("path", { d, class: "edge-path", "marker-end": `url(#${markerId || "arrow"})` }));
  if (e.caption && pts.length) {
    const pos = e.labelAt || { x: pts[0].x + 8, y: pts[0].y - 6, anchor: "start" };
    const label = svgEl("text", {
      x: String(pos.x),
      y: String(pos.y),
      class: "edge-label",
      "text-anchor": pos.anchor || "start",
      fill: "#1f3348",
      "font-size": "10",
      "font-weight": "700",
      stroke: "#f7f8fa",
      "stroke-width": "4",
      "paint-order": "stroke",
      "stroke-linejoin": "round",
    });
    label.textContent = e.caption;
    g.appendChild(label);
  }
  return g;
}

function hideDetail() {
  detail.classList.add("hidden");
  const handle = document.getElementById("detail-resizer");
  if (handle) handle.classList.add("hidden");
  scheduleFit();
}

function fieldLabel(key) {
  const labels = {
    agent_kind: "에이전트 종류",
    id: "이벤트",
    server: "서버",
    type: "종류",
    name: "이름",
    object_kind: "객체 종류",
    macro: "매크로",
    item_type: "아이템 종류",
    "max-logon-attempt": "최대 로그온 시도",
    "auth-type": "인증 방식",
    "start-uri": "시작 URI",
    "success-match-value": "성공 매칭",
    partition: "파티션",
  };
  return labels[key] || String(key).replace(/-/g, " ");
}

function isHiddenDetailKey(key) {
  return key === "_items" || key === "_value" || key === "name";
}

function formatDetailValue(value) {
  if (value === true) return "예";
  if (value === false || value == null || value === "") return "—";
  if (Array.isArray(value)) {
    return value.map((item) => (typeof item === "object" ? JSON.stringify(item) : String(item))).join(", ");
  }
  return String(value);
}

function renderFieldList(obj, skip) {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return "";
  const rows = Object.entries(obj)
    .filter(([key]) => !isHiddenDetailKey(key) && !(skip && skip.has(key)))
    .map(([key, value]) => {
      if (value && typeof value === "object" && !Array.isArray(value)) {
        const inner = renderFieldList(value);
        if (!inner) return "";
        return `<dt>${escapeHtml(fieldLabel(key))}</dt><dd><dl>${inner}</dl></dd>`;
      }
      return `<dt>${escapeHtml(fieldLabel(key))}</dt><dd>${escapeHtml(formatDetailValue(value))}</dd>`;
    })
    .filter(Boolean);
  return rows.join("");
}

function lookupObject(name) {
  if (!name || !MODEL) return null;
  const objects = MODEL.objects || {};
  if (objects[name]) return objects[name];
  const want = lastPathSegment(name);
  return Object.values(objects).find((obj) => lastPathSegment(obj.name) === want) || null;
}

function collectReferences(node) {
  const listed = [...(node.references || [])];
  const seen = new Set(listed.map((item) => item.name));
  const walk = (obj) => {
    if (!obj || typeof obj !== "object") return;
    if (Array.isArray(obj)) {
      obj.forEach(walk);
      return;
    }
    Object.entries(obj).forEach(([key, value]) => {
      if (typeof value === "string" && value.startsWith("/") && !seen.has(value)) {
        const resolved = lookupObject(value);
        if (resolved) {
          seen.add(value);
          listed.push({ key, name: value, object: resolved });
        }
      } else {
        walk(value);
      }
    });
  };
  walk(node.agent_details);
  return listed;
}

function renderNamedCard(title, fieldsHtml, extraHtml) {
  const fields = fieldsHtml ? `<dl>${fieldsHtml}</dl>` : "";
  return `<div class="ref-card"><h5>${escapeHtml(title)}</h5>${fields}${extraHtml || ""}</div>`;
}

function renderAgentCard(agent) {
  const title = lastPathSegment(agent.name || "") || agent.agent_kind || "에이전트";
  return renderNamedCard(title, renderFieldList(agent, new Set()));
}

function isLtmRuleRef(ref) {
  const obj = (ref && ref.object) || lookupObject(ref && ref.name) || {};
  return Boolean(ref && (ref.key === "ltm rule" || obj.object_kind === "ltm rule"));
}

function renderRefCard(ref) {
  const obj = ref.object || lookupObject(ref.name) || {};
  const title = lastPathSegment(ref.name || obj.name || "") || fieldLabel(ref.key);
  return renderNamedCard(title, renderFieldList(obj, new Set(["source"])));
}

function sameTmshName(left, right) {
  return Boolean(left && right && (left === right || lastPathSegment(left) === lastPathSegment(right)));
}

function activeTclSource(source) {
  return String(source || "")
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("#"))
    .join("\n");
}

function ruleHasAgentId(source, agentId) {
  const src = activeTclSource(source);
  const id = String(agentId || "");
  if (!id) return false;
  const escaped = id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`agent_id\\s*\\]\\s+(?:eq|ne|equals|==|!=)\\s+(?:"${escaped}"|${escaped}|\\{${escaped}\\})`).test(src)
    || new RegExp(`ACCESS::policy\\s+agent_id\\s+${escaped}\\b`).test(src)
    || new RegExp(`AGENT::event\\s+${escaped}\\b`).test(src);
}

function selectedAccessProfileNames() {
  const names = new Set();
  (MODEL.profiles || []).forEach((profile) => {
    if (!isSelectedProfile(profile)) return;
    if (profile.name) names.add(profile.name);
    if (profile.access_policy) names.add(profile.access_policy);
  });
  if (SELECTED_PROFILE) names.add(SELECTED_PROFILE);
  return names;
}

function addVirtual(listed, seen, vs) {
  if (!vs || !vs.name || seen.has(vs.name)) return;
  seen.add(vs.name);
  listed.push(vs);
}

function virtualsForDetail(graph) {
  const listed = selectedVirtuals();
  const seen = new Set(listed.map((vs) => vs.name));
  (graph && graph.virtuals ? graph.virtuals : []).forEach((vs) => addVirtual(listed, seen, vs));
  const parent = graphByName(SELECTED_PROFILE);
  (parent && parent.virtuals ? parent.virtuals : []).forEach((vs) => addVirtual(listed, seen, vs));
  return listed;
}

function rulesFromVirtuals(virtuals) {
  const byRule = new Map();
  (virtuals || []).forEach((vs) => {
    (vs.rules || []).forEach((ruleName) => {
      const entry = byRule.get(ruleName) || { name: ruleName, virtuals: [] };
      if (vs.name && !entry.virtuals.includes(vs.name)) entry.virtuals.push(vs.name);
      byRule.set(ruleName, entry);
    });
  });
  return [...byRule.values()];
}

function virtualRulesForSelectedProfile() {
  return rulesFromVirtuals(selectedVirtuals());
}

function lookupObjectRule(ruleName) {
  const objects = MODEL && MODEL.objects ? MODEL.objects : {};
  if (objects[ruleName]) return objects[ruleName];
  return Object.values(objects).find((obj) => obj && obj.object_kind === "ltm rule" && sameTmshName(obj.name, ruleName)) || null;
}

function selectedVirtuals() {
  const names = selectedAccessProfileNames();
  const listed = [];
  const seen = new Set();
  (MODEL.virtuals || []).forEach((vs) => {
    const vsProfiles = vs.profiles || [];
    if ([...names].some((name) => vsProfiles.some((profile) => sameTmshName(name, profile)))) addVirtual(listed, seen, vs);
  });
  (MODEL.profiles || []).forEach((profile) => {
    if (!isSelectedProfile(profile)) return;
    (profile.virtuals || []).forEach((vs) => addVirtual(listed, seen, vs));
  });
  const policy = graphByName(SELECTED) || graphByName(SELECTED_PROFILE) || (MODEL.policies || []).find((p) => p.name === SELECTED || p.name === SELECTED_PROFILE);
  (policy && policy.virtuals ? policy.virtuals : []).forEach((vs) => addVirtual(listed, seen, vs));
  return listed;
}

function lookupIrules(node, graph) {
  const ids = (node.agent_details || [])
    .filter((ag) => ag.agent_kind === "irule-event" || ag.type === "irule-event")
    .map((ag) => ag.id)
    .filter(Boolean);
  const virtuals = virtualsForDetail(graph);
  const allowed = rulesFromVirtuals(virtuals);
  const listed = [];
  const seen = new Set();
  const addRule = (rule, virtualsForRule) => {
    if (!rule || !rule.name || seen.has(rule.name)) return;
    seen.add(rule.name);
    listed.push({
      ...rule,
      virtuals: virtualsForRule || rule.virtuals || [],
      scope: virtuals.length ? "virtual" : "global",
    });
  };
  ids.forEach((id) => {
    allowed.forEach((item) => {
      const obj = lookupObjectRule(item.name) || lookupObject(item.name);
      if (obj && ruleHasAgentId(obj.source, id)) addRule(obj, item.virtuals);
    });
  });
  if (!listed.length && !virtuals.length) {
    Object.values((MODEL && MODEL.objects) || {}).forEach((obj) => {
      if (obj && obj.object_kind === "ltm rule" && ids.some((id) => ruleHasAgentId(obj.source, id))) {
        addRule(obj, obj.virtuals || []);
      }
    });
  }
  return listed;
}

function renderIruleSource(source) {
  const text = String(source || "");
  const rows = Math.min(24, Math.max(8, text.split("\n").length + 1));
  return `<div class="irule-block">
    <div class="irule-toolbar"><button type="button" class="irule-copy">복사</button></div>
    <textarea class="irule-source" readonly spellcheck="false" rows="${rows}">${escapeHtml(text)}</textarea>
  </div>`;
}

function renderIruleCard(rule) {
  const obj = lookupObjectRule(rule.name) || lookupObject(rule.name);
  const source = rule.source || (obj && obj.source) || "";
  const kind = (obj && obj.object_kind) || "ltm rule";
  return renderNamedCard(
    lastPathSegment(rule.name || ""),
    `<dt>객체 종류</dt><dd>${escapeHtml(kind)}</dd>`,
    renderIruleSource(source)
  );
}

function bindIruleCopy() {
  detailBody.querySelectorAll(".irule-copy").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const area = btn.closest(".irule-block")?.querySelector(".irule-source");
      if (!area) return;
      const text = area.value;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text);
        } else {
          area.focus();
          area.select();
          document.execCommand("copy");
        }
        btn.textContent = "복사됨";
        window.setTimeout(() => {
          btn.textContent = "복사";
        }, 1400);
      } catch (_err) {
        area.focus();
        area.select();
      }
    });
  });
}

function renderVirtualSummary(virtuals) {
  if (!virtuals.length) {
    return `<p class="detail-note">이 Access Profile이 적용된 Virtual Server가 설정에 없습니다. agent_id가 있는 전체 iRule을 표시합니다.</p>`;
  }
  return virtuals.map((vs) => {
    const vsName = lastPathSegment(vs.name || "");
    const dest = vs.destination ? lastPathSegment(vs.destination) : "";
    const rules = (vs.rules || []).map((name) => `<li>${escapeHtml(lastPathSegment(name))}</li>`).join("") || "<li>없음</li>";
    return renderNamedCard(
      vsName,
      `${dest ? `<dt>목적지</dt><dd>${escapeHtml(dest)}</dd>` : ""}<dt>적용 iRule</dt><dd><ul class="rule-list">${rules}</ul></dd>`
    );
  }).join("");
}

function showPolicyOverview(policy) {
  const titleEl = document.getElementById("detail-title");
  if (titleEl) titleEl.textContent = policy.caption || lastPathSegment(policy.name);
  const profile = (MODEL.profiles || []).find((item) => (
    item.access_policy === policy.name || item.name === policy.name || sameTmshName(item.name, SELECTED_PROFILE)
  ));
  const virtuals = (policy.virtuals && policy.virtuals.length ? policy.virtuals : null)
    || (profile && profile.virtuals) || selectedVirtuals();
  detail.classList.remove("hidden");
  const handle = document.getElementById("detail-resizer");
  if (handle) handle.classList.remove("hidden");
  detailBody.innerHTML = `
    <dl>
      <dt>객체</dt><dd>${escapeHtml(policy.name)}</dd>
      <dt>종류</dt><dd>${escapeHtml(policy.type || "access-policy")}</dd>
      ${profile ? `<dt>Access Profile</dt><dd>${escapeHtml(profile.name)}</dd>` : ""}
    </dl>
    <h4>Virtual Server</h4>
    ${renderVirtualSummary(virtuals)}
  `;
  scheduleFit();
}

function showDetail(node, graph) {
  const orig = graph.nodes.find((n) => n.id === node.id) || node;
  const edges = graph.edges.filter((e) => e.from === orig.id);
  const irules = lookupIrules(orig, graph);
  const refs = collectReferences(orig).filter((ref) => !isLtmRuleRef(ref));
  const agentIds = (orig.agent_details || [])
    .filter((ag) => ag.agent_kind === "irule-event" || ag.type === "irule-event")
    .map((ag) => ag.id)
    .filter(Boolean);
  const titleEl = document.getElementById("detail-title");
  if (titleEl) titleEl.textContent = orig.caption || lastPathSegment(orig.id);
  const agentCards = (orig.agent_details || []).map(renderAgentCard).join("");
  const refCards = refs.map(renderRefCard).join("");
  const iruleCards = irules.map(renderIruleCard).join("");
  const hasVirtual = virtualsForDetail(graph).length > 0;
  let emptyIrule = "";
  if (agentIds.length && !irules.length && hasVirtual) {
    emptyIrule = `<p class="detail-note">Access Profile이 적용된 Virtual Server iRule에서 agent_id <code>${escapeHtml(agentIds.join(", "))}</code>를 찾지 못했습니다.</p>`;
  } else if (agentIds.length && !irules.length) {
    emptyIrule = `<p class="detail-note">이 Access Profile에는 적용된 Virtual Server가 없고, 전체 ltm rule에서도 agent_id <code>${escapeHtml(agentIds.join(", "))}</code>를 찾지 못했습니다.</p>`;
  } else if (agentIds.length && irules.length && !hasVirtual) {
    emptyIrule = `<p class="detail-note">이 Access Profile에는 적용된 Virtual Server가 없어 전체 ltm rule에서 agent_id로 찾았습니다.</p>`;
  }
  detail.classList.remove("hidden");
  const handle = document.getElementById("detail-resizer");
  if (handle) handle.classList.remove("hidden");
  detailBody.innerHTML = `
    <dl>
      <dt>객체</dt><dd>${escapeHtml(orig.id)}</dd>
      <dt>종류</dt><dd>${escapeHtml(orig.kind)}${orig.item_type ? " / " + escapeHtml(orig.item_type) : ""}</dd>
      ${orig.macro ? `<dt>매크로</dt><dd>${escapeHtml(orig.macro)}</dd>` : ""}
      ${!(orig.agent_details && orig.agent_details.length) && (orig.agents || []).length ? `<dt>에이전트</dt><dd>${(orig.agents || []).map((a) => escapeHtml(a.type || a.name)).join(", ") || "—"}</dd>` : ""}
      <dt>분기</dt><dd>${edges.map((e) => `${escapeHtml(e.caption)} → ${escapeHtml((e.to || "").split("/").pop())}`).join("<br>") || "—"}</dd>
      ${edges.some((e) => e.expression) ? `<dt>표현식</dt><dd>${edges.filter((e) => e.expression).map((e) => `<div><b>${escapeHtml(e.caption)}</b><pre>${escapeHtml(e.expression)}</pre></div>`).join("")}</dd>` : ""}
    </dl>
    ${agentCards ? `<h4>에이전트 설정</h4>${agentCards}` : ""}
    ${(iruleCards || refCards) ? `<h4>참조 객체</h4>${iruleCards}${refCards}` : emptyIrule}
  `;
  bindIruleCopy();
  scheduleFit();
}

function svgEl(name, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
  return el;
}

function textEl(x, y, value, fill, size, anchor, weight) {
  const t = svgEl("text", { x, y, fill, "font-size": size, "text-anchor": anchor || "start", "font-weight": weight || 600 });
  t.textContent = value;
  return t;
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function initPanelResize(handleId, panelId, cssVar, storageKey, grow) {
  const panel = document.getElementById(panelId);
  const handle = document.getElementById(handleId);
  if (!panel || !handle) return;

  const stored = Number(localStorage.getItem(storageKey));
  if (Number.isFinite(stored) && stored >= 200) {
    document.documentElement.style.setProperty(cssVar, `${Math.min(800, stored)}px`);
  }

  let startX = 0;
  let startWidth = 0;

  const onMove = (event) => {
    const delta = grow === "left" ? event.clientX - startX : startX - event.clientX;
    const next = Math.min(800, Math.max(200, startWidth + delta));
    document.documentElement.style.setProperty(cssVar, `${next}px`);
    applyZoom();
  };

  const onUp = () => {
    handle.classList.remove("dragging");
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
    const width = parseInt(getComputedStyle(document.documentElement).getPropertyValue(cssVar), 10);
    if (Number.isFinite(width)) localStorage.setItem(storageKey, String(width));
  };

  handle.addEventListener("mousedown", (event) => {
    event.preventDefault();
    startX = event.clientX;
    startWidth = panel.getBoundingClientRect().width;
    handle.classList.add("dragging");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  });
}

initPanelResize("sidebar-resizer", "sidebar", "--sidebar-width", "vpe-sidebar-width", "left");
initPanelResize("detail-resizer", "detail", "--detail-width", "vpe-detail-width", "right");
const canvasFrame = document.querySelector(".canvas-frame");
if (canvasFrame && typeof ResizeObserver !== "undefined") {
  const fitWatch = new ResizeObserver(() => scheduleFit());
  fitWatch.observe(canvasFrame);
}
window.addEventListener("resize", scheduleFit);
initZoom();
loadModel();
