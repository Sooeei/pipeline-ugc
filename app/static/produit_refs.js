"use strict";
// Produit et réfs — éditeur de FICHE PRODUIT (client « Clients & persos » + pub Avatar IA / Objet
// animé) et panneau « Réfs de la pub » (ajouter, retirer, type, ↑↓, ⭐ principale).
// Chargé APRÈS app.js : réutilise $, api, toast, esc, showModal. Points d'entrée window.* seulement.
(function () {
  const ANGLES = [["face", "Face"], ["profil", "Profil"], ["usage", "En utilisation"], ["packaging", "Packaging"]];

  const jsonOpts = (method, body) => ({
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
  });

  // ================================================ FICHE PRODUIT
  // base = "/api/presets/{id}" ou "/api/ads/{id}" ; opts.ad = true → bouton « Recopier du client ».
  async function renderProductSheetEditor(box, base, opts = {}) {
    if (!box) return;
    if (!base) {
      box.innerHTML = `<div class="card-block ps-box"><b>🧴 Fiche produit</b>` +
        `<p class="muted small">Enregistre d'abord le client pour lui ajouter sa fiche produit.</p></div>`;
      return;
    }
    let d;
    try { d = await api(base + "/product-sheet"); } catch (e) { box.innerHTML = ""; return toast(e.message); }
    box.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "card-block ps-box";
    wrap.innerHTML =
      `<div class="ps-head"><b>🧴 Fiche produit</b> <span class="muted small">— injectée automatiquement ` +
      `(en anglais) dans chaque image où le produit est visible, avec ses photos face → profil → usage ` +
      `(packaging seulement si le plan le demande).${opts.ad ? " Copie propre à CETTE pub : la modifier ne change pas le client." : ""}</span></div>` +
      `<label>Nom court (anglais, facultatif) <input type="text" class="ps-name" maxlength="80" placeholder="ex. lash clip" /></label>` +
      `<label>Description canonique (ANGLAIS : forme, taille, matière, comment on le tient, le geste)` +
      `<textarea class="ps-desc" rows="4" placeholder="ex. small white plastic CLIP ~4 cm, one strip folded into a U…"></textarea></label>` +
      `<label>Jamais (anglais, un par ligne ou séparés par des virgules)` +
      `<textarea class="ps-never" rows="2" placeholder="tweezers, pliers, a C-clamp, a mask around the eye"></textarea></label>` +
      `<label class="check"><input type="checkbox" class="ps-notext" /> Pas de texte / logo / étiquette sur le produit</label>` +
      `<div class="ps-photos"></div>` +
      `<div class="ps-preview muted small"></div><div class="ps-warn"></div>` +
      `<div class="row"><button type="button" class="btn small primary ps-save">💾 Enregistrer la fiche</button>` +
      (opts.ad ? `<button type="button" class="btn small ps-copy" title="Écrase la fiche de la pub par celle du client">↺ Recopier depuis le client</button>` : "") +
      `<span class="muted small ps-msg"></span></div>`;
    box.appendChild(wrap);
    const q = (sel) => wrap.querySelector(sel);

    // Pub liée à un client : « ↺ Depuis le client » par angle (recopie la photo de CET angle).
    let presetId = opts.ad ? (d.preset_id || null) : null;
    // Photos (+ aperçu) seulement : un changement de photo ne touche pas aux textes en cours de saisie.
    const fillPhotos = (s) => {
      if (opts.ad && s.preset_id !== undefined) presetId = s.preset_id || null;
      q(".ps-preview").innerHTML = s.preview
        ? `<b>Bloc envoyé :</b> <code>${esc(s.preview)}</code>` : "Fiche vide : rien n'est ajouté aux prompts.";
      q(".ps-warn").innerHTML = (s.warnings || []).map((w) => `<div class="warn">⚠ ${esc(w)}</div>`).join("");
      const ph = q(".ps-photos");
      ph.innerHTML = "";
      ANGLES.forEach(([a, label]) => {
        const cur = (s.photos || []).find((p) => p.angle === a) || {};
        const cell = document.createElement("div");
        cell.className = "ps-photo";
        cell.innerHTML =
          (cur.url ? `<img src="${esc(cur.url)}" alt="${esc(label)}" />` : `<div class="thumb empty">—</div>`) +
          `<span>${esc(label)}</span>` +
          `<label class="btn small" title="${cur.url ? "Remplacer la photo de cet angle (les autres ne bougent pas)" : "Ajouter une photo pour cet angle"}">` +
          `${cur.url ? "📷 Remplacer" : "📷 Ajouter"}<input type="file" accept="image/*" hidden /></label>` +
          (presetId ? `<button type="button" class="btn small ps-from-preset" title="Recopie la photo « ${esc(label)} » du client (les autres angles ne bougent pas)">↺ Depuis le client</button>` : "") +
          (cur.url ? `<button type="button" class="btn small danger-outline ps-rm" title="Retirer">✕</button>` : "");
        cell.querySelector("input").addEventListener("change", async (ev) => {
          const f = ev.target.files && ev.target.files[0];
          if (!f) return;
          const fd = new FormData();
          fd.append("file", f, f.name);
          try {
            fillPhotos(await api(`${base}/product-sheet/photos/${a}`, { method: "POST", body: fd }));
            toast(`Photo « ${label} » ${cur.url ? "remplacée" : "ajoutée"} ✓`);
          } catch (e) { toast(e.message); }
        });
        const fromPreset = cell.querySelector(".ps-from-preset");
        if (fromPreset) fromPreset.addEventListener("click", async () => {
          try {
            fillPhotos(await api(`${base}/product-sheet/photos/${a}/from-preset`, jsonOpts("POST", {})));
            toast(`Photo « ${label} » recopiée depuis le client ✓`);
          } catch (e) { toast(e.message); }
        });
        const rm = cell.querySelector(".ps-rm");
        if (rm) rm.addEventListener("click", async () => {
          try { fillPhotos(await api(`${base}/product-sheet/photos/${a}`, { method: "DELETE" })); }
          catch (e) { toast(e.message); }
        });
        ph.appendChild(cell);
      });
    };
    const fill = (s) => {
      q(".ps-name").value = s.name || "";
      q(".ps-desc").value = s.description || "";
      q(".ps-never").value = (s.never || []).join(", ");
      q(".ps-notext").checked = !!s.no_text;
      fillPhotos(s);
    };
    fill(d);

    q(".ps-save").addEventListener("click", async () => {
      try {
        const s = await api(base + "/product-sheet", jsonOpts("PUT", {
          name: q(".ps-name").value.trim(), description: q(".ps-desc").value.trim(),
          never: q(".ps-never").value, no_text: q(".ps-notext").checked,
        }));
        fill(s);
        q(".ps-msg").textContent = "✓ Fiche enregistrée (prise en compte aux prochaines images).";
      } catch (e) { toast(e.message); }
    });
    const copy = q(".ps-copy");
    if (copy) copy.addEventListener("click", async () => {
      const ok = await showModal({
        title: "Recopier la fiche du client ?",
        message: "La fiche produit de cette pub sera remplacée par celle du client.",
        confirmText: "Recopier", cancelText: "Annuler",
      });
      if (!ok) return;
      try { fill(await api(base + "/product-sheet/from-preset", jsonOpts("POST", {}))); }
      catch (e) { toast(e.message); }
    });
  }

  // ================================================ RÉFS DE LA PUB
  async function renderAdRefsPanel(box, adId, onChange) {
    if (!box || !adId) return;
    let r;
    try { r = await api(`/api/ads/${adId}/refs`); } catch (e) { return toast(e.message); }
    box.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "card-block refs-box";
    wrap.innerHTML =
      `<div class="ps-head"><b>🖼️ Réfs de la pub</b> <span class="muted small">— envoyées dans cet ordre ` +
      `(selon les chips de chaque plan). ⭐ = réf principale (image 1, elle prime). Les changements ` +
      `valent pour les PROCHAINES générations.</span></div><div class="refs-list"></div>` +
      `<div class="row refs-add"><select class="refs-add-kind"></select>` +
      `<label class="btn small">+ Ajouter une réf<input type="file" accept="image/*" multiple hidden /></label></div>` +
      `<div class="refs-warn"></div>`;
    box.appendChild(wrap);
    const kinds = r.kinds || [];
    const kindOpts = (v) => kinds.map((k) =>
      `<option value="${esc(k.v)}" ${k.v === (v || "") ? "selected" : ""}>${esc(k.t)}</option>`).join("");
    wrap.querySelector(".refs-add-kind").innerHTML = kindOpts("produit");
    const refs = r.refs || [];
    const changed = async (p) => {
      try { await p; } catch (e) { toast(e.message); }
      // onChange recharge la galerie (qui re-rend ce panneau) ; sinon on se re-rend soi-même.
      if (onChange) onChange();
      else await renderAdRefsPanel(box, adId, onChange);
    };
    const list = wrap.querySelector(".refs-list");
    if (!refs.length) list.innerHTML = `<p class="muted small">Aucune réf pour l'instant.</p>`;
    refs.forEach((x, i) => {
      const row = document.createElement("div");
      row.className = "ref-row" + (x.is_main ? " main" : "");
      row.innerHTML =
        (x.url ? `<img src="${esc(x.url)}" alt="réf ${i + 1}" />` : `<div class="thumb empty">${x.missing ? "absente" : "—"}</div>`) +
        `<span class="ref-n">${i + 1}</span>` +
        `<select class="ref-kind">${kindOpts(x.kind)}</select>` +
        `<button type="button" class="btn small up" title="Monter" ${i === 0 ? "disabled" : ""}>↑</button>` +
        `<button type="button" class="btn small down" title="Descendre" ${i === refs.length - 1 ? "disabled" : ""}>↓</button>` +
        `<button type="button" class="btn small star ${x.is_main ? "on" : ""}" title="${x.main_explicit ? "Réf principale (cliquer pour retirer)" : x.is_main ? "Réf principale par défaut (1re photo Produit)" : "Choisir comme réf principale"}">${x.is_main ? "⭐" : "☆"}</button>` +
        `<button type="button" class="btn small danger-outline rm" title="Retirer cette réf">✕</button>`;
      row.querySelector(".ref-kind").addEventListener("change", (ev) =>
        changed(api(`/api/ads/${adId}/refs/${x.id}`, jsonOpts("PATCH", { kind: ev.target.value }))));
      const move = (delta) => {
        const ids = refs.map((y) => y.id);
        const j = i + delta;
        [ids[i], ids[j]] = [ids[j], ids[i]];
        changed(api(`/api/ads/${adId}/refs/order`, jsonOpts("POST", { ids })));
      };
      row.querySelector(".up").addEventListener("click", () => move(-1));
      row.querySelector(".down").addEventListener("click", () => move(1));
      row.querySelector(".star").addEventListener("click", () =>
        changed(api(`/api/ads/${adId}/refs/${x.id}`, jsonOpts("PATCH", { is_main: !x.main_explicit }))));
      row.querySelector(".rm").addEventListener("click", async () => {
        const ok = await showModal({
          title: "Retirer cette réf ?", message: `La réf ${i + 1} ne sera plus envoyée aux prochaines générations.`,
          confirmText: "Retirer", cancelText: "Annuler", danger: true,
        });
        if (ok) changed(api(`/api/ads/${adId}/refs/${x.id}`, { method: "DELETE" }));
      });
      list.appendChild(row);
    });
    wrap.querySelector(".refs-add input").addEventListener("change", async (ev) => {
      const files = Array.from(ev.target.files || []);
      const kind = wrap.querySelector(".refs-add-kind").value;
      for (const f of files) {
        const fd = new FormData();
        fd.append("file", f, f.name);
        fd.append("kind", kind);
        try { await api(`/api/ads/${adId}/refs`, { method: "POST", body: fd }); }
        catch (e) { toast(e.message); break; }
      }
      changed(Promise.resolve());
    });
    wrap.querySelector(".refs-warn").innerHTML =
      (r.ref_warnings || []).map((w) => `<div class="warn">⚠ ${esc(w)}</div>`).join("");
  }

  // Fiche produit + réfs d'une pub (Avatar IA / Objet animé). La fiche n'est re-rendue que si la
  // pub change (pas de saisie perdue quand la galerie se recharge).
  async function renderAdProductAndRefs(box, adId, onRefsChange) {
    if (!box || !adId) return;
    let sheetBox = box.querySelector(".ps-mount");
    let refsBox = box.querySelector(".refs-mount");
    if (!sheetBox || box.dataset.adId !== String(adId)) {
      box.innerHTML = `<div class="refs-mount"></div><div class="ps-mount"></div>`;
      box.dataset.adId = String(adId);
      sheetBox = box.querySelector(".ps-mount");
      refsBox = box.querySelector(".refs-mount");
      renderProductSheetEditor(sheetBox, `/api/ads/${adId}`, { ad: true });
    }
    renderAdRefsPanel(refsBox, adId, onRefsChange);
  }

  window.renderProductSheetEditor = renderProductSheetEditor;
  window.renderAdRefsPanel = renderAdRefsPanel;
  window.renderAdProductAndRefs = renderAdProductAndRefs;
})();
