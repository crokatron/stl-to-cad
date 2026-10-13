/* STL -> CAD Converter — front end */
(() => {
"use strict";
const $ = (s) => document.querySelector(s);

// ---------- 3D scene ----------
const canvas = $("#canvas");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x181b21);
const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 1e6);
camera.position.set(120, 90, 140);
const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

scene.add(new THREE.HemisphereLight(0xffffff, 0x2b3242, 1.0));
scene.add(new THREE.AmbientLight(0xffffff, 0.25));
const key = new THREE.DirectionalLight(0xffffff, 0.8);
key.position.set(1, 2, 1.5);
scene.add(key);
const fill = new THREE.DirectionalLight(0xbcd0ff, 0.35);
fill.position.set(-1.5, -0.5, -1);
scene.add(fill);
const grid = new THREE.GridHelper(2000, 40, 0x2a3040, 0x20242c);
scene.add(grid);

const loader = new THREE.GLTFLoader();
const layers = { solid: null, mesh: null, dev: null };
let wireframe = false;

function frameObject(obj) {
  const box = new THREE.Box3().setFromObject(obj);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const r = Math.max(size.x, size.y, size.z) || 100;
  grid.position.y = box.min.y;
  grid.scale.setScalar(Math.max(1, r / 50));
  controls.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(r * 1.1, r * 0.9, r * 1.4));
  camera.near = r / 100; camera.far = r * 50; camera.updateProjectionMatrix();
}

function clearLayer(name) {
  if (layers[name]) { scene.remove(layers[name]); disposeTree(layers[name]); layers[name] = null; }
}
function disposeTree(o) {
  o.traverse((c) => { if (c.geometry) c.geometry.dispose();
    if (c.material) [].concat(c.material).forEach((m) => m.dispose()); });
}

function loadLayer(name, url, makeMaterial) {
  return new Promise((res, rej) => {
    loader.load(url, (gltf) => {
      clearLayer(name);
      const g = gltf.scene;
      g.traverse((c) => {
        if (!c.isMesh) return;
        if (!c.geometry.attributes.normal) c.geometry.computeVertexNormals();
        if (makeMaterial) c.material = makeMaterial(c);
      });
      layers[name] = g;
      scene.add(g);
      res(g);
    }, undefined, rej);
  });
}

let byType = false;
const TYPE_COLORS = {
  plane: "#9aa6b8", cylinder: "#4c9aff", cone: "#3ecf8e", sphere: "#ffb454",
  torus: "#c58af9", bspline: "#ff6b6b", other: "#78808c",
};
const solidMat = () => byType
  ? new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0.05,
      roughness: 0.6, wireframe, side: THREE.DoubleSide })
  : new THREE.MeshStandardMaterial({ color: 0x9fb0c4, metalness: 0.1,
      roughness: 0.55, wireframe, side: THREE.DoubleSide });
const meshMat = () => new THREE.MeshStandardMaterial({
  color: 0x5a6272, metalness: 0, roughness: 1, transparent: true, opacity: 0.35,
  wireframe: true,
});
const devMat = (c) => new THREE.MeshStandardMaterial({
  vertexColors: !!(c.geometry.attributes.color), color: 0xffffff,
  metalness: 0, roughness: 1, flatShading: true, side: THREE.DoubleSide,
});

let lastKinds = [];
function updateLegend() {
  const devOn = layers.dev && $('[data-layer="dev"]').classList.contains("on");
  const typeOn = byType && layers.solid && $('[data-layer="solid"]').classList.contains("on");
  const el = $("#legend");
  if (devOn) {
    el.className = "";
    el.innerHTML = '<i style="background:#2b6cff"></i>0<i style="background:#3ecf8e"></i>½·tol<i style="background:#ff6b6b"></i>tol';
  } else if (typeOn && lastKinds.length) {
    el.className = "";
    el.innerHTML = lastKinds.map((k) =>
      `<i style="background:${TYPE_COLORS[k] || TYPE_COLORS.other}"></i>${k}`).join("");
  } else {
    el.className = "hidden";
  }
}

function applyVisibility() {
  document.querySelectorAll("#toolbar [data-layer]").forEach((b) => {
    const l = layers[b.dataset.layer];
    if (l) l.visible = b.classList.contains("on");
  });
  updateLegend();
}

