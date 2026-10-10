// Jarvis Junior — espace parents (application web installable).
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const WEEKDAYS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
const ICONS = [[/math|calcul|géom/i, "🔢"], [/fran|dict|conjug|gramm|orthog|lecture|rédac|poés/i, "📖"],
  [/angl|espag|allem|langue/i, "🌍"], [/hist|géo|emc/i, "🗺️"], [/scien|svt|physi|chimi|techno/i, "🔬"],
  [/musi/i, "🎵"], [/art/i, "🎨"]];
const icon = (s) => (ICONS.find(([re]) => re.test(s)) || [0, "✏️"])[1];

let token = localStorage.getItem("jj-token");
let data = null;
let filter = "tous";
let reportFilter = "tous";
let editing = null;
let photoChild = "";
let photoFiles = [];
const jobs = new Map(); // id → état de lecture en cours

/* ------------------------------------------------------------------ API */
async function api(method, path, body, isForm = false) {
  const headers = token ? { authorization: `Bearer ${token}` } : {};
  if (body && !isForm) headers["content-type"] = "application/json";
  const res = await fetch(`/api/${path}`, { method, headers, body: isForm ? body : body && JSON.stringify(body) });
  const out = await res.json().catch(() => ({}));
  if (res.status === 401 && path !== "login") { logout(); throw new Error(out.error || "Session expirée"); }
  if (!res.ok) throw new Error(out.error || `Erreur ${res.status}`);
  return out;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 2600);
}

/* ------------------------------------------------------------------ dates */
function dueLabel(iso) {
  if (!iso) return "sans date";
  const d = new Date(`${iso}T12:00:00`);
  const today = new Date(); today.setHours(12, 0, 0, 0);
  const days = Math.round((d - today) / 86_400_000);
  if (days < 0) return `en retard (${d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" })})`;
  if (days === 0) return "pour aujourd'hui";
  if (days === 1) return "pour demain";
  if (days < 7) return `pour ${WEEKDAYS[d.getDay()]}`;
  return `pour le ${d.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" })}`;
}
function ago(iso) {
  if (!iso) return "jamais";
  const min = Math.round((Date.now() - Date.parse(iso)) / 60000);
  if (min < 2) return "à l'instant";
  if (min < 60) return `il y a ${min} min`;
  const h = Math.round(min / 60);
  if (h < 48) return `il y a ${h} h`;
  return `il y a ${Math.round(h / 24)} jours`;
}
const when = (iso) => new Date(iso).toLocaleString("fr-FR", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });

/* ------------------------------------------------------------------ connexion */
function showLogin() {
  $("#app").classList.add("hidden");
  $("#login").classList.remove("hidden");
  const last = localStorage.getItem("jj-name");
  if (last) $("#login-name").value = last;
  syncChips();
}
function syncChips() {
  document.querySelectorAll("#name-chips .chip").forEach((c) => c.classList.toggle("on", c.dataset.name === $("#login-name").value));
}
document.querySelectorAll("#name-chips .chip").forEach((c) => (c.onclick = () => { $("#login-name").value = c.dataset.name; syncChips(); }));
$("#login-name").oninput = syncChips;
$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    const name = $("#login-name").value.trim() || "Parent";
    const res = await api("POST", "login", { name, password: $("#login-pass").value });
    token = res.token;
    localStorage.setItem("jj-token", token);
    localStorage.setItem("jj-name", res.name);
    $("#login-pass").value = "";
    start();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
};
function logout() {
  token = null;
  localStorage.removeItem("jj-token");
  showLogin();
}
$("#logout").onclick = logout;

/* ------------------------------------------------------------------ onglets */
function openTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("hidden", t.id !== `tab-${name}`));
  document.querySelectorAll(".tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  window.scrollTo({ top: 0 });
}
document.querySelectorAll(".tabbar button").forEach((b) => (b.onclick = () => { history.replaceState(null, "", `#${b.dataset.tab}`); openTab(b.dataset.tab); }));

/* ------------------------------------------------------------------ rendu */
const kid = (id) => data.children.find((c) => c.id === id);
const kidName = (id) => kid(id)?.name || (id === "inconnu" ? "À attribuer" : id);
const avatar = (id) => { const c = kid(id); return `<span class="avatar" style="--c:${esc(c?.color || "#999")}">${esc(c?.avatar || "❓")}</span>`; };

function segmented(el, current, onPick, extra = [{ id: "tous", name: "Tous" }]) {
  el.innerHTML = [...extra, ...data.children].map((c) =>
    `<button type="button" data-id="${esc(c.id)}" class="${c.id === current ? "on" : ""}">${esc(c.avatar ? `${c.avatar} ${c.name}` : c.name)}</button>`).join("");
  el.querySelectorAll("button").forEach((b) => (b.onclick = () => onPick(b.dataset.id)));
}

