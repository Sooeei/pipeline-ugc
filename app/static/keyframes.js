"use strict";
// Keyframes — sur la carte d'un plan (Objet animé, Avatar IA, Mashup) :
//   • historique des VERSIONS de l'image (miniatures + « Utiliser cette version ») ;
//   • « Retoucher » : retouche ciblée Nano Banana Pro (image actuelle + consigne courte) ;
//   • outils locaux sans API : « Miroir », « Effacer une zone », « Recadrer » (rectangle tracé
//     sur l'image agrandie) — chacun crée une nouvelle version.
// + panneau « Réf visage auto » (Avatar IA).
// Chargé APRÈS app.js : réutilise $, api, toast, esc, showModal, currentSettings, prettyError.
// Points d'entrée globaux :
//   kfTools(container, s, { onChange })   → ajoute le bloc versions + outils à la carte
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
  function kfTools(container, s, { onChange } = {}) {
    if (!container || !s || !s.clip_id) return;
    const wrap = document.createElement("div");
    wrap.className = "kf-tools";
    const hasImg = !!s.image_url;
    wrap.innerHTML =
      `<div class="kf-tool-row">` +
      `<button class="btn small kf-retouch" type="button"${hasImg ? "" : " disabled"} title="Modifie UN détail de l'image actuelle (Nano Banana Pro) — ≠ Regénérer, qui repart de zéro">✏️ Retoucher</button>` +
      `<button class="btn small kf-mirror" type="button"${hasImg ? "" : " disabled"} title="Miroir horizontal (local, gratuit)">↔️ Miroir</button>` +
      `<button class="btn small kf-erase" type="button"${hasImg ? "" : " disabled"} title="Efface un texte, une étiquette, une fausse barre d'état… (local, gratuit)">🧽 Effacer une zone</button>` +
      `<button class="btn small kf-crop" type="button"${hasImg ? "" : " disabled"} title="Recadre puis remet au format 9:16 (local, gratuit)">✂️ Recadrer</button>` +
      `</div>` +
      `<div class="kf-retouch-form hidden">` +
      `<input type="text" class="kf-retouch-txt" maxlength="300" placeholder="Ce qui change UNIQUEMENT — ex. « le pull en bleu marine »" />` +
      `<label class="small"><input type="checkbox" class="kf-retouch-prod" /> Envoyer aussi les photos produit</label>` +
      `<button class="btn small primary kf-retouch-go" type="button">Lancer la retouche</button>` +
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
      run(() => post(`/api/clips/${s.clip_id}/retouch`, { instruction, with_product_refs, confirm: true }),
        "Retouche faite ✓ — nouvelle version à valider.");
    });
    wrap.querySelector(".kf-mirror").addEventListener("click", () =>
      run(() => post(`/api/clips/${s.clip_id}/tools/mirror`), "Miroir appliqué ✓ — nouvelle version."));
    wrap.querySelector(".kf-erase").addEventListener("click", async () => {
      const r = await pickRect(s.image_url, {
        title: "Effacer une zone",
        hint: "Trace un rectangle autour du texte, de l'étiquette ou de la barre d'état à effacer (seuls les pixels contrastés de la zone sont repeints).",
        confirmText: "Effacer",
      });
      if (r) run(() => post(`/api/clips/${s.clip_id}/tools/erase`, r), "Zone effacée ✓ — nouvelle version.");
    });
    wrap.querySelector(".kf-crop").addEventListener("click", async () => {
      const r = await pickRect(s.image_url, {
        title: "Recadrer", hint: "Trace le rectangle à garder.", confirmText: "Recadrer", withFormat: true,
      });
      if (r) run(() => post(`/api/clips/${s.clip_id}/tools/crop`, r), "Recadrage fait ✓ — nouvelle version.");
    });
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
    const refs = (d.refs || []).map((r) =>
      `<span class="kf-af-ref">${r.url ? `<img src="${esc(r.url)}" alt="${esc(r.kind)}" />` : ""}` +
      `Visage perso ${esc(String(r.kind).replace("visage", ""))} <button class="btn small kf-af-del" type="button" data-kind="${esc(r.kind)}">Retirer</button></span>`).join("");
    el.innerHTML =
      `<label class="small"><input type="checkbox" class="kf-af-on"${d.enabled ? " checked" : ""} /> ` +
      `Réf visage automatique : la 1re image validée où un perso apparaît seul devient sa réf « Visage perso N » ` +
      `(jamais à la place d'une réf que tu as fournie)</label>` +
      (refs ? `<div class="kf-af-refs">${refs}</div>` : "");
    el.querySelector(".kf-af-on").addEventListener("change", async (ev) => {
      try {
        await post(`/api/ads/${adId}/auto-face`, { enabled: ev.target.checked });
        toast(ev.target.checked ? "Réf visage auto activée." : "Réf visage auto désactivée.");
      } catch (e) { toast(e.message); }
    });
    el.querySelectorAll(".kf-af-del").forEach((b) => b.addEventListener("click", async () => {
      try {
        await api(`/api/ads/${adId}/auto-face?kind=${encodeURIComponent(b.dataset.kind)}`, { method: "DELETE" });
        toast("Réf visage auto retirée.");
        kfAutoFacePanel(adId);
      } catch (e) { toast(e.message); }
    }));
  }

  window.kfTools = kfTools;
  window.kfAutoFacePanel = kfAutoFacePanel;
})();