document.querySelectorAll("#toolbar [data-layer]").forEach((b) => {
  b.onclick = () => { b.classList.toggle("on"); applyVisibility(); };
});
$("#bytype").onclick = () => {
  byType = !byType;
  $("#bytype").classList.toggle("on", byType);
  if (layers.solid) layers.solid.traverse((c) => { if (c.isMesh) c.material = solidMat(); });
  updateLegend();
};
$("#wire").onclick = () => {
  wireframe = !wireframe;
  $("#wire").classList.toggle("on", wireframe);
  if (layers.solid) layers.solid.traverse((c) => { if (c.isMesh) c.material.wireframe = wireframe; });
};
$("#reset").onclick = () => { const l = layers.solid || layers.dev || layers.mesh; if (l) frameObject(l); };

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h; camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe($("#view"));
resize();
(function tick() { requestAnimationFrame(tick); controls.update(); renderer.render(scene, camera); })();

// ---------- upload / job ----------
const fileInput = $("#file"), drop = $("#drop"), runBtn = $("#run");
let picked = null, polling = null;

function setPicked(f) {
  picked = f;
  $("#dropText").innerHTML = f
    ? `<b>${f.name}</b><br><small>${(f.size / 1e6).toFixed(1)} MB — click to change</small>`
    : `Drop an STL here<br><small>or click to browse</small>`;
  runBtn.disabled = !f;
}
fileInput.onchange = () => setPicked(fileInput.files[0] || null);

const methodNotes = {
  faceted: "Every mesh triangle becomes a face — always closes, 0 mm off the mesh, but a heavy STEP and faceted holes.",
  arcwise: "Fits real planes/cylinders/cones/tori + B-spline patches → round holes, compact STEP. Decimation is relaxed automatically so small features survive.",
  hybrid: "Analytic faces where confident, raw triangles elsewhere.",
};
const methodSel = $("#method");
function updateMethodNote() {
  $("#methodNote").textContent = methodNotes[methodSel.value] || "";
  $("#faces").closest("label").style.opacity = methodSel.value === "faceted" ? "1" : "0.5";
}
methodSel.onchange = updateMethodNote;
updateMethodNote();

// sample files served from the project folder
fetch("/api/samples").then((r) => r.json()).then((list) => {
  if (!list.length) return;
  const box = $("#samples");
  box.innerHTML = '<span>samples:</span> ';
  list.forEach((name) => {
    const b = document.createElement("button");
    b.textContent = name.replace(/\.stl$/i, "");
    b.onclick = async () => {
      b.disabled = true;
      const buf = await (await fetch("/api/samples/" + encodeURIComponent(name))).arrayBuffer();
      setPicked(new File([buf], name, { type: "model/stl" }));
      b.disabled = false;
    };
    box.appendChild(b);
  });
});
drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("hot"); };
drop.ondragleave = () => drop.classList.remove("hot");
drop.ondrop = (e) => {
  e.preventDefault(); drop.classList.remove("hot");
  const f = [...e.dataTransfer.files].find((x) => x.name.toLowerCase().endsWith(".stl"));
  if (f) { setPicked(f); } else { flashStatus("That isn't an .stl file", true); }
};

function flashStatus(msg, err) {
  const s = $("#status");
  s.classList.remove("hidden"); s.classList.toggle("err", !!err);
  s.innerHTML = msg + (err ? "" : `<div class="bar"><i></i></div>`);
}

