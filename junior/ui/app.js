/* Jarvis Junior — interface. Parle au Python via window.pywebview.api ; reçoit ses événements via junior.on(). */
"use strict";

const $ = (s) => document.querySelector(s);
const SUBJECT_ICONS = [
  [/math|calcul|géom|geom/i, "🔢"], [/fran|dict|conjug|gramm|orthog|lecture|rédac|poés|poes/i, "📖"],
  [/angl|english|espag|allem|langue/i, "🌍"], [/hist|géo|geo|emc|civique/i, "🗺️"],
  [/scien|svt|physi|chimi|techno/i, "🔬"], [/musi/i, "🎵"], [/art|dessin/i, "🎨"],
];
const iconFor = (subject) => (SUBJECT_ICONS.find(([re]) => re.test(subject)) || [0, "✏️"])[1];

const STATUS_TEXT = {
  idle: "Touche Jarvis pour lui parler",
  listening: "Je t'écoute…",
  thinking: "Je réfléchis…",
  speaking: "Touche-moi pour me couper la parole",
  break: "C'est la pause",
  ended: "Séance terminée",
};

let api = null;
let profiles = [];
let current = null; // profil sélectionné
let session = { homework: [], tonight: [], started: 0, timer: null };

/* ---------------------------------------------------------------- navigation */
function show(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.toggle("active", s.id === id));
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Bonjour !" : h < 18 ? "Coucou !" : "Bonsoir !";
}

/* ---------------------------------------------------------------- profils */
async function loadProfiles() {
  if (api.refresh) await api.refresh(); // derniers devoirs envoyés par les parents
  profiles = await api.profiles();
  $("#hello-title").textContent = greeting();
  const box = $("#profiles");
  box.innerHTML = "";
  for (const p of profiles) {
    const card = document.createElement("button");
    card.className = "profile";
    card.style.setProperty("--c", p.color);
    const todo = p.count === 0
      ? "Pas de devoirs ce soir 🎉"
      : `${p.count} devoir${p.count > 1 ? "s" : ""} · environ ${p.minutes} min`;
    card.innerHTML = `<div class="avatar" style="--c:${p.color}">${p.avatar}</div>
      <div class="name"></div><span class="grade">${p.grade}</span><div class="todo">${todo}</div>`;
    card.querySelector(".name").textContent = p.name;
    card.onclick = () => openPin(p);
    box.appendChild(card);
  }
  show("screen-profiles");
}

/* ---------------------------------------------------------------- code secret */
let pin = "";
let pinMode = "child"; // ou "parent"

function openPin(profile) {
  current = profile;
  pinMode = profile ? "child" : "parent";
  pin = "";
  const av = $("#pin-avatar");
  if (profile) {
    av.textContent = profile.avatar;
    av.style.setProperty("--c", profile.color);
    $("#pin-title").textContent = `${profile.name}, tape ton code secret`;
    if (!profile.has_pin) return login("");
  } else {
    av.textContent = "🔒";
    av.style.setProperty("--c", "#4b3d99");
    $("#pin-title").textContent = "Code parent";
  }
  renderDots();
  show("screen-pin");
}

function renderDots(error = false) {
  const dots = $("#pin-dots");
  dots.querySelectorAll("i").forEach((d, i) => d.classList.toggle("on", i < pin.length));
  dots.classList.toggle("error", error);
}

function buildPad() {
  const pad = $("#pin-pad");
  for (const k of ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "⌫"]) {
    const b = document.createElement("button");
    b.textContent = k;
    if (!k) { b.className = "muted"; b.disabled = true; }
    if (k === "⌫") b.className = "muted";
    b.onclick = () => pressKey(k);
    pad.appendChild(b);
  }
  document.addEventListener("keydown", (e) => {
    if (!$("#screen-pin").classList.contains("active")) return;
    if (/^\d$/.test(e.key)) pressKey(e.key);
    if (e.key === "Backspace") pressKey("⌫");
  });
}

async function pressKey(k) {
  if (k === "⌫") pin = pin.slice(0, -1);
  else if (pin.length < 4) pin += k;
  renderDots();
  if (pin.length === 4) {
    const ok = pinMode === "child" ? await login(pin) : await parentLogin(pin);
    if (!ok) { pin = ""; renderDots(true); setTimeout(() => renderDots(), 600); }
  }
}

