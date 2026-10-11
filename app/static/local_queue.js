"use strict";
// Section « 🖥️ Local » — onglet « 📋 File locale » : plusieurs pubs Avatar IA (MiniMax H3) animées
// à la suite sur le PC, un plan après l'autre (CONTRAT_LOCAL.md K7 / K8).
//   • pubs éligibles (cases à cocher) → « ▶ Lancer tout en local » (+ export automatique) ;
//   • file ordonnable (glisser-déposer + boutons ↑ / ↓), retirer une pub ;
//   • progression : pub et plan en cours, %, nœud Comfy, temps écoulé / restant, plans faits,
//     attente de Comfy, pause (avec sa raison) ;
//   • Pause / Reprendre / Annuler la file (confirmation) / relancer les plans en échec ;
//   • fin de file : toast + bandeau + notification du navigateur (une seule fois par file,
//     acquittée via « summary/seen »).
// Chargé APRÈS app.js et local.js : réutilise $, api, srvFetch, toast, esc, showModal.
// Polling : 2 s quand l'onglet est visible, 15 s sinon tant que la file est active.
(function () {
  if (!document.getElementById("lqPanel")) return;

  const Q = "/api/local/queue";
  const FAST_MS = 2000;
  const SLOW_MS = 15000;
  const STATE_LABELS = {
    inactive: "File vide",
    en_cours: "En cours",
    pause_demandee: "Pause demandée (fin du plan en cours)",
    en_pause: "En pause",
    attente_comfy: "En attente de Comfy",
    termine: "Terminée",
  };
  const STATE_CLASS = {
    inactive: "wait", en_cours: "ok", pause_demandee: "busy", en_pause: "busy", attente_comfy: "err", termine: "ok",
  };
  const AD_STATUS = {
    en_attente: "En attente", en_cours: "En cours", termine: "Terminée", partiel: "Terminée avec des échecs",
    annule: "Annulée", retire: "Retirée",
  };
  const PLAN_STATUS = {
    en_attente: "en attente", en_cours: "en cours", termine: "fait", echec: "à relancer", annule: "annulé",
    ignore: "ignoré (déjà en cours ailleurs)",
  };
  const EXPORT_STATUS = {
    ok: "exportée", incomplet: "export non fait (plans en échec)", sans_dossier: "pas de dossier d'export (client)",
    echec: "export en échec",
  };
  const COMFY_LABELS = {
    pret: "Comfy prêt", occupe: "Comfy occupé — rendu en cours", demarrage: "Comfy démarre…",
    injoignable: "Comfy ne répond pas",
  };
  const ACTIVE_STATES = ["en_cours", "pause_demandee", "en_pause", "attente_comfy"];

  let view = null;          // dernière vue GET /api/local/queue
  let eligible = [];        // GET /api/local/queue/eligible → ads
  let timer = null;
  let busy = false;         // action en cours (boutons)
  let dragId = null;        // ad_id glissé
  const notified = new Set();   // run_id déjà notifiés (cette page)

  // ------------------------------------------------ utilitaires
  function fmtDur(s) {
    if (s === null || s === undefined || s === "" || !isFinite(Number(s))) return "—";
    const t = Math.max(0, Math.round(Number(s)));
    if (t < 60) return `${t} s`;
    const m = Math.round(t / 60);
    if (m < 60) return `${m} min`;
    return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`;
  }
  function isVisible() {
    const sec = $("local");
    const panel = $("lqPanel");
    return !!(sec && sec.classList.contains("active") && panel && !panel.classList.contains("hidden")) &&
      document.visibilityState !== "hidden";
  }
  function isActiveRun(v) {
    return !!(v && ACTIVE_STATES.includes(v.state));
  }
  async function call(path, body, method = "POST") {
    const r = await srvFetch(Q + path, {
      method, headers: { "Content-Type": "application/json" },
      body: method === "GET" ? undefined : JSON.stringify(body || {}),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const err = new Error(detailToMessage(data.detail) || "Action impossible — réessaie.");
      err.status = r.status;
      throw err;
    }
    return data;
  }

  // ------------------------------------------------ pubs éligibles
  async function loadEligible() {
    try {
      const r = await api(Q + "/eligible");
      eligible = Array.isArray(r.ads) ? r.ads : [];
    } catch (e) {
      eligible = [];
      $("lqEligible").innerHTML = `<p class="local-error">${esc(e.message)}</p>`;
      return;
    }
    renderEligible();
  }
  function renderEligible() {
    const box = $("lqEligible");
    const keep = new Set([...box.querySelectorAll("input.lq-pick:checked")].map((i) => Number(i.value)));
    if (!eligible.length) {
      box.innerHTML = `<p class="muted small">Aucune pub prête : choisis « MiniMax H3 (local) » comme modèle vidéo d'une pub
        Avatar IA et valide ses keyframes.</p>`;
      syncStartBtn();
      return;
    }
    box.innerHTML = eligible.map((a) => {
      const can = !!a.eligible && !a.in_queue;
      const why = a.in_queue ? "déjà dans la file" : (a.reason || "");
      const thumb = a.thumb_url
        ? `<img src="${esc(a.thumb_url)}" alt="" loading="lazy" />`
        : `<div class="lq-thumb-empty">—</div>`;
      return `<label class="lq-elig${can ? "" : " off"}">` +
        `<input type="checkbox" class="lq-pick" value="${esc(a.ad_id)}"${can ? "" : " disabled"}${can && keep.has(Number(a.ad_id)) ? " checked" : ""} />` +
        `<span class="lq-thumb">${thumb}</span>` +
        `<span class="lq-elig-info"><b>${esc(a.name || "Pub #" + a.ad_id)}</b>` +
        (a.client ? ` <span class="muted small">· ${esc(a.client)}</span>` : "") +
        `<span class="muted small">${esc(a.plans_todo ?? "?")} plan(s) à animer sur ${esc(a.plans_total ?? "?")}` +
        (a.est_s ? ` · ~${esc(fmtDur(a.est_s))}` : "") + `</span>` +
        (why ? `<span class="muted small lq-why">${esc(why)}</span>` : "") +
        `</span></label>`;
    }).join("");
    syncStartBtn();
  }
  function pickedIds() {
    return [...$("lqEligible").querySelectorAll("input.lq-pick:checked")].map((i) => Number(i.value));
  }
  function syncStartBtn() {
    $("lqStartBtn").disabled = busy || !pickedIds().length;
  }
  $("lqEligible").addEventListener("change", syncStartBtn);
  $("lqEligibleRefresh").addEventListener("click", loadEligible);

  // Notifications du navigateur : permission demandée au clic (geste utilisateur), jamais bloquante.
  function askNotifyPermission() {
    try {
      if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    } catch (_) { /* navigateur sans notifications */ }
  }

  $("lqStartBtn").addEventListener("click", async () => {
    const ids = pickedIds();
    if (!ids.length) return toast("Coche au moins une pub.");
    askNotifyPermission();
    busy = true;
    syncStartBtn();
    try {
      const r = await call("/add", { ad_ids: ids, start: true, auto_export: $("lqAutoExport").checked });
      const added = Array.isArray(r.added) ? r.added.length : 0;
      const skipped = Array.isArray(r.skipped) ? r.skipped : [];
      toast(added ? `${added} pub(s) ajoutée(s) à la file ✓` : "Aucune pub ajoutée.");
      if (skipped.length) {
        toast(skipped.map((s) => `Pub #${s.ad_id} : ${s.reason || "ignorée"}`).join(" · "));
      }
      applyView(r);
      loadEligible();
    } catch (e) {
      toast(e.message);
    } finally {
      busy = false;
      syncStartBtn();
    }
  });

  $("lqAutoExport").addEventListener("change", async () => {
    if (!isActiveRun(view)) return;   // sinon : envoyé avec « Lancer tout en local »
    try {
      applyView(await call("/options", { auto_export: $("lqAutoExport").checked }));
    } catch (e) {
      toast(e.message);
    }
  });

  // ------------------------------------------------ vue de la file
  function adPlanIndex(v, cur) {
    const ad = (v.ads || []).find((a) => Number(a.ad_id) === Number(cur.ad_id));
    const plans = (ad && Array.isArray(ad.plans)) ? ad.plans : [];
    const i = plans.findIndex((p) => Number(p.clip_id) === Number(cur.clip_id));
    return { n: i >= 0 ? i + 1 : null, total: plans.length || (ad && ad.plans_total) || null };
  }
  function renderProgress(v) {
    const box = $("lqProgress");
    const st = v.state || "inactive";
    const pill = $("lqStatePill");
    pill.className = "local-pill " + (STATE_CLASS[st] || "wait");
    pill.textContent = "● " + (STATE_LABELS[st] || st);
    if (st === "inactive" && !(v.ads || []).length) {
      box.innerHTML = `<p class="muted small">La file est vide.</p>`;
      return;
    }
    const parts = [];
    const cur = v.current;
    if (cur) {
      const idx = adPlanIndex(v, cur);
      const pct = Math.max(0, Math.min(100, Math.round(Number(cur.percent) || 0)));
      parts.push(
        `<div class="lq-current">` +
        (cur.thumb_url ? `<img class="lq-cur-thumb" src="${esc(cur.thumb_url)}" alt="" loading="lazy" />` : "") +
        `<div class="lq-cur-info"><b>${esc(cur.ad_name || "Pub #" + cur.ad_id)}</b> — plan ${esc(idx.n ?? cur.scene_n ?? "?")}` +
        (idx.total ? `/${esc(idx.total)}` : "") + (cur.label ? ` <span class="muted small">(${esc(cur.label)})</span>` : "") +
        `<div class="local-bar lq-bar"><div style="width:${pct}%"></div></div>` +
        `<div class="muted small">${pct} %` + (cur.node_label ? ` · ${esc(cur.node_label)}` : "") +
        ` · écoulé ${esc(fmtDur(cur.elapsed_s))}` +
        (cur.remaining_s != null ? ` · reste ~${esc(fmtDur(cur.remaining_s))}` : "") + `</div></div></div>`);
    }
    const done = Number(v.plans_done) || 0;
    const total = Number(v.plans_total) || 0;
    const failed = Number(v.plans_failed) || 0;
    parts.push(`<div class="lq-totals">Plans faits : <b>${done}/${total}</b>` +
      (failed ? ` · <span class="local-error">${failed} à relancer</span>` : "") +
      (v.started_at ? ` · écoulé ${esc(fmtDur(v.elapsed_s))}` : "") +
      (v.remaining_s != null && isActiveRun(v) ? ` · reste ~${esc(fmtDur(v.remaining_s))}` : "") + `</div>`);
    const c = v.comfy || {};
    if (st === "attente_comfy" || c.state === "injoignable" || c.state === "demarrage") {
      parts.push(`<div class="lq-wait">⏳ ${esc(c.message || COMFY_LABELS[c.state] || "En attente de Comfy")}` +
        (c.next_check_s != null ? ` · nouvelle vérification dans ${esc(fmtDur(c.next_check_s))}` : "") +
        (c.waiting_since ? ` · depuis ${esc(fmtDur(Date.now() / 1000 - Number(c.waiting_since)))}` : "") + `</div>`);
    }
    if ((st === "en_pause" || st === "pause_demandee") && v.pause_reason) {
      parts.push(`<div class="lq-wait">⏸ ${esc(v.pause_reason)}</div>`);
    }
    box.innerHTML = parts.join("");
  }
  function renderControls(v) {
    const st = (v && v.state) || "inactive";
    const running = st === "en_cours" || st === "attente_comfy";
    const paused = st === "en_pause" || st === "pause_demandee";
    $("lqPauseBtn").classList.toggle("hidden", !running);
    $("lqResumeBtn").classList.toggle("hidden", !paused);
    $("lqCancelBtn").classList.toggle("hidden", !isActiveRun(v));
    $("lqRetryBtn").classList.toggle("hidden", !(v && Number(v.plans_failed) > 0));
    ["lqPauseBtn", "lqResumeBtn", "lqCancelBtn", "lqRetryBtn"].forEach((id) => { $(id).disabled = busy; });
    if (v && typeof v.auto_export === "boolean" && document.activeElement !== $("lqAutoExport")) {
      $("lqAutoExport").checked = v.auto_export;
    }
  }
  function planRows(a) {
    const plans = Array.isArray(a.plans) ? a.plans : [];
    if (!plans.length) return "";
    return `<details class="lq-plans"><summary>Plans (${esc(a.plans_done ?? 0)}/${esc(a.plans_total ?? plans.length)})</summary><ul>` +
      plans.map((p) => {
        const label = PLAN_STATUS[p.status] || p.status || "";
        return `<li class="lq-plan ${esc(p.status || "")}">Plan ${esc(p.scene_n ?? "?")}` +
          (p.label ? ` <span class="muted small">${esc(p.label)}</span>` : "") +
          ` — <span class="${p.status === "echec" ? "local-error" : "muted"}">${esc(label)}</span>` +
          (p.status === "termine" && p.seconds_gen ? ` <span class="muted small">(${esc(fmtDur(p.seconds_gen))})</span>` : "") +
          (p.status === "en_attente" && p.est_s ? ` <span class="muted small">(~${esc(fmtDur(p.est_s))})</span>` : "") +
          (p.mp4_url ? ` <a href="${esc(p.mp4_url)}" target="_blank" rel="noopener">▶ voir</a>` : "") +
          (p.error ? `<div class="local-error small">${esc(p.error)}</div>` : "") + `</li>`;
      }).join("") + `</ul></details>`;
  }
  function renderList(v) {
    const list = $("lqList");
    const ads = (v.ads || []).slice().sort((x, y) => (Number(x.position) || 0) - (Number(y.position) || 0));
    if (!ads.length) {
      list.innerHTML = "";
      return;
    }
    const movable = (a) => a.status === "en_attente";
    list.innerHTML = ads.map((a, i) => {
      const failed = Number(a.plans_failed) || 0;
      const exp = a.export || {};
      const thumb = a.thumb_url ? `<img src="${esc(a.thumb_url)}" alt="" loading="lazy" />` : `<div class="lq-thumb-empty">—</div>`;
      return `<li class="lq-item ${esc(a.status || "")}" data-ad="${esc(a.ad_id)}"${movable(a) ? ' draggable="true"' : ""}>` +
        `<span class="lq-grip" aria-hidden="true">${movable(a) ? "⋮⋮" : ""}</span>` +
        `<span class="lq-thumb">${thumb}</span>` +
        `<div class="lq-item-info"><b>${esc(a.name || "Pub #" + a.ad_id)}</b> ` +
        `<span class="muted small">· ${esc(AD_STATUS[a.status] || a.status || "")} · ${esc(a.plans_done ?? 0)}/${esc(a.plans_total ?? 0)} plans` +
        (a.remaining_s != null && (a.status === "en_attente" || a.status === "en_cours") ? ` · ~${esc(fmtDur(a.remaining_s))}` : "") + `</span>` +
        (failed ? `<div class="local-error small">${failed} plan(s) en échec — à relancer</div>` : "") +
        (exp.status ? `<div class="muted small">Export : ${esc(EXPORT_STATUS[exp.status] || exp.status)}` +
          (exp.dest ? ` — ${esc(exp.dest)}` : "") + (exp.error ? ` (${esc(exp.error)})` : "") + `</div>` : "") +
        planRows(a) + `</div>` +
        `<div class="lq-item-actions">` +
        (movable(a) ? `<button type="button" class="btn small" data-lq="up" aria-label="Monter"${i === 0 ? " disabled" : ""}>↑</button>` +
          `<button type="button" class="btn small" data-lq="down" aria-label="Descendre"${i === ads.length - 1 ? " disabled" : ""}>↓</button>` : "") +
        (failed ? `<button type="button" class="btn small" data-lq="retry">↻ Relancer les échecs</button>` : "") +
        (a.status === "en_attente" || a.status === "en_cours"
          ? `<button type="button" class="btn small danger-outline" data-lq="remove">Retirer</button>` : "") +
        `</div></li>`;
    }).join("");
  }
  function renderBanner(v) {
    const b = $("lqBanner");
    const s = v && v.summary;
    if (!s || s.seen) {
      b.classList.add("hidden");
      b.innerHTML = "";
      return;
    }
    const txt = s.message ||
      `File terminée : ${s.plans ?? 0} plan(s) rendu(s) sur ${s.ads ?? 0} pub(s)` +
      (s.failed ? `, ${s.failed} en échec` : "") + (s.exported ? `, ${s.exported} pub(s) exportée(s)` : "") +
      (s.duration_s ? ` en ${fmtDur(s.duration_s)}` : "") + ".";
    b.innerHTML = `<span>✅ ${esc(txt)}</span> <button type="button" class="btn small" id="lqBannerOk">OK</button>`;
    b.classList.remove("hidden");
    $("lqBannerOk").addEventListener("click", markSeen);
    notifyEnd(s, txt);
  }
  // Fin de file : une seule notification par run_id (cette page, puis « seen » côté serveur).
  function notifyEnd(s, txt) {
    const key = String(s.run_id || s.finished_at || "fin");
    if (notified.has(key)) return;
    notified.add(key);
    toast("📋 " + txt);
    try {
      if ("Notification" in window && Notification.permission === "granted" && document.visibilityState === "hidden") {
        new Notification("File locale terminée", { body: txt, tag: "ugc-local-queue-" + key });
      }
    } catch (_) { /* notifications indisponibles : le toast et le bandeau suffisent */ }
  }
  async function markSeen() {
    try {
      applyView(await call("/summary/seen", {}));
    } catch (e) {
      toast(e.message);
    }
  }

  function applyView(v) {
    if (!v || typeof v !== "object" || !("state" in v)) return;
    const wasActive = isActiveRun(view);
    view = v;
    renderProgress(v);
    renderControls(v);
    renderList(v);
    renderBanner(v);
    if (wasActive && !isActiveRun(v) && isVisible()) loadEligible();
    schedule();
  }
  async function refresh() {
    try {
      applyView(await api(Q));
    } catch (e) {
      $("lqProgress").innerHTML = `<p class="local-error">${esc(e.message)}</p>`;
      schedule();
    }
  }
  // 2 s onglet visible ; 15 s sinon, seulement tant que la file tourne (fin → notification).
  function schedule() {
    clearTimeout(timer);
    timer = null;
    const visible = isVisible();
    if (!visible && !isActiveRun(view)) return;
    timer = setTimeout(refresh, visible ? FAST_MS : SLOW_MS);
  }

  // ------------------------------------------------ actions
  async function act(path, body, okMsg) {
    busy = true;
    renderControls(view);
    try {
      applyView(await call(path, body));
      if (okMsg) toast(okMsg);
    } catch (e) {
      toast(e.message);
    } finally {
      busy = false;
      renderControls(view);
    }
  }
  $("lqPauseBtn").addEventListener("click", () => act("/pause", {}, "Pause demandée : le plan en cours se termine d'abord."));
  $("lqResumeBtn").addEventListener("click", () => act("/resume", {}, "File relancée ✓"));
  $("lqRetryBtn").addEventListener("click", () => act("/retry-failed", { ad_id: null }, "Plans en échec remis dans la file ✓"));
  $("lqCancelBtn").addEventListener("click", async () => {
    const ok = await showModal({
      title: "Annuler la file locale ?",
      message: "Le plan en cours est arrêté et les plans restants ne seront pas rendus. Les vidéos déjà faites sont gardées.",
      confirmText: "Annuler la file", cancelText: "Continuer", danger: true, enterConfirms: false,
    });
    if (ok) act("/cancel", {}, "File annulée.");
  });

  function currentOrder() {
    return [...$("lqList").querySelectorAll(".lq-item")].map((li) => Number(li.dataset.ad));
  }
  function sendOrder(ids) {
    return act("/reorder", { ad_ids: ids });
  }
  $("lqList").addEventListener("click", async (ev) => {
    const b = ev.target.closest("button[data-lq]");
    if (!b || busy) return;
    const li = b.closest(".lq-item");
    const adId = Number(li.dataset.ad);
    const what = b.dataset.lq;
    if (what === "up" || what === "down") {
      const ids = currentOrder();
      const i = ids.indexOf(adId);
      const j = what === "up" ? i - 1 : i + 1;
      if (i < 0 || j < 0 || j >= ids.length) return;
      [ids[i], ids[j]] = [ids[j], ids[i]];
      sendOrder(ids);
    } else if (what === "retry") {
      act("/retry-failed", { ad_id: adId }, "Plans en échec remis dans la file ✓");
    } else if (what === "remove") {
      const ok = await showModal({
        title: "Retirer cette pub de la file ?",
        message: "Ses plans restants ne seront pas rendus. Les vidéos déjà faites sont gardées.",
        confirmText: "Retirer", cancelText: "Annuler", danger: true,
      });
      if (!ok) return;
      try {
        applyView(await call("/remove", { ad_id: adId, cancel_running: false }));
        toast("Pub retirée de la file.");
      } catch (e) {
        if (e.status !== 409) return toast(e.message);
        const stop = await showModal({
          title: "Un plan de cette pub est en cours",
          message: "Arrêter le plan en cours et retirer la pub ?",
          confirmText: "Arrêter et retirer", cancelText: "Annuler", danger: true, enterConfirms: false,
        });
        if (stop) act("/remove", { ad_id: adId, cancel_running: true }, "Pub retirée de la file.");
      }
      loadEligible();
    }
  });

  // Glisser-déposer HTML5 (pubs en attente seulement) ; l'ordre est renvoyé au serveur au dépôt.
  $("lqList").addEventListener("dragstart", (ev) => {
    const li = ev.target.closest(".lq-item[draggable='true']");
    if (!li) return;
    dragId = Number(li.dataset.ad);
    li.classList.add("dragging");
    try { ev.dataTransfer.effectAllowed = "move"; ev.dataTransfer.setData("text/plain", String(dragId)); } catch (_) { /* ok */ }
  });
  $("lqList").addEventListener("dragover", (ev) => {
    if (dragId === null) return;
    const over = ev.target.closest(".lq-item");
    if (!over || Number(over.dataset.ad) === dragId) return;
    ev.preventDefault();
    const dragged = $("lqList").querySelector(`.lq-item[data-ad="${dragId}"]`);
    if (!dragged) return;
    const r = over.getBoundingClientRect();
    const after = ev.clientY > r.top + r.height / 2;
    over.parentNode.insertBefore(dragged, after ? over.nextSibling : over);
  });
  $("lqList").addEventListener("drop", (ev) => {
    if (dragId === null) return;
    ev.preventDefault();
  });
  $("lqList").addEventListener("dragend", () => {
    const moved = dragId !== null;
    dragId = null;
    $("lqList").querySelectorAll(".dragging").forEach((el) => el.classList.remove("dragging"));
    if (!moved) return;
    const before = ((view && view.ads) || []).slice()
      .sort((x, y) => (Number(x.position) || 0) - (Number(y.position) || 0)).map((a) => Number(a.ad_id));
    const ids = currentOrder();
    if (ids.join(",") !== before.join(",")) sendOrder(ids);
  });

  // ------------------------------------------------ activation
  function onShow() {
    if (!isVisible()) return;
    loadEligible();
    refresh();
  }
  const tabBtn = document.querySelector('#local [data-localtab="queue"]');
  // Après le gestionnaire de local.js (onglets) : le panneau est déjà affiché ici.
  if (tabBtn) tabBtn.addEventListener("click", onShow);
  document.querySelectorAll("#local [data-localtab]").forEach((b) => {
    if (b !== tabBtn) b.addEventListener("click", schedule);
  });
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => { if (btn.dataset.section === "local") onShow(); else schedule(); });
  });
  document.addEventListener("visibilitychange", () => { if (isVisible()) refresh(); else schedule(); });

  // Au chargement : une lecture pour savoir si une file tourne (suivi en arrière-plan + notification).
  refresh();
})();
