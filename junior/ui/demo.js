/* Mode démo (navigateur, sans Python) : simule l'API pour prévisualiser l'interface. index.html?demo */
"use strict";
(() => {
  const hw = [
    { id: "a1", subject: "Mathématiques", task: "Exercices 3 et 4 page 52 (fractions décimales)", due: "pour demain", minutes: 20, status: "fait", kind: "exercice" },
    { id: "a2", subject: "Français", task: "Apprendre la poésie « Le Corbeau et le Renard » (2 strophes)", due: "pour demain", minutes: 15, status: "à faire", kind: "récitation" },
    { id: "a3", subject: "Histoire", task: "Relire la leçon sur la Révolution française", due: "pour vendredi", minutes: 10, status: "à faire", kind: "leçon" },
  ];
  const emit = (e) => window.junior.on(e);
  const demoApi = {
    profiles: async () => [
      { id: "amine", name: "Amine", grade: "CM2", avatar: "🦁", color: "#ff8a3d", has_pin: true, count: 2, minutes: 35 },
      { id: "ibrahim", name: "Ibrahim", grade: "5e", avatar: "🚀", color: "#3d8bff", has_pin: true, count: 3, minutes: 50 },
    ],
    login: async (id, pin) => {
      if (pin !== "1234") return { ok: false };
      setTimeout(() => {
        emit({ kind: "state", state: "speaking" });
        emit({ kind: "subtitle", text: "Bonjour Amine ! J'espère que tu as passé une super journée. Ce soir, on en a pour trente-cinq minutes si tu es sérieux. Tu es prêt ?" });
        emit({ kind: "current", id: "a2" });
        emit({ kind: "screen", title: "Poésie — strophe 1", content: "Maître Corbeau, sur un arbre perché,\nTenait en son bec un fromage." });
        emit({ kind: "heard", text: "Oui je suis prêt, on commence par la poésie !" });
      }, 300);
      return { ok: true, homework: hw, tonight: ["a1", "a2"] };
    },
    tap: () => {
      const orb = document.querySelector("#orb");
      const order = ["idle", "listening", "thinking", "speaking"];
      const next = order[(order.indexOf(orb.dataset.state) + 1) % order.length];
      emit({ kind: "state", state: next });
      if (next === "listening") {
        let t = 0;
        const iv = setInterval(() => { emit({ kind: "level", value: Math.abs(Math.sin(t += 0.4)) }); if (t > 30) clearInterval(iv); }, 80);
      }
    },
    send_text: (t) => emit({ kind: "heard", text: t }),
    end_break: () => {},
    quit: () => {},
    parent_login: async (pin) => pin === "0000",
    parent_data: async () => ({
      children: [{ id: "amine", name: "Amine" }, { id: "ibrahim", name: "Ibrahim" }],
      homework: hw.map((h) => ({ ...h, child_name: "Amine" })),
      reports: [{ child_name: "Amine", date: "2026-10-09T18:42:00", text: "✅ Amine a terminé ses devoirs (38 min).\n\n✔︎ Mathématiques — Exercices 3 et 4 p. 52 : réussi après deux indices\n✔︎ Français — Poésie : sue presque par cœur\n\n📝 Séance agréable, Amine était concentré.\n\n⚠️ Difficultés :\n• Confond 0,25 et 2,5 dans les conversions\n\n🔁 À renforcer :\n• Faire 5 minutes de conversions fractions / décimaux demain" }],
    }),
    parent_add: async () => true,
    parent_delete: async () => true,
    parent_logout: () => {},
  };
  window.demo = { emit, break: (m) => emit({ kind: "break", minutes: m || 5 }), end: () => { hw.forEach((h) => (h.status = "fait")); emit({ kind: "ended" }); } };
  boot(demoApi);
})();