/* ---------------------------------------------------------------- séance */
async function login(code) {
  const res = await api.login(current.id, code);
  if (!res.ok) return false;
  session = { homework: res.homework, tonight: res.tonight, started: Date.now(), timer: null, current: null };
  $("#s-avatar").textContent = current.avatar;
  $("#s-avatar").style.setProperty("--c", current.color);
  $("#s-name").textContent = current.name;
  $("#subtitle").textContent = "";
  $("#heard").textContent = "";
  $("#screen-card").classList.add("hidden");
  setState("thinking");
  renderHomework();
  session.timer = setInterval(tick, 15000);
  tick();
  show("screen-session");
  return true;
}

function tick() {
  const min = Math.max(0, Math.round((Date.now() - session.started) / 60000));
  $("#s-timer").textContent = `⏱ ${min} min`;
}

function renderHomework() {
  const list = $("#hw-list");
  list.innerHTML = "";
  const items = session.homework;
  if (!items.length) {
    list.innerHTML = `<li class="empty">Aucun devoir enregistré. Jarvis peut t'aider à réviser !</li>`;
  }
  for (const h of items) {
    const li = document.createElement("li");
    const later = !session.tonight.includes(h.id) && h.status === "à faire";
    li.className = "hw" + (h.status === "fait" ? " done" : h.status === "partiel" ? " partial" : "")
      + (session.current === h.id ? " current" : "") + (later ? " later" : "");
    li.innerHTML = `<div class="icon">${h.status === "fait" ? "✓" : iconFor(h.subject)}</div>
      <div><div class="subj"></div><div class="task"></div><div class="meta"></div></div>`;
    li.querySelector(".subj").textContent = h.subject;
    li.querySelector(".task").textContent = h.task;
    li.querySelector(".meta").textContent = `${h.due} · ~${h.minutes} min`;
    list.appendChild(li);
  }
  const tonight = items.filter((h) => session.tonight.includes(h.id));
  const done = tonight.filter((h) => h.status === "fait").length;
  $("#s-progress").style.width = tonight.length ? `${(100 * done) / tonight.length}%` : "0";
  $("#s-progress-label").textContent = tonight.length ? `${done} / ${tonight.length} devoirs` : "";
}

function setState(state) {
  $("#orb").dataset.state = state;
  $("#status").textContent = STATUS_TEXT[state] || "";
}

/* ---------------------------------------------------------------- événements venant du Python */
const handlers = {
  state: ({ state }) => setState(state),
  level: ({ value }) => $("#orb").style.setProperty("--level", value),
  subtitle: ({ text }) => { $("#subtitle").textContent = text; },
  heard: ({ text }) => { $("#heard").textContent = text; },
  current: ({ id }) => { session.current = id; renderHomework(); },
  homework: ({ item }) => {
    const h = session.homework.find((x) => x.id === item.id);
    if (h) h.status = item.status;
    renderHomework();
  },
  screen: ({ title, content }) => {
    $("#sc-title").textContent = title;
    $("#sc-content").textContent = content;
    const card = $("#screen-card");
    card.classList.remove("hidden");
    card.style.animation = "none"; void card.offsetWidth; card.style.animation = "";
  },
  break: ({ minutes }) => startBreak(minutes),
  ended: () => setTimeout(showEnd, 400),
  error: ({ message }) => { $("#subtitle").textContent = "Oups, un petit souci technique…"; console.error(message); },
};
window.junior = { on: (evt) => (handlers[evt.kind] || (() => {}))(evt) };

