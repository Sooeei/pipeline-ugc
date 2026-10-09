"use strict";
// Traçabilité — panneau « Détails de la génération » par plan, raisons « gardé / régénéré /
// rejeté » en 1 clic (jamais bloquant) et page « Stats ».
// Chargé APRÈS app.js : réutilise $, api, toast, esc, usd. Points d'entrée globaux :
//   traceDetails(container, clipId)                 → ajoute le panneau repliable au plan
//   traceNow()                                      → horodatage à prendre AVANT une relance
//   traceFeedback(clipId, action, kind, {before, suggest})  → journalise + propose les raisons
(function () {
  const ROLE_LABELS = {
    first_frame: "Start frame (image de départ)",
    reference: "Référence",
    anchor: "Ancre à retoucher",
    main_ref: "Réf principale",
    character: "Personnage",
  };
  const REASONS = {
    perso_different: "Perso différent",
    start_frame: "Start frame non respectée",
    voix: "Voix",
    lipsync: "Lip-sync",
    replique_coupee: "Réplique coupée",
    cadrage: "Cadrage",
    texte_incruste: "Texte incrusté",
    autre: "Autre",
  };
  const fmtTs = (ts) => (ts ? new Date(ts * 1000).toLocaleString("fr-FR") : "");

  // ------------------------------------------------ rendu d'une génération
  function costHtml(g) {
    if (g.dry_run) return `${usd(0)} <span class="muted">(simulation — réel estimé ${usd(g.usd_estimate)})</span>`;
    return `${usd(g.usd)}` + (Math.abs(g.usd - g.usd_estimate) > 0.005
      ? ` <span class="muted">(estimé ${usd(g.usd_estimate)})</span>` : "");
  }

  function paramsHtml(p) {
    const parts = [];
    if (p.seconds) parts.push(`${esc(p.seconds)} s`);
    if (p.resolution) parts.push(esc(p.resolution));
    if (p.aspect) parts.push(esc(p.aspect));
    if (p.size) parts.push(esc(p.size));
    if (p.extension) parts.push("extension");
    if (p.store) parts.push("chaîne (store)");
    if (p.generate_audio) parts.push("audio natif");
    return parts.join(" · ") || "—";
  }

  function genHtml(g, title) {
    const imgs = (g.images || []).length
      ? `<ol class="gt-imgs">` + g.images.map((im) =>
        `<li title="${esc(im.path)}">` +
        (im.url ? `<img src="${esc(im.url)}" alt="image ${esc(im.n)}" loading="lazy" />` : `<span class="gt-noimg">?</span>`) +
        `<span><b>Image ${esc(im.n)}</b> — ${esc(ROLE_LABELS[im.role] || im.role || "—")}<br>` +
        `<span class="muted small">${esc(String(im.path || "").split(/[\\/]/).pop())}</span></span></li>`).join("") + `</ol>`
      : `<div class="muted small">Aucune image envoyée (texte seul / extension).</div>`;
    const issues = (g.issues || []).length
      ? `<ul class="gt-issues">` + g.issues.map((i) =>
        `<li class="${i.level === "error" ? "ko" : "warn"}">${i.level === "error" ? "⛔" : "⚠"} ${esc(i.message || i.code)}</li>`).join("") + `</ul>`
      : `<div class="muted small">Aucun avertissement du contrôle avant envoi.</div>`;
    return `<div class="gt-gen">` +
      `<div class="gt-title"><b>${esc(title)}</b> <span class="muted small">#${esc(g.id)} · ${esc(fmtTs(g.ts))}` +
      `${g.step_label ? " · " + esc(g.step_label) : ""}</span></div>` +
      `<table class="gt-meta"><tr><th>Modèle</th><td><code>${esc(g.model || "—")}</code></td></tr>` +
      `<tr><th>Paramètres</th><td>${paramsHtml(g.params || {})}</td></tr>` +
      (g.interaction_id ? `<tr><th>interaction_id</th><td><code>${esc(g.interaction_id)}</code></td></tr>` : "") +
      `<tr><th>Coût</th><td>${costHtml(g)}</td></tr></table>` +
      `<div class="lbl">Prompt final exact <button class="btn small gt-copy" type="button">Copier</button></div>` +
      `<pre class="gt-prompt">${esc(g.prompt || "")}</pre>` +
      `<div class="lbl">Images envoyées (dans l'ordre)</div>${imgs}` +
      `<div class="lbl">Contrôle avant envoi</div>${issues}` +
      `</div>`;
  }

  function bindCopy(root, gens) {
    root.querySelectorAll(".gt-copy").forEach((btn, i) => {
      btn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        const text = (gens[i] && gens[i].prompt) || "";
        try {
          await navigator.clipboard.writeText(text);
          toast("Prompt copié ✓");
        } catch (_) {
          const pre = btn.closest(".gt-gen").querySelector(".gt-prompt");
          const r = document.createRange();
          r.selectNodeContents(pre);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(r);
          toast("Sélectionné — Ctrl+C pour copier.");
        }
      });
    });
  }

  async function fillDetails(box, clipId) {
    const body = box.querySelector(".gt-body");
    body.innerHTML = `<div class="muted small">Chargement…</div>`;
    let d;
    try {
      d = await api(`/api/clips/${clipId}/generations`);
    } catch (e) {
      body.innerHTML = `<div class="muted small">${esc(e.message)}</div>`;
      return;
    }
    const shown = [];
    let html = "";
    if (d.last_image) { html += genHtml(d.last_image, "🖼️ Dernière image"); shown.push(d.last_image); }
    if (d.last_video) {
      html += genHtml(d.last_video, "🎬 Dernière vidéo");
      shown.push(d.last_video);
      html += `<div class="gt-verdict"><span class="muted small">Cette vidéo :</span>` +
        `<button class="btn small gt-keep" type="button">✓ Je la garde</button>` +
        `<button class="btn small gt-reject" type="button">✗ Je la rejette</button></div>`;
    }
    if (!shown.length) html = `<div class="muted small">Aucune génération journalisée pour ce plan (les plans générés avant cette version n'ont pas d'historique).</div>`;
    const older = (d.history || []).filter((g) => !shown.some((s) => s.id === g.id));
    if (older.length) {
      html += `<details class="gt-history"><summary>Historique (${older.length} génération${older.length > 1 ? "s" : ""} précédente${older.length > 1 ? "s" : ""})</summary>` +
        older.map((g) => genHtml(g, g.kind === "image" ? "🖼️ Image" : "🎬 Vidéo")).join("") + `</details>`;
      shown.push(...older);
    }
    const fb = (d.feedback || []).slice(0, 5);
    if (fb.length) {
      html += `<div class="gt-fb muted small">Décisions : ` + fb.map((f) =>
        `${esc(f.action)}${f.reason_label ? " (" + esc(f.reason_label) + ")" : ""}`).join(" · ") + `</div>`;
    }
    body.innerHTML = html;
    bindCopy(body, shown);
    const keep = body.querySelector(".gt-keep");
    if (keep) keep.addEventListener("click", () => traceFeedback(clipId, "gardé", "video").then(() => fillDetails(box, clipId)));
    const rej = body.querySelector(".gt-reject");
    if (rej) rej.addEventListener("click", () => traceFeedback(clipId, "rejeté", "video").then(() => fillDetails(box, clipId)));
  }

  // Panneau repliable, chargé à l'ouverture (aucune requête tant qu'il reste fermé).
  function traceDetails(container, clipId) {
    if (!container || !clipId) return;
    const box = document.createElement("details");
    box.className = "gen-trace";
    box.innerHTML = `<summary>🔎 Détails de la génération</summary><div class="gt-body"></div>`;
    box.addEventListener("toggle", () => { if (box.open) fillDetails(box, clipId); });
    container.appendChild(box);
  }

  // ------------------------------------------------ feedback : raison en 1 clic (non bloquant)
  function traceNow() {
    return Date.now() / 1000;
  }

  let barTimer = null;
  function showReasonBar(fid, action, suggest) {
    let bar = $("fbReasonBar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "fbReasonBar";
      bar.className = "fb-bar";
      bar.setAttribute("role", "status");
      document.body.appendChild(bar);
    }
    const chips = Object.entries(REASONS).map(([k, label]) =>
      `<button type="button" class="fb-chip${k === suggest ? " sugg" : ""}" data-reason="${k}">${esc(label)}</button>`).join("");
    bar.innerHTML = `<div class="fb-head"><span>Plan ${esc(action)} — pourquoi ? <span class="muted small">(facultatif)</span></span>` +
      `<button type="button" class="fb-close" title="Ignorer">✕</button></div><div class="fb-chips">${chips}</div>`;
    bar.classList.remove("hidden");
    const hide = () => { bar.classList.add("hidden"); clearTimeout(barTimer); };
    bar.querySelector(".fb-close").addEventListener("click", hide);
    bar.querySelectorAll(".fb-chip").forEach((b) => b.addEventListener("click", async () => {
      hide();
      try {
        await api(`/api/feedback/${fid}/reason`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: b.dataset.reason }),
        });
        toast("Raison notée ✓ (page Stats)");
      } catch (e) { toast(e.message); }
    }));
    clearTimeout(barTimer);
    barTimer = setTimeout(hide, 20000);
  }

  // Journalise la décision ; propose les raisons pour « régénéré » / « rejeté ». Ne lève jamais.
  async function traceFeedback(clipId, action, kind, opts = {}) {
    if (!clipId) return null;
    try {
      const r = await api("/api/feedback", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clip_id: clipId, action, kind: kind || "", before: opts.before ?? null }),
      });
      if (r && r.id && action !== "gardé") showReasonBar(r.id, action, opts.suggest || "");
      return r;
    } catch (_) {
      return null;   // le journal ne doit jamais gêner l'utilisateur
    }
  }

  // ------------------------------------------------ page Stats
  const pct = (x) => (x == null ? "—" : Math.round(x * 100) + " %");
  const money = (x) => (x == null ? "—" : usd(x));

  async function loadStats() {
    const root = $("statsContent");
    if (!root) return;
    root.innerHTML = `<p class="muted">Chargement…</p>`;
    let s;
    try {
      s = await api("/api/stats");
    } catch (e) {
      root.innerHTML = `<p class="muted">${esc(e.message)}</p>`;
      return;
    }
    const byMode = (s.by_mode || []).map((m) =>
      `<tr><td>${esc(m.mode_label || "—")}</td><td class="num">${esc(m.plans_gardes)}</td>` +
      `<td class="num">${esc(m.garde)} / ${esc(m.total)} <b>${pct(m.taux_garde)}</b></td>` +
      `<td class="num">${esc(m.generations)}</td><td class="num">${money(m.usd)}</td>` +
      `<td class="num">${money(m.usd_par_plan_garde)}</td><td class="num muted">${money(m.usd_estime_par_plan_garde)}</td></tr>`).join("");
    const byModel = (s.by_model || []).map((m) =>
      `<tr><td>${esc(m.mode_label || "—")}</td><td><code>${esc(m.model || "—")}</code></td>` +
      `<td class="num">${esc(m.garde)}</td><td class="num">${esc(m.regenere)}</td><td class="num">${esc(m.rejete)}</td>` +
      `<td class="num"><b>${pct(m.taux_garde)}</b></td></tr>`).join("");
    const maxR = Math.max(1, ...(s.reasons || []).map((r) => r.count));
    const reasons = (s.reasons || []).map((r) =>
      `<li><span class="st-lbl">${esc(r.label)}</span><span class="st-bar"><i style="width:${Math.round((r.count / maxR) * 100)}%"></i></span>` +
      `<span class="num">${esc(r.count)}</span></li>`).join("");
    const t = s.total || {};
    // Essais par plan validé (générations image / vidéo jusqu'à l'état gardé).
    const es = s.essais || {};
    const avgTxt = (x) => (x && x.plans ? `${String(x.moyenne).replace(".", ",")} <span class="muted small">(${esc(x.plans)} plan(s), max ${esc(x.max)})</span>` : "—");
    const essaisMode = (es.by_mode || []).map((m) =>
      `<tr><td>${esc(m.mode_label || "—")}</td><td class="num">${avgTxt(m.image)}</td><td class="num">${avgTxt(m.video)}</td></tr>`).join("");
    const essaisModel = (es.by_model || []).map((m) =>
      `<tr><td>${esc(m.mode_label || "—")}</td><td>${m.kind === "video" ? "Vidéo" : "Image"}</td><td><code>${esc(m.model || "—")}</code></td>` +
      `<td class="num">${esc(m.plans)}</td><td class="num"><b>${esc(String(m.moyenne).replace(".", ","))}</b></td><td class="num">${esc(m.max)}</td></tr>`).join("");
    const essaisHtml = `<div class="card-block"><h2>Essais par plan validé</h2>` +
      ((es.image && es.image.plans) || (es.video && es.video.plans)
        ? `<p>Moyenne : <b>image</b> ${avgTxt(es.image)} · <b>vidéo</b> ${avgTxt(es.video)}</p>` +
          `<table class="cost-table"><tr><th>Mode</th><th>Essais image / plan</th><th>Essais vidéo / plan</th></tr>${essaisMode}</table>` +
          `<table class="cost-table"><tr><th>Mode</th><th>Type</th><th>Modèle</th><th>Plans validés</th><th>Essais moyens</th><th>Max</th></tr>${essaisModel}</table>`
        : `<p class="muted">Aucun plan validé pour l'instant.</p>`) +
      `<p class="muted small">Nombre de générations (keyframe, régénérations, retouches ; clips vidéo) faites sur un plan avant qu'il soit gardé.</p></div>`;
    root.innerHTML =
      `<div class="cards">` +
      `<div class="card"><div class="card-label">Décisions notées</div><div class="card-value">${esc(t.decisions ?? 0)}</div></div>` +
      `<div class="card"><div class="card-label">Plans gardés</div><div class="card-value">${esc(t.plans_gardes ?? 0)}</div></div>` +
      `<div class="card"><div class="card-label">Dépenses réelles (Coûts)</div><div class="card-value">${money(t.cost_events_usd)}</div></div>` +
      `<div class="card"><div class="card-label">Coût moyen / plan gardé</div><div class="card-value">${money(t.usd_par_plan_garde)}</div></div>` +
      `</div>` +
      `<div class="card-block"><h2>Par mode</h2>` +
      (byMode ? `<table class="cost-table"><tr><th>Mode</th><th>Plans gardés</th><th>Gardés / décisions</th><th>Générations</th>` +
        `<th>Coût réel</th><th>Coût réel / plan gardé</th><th>Estimé / plan gardé</th></tr>${byMode}</table>`
        : `<p class="muted">Aucune donnée pour l'instant.</p>`) +
      `<p class="muted small">« Estimé » = ce qu'auraient coûté les générations (simulation comprise), d'après les tarifs de l'app.</p></div>` +
      `<div class="card-block"><h2>Taux de plans gardés par modèle</h2>` +
      (byModel ? `<table class="cost-table"><tr><th>Mode</th><th>Modèle</th><th>Gardés</th><th>Régénérés</th><th>Rejetés</th><th>Taux gardé</th></tr>${byModel}</table>`
        : `<p class="muted">Valide, régénère ou rejette des plans pour remplir ce tableau.</p>`) + `</div>` +
      essaisHtml +
      `<div class="card-block"><h2>Raisons de rejet les plus fréquentes</h2>` +
      (reasons ? `<ul class="st-reasons">${reasons}</ul>` : `<p class="muted">Aucune raison notée (clique une puce après une régénération ou un rejet).</p>`) +
      `</div>`;
  }

  const navBtn = document.querySelector('.nav-item[data-section="stats"]');
  if (navBtn) navBtn.addEventListener("click", loadStats);
  const refresh = $("refreshStats");
  if (refresh) refresh.addEventListener("click", loadStats);

  window.traceDetails = traceDetails;
  window.traceFeedback = traceFeedback;
  window.traceNow = traceNow;
  window.loadStats = loadStats;
})();
