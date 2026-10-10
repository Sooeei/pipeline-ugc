"use strict";
// Keyframes — sur la carte d'un plan (Objet animé, Avatar IA, Mashup) :
//   • historique des VERSIONS de l'image (miniatures + « Utiliser cette version ») ;
//   • « Retoucher » : retouche ciblée Nano Banana Pro (image actuelle + consigne courte) ;
//   • outils locaux sans API : « 🧽 Effacer (gratuit) » (petit défaut), « Miroir », « Recadrer »
//     (rectangle tracé sur l'image agrandie) — chacun crée une nouvelle version ;
//   • « 📐 Même cadrage que le plan 1 » (Avatar IA, plans hors ancre) : régénération payante.
// + panneau « Réf visage auto » (Avatar IA).
// Chargé APRÈS app.js : réutilise $, api, toast, esc, showModal, currentSettings, prettyError.
// Points d'entrée globaux :
//   kfTools(container, s, { onChange, sameFraming })   → ajoute le bloc versions + outils à la carte
//   kfAutoFacePanel(adId)                 → (re)remplit #aoAutoFace (Avatar IA)
(function () {
  const fmtTs = (ts) => (ts ? new Date(ts * 1000).toLocaleString("fr-FR") : "");
  const post = (url, body) => api(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
  });
  // eslint-disable-next-line no-undef
  const isDry = () => typeof currentSettings !== "undefined" && !!(currentSettings && currentSettings.dry_run);

  // ------------------------------------------------ versions
  function versionsHtml(d) {
    const vs = (d && d.versions) || [];
    if (vs.length < 2) {
      return `<div class="muted small">${vs.length ? "Une seule version pour l'instant." : "Aucune image pour l'instant."}</div>`;
    }
    return `<div class="kf-versions">` + vs.map((v) =>
      `<div class="kf-ver${v.current ? " current" : ""}" title="${esc((v.prompt || v.note || "").slice(0, 600))}">` +
      (v.url && v.exists ? `<img src="${esc(v.url)}" alt="version ${esc(v.v)}" loading="lazy" />`
        : `<div class="kf-ver-missing">fichier absent</div>`) +
      `<div class="kf-ver-meta"><b>v${esc(v.v)}</b> · ${esc(v.source_label || v.source)}` +
      (v.generation_id ? ` · <span class="muted">#${esc(v.generation_id)}</span>` : "") +
      `<br><span class="muted">${esc(fmtTs(v.ts))}</span></div>` +
      (v.current ? `<span class="badge ok">actuelle</span>`
        : `<button class="btn small kf-use" type="button" data-v="${esc(v.v)}"${v.exists ? "" : " disabled"}>Utiliser cette version</button>`) +
      `</div>`).join("") + `</div>`;
  }

  async function fillVersions(box, s, onChange) {
    const body = box.querySelector(".kf-ver-body");
    let d;
    try {
      d = await api(`/api/clips/${s.clip_id}/versions`);
    } catch (e) {
      body.innerHTML = `<div class="muted small">${esc(e.message)}</div>`;
      return;
    }
    box.querySelector(".kf-ver-count").textContent = d.versions.length > 1 ? ` (${d.versions.length})` : "";
    body.innerHTML = versionsHtml(d);
    body.querySelectorAll(".kf-use").forEach((btn) => btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const r = await post(`/api/clips/${s.clip_id}/versions/${btn.dataset.v}/use`);
        toast(r.changed ? `Version v${r.v} utilisée — l'image est à revalider.` : "C'est déjà l'image actuelle.");
        if (onChange) await onChange();
      } catch (e) {
        btn.disabled = false;
        toast(e.message);
      }
    }));
  }

  // ------------------------------------------------ tracé d'un rectangle sur l'image agrandie
  // Renvoie {x, y, w, h} RELATIFS (0..1) + options, ou null si annulé.
  function pickRect(imageUrl, { title, hint, confirmText, withFormat }) {
    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.className = "modal-overlay kf-rect-overlay";
      ov.innerHTML =
        `<div class="modal wide kf-rect-modal" role="dialog" aria-modal="true">` +
        `<h3 class="modal-title">${esc(title)}</h3>` +
        `<p class="muted small">${esc(hint)}</p>` +
        `<div class="kf-rect-stage"><img alt="image du plan" /><canvas></canvas></div>` +
        (withFormat
          ? `<label class="kf-rect-fmt">Format final <select>` +
            `<option value="plan">9:16 — 720x1280 (format du plan)</option>` +
            `<option value="original">Format d'origine de l'image</option></select></label>`
          : "") +
        `<div class="modal-actions"><button class="btn" type="button" data-act="cancel">Annuler</button>` +
        `<button class="btn primary" type="button" data-act="ok" disabled>${esc(confirmText)}</button></div></div>`;
      document.body.appendChild(ov);
      const img = ov.querySelector("img");
      const cv = ov.querySelector("canvas");
      const okBtn = ov.querySelector('[data-act="ok"]');
      const ctx = cv.getContext("2d");
      let rect = null;
      let start = null;
      const draw = () => {
        ctx.clearRect(0, 0, cv.width, cv.height);
        if (!rect) return;
        ctx.fillStyle = "rgba(0,0,0,.35)";
        ctx.fillRect(0, 0, cv.width, cv.height);
        ctx.clearRect(rect.x, rect.y, rect.w, rect.h);
        ctx.strokeStyle = "#ffcc00";
        ctx.lineWidth = 2;
        ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
      };
      const pos = (ev) => {
        const b = cv.getBoundingClientRect();
        const p = ev.touches ? ev.touches[0] : ev;
        return { x: Math.min(Math.max(p.clientX - b.left, 0), b.width), y: Math.min(Math.max(p.clientY - b.top, 0), b.height) };
      };
      img.onload = () => { cv.width = img.clientWidth; cv.height = img.clientHeight; draw(); };
      img.src = imageUrl;
      const down = (ev) => { ev.preventDefault(); start = pos(ev); rect = { x: start.x, y: start.y, w: 0, h: 0 }; draw(); };
      const move = (ev) => {
        if (!start) return;
        ev.preventDefault();
        const p = pos(ev);
        rect = { x: Math.min(start.x, p.x), y: Math.min(start.y, p.y), w: Math.abs(p.x - start.x), h: Math.abs(p.y - start.y) };
        draw();
      };
      const up = () => { start = null; okBtn.disabled = !(rect && rect.w > 4 && rect.h > 4); };
      cv.addEventListener("mousedown", down);
      cv.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
      cv.addEventListener("touchstart", down, { passive: false });
      cv.addEventListener("touchmove", move, { passive: false });
      cv.addEventListener("touchend", up);
      const close = (val) => { window.removeEventListener("mouseup", up); ov.remove(); resolve(val); };
      ov.querySelector('[data-act="cancel"]').addEventListener("click", () => close(null));
      ov.addEventListener("click", (ev) => { if (ev.target === ov) close(null); });
      okBtn.addEventListener("click", () => {
        if (!rect || !cv.width || !cv.height) return close(null);
        const fmt = ov.querySelector(".kf-rect-fmt select");
        close({ x: rect.x / cv.width, y: rect.y / cv.height, w: rect.w / cv.width, h: rect.h / cv.height,
          format: fmt ? fmt.value : "plan" });
      });
    });
  }

  // ------------------------------------------------ carte d'un plan
  const ERASE_HINT = "grain de beauté, petite tache, texte, étiquette, trépied… — local, gratuit, immédiat";

  // « 📐 Même cadrage que le plan 1 » : côté du logo du produit (droite / gauche / même côté).
  function pickFramingSide() {
    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.className = "modal-overlay kf-rect-overlay";
      ov.innerHTML =
        `<div class="modal" role="dialog" aria-modal="true">` +
        `<h3 class="modal-title">📐 Même cadrage que le plan 1</h3>` +
        `<p class="muted small">L'image est regénérée avec la même position de caméra, la même distance et la même ` +
        `orientation du produit que le plan 1 (l'ancre). De quel côté doit apparaître le logo du produit ?</p>` +
        `<p class="muted small">Seul le côté du logo est faux ? « ↔️ Miroir » (gratuit) suffit souvent.</p>` +
        `<div class="modal-actions">` +
        `<button class="btn" type="button" data-side="gauche">Logo à gauche</button>` +
        `<button class="btn" type="button" data-side="droite">Logo à droite</button>` +
        `<button class="btn primary" type="button" data-side="auto">Même côté que le plan 1</button>` +
        `<button class="btn" type="button" data-act="cancel">Annuler</button></div></div>`;
      document.body.appendChild(ov);
      const close = (val) => { ov.remove(); resolve(val); };
      ov.querySelector('[data-act="cancel"]').addEventListener("click", () => close(null));
      ov.addEventListener("click", (ev) => { if (ev.target === ov) close(null); });
      ov.querySelectorAll("[data-side]").forEach((b) => b.addEventListener("click", () => close(b.dataset.side)));
    });
  }

  const SIDE_LABELS = { droite: "logo à droite", gauche: "logo à gauche", auto: "logo du même côté" };

  function kfTools(container, s, { onChange, sameFraming } = {}) {
    if (!container || !s || !s.clip_id) return;
    const wrap = document.createElement("div");
    wrap.className = "kf-tools";
    const hasImg = !!s.image_url;
    const dis = hasImg ? "" : " disabled";
    wrap.innerHTML =
      `<div class="kf-tool-row">` +
      `<button class="btn small kf-retouch" type="button"${dis} title="Modifie UN détail de l'image actuelle (Nano Banana Pro, payant) — ≠ Regénérer, qui repart de zéro">✏️ Retoucher</button>` +
      `<button class="btn small kf-erase" type="button"${dis} title="Efface un petit défaut : ${esc(ERASE_HINT)}">🧽 Effacer (gratuit)</button>` +
      `<button class="btn small kf-mirror" type="button"${dis} title="Miroir horizontal (local, gratuit) — ex. logo du produit du mauvais côté">↔️ Miroir</button>` +
      `<button class="btn small kf-crop" type="button"${dis} title="Recadre puis remet au format 9:16 (local, gratuit)">✂️ Recadrer</button>` +
      (sameFraming === true
        ? `<button class="btn small kf-same-framing" type="button" title="Regénère l'image (payant) avec la même position de caméra, distance et orientation du produit que le plan 1. Si seul le côté du logo est faux : « ↔️ Miroir » (gratuit).">📐 Même cadrage que le plan 1</button>`
        : "") +
      `</div>` +
      `<div class="kf-retouch-form hidden">` +
      `<input type="text" class="kf-retouch-txt" maxlength="300" placeholder="Ce qui change UNIQUEMENT — ex. « le pull en bleu marine »" />` +
      `<label class="small"><input type="checkbox" class="kf-retouch-prod" /> Envoyer aussi les photos produit (réfs produit + toutes les photos de la fiche)</label>` +
      `<button class="btn small primary kf-retouch-go" type="button">Lancer la retouche</button>` +
      `<span class="kf-retouch-prog muted small" aria-live="polite"></span>` +
      `<div class="muted small kf-retouch-help">Ta consigne part mot pour mot (le français est compris). ` +
      `Petit défaut ? 🧽 Effacer : local, gratuit, immédiat.</div>` +
      `</div>` +
      `<details class="kf-ver-box"><summary>🗂️ Versions de l'image<span class="kf-ver-count"></span></summary><div class="kf-ver-body"></div></details>`;
    container.appendChild(wrap);
    const card = container.closest(".obj-shot") || container;
    const box = wrap.querySelector(".kf-ver-box");
    box.addEventListener("toggle", () => { if (box.open) fillVersions(box, s, onChange); });
    // Compteur de versions affiché d'emblée (une requête légère par carte).
    api(`/api/clips/${s.clip_id}/versions`).then((d) => {
      const n = (d.versions || []).length;
      box.querySelector(".kf-ver-count").textContent = n > 1 ? ` (${n})` : "";
      const corr = card.querySelector(".kf-corr");
      if (corr && !corr.value && d.last_correction) corr.value = d.last_correction;
    }).catch(() => {});

    const run = async (fn, okMsg) => {
      card.classList.add("busy");
      try {
        await fn();
        if (okMsg) toast(okMsg);
        if (onChange) await onChange();
        else card.classList.remove("busy");
      } catch (e) {
        card.classList.remove("busy");
        toast(typeof prettyError === "function" ? prettyError(e.message) : e.message);
      }
    };

    const form = wrap.querySelector(".kf-retouch-form");
    wrap.querySelector(".kf-retouch").addEventListener("click", () => {
      form.classList.toggle("hidden");
      if (!form.classList.contains("hidden")) form.querySelector(".kf-retouch-txt").focus();
    });
    wrap.querySelector(".kf-retouch-go").addEventListener("click", async () => {
      const instruction = form.querySelector(".kf-retouch-txt").value.trim();
      if (!instruction) return toast("Écris la retouche voulue.");
      const with_product_refs = form.querySelector(".kf-retouch-prod").checked;
      if (!isDry()) {
        const ok = await showModal({
          title: "Retoucher l'image",
          message: `Retouche Nano Banana Pro (payant) : « ${instruction} ». Le reste de l'image est gardé ; une nouvelle version est créée (à revalider). Continuer ?`,
          confirmText: "Retoucher", cancelText: "Annuler", danger: true,
        });
        if (!ok) return;
      }
      // Job de FOND (~30 s en réel) : progression dans la carte, le reste de l'interface reste libre.
      const prog = form.querySelector(".kf-retouch-prog");
      const go = form.querySelector(".kf-retouch-go");
      const t0 = Date.now();
      go.disabled = true;
      card.classList.add("busy");
      prog.textContent = "⏳ Retouche lancée…";
      try {
        const r = await post(`/api/clips/${s.clip_id}/retouch`, { instruction, with_product_refs, confirm: true });
        const j = await waitJob(r.job_id, (snap) => {
          const sc = (snap.scenes || [])[0] || {};
          const secs = Math.round((Date.now() - t0) / 1000);
          prog.textContent = `⏳ ${sc.message || "Retouche en cours…"} ${secs} s`;
        });
        if (j.state === "echec") throw new Error((j.summary && j.summary.message) || "Retouche impossible.");
        prog.textContent = "";
        toast("Retouche faite ✓ — nouvelle version à valider.");
        if (onChange) await onChange();
        else card.classList.remove("busy");
      } catch (e) {
        prog.textContent = "";
        card.classList.remove("busy");
        toast(typeof prettyError === "function" ? prettyError(e.message) : e.message);
      } finally {
        go.disabled = false;
      }
    });
    wrap.querySelector(".kf-mirror").addEventListener("click", () =>
      run(() => post(`/api/clips/${s.clip_id}/tools/mirror`), "Miroir appliqué ✓ — nouvelle version."));
    wrap.querySelector(".kf-erase").addEventListener("click", async () => {
      const r = await pickRect(s.image_url, {
        title: "🧽 Effacer (gratuit)",
        hint: `Trace un rectangle autour du défaut à effacer : ${ERASE_HINT}. Seuls les pixels contrastés de la zone sont repeints.`,
        confirmText: "Effacer",
      });
      if (r) run(() => post(`/api/clips/${s.clip_id}/tools/erase`, r), "Zone effacée ✓ — nouvelle version.");
    });
    const sf = wrap.querySelector(".kf-same-framing");
    if (sf) sf.addEventListener("click", async () => {
      const side = await pickFramingSide();
      if (!side) return;
      if (!isDry()) {
        const ok = await showModal({
          title: "📐 Même cadrage que le plan 1",
          message: `Regénérer cette image via Nano Banana Pro (payant) avec le cadrage du plan 1 (${SIDE_LABELS[side]}). ` +
            "Le keyframe devra être revalidé. Continuer ?",
          confirmText: "Regénérer", cancelText: "Annuler", danger: true,
        });
        if (!ok) return;
      }
      card.classList.add("busy");
      sf.disabled = true;
      try {
        const r = await post(`/api/avatar-omni/regenerate-image/${s.clip_id}`, { same_framing: side, confirm: true });
        if (r && r.job_id) {
          const j = await waitJob(r.job_id);
          if (j.state === "echec") throw new Error((j.summary && j.summary.message) || "Régénération en échec.");
        }
        toast("Même cadrage que le plan 1 ✓ — nouvelle image à valider.");
        if (onChange) await onChange();
        else card.classList.remove("busy");
      } catch (e) {
        card.classList.remove("busy");
        toast(typeof prettyError === "function" ? prettyError(e.message) : e.message);
      } finally {
        sf.disabled = false;
      }
    });
    wrap.querySelector(".kf-crop").addEventListener("click", async () => {
      const r = await pickRect(s.image_url, {
        title: "Recadrer", hint: "Trace le rectangle à garder.", confirmText: "Recadrer", withFormat: true,
      });
      if (r) run(() => post(`/api/clips/${s.clip_id}/tools/crop`, r), "Recadrage fait ✓ — nouvelle version.");
    });
  }

  // Attend la fin d'un job de fond (/api/jobs/{id}) en rappelant `onTick(snapshot)` chaque seconde.
  async function waitJob(jobId, onTick) {
    for (;;) {
      const snap = await api(`/api/jobs/${jobId}`);
      if (onTick) onTick(snap);
      if (!["en_cours", "en_attente"].includes(snap.state)) return snap;
      await new Promise((r) => setTimeout(r, 1000));
    }
  }

  // ------------------------------------------------ réf visage auto (Avatar IA)
  async function kfAutoFacePanel(adId) {
    const el = document.getElementById("aoAutoFace");
    if (!el || !adId) return;
    let d;
    try {
      d = await api(`/api/ads/${adId}/auto-face`);
    } catch (_) {
      el.innerHTML = "";
      return;
    }
    // Une carte par perso : sa réf visage générée, comment elle a été recadrée, « Changer » / « Retirer ».
    const cards = (d.refs || []).map((r, i) => {
      const who = `Perso ${esc(String(r.character || ""))}${r.name ? ` (${esc(r.name)})` : ""}`;
      const warn = r.method === "approx" ? " kf-af-warn" : "";
      return `<div class="kf-af-card${warn}" data-i="${i}">` +
        (r.url ? `<img src="${esc(r.url)}" alt="réf visage ${who}" />` : `<div class="kf-ver-missing">absente</div>`) +
        `<div class="kf-af-meta"><b>${who}</b><br><span class="small">Réf « Visage perso ${esc(String(r.character || ""))} »` +
        `${r.source_n ? ` · depuis le plan ${esc(String(r.source_n))}` : ""}</span>` +
        (r.method_label ? `<br><span class="small kf-af-method">${esc(r.method_label)}</span>` : "") +
        `<div class="kf-tool-row"><button class="btn small kf-af-change" type="button">🔁 Changer</button>` +
        `<button class="btn small kf-af-del" type="button">Retirer</button></div></div></div>`;
    }).join("");
    el.innerHTML =
      `<label class="small"><input type="checkbox" class="kf-af-on"${d.enabled ? " checked" : ""} /> ` +
      `Réf visage automatique : la 1re image validée où un perso apparaît seul devient sa réf « Visage perso N » ` +
      `(jamais à la place d'une réf que tu as fournie)</label>` +
      (d.detector_label ? `<p class="muted small">${esc(d.detector_label)}</p>` : "") +
      (cards ? `<div class="kf-af-refs">${cards}</div>` : "");
    el.querySelector(".kf-af-on").addEventListener("change", async (ev) => {
      try {
        await post(`/api/ads/${adId}/auto-face`, { enabled: ev.target.checked });
        toast(ev.target.checked ? "Réf visage auto activée." : "Réf visage auto désactivée.");
      } catch (e) { toast(e.message); }
    });
    el.querySelectorAll(".kf-af-card").forEach((card) => {
      const r = d.refs[Number(card.dataset.i)];
      card.querySelector(".kf-af-del").addEventListener("click", async () => {
        try {
          await api(`/api/ads/${adId}/auto-face?kind=${encodeURIComponent(r.kind)}`, { method: "DELETE" });
          toast("Réf visage auto retirée.");
          kfAutoFacePanel(adId);
        } catch (e) { toast(e.message); }
      });
      card.querySelector(".kf-af-change").addEventListener("click", async () => {
        const pick = await pickFaceSource(r);
        if (!pick) return;
        try {
          await post(`/api/ads/${adId}/auto-face/${r.id}`, pick);
          toast("Réf visage mise à jour ✓ — elle part sur les prochains plans de ce perso.");
          kfAutoFacePanel(adId);
        } catch (e) { toast(e.message); }
      });
    });
  }

  // « Changer » : choisir l'image de plan source, puis recadrer le visage à la main (ou laisser l'auto).
  function pickFaceSource(r) {
    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.className = "modal-overlay kf-rect-overlay";
      const thumbs = (r.candidates || []).map((c) =>
        `<button type="button" class="kf-af-src${c.clip_id === r.source_clip_id ? " current" : ""}" data-id="${c.clip_id}">` +
        `<img src="${esc(c.image_url)}" alt="plan ${c.n}" /><span class="small">Plan ${c.n}</span></button>`).join("");
      ov.innerHTML =
        `<div class="modal wide" role="dialog" aria-modal="true">` +
        `<h3 class="modal-title">Changer la réf visage</h3>` +
        `<p class="muted small">Choisis l'image d'un plan où ce perso apparaît, puis trace le cadre du visage ` +
        `(« Recadrage auto » garde le recadrage automatique).</p>` +
        (thumbs ? `<div class="kf-af-srcs">${thumbs}</div>` : `<p class="muted">Aucun plan avec image pour ce perso.</p>`) +
        `<div class="modal-actions"><button class="btn" type="button" data-act="cancel">Annuler</button></div></div>`;
      document.body.appendChild(ov);
      const close = (val) => { ov.remove(); resolve(val); };
      ov.querySelector('[data-act="cancel"]').addEventListener("click", () => close(null));
      ov.addEventListener("click", (ev) => { if (ev.target === ov) close(null); });
      ov.querySelectorAll(".kf-af-src").forEach((b) => b.addEventListener("click", async () => {
        const clipId = Number(b.dataset.id);
        const url = b.querySelector("img").getAttribute("src");
        ov.style.display = "none";
        const rect = await pickRect(url, {
          title: "Recadrer le visage",
          hint: "Trace un cadre autour du visage (cheveux et menton compris). Sans tracé : recadrage automatique.",
          confirmText: "Utiliser ce visage",
        });
        if (rect === null && !(await showModal({
          title: "Recadrage automatique ?", message: "Aucun cadre tracé : utiliser le recadrage automatique sur cette image ?",
          confirmText: "Oui", cancelText: "Non",
        }))) return close(null);
        close(rect ? { clip_id: clipId, x: rect.x, y: rect.y, w: rect.w, h: rect.h } : { clip_id: clipId });
      }));
    });
  }

  window.kfTools = kfTools;
  window.kfAutoFacePanel = kfAutoFacePanel;
})();