runBtn.onclick = async () => {
  if (!picked) return;
  runBtn.disabled = true; runBtn.classList.add("busy"); runBtn.textContent = "Converting…";
  $("#results").classList.add("hidden");
  ["solid", "mesh", "dev"].forEach(clearLayer);
  $("#hint").textContent = "Working…";
  flashStatus("Uploading…");

  const fd = new FormData();
  fd.append("file", picked);
  fd.append("method", $("#method").value);
  fd.append("tol", $("#tol").value);
  fd.append("faces", $("#faces").value);
  fd.append("dihedral", $("#dihedral").value);
  fd.append("arc_simplify", $("#arc").value);
  fd.append("refine", $("#refine").checked ? "true" : "false");

  let id;
  try {
    const r = await fetch("/api/convert", { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    id = (await r.json()).id;
  } catch (e) { return finish(null, e.message); }

  polling = setInterval(async () => {
    let j;
    try { j = await (await fetch(`/api/jobs/${id}`)).json(); }
    catch { return; }
    const pct = { load: 8, heal: 22, segment: 40, fit: 55, build: 75, validate: 88, preview: 95, done: 100 }[j.stage] || 12;
    flashStatus(`<b>${j.stage || "queued"}</b> — ${j.message || "…"} <span style="float:right">${j.elapsed}s</span>`);
    $("#status .bar>i") && ($("#status .bar>i").style.width = pct + "%");
    if (j.status === "done") { clearInterval(polling); finish(id, null, j.result); }
    if (j.status === "error") { clearInterval(polling); finish(null, j.error); }
  }, 900);
};

async function finish(id, err, result) {
  runBtn.disabled = false; runBtn.classList.remove("busy"); runBtn.textContent = "Convert";
  if (err) { flashStatus("✗ " + err, true); $("#hint").textContent = "Conversion failed"; return; }
  $("#status").classList.add("hidden");
  $("#hint").classList.add("hidden");
  lastKinds = result.kinds || Object.keys(result.face_hist || {});
  renderResult(id, result);

  try {
    await loadLayer("solid", `/api/jobs/${id}/solid.glb`, solidMat);
    frameObject(layers.solid);
  } catch { $("#hint").classList.remove("hidden"); $("#hint").textContent = "No solid to preview"; }
  loadLayer("mesh", `/api/jobs/${id}/mesh.glb`, meshMat).then(() => { layers.mesh.visible = false; });
  loadLayer("dev", `/api/jobs/${id}/mesh.glb`, devMat).then(() => { layers.dev.visible = false; });
  applyVisibility();
}

function renderResult(id, r) {
  $("#results").classList.remove("hidden");
  const v = $("#verdict");
  v.className = r.passed ? "ok" : "bad";
  v.textContent = r.passed
    ? `PASS — ${r.n_solids} closed solid${r.n_solids > 1 ? "s" : ""}, ≤ ${r.dev_max} mm`
    : `CHECK — ${r.closed ? "closed" : "NOT closed"}, ${r.free_edges >= 0 ? r.free_edges + " open edges" : ""}`;

  const rows = [
    ["source", r.source],
    ["mesh → healed", `${r.mesh_tris.toLocaleString()} → ${r.healed_tris.toLocaleString()} tris`],
    ["method", r.method + (r.n_patches ? ` · ${r.n_patches} patches` : "")],
    ["faces", Object.entries(r.face_hist).map(([k, n]) => `${n} ${k}`).join(", ") || "—"],
    ["solids", r.n_solids + (r.closed ? " (closed)" : " (open)")],
    ["deviation max / rms / p95", `${r.dev_max} / ${r.dev_rms} / ${r.dev_p95} mm`],
    ["volume", `${r.volume_solid.toLocaleString()} mm³`],
    ["vs mesh", `${r.volume_mesh ? r.volume_mesh.toLocaleString() + " mm³  (" + r.volume_rel_err + "%)" : "n/a"}`],
    ["time", Object.entries(r.timings).map(([k, s]) => `${k} ${s}s`).join("  ")],
  ];
  $("#metrics").innerHTML = rows.map(([k, val]) => `<tr><td>${k}</td><td>${val}</td></tr>`).join("");
  $("#notes").textContent = (r.notes || []).join("\n");

  const dl = $("#downloads");
  dl.innerHTML = "";
  const kinds = Object.keys(r.outputs || {}).filter((k) => ["step", "brep", "iges"].includes(k));
  kinds.forEach((k, i) => {
    const a = document.createElement("a");
    a.href = `/api/jobs/${id}/download/${k}`;
    a.textContent = k.toUpperCase();
    if (i === 0) a.className = "primary";
    dl.appendChild(a);
  });
  if (kinds.length > 1) {
    const a = document.createElement("a");
    a.href = `/api/jobs/${id}/download-all`; a.textContent = "ZIP";
    dl.appendChild(a);
  }
}
})();