/* ---------------------------------------------------------------- pause */
let breakTimer = null;
function startBreak(minutes) {
  let left = minutes * 60;
  const draw = () => { $("#break-timer").textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`; };
  draw();
  $("#break").classList.remove("hidden");
  clearInterval(breakTimer);
  breakTimer = setInterval(() => { left = Math.max(0, left - 1); draw(); if (!left) clearInterval(breakTimer); }, 1000);
}
function endBreak() {
  clearInterval(breakTimer);
  $("#break").classList.add("hidden");
  api.end_break();
}

/* ---------------------------------------------------------------- fin */
function showEnd() {
  clearInterval(session.timer);
  const tonight = session.homework.filter((h) => session.tonight.includes(h.id));
  const allDone = tonight.every((h) => h.status === "fait");
  $("#end-title").textContent = allDone ? `Bravo ${current.name} !` : `Merci ${current.name} !`;
  $("#end-text").textContent = "Tes parents ont reçu le bilan de ta séance. À demain !";
  $("#end").classList.remove("hidden");
  if (allDone) confetti();
}
function closeEnd() {
  $("#end").classList.add("hidden");
  loadProfiles();
}

function confetti() {
  const c = $("#confetti");
  const ctx = c.getContext("2d");
  c.width = innerWidth; c.height = innerHeight;
  const colors = ["#ffd166", "#3ddc97", "#7c5cff", "#ff8a3d", "#3d8bff", "#ff6b8b"];
  const parts = Array.from({ length: 160 }, () => ({
    x: Math.random() * c.width, y: -20 - Math.random() * c.height * 0.5,
    r: 4 + Math.random() * 6, vy: 2 + Math.random() * 3, vx: -1 + Math.random() * 2,
    a: Math.random() * 6, color: colors[Math.floor(Math.random() * colors.length)],
  }));
  let frames = 0;
  (function loop() {
    ctx.clearRect(0, 0, c.width, c.height);
    for (const p of parts) {
      p.y += p.vy; p.x += p.vx; p.a += 0.1;
      ctx.fillStyle = p.color;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a); ctx.fillRect(-p.r, -p.r / 2, p.r * 2, p.r); ctx.restore();
    }
    if (frames++ < 360) requestAnimationFrame(loop); else ctx.clearRect(0, 0, c.width, c.height);
  })();
}

/* ---------------------------------------------------------------- espace parents */
async function parentLogin(code) {
  if (!(await api.parent_login(code))) return false;
  await renderParent();
  show("screen-parent");
  return true;
}

async function renderParent() {
  const data = await api.parent_data();
  const sel = $("#add-child");
  sel.innerHTML = data.children.map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
  const body = $("#parent-hw");
  body.innerHTML = data.homework.length ? "" : `<tr><td class="empty">Aucun devoir en attente.</td></tr>`;
  for (const h of data.homework) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><strong></strong></td><td></td><td></td><td></td><td><button class="del">Supprimer</button></td>`;
    const cells = tr.querySelectorAll("td");
    cells[0].firstChild.textContent = h.child_name;
    cells[1].textContent = h.subject;
    cells[2].textContent = h.task;
    cells[3].textContent = `${h.due} · ${h.minutes} min · ${h.status}`;
    tr.querySelector(".del").onclick = async () => { await api.parent_delete(h.id); renderParent(); };
    body.appendChild(tr);
  }
  const reports = $("#tab-reports");
  reports.innerHTML = data.reports.length ? "" : `<p class="empty">Aucun rapport pour l'instant.</p>`;
  for (const r of data.reports) {
    const div = document.createElement("div");
    div.className = "report";
    div.innerHTML = "<h4></h4><div></div>";
    div.querySelector("h4").textContent = `${r.child_name} — ${r.date.slice(0, 10).split("-").reverse().join("/")} à ${r.date.slice(11, 16)}`;
    div.querySelector("div").textContent = r.text;
    reports.appendChild(div);
  }
}

/* ---------------------------------------------------------------- branchements */
function wire() {
  buildPad();
  document.querySelectorAll("[data-back]").forEach((b) => (b.onclick = () => show("screen-profiles")));
  $("#parent-btn").onclick = () => openPin(null);
  $("#parent-back").onclick = () => { api.parent_logout(); loadProfiles(); };
  $("#orb").onclick = () => api.tap();
  $("#quit-btn").onclick = () => $("#confirm").classList.remove("hidden");
  $("#confirm-no").onclick = () => $("#confirm").classList.add("hidden");
  $("#confirm-yes").onclick = () => {
    $("#confirm").classList.add("hidden");
    clearInterval(session.timer);
    api.quit();
    loadProfiles();
  };
  $("#break-done").onclick = endBreak;
  $("#end-done").onclick = closeEnd;
  $("#type-form").onsubmit = (e) => {
    e.preventDefault();
    const v = $("#type-input").value.trim();
    if (v) { api.send_text(v); $("#type-input").value = ""; }
  };
  document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
    $("#tab-hw").classList.toggle("hidden", t.dataset.tab !== "hw");
    $("#tab-reports").classList.toggle("hidden", t.dataset.tab !== "reports");
  }));
  $("#add-form").onsubmit = async (e) => {
    e.preventDefault();
    await api.parent_add($("#add-child").value, $("#add-subject").value, $("#add-task").value,
      $("#add-due").value, Number($("#add-min").value));
    e.target.reset();
    renderParent();
  };
  // Barre d'espace = bouton Jarvis (pratique au clavier)
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && $("#screen-session").classList.contains("active") && document.activeElement.tagName !== "INPUT") {
      e.preventDefault();
      api.tap();
    }
  });
}

function boot(realApi) {
  api = realApi;
  wire();
  loadProfiles();
}

window.addEventListener("pywebviewready", () => boot(window.pywebview.api));
// Aperçu dans un navigateur (sans Python) : index.html?demo
if (location.search.includes("demo")) {
  const s = document.createElement("script");
  s.src = "demo.js";
  document.body.appendChild(s);
}