function render() {
  const h = new Date().getHours();
  $("#hello").textContent = `${h < 18 ? "Bonjour" : "Bonsoir"} ${data.me.name} 👋`;
  const fresh = data.mac_seen && Date.now() - Date.parse(data.mac_seen) < 10 * 60_000;
  $("#mac-status").innerHTML = `<span class="dot ${data.mac_seen ? (fresh ? "on" : "off") : ""}"></span> Mac ${data.mac_seen ? `synchronisé ${ago(data.mac_seen)}` : "jamais connecté"}`;
  $("#mac-detail").textContent = data.mac_seen
    ? `Dernière synchronisation ${ago(data.mac_seen)}. ${fresh ? "Tout est à jour." : "Le Mac est peut-être éteint : il récupérera les devoirs à son allumage."}`
    : "Le Mac ne s'est pas encore connecté. Terminez l'installation sur le Mac (python -m junior setup).";
  $("#me-detail").textContent = `Connecté en tant que ${data.me.name}.`;
  renderHomework();
  renderReports();
  renderNotes();
}

function renderHomework() {
  segmented($("#child-filter"), filter, (id) => { filter = id; renderHomework(); });
  const list = data.homework.filter((x) => filter === "tous" || x.child === filter);
  const groups = new Map();
  for (const x of list.sort((a, b) => (a.due || "9999").localeCompare(b.due || "9999"))) {
    if (!groups.has(x.child)) groups.set(x.child, []);
    groups.get(x.child).push(x);
  }
  const box = $("#homework-list");
  if (!list.length) {
    box.innerHTML = `<div class="empty">Aucun devoir en attente 🎉<br><span class="small">Envoyez une photo du cahier de textes pour commencer.</span></div>`;
    return;
  }
  box.innerHTML = [...groups.entries()].map(([child, items]) => {
    const total = items.filter((x) => x.status !== "fait").reduce((s, x) => s + x.minutes, 0);
    return `<div class="group-title">${avatar(child)} ${esc(kidName(child))} <span class="muted small">· ~${total} min restantes</span></div>` +
      items.map((x) => {
        const late = x.due && x.status !== "fait" && dueLabel(x.due).startsWith("en retard");
        const badge = x.status === "fait" ? `<span class="badge done">✓ fait</span>` : x.status === "partiel" ? `<span class="badge partial">en partie</span>`
          : late ? `<span class="badge late">en retard</span>` : `<span class="badge todo">à faire</span>`;
        return `<div class="card hw" data-id="${esc(x.id)}"><div class="icon">${icon(x.subject)}</div>
          <div><div class="subj">${esc(x.subject)}</div><div class="task">${esc(x.task)}</div>${x.comment ? `<div class="task">💬 ${esc(x.comment)}</div>` : ""}</div>
          <div class="meta">${esc(dueLabel(x.due))}<br>~${x.minutes} min<br>${badge}</div></div>`;
      }).join("");
  }).join("");
  box.querySelectorAll(".hw").forEach((el) => (el.onclick = () => openEdit(data.homework.find((x) => x.id === el.dataset.id))));
}

function renderReports() {
  segmented($("#report-filter"), reportFilter, (id) => { reportFilter = id; renderReports(); });
  const list = data.reports.filter((r) => reportFilter === "tous" || r.child === reportFilter);
  $("#reports").innerHTML = list.length ? list.map((r) =>
    `<div class="card report" id="rapport-${esc(r.id)}"><div class="report-head">${avatar(r.child)}<div><b>${esc(kidName(r.child))}</b><div class="when">${esc(when(r.date))}</div></div></div>${esc(r.text)}</div>`).join("")
    : `<div class="empty">Pas encore de rapport. Il arrive ici (et en notification) à la fin de chaque séance.</div>`;
  const target = location.hash.match(/^#rapport-(.+)/);
  if (target) {
    openTab("rapports");
    const el = document.getElementById(`rapport-${target[1]}`);
    if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("flash"); }
  }
}

