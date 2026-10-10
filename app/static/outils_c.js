"use strict";
// Agent C — Export de la pub par client, estimation/suivi du coût d'une pub, page « Modèles ».
// Chargé APRÈS app.js : réutilise $, api, toast, esc, usd, money, currentSettings.
// Tout est dans une IIFE (aucun nom global ajouté sauf les 3 points d'entrée window.*).
(function () {
  // ================================================ COÛT D'UNE PUB (estimé / réel)
  const fmt = (n) => "$" + (Number(n) || 0).toFixed(2);

  // Estimation détaillée AVANT lancement (keyframes + vidéos), ajoutée sous l'estimation existante.
  async function renderPubEstimate(kind, shots, el) {
    if (!el || !Array.isArray(shots) || !shots.length) return;
    let e;
    try {
      e = await api("/api/pub-cost/estimate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, shots }),
      });
    } catch (err) {
      return;   // l'estimation historique reste affichée
    }
    const old = el.querySelector(".pub-cost-est");
    if (old) old.remove();
    const box = document.createElement("div");
    box.className = "pub-cost-est";
    const rows = (e.lines || []).map((l) =>
      `<tr><td>Plan ${esc(l.n)}</td><td class="num">${esc(l.seconds)} s</td>` +
      `<td class="num">${fmt(l.usd_image)}</td><td class="num">${fmt(l.usd_video)}</td></tr>`).join("");
    const perInput = e.tarif_image_entree_usd ? ` + ${fmt(e.tarif_image_entree_usd)}/image d'entrée` : "";
    box.innerHTML =
      `<div>💰 <b>Estimation complète de la pub : ${fmt(e.usd_total)}</b> ` +
      `<span class="muted">— keyframes ${e.shots} × ${fmt(e.tarif_image_usd)} = ${fmt(e.usd_images)} ` +
      `(${esc(e.image_model)}) · vidéo ${e.seconds_total} s × ${fmt(e.tarif_video_usd_par_s)}/s${perInput} ` +
      `= ${fmt(e.usd_video)} (${esc(e.video_model)})</span></div>` +
      (e.dry_run ? `<div class="card-sub">Mode simulation : rien ne sera facturé.</div>` : "") +
      `<details><summary class="small">Détail par plan</summary>` +
      `<table class="cost-table"><tr><th>Plan</th><th>Durée</th><th>Keyframe</th><th>Vidéo</th></tr>${rows}</table></details>`;
    el.appendChild(box);
  }

  // Coût RÉEL cumulé (après génération) comparé à l'estimation sur les plans en base.
  async function renderPubRealCost(adId, box) {
    if (!box || !adId) return;
    let r;
    try {
      r = await api("/api/pub-cost/" + adId);
    } catch (err) {
      box.classList.add("hidden");
      return;
    }
    const real = r.real || { usd: 0, services: [] };
    const est = r.estimate;
    const detail = (real.services || []).map((s) =>
      `<li>${esc(s.label)} — ${esc(s.units)} : <b>${fmt(s.usd)}</b></li>`).join("");
    // Ventilation (images / retouches / vidéos / relances) : même total que le bandeau de la pub.
    const b = r.cost_breakdown || real.breakdown;
    const parts = b ? [["images", "images"], ["retouches", "retouches"], ["videos", "vidéos"],
      ["relances", "relances"], ["autres", "autres"]]
      .filter(([k]) => b[k] && b[k].n)
      .map(([k, label]) => `${label} ${b[k].n} (${fmt(b[k].usd)})`) : [];
    box.innerHTML =
      `<div>💸 <b>Coût réel cumulé de la pub : ${fmt(real.usd)}</b>` +
      (est ? ` <span class="muted">(estimation pour ${est.shots} plan(s) : ${fmt(est.usd_total)})</span>` : "") +
      `</div>` +
      (parts.length ? `<div class="small muted">${esc(parts.join(" · "))}</div>` : "") +
      (detail ? `<ul class="pub-cost-services">${detail}</ul>`
        : `<div class="muted small">Aucune dépense enregistrée${est && est.dry_run ? " (mode simulation)" : ""}.</div>`);
    box.classList.remove("hidden");
  }

  // ================================================ EXPORT DE LA PUB
  let exAdId = null;
  let exPreview = null;
  let exTimer = null;

  function exShow(on) { $("exportOverlay").classList.toggle("hidden", !on); }

  // Case « Débruiter l'audio » (décochée par défaut), ajoutée au formulaire d'export : les clips
  // copiés ont un audio débruité (afftdn léger) — les originaux ne sont jamais modifiés.
  function exDenoiseBox() {
    let box = $("exportDenoise");
    if (box) return box;
    const form = $("exportForm");
    if (!form) return null;
    const label = document.createElement("label");
    label.className = "small export-denoise";
    label.title = "Réduit les grésillements de fond (copies seulement, les originaux restent intacts).";
    label.innerHTML = `<input type="checkbox" id="exportDenoise"> Débruiter l'audio (grésillements)`;
    form.appendChild(label);
    box = $("exportDenoise");
    return box;
  }

  async function exLoad(params) {
    const q = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") q.set(k, v); });
    exPreview = await api(`/api/export/${exAdId}?${q.toString()}`);
    exRender();
  }

  function exRender() {
    const p = exPreview;
    const sel = $("exportClient");
    const cur = p.preset_id != null ? String(p.preset_id) : sel.value;
    sel.innerHTML = `<option value="">— aucun —</option>` +
      (p.clients || []).map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
    sel.value = (p.clients || []).some((c) => String(c.id) === cur) ? cur : "";
    $("exportDir").value = p.export_dir || "";
    $("exportSubdir").value = p.subdir || "";
    $("exportDest").textContent = p.dest ? "Destination : " + p.dest : "Indique le dossier d'export du client.";
    $("exportConflict").classList.toggle("hidden", !p.conflicts);
    $("exportConflictN").textContent = String(p.conflicts || 0);
    const files = (p.files || []).map((f) =>
      `<li>${f.exists ? "⚠ " : ""}<code>${esc(f.name)}</code></li>`).join("");
    const skipped = (p.skipped || []).map((s) =>
      `<li class="muted">Plan ${esc(s.scene_n)} — ${esc(s.reason)}</li>`).join("");
    $("exportFiles").innerHTML =
      `<p class="small"><b>${(p.files || []).length}</b> clip(s) validé(s) à copier, dans l'ordre du script :</p>` +
      `<ul>${files || '<li class="muted">aucun</li>'}</ul>` +
      (skipped ? `<p class="small muted">Exclus (non validés) :</p><ul>${skipped}</ul>` : "");
    $("exportGo").disabled = !(p.files || []).length;
  }

  async function openExportDialog(adId) {
    if (!adId) return toast("Génère, valide et anime d'abord des plans.");
    exAdId = adId;
    $("exportForm").classList.remove("hidden");
    $("exportResult").classList.add("hidden");
    $("exportOpenBtn").classList.add("hidden");
    $("exportGo").classList.remove("hidden");
    $("exportClient").value = "";
    const dn = exDenoiseBox();
    if (dn) dn.checked = false;
    try {
      await exLoad({});
    } catch (e) {
      return toast(e.message);
    }
    exShow(true);
  }

  function exRefreshSoon() {
    clearTimeout(exTimer);
    exTimer = setTimeout(() => {
      exLoad({
        export_dir: $("exportDir").value.trim(),
        subdir: $("exportSubdir").value.trim(),
        preset_id: $("exportClient").value,
      }).catch((e) => toast(e.message));
    }, 350);
  }

  $("exportClient").addEventListener("change", () => {
    // Choix du client → on pré-remplit avec SON dossier d'export (et un sous-dossier ADSx recalculé).
    const pid = $("exportClient").value;
    const c = ((exPreview && exPreview.clients) || []).find((x) => String(x.id) === pid);
    if (c && c.export_dir) $("exportDir").value = c.export_dir;
    $("exportSubdir").value = "";
    exRefreshSoon();
  });
  $("exportDir").addEventListener("input", () => { $("exportSubdir").value = ""; exRefreshSoon(); });
  $("exportSubdir").addEventListener("input", exRefreshSoon);
  $("exportCancel").addEventListener("click", () => exShow(false));
  $("exportOverlay").addEventListener("mousedown", (e) => { if (e.target === $("exportOverlay")) exShow(false); });

  $("exportGo").addEventListener("click", async () => {
    const dir = $("exportDir").value.trim();
    if (!dir) return toast("Indique le dossier d'export du client.");
    const choice = document.querySelector('input[name="exportConflict"]:checked');
    const pid = $("exportClient").value;
    let res;
    $("exportGo").disabled = true;
    try {
      res = await api("/api/export/" + exAdId, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          export_dir: dir, subdir: $("exportSubdir").value.trim(),
          preset_id: pid ? Number(pid) : null, remember_for_client: $("exportRemember").checked,
          on_conflict: choice ? choice.value : "suffix",
          denoise: !!(exDenoiseBox() && exDenoiseBox().checked),
        }),
      });
    } catch (e) {
      $("exportGo").disabled = false;
      return toast(e.message);
    }
    const renamed = res.copied.filter((c) => c.renamed).length;
    $("exportForm").classList.add("hidden");
    $("exportGo").classList.add("hidden");
    $("exportResult").innerHTML =
      `<p>✅ <b>${res.copied.length}</b> clip(s) copié(s) dans :<br><code>${esc(res.dest)}</code></p>` +
      (res.denoise ? `<p class="small">Audio débruité : ${res.copied.filter((c) => c.denoised).length} / ${res.copied.length} clip(s)` +
        ` (en cas d'échec, l'original a été copié).</p>` : "") +
      (renamed ? `<p class="small">${renamed} fichier(s) existant(s) : copie suffixée (_2…), rien n'a été écrasé.</p>` : "") +
      (res.kept_existing.length ? `<p class="small">${res.kept_existing.length} fichier(s) déjà présent(s) laissé(s) tel(s) quel(s).</p>` : "") +
      (res.skipped.length ? `<p class="small muted">${res.skipped.length} plan(s) non validé(s) exclu(s).</p>` : "");
    $("exportResult").classList.remove("hidden");
    $("exportOpenBtn").classList.remove("hidden");
  });

  $("exportOpenBtn").addEventListener("click", async () => {
    try {
      await api(`/api/export/${exAdId}/open`, { method: "POST" });
    } catch (e) {
      toast(e.message);
    }
  });

  // Boutons d'export : flux Objet animé / Mashup + en-têtes de la Bibliothèque (délégation).
  $("objExportBtn").addEventListener("click", () => openExportDialog(typeof objAdId !== "undefined" ? objAdId : null));
  $("mashExportBtn").addEventListener("click", () => openExportDialog(typeof mashAdId !== "undefined" ? mashAdId : null));
  document.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest(".btn-export-pub");
    if (b) openExportDialog(Number(b.dataset.adId));
  });

  // ================================================ PAGE « MODÈLES »
  const KEY_CLASS = { ok: "ok", absente: "ko", invalide: "ko", presente: "", erreur: "warn" };

  function renderKeys(keys) {
    $("modelesKeys").innerHTML = (keys || []).map((k) =>
      `<div class="key-status"><span class="key-name">${esc(k.label)}</span>` +
      `<span class="badge ${KEY_CLASS[k.status] || ""}">${esc(k.status_label)}</span>` +
      (k.message ? `<span class="muted small">${esc(k.message)}</span>` : "") + `</div>`).join("");
  }

  async function loadModeles() {
    let r;
    try {
      r = await api("/api/modeles");
    } catch (e) {
      return toast(e.message);
    }
    renderKeys(r.keys);
    $("checkKeysMsg").textContent = r.dry_run ? "Mode simulation : la vérification ne fera aucun appel réseau." : "";
    const rows = (r.rows || []).map((x) =>
      `<tr class="${x.actif ? "actif" : "inactif"}"><td>${esc(x.mode)}</td><td>${esc(x.etape)}</td>` +
      `<td>${esc(x.fournisseur)}</td><td><code>${esc(x.modele)}</code><div class="muted small">${esc(x.libelle)}</div></td>` +
      `<td class="num">${esc(x.prix)}</td><td>${x.actif ? "✓" : ""}${x.note ? ` <span class="muted small">${esc(x.note)}</span>` : ""}</td></tr>`).join("");
    $("modelesTable").innerHTML =
      `<table class="cost-table modeles-table"><tr><th>Mode</th><th>Étape</th><th>Fournisseur</th>` +
      `<th>Modèle</th><th>Prix estimé</th><th>Utilisé</th></tr>${rows}</table>`;
  }

  $("checkKeysBtn").addEventListener("click", async () => {
    $("checkKeysBtn").disabled = true;
    $("checkKeysMsg").textContent = "Vérification…";
    try {
      const r = await api("/api/modeles/cles/verifier", { method: "POST" });
      renderKeys(r.keys);
      $("checkKeysMsg").textContent = r.dry_run
        ? "Mode simulation : aucune vérification réseau (statut = présence de la clé)."
        : "Vérification terminée.";
    } catch (e) {
      $("checkKeysMsg").textContent = "";
      toast(e.message);
    } finally {
      $("checkKeysBtn").disabled = false;
    }
  });
  $("refreshModeles").addEventListener("click", loadModeles);
  const nav = document.querySelector('.nav-item[data-section="modeles"]');
  if (nav) nav.addEventListener("click", loadModeles);

  // Points d'entrée appelés par app.js (crochets d'une ligne).
  window.renderPubEstimate = renderPubEstimate;
  window.renderPubRealCost = renderPubRealCost;
  window.openExportDialog = openExportDialog;
})();