function renderNotes() {
  $("#note-child").innerHTML = `<option value="tous">Pour les deux</option>` + data.children.map((c) => `<option value="${esc(c.id)}">Pour ${esc(c.name)}</option>`).join("");
  $("#notes").innerHTML = data.notes.length ? data.notes.map((n) =>
    `<div class="card note"><div>${n.child !== "tous" ? avatar(n.child) : "👨‍👩‍👦"} ${esc(n.text)}<div class="muted small">${esc(n.author)} · ${esc(ago(n.date))}</div></div><button class="x" data-id="${esc(n.id)}" aria-label="Retirer">×</button></div>`).join("")
    : `<div class="empty">Aucune consigne pour l'instant.</div>`;
  $("#notes").querySelectorAll(".x").forEach((b) => (b.onclick = async () => { await api("DELETE", `notes/${b.dataset.id}`); refresh(); }));
  const diff = data.difficulties.slice(0, 15);
  $("#difficulties").innerHTML = diff.length ? diff.map((d) =>
    `<div class="card">${avatar(d.child)} <b>${esc(d.subject)}</b> — ${esc(d.topic)}<div class="muted small">${esc(d.detail)} · ${esc(ago(d.date))}</div></div>`).join("")
    : `<div class="empty">Rien de signalé pour l'instant.</div>`;
}
$("#note-form").onsubmit = async (e) => {
  e.preventDefault();
  await api("POST", "notes", { child: $("#note-child").value, text: $("#note-text").value });
  $("#note-text").value = "";
  toast("Consigne transmise à Jarvis ✓");
  refresh();
};

/* ------------------------------------------------------------------ modifier un devoir */
function openEdit(item) {
  editing = item || null;
  $("#edit-title").textContent = item ? "Modifier le devoir" : "Nouveau devoir";
  $("#e-child").innerHTML = data.children.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("") +
    (item?.child === "inconnu" ? `<option value="inconnu">À attribuer</option>` : "");
  $("#e-child").value = item?.child || (filter !== "tous" ? filter : data.children[0]?.id);
  $("#e-subject").value = item?.subject || "";
  $("#e-task").value = item?.task || "";
  $("#e-due").value = item?.due || "";
  $("#e-min").value = item?.minutes || 15;
  $("#e-status").value = item?.status || "à faire";
  $("#e-delete").classList.toggle("hidden", !item);
  const img = $("#e-photo");
  img.classList.toggle("hidden", !item?.photo);
  if (item?.photo) img.src = `/api/photo/${item.photo}?t=${encodeURIComponent(token)}`;
  $("#edit-sheet").showModal();
}
$("#add-manual").onclick = () => openEdit(null);
$("#edit-form").onsubmit = async (e) => {
  if (e.submitter?.value !== "save") return;
  e.preventDefault();
  const body = { child: $("#e-child").value, subject: $("#e-subject").value, task: $("#e-task").value,
    due: $("#e-due").value, minutes: Number($("#e-min").value), status: $("#e-status").value };
  try {
    if (editing) await api("PATCH", `homework/${editing.id}`, body);
    else await api("POST", "homework", body);
    $("#edit-sheet").close();
    toast("Enregistré ✓");
    refresh();
  } catch (err) { toast(err.message); }
};
$("#e-delete").onclick = async () => {
  if (!editing || !confirm("Supprimer ce devoir ?")) return;
  await api("DELETE", `homework/${editing.id}`);
  $("#edit-sheet").close();
  toast("Supprimé");
  refresh();
};

/* ------------------------------------------------------------------ photos */
$("#send-photo").onclick = () => {
  photoFiles = [];
  photoChild = "";
  $("#previews").innerHTML = "";
  $("#photo-caption").value = "";
  $("#photo-send").disabled = true;
  $("#drop-label").textContent = "📸 Prendre ou choisir des photos";
  renderPhotoChild();
  $("#photo-sheet").showModal();
};
function renderPhotoChild() {
  segmented($("#photo-child"), photoChild, (id) => { photoChild = id; renderPhotoChild(); }, [{ id: "", name: "🔮 Deviner" }]);
}
$("#photo-input").onchange = async (e) => {
  const files = [...e.target.files].slice(0, 6);
  $("#drop-label").textContent = "Préparation…";
  photoFiles = await Promise.all(files.map(shrink));
  $("#previews").innerHTML = photoFiles.map((b) => `<img src="${URL.createObjectURL(b)}" alt="">`).join("");
  $("#drop-label").textContent = `${photoFiles.length} photo${photoFiles.length > 1 ? "s" : ""} · toucher pour changer`;
  $("#photo-send").disabled = !photoFiles.length;
};

/** Réduit la photo (≤ 2200 px, JPEG) : envoi rapide et lecture fiable. */
async function shrink(file) {
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, 2200 / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
    return await new Promise((ok) => canvas.toBlob(ok, "image/jpeg", 0.85));
  } catch {
    return file;
  }
}

$("#photo-form").onsubmit = async (e) => {
  if (e.submitter?.value !== "send") return;
  e.preventDefault();
  const form = new FormData();
  photoFiles.forEach((b, i) => form.append("photo", b, `devoirs-${i}.jpg`));
  form.append("child", photoChild);
  form.append("caption", $("#photo-caption").value);
  $("#photo-send").disabled = true;
  try {
    const { id } = await api("POST", "photos", form, true);
    $("#photo-sheet").close();
    jobs.set(id, { status: "pending", started: Date.now() });
    renderJobs();
    pollJob(id);
  } catch (err) {
    toast(err.message);
    $("#photo-send").disabled = false;
  }
};

async function pollJob(id) {
  const info = jobs.get(id);
  try {
    const job = await api("GET", `jobs/${id}`);
    Object.assign(info, job);
  } catch { /* réseau : on réessaie */ }
  renderJobs();
  if (info.status === "pending" && Date.now() - info.started < 10 * 60_000) setTimeout(() => pollJob(id), 2500);
  else if (info.status === "done") refresh();
}

function renderJobs() {
  $("#jobs").innerHTML = [...jobs.entries()].map(([id, j]) => {
    if (j.status === "pending") {
      const slow = Date.now() - j.started > 90_000;
      return `<div class="card job"><div class="spinner"></div><div><b>Jarvis lit la photo…</b><p class="muted small">${slow
        ? "C'est plus long que prévu : si le serveur n'y arrive pas, le Mac s'en chargera à sa prochaine synchronisation."
        : "Quelques secondes, le temps de déchiffrer le cahier."}</p></div></div>`;
    }
    if (j.status === "error") return `<div class="card job">⚠️<div><b>Lecture impossible</b><p class="muted small">${esc(j.message)}</p></div></div>`;
    const items = (j.items || []).map((hid) => data?.homework.find((h) => h.id === hid)).filter(Boolean);
    const who = j.child === "inconnu" ? "<b>Pour qui ?</b> Touchez un devoir pour choisir l'enfant." : `pour <b>${esc(kidName(j.child))}</b>${j.guessed ? " (deviné d'après le niveau — touchez pour corriger)" : ""}`;
    return `<div class="card job">✅<div style="flex:1"><b>${items.length} devoir${items.length > 1 ? "s" : ""} enregistré${items.length > 1 ? "s" : ""}</b> ${who}
      <ul>${items.map((h) => `<li>${esc(h.subject)} — ${esc(h.task)} <span class="muted">(${esc(dueLabel(h.due))}, ~${h.minutes} min)</span></li>`).join("")}</ul>
      ${j.remarks ? `<p class="muted small">ℹ️ ${esc(j.remarks)}</p>` : ""}</div><button class="btn ghost" data-close="${esc(id)}">OK</button></div>`;
  }).join("");
  $("#jobs").querySelectorAll("[data-close]").forEach((b) => (b.onclick = () => { jobs.delete(b.dataset.close); renderJobs(); }));
}

/* ------------------------------------------------------------------ notifications */
const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;

async function pushState() {
  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  $("#ios-hint").classList.toggle("hidden", !(isIOS && !standalone));
  if (!supported) {
    $("#push-status").textContent = isIOS && !standalone
      ? "Ajoutez d'abord Jarvis Parents à l'écran d'accueil (voir ci-dessous)."
      : "Ce navigateur ne gère pas les notifications.";
    $("#push-enable").classList.add("hidden");
    return;
  }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  const on = Notification.permission === "granted" && sub;
  $("#push-status").textContent = on ? "Activées sur cet appareil ✓ Vous serez prévenu à chaque rapport et à chaque envoi de devoirs."
    : Notification.permission === "denied" ? "Refusées : autorisez-les dans les réglages du téléphone."
    : "Recevez une notification à la fin de chaque séance.";
  $("#push-enable").classList.toggle("hidden", !!on);
  $("#push-test").classList.toggle("hidden", !on);
}

$("#push-enable").onclick = async () => {
  try {
    if ((await Notification.requestPermission()) !== "granted") return pushState();
    const reg = await navigator.serviceWorker.ready;
    const { publicKey } = await api("GET", "push/key");
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(publicKey) });
    await api("POST", "push/subscribe", { subscription: sub.toJSON() });
    toast("Notifications activées ✓");
  } catch (err) {
    toast(`Impossible d'activer : ${err.message}`);
  }
  pushState();
};
$("#push-test").onclick = async () => { const r = await api("POST", "push/test"); toast(`Envoyée à ${r.sent} appareil${r.sent > 1 ? "s" : ""}`); };

function b64ToBytes(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/* ------------------------------------------------------------------ démarrage */
async function refresh() {
  try {
    data = await api("GET", "state");
    render();
    renderJobs();
  } catch (err) {
    if (token) toast(err.message);
  }
}

async function start() {
  if (!token) return showLogin();
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  const tab = location.hash.replace("#", "");
  openTab(["devoirs", "rapports", "consignes", "reglages"].includes(tab) ? tab : tab.startsWith("rapport-") ? "rapports" : "devoirs");
  await refresh();
  pushState();
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
document.addEventListener("visibilitychange", () => { if (!document.hidden && token) refresh(); });
window.addEventListener("hashchange", () => data && renderReports());
start();
