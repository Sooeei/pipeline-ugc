"use strict";
// Section « 🖥️ Local » — génération GRATUITE sur le PC via ComfyUI (Comfy Desktop) :
//   • Vidéo : MiniMax H3 image→vidéo (image de départ, image de fin optionnelle, réplique, direction) ;
//   • Image : Qwen Image édition (image source + jusqu'à 9 références + consigne) ;
//   • suivi des jobs (file d'attente, %, nœud en cours, temps écoulé, annulation, reprise après F5) ;
//   • statut Comfy (pastille + « Lancer Comfy »), « Libérer la mémoire », réglages propres à la section ;
//   • galerie des générations (télécharger, autre seed, dossier, supprimer, utiliser comme image
//     d'un plan, animer une image).
// Chargé APRÈS app.js : réutilise $, api, toast, esc, showModal. Ne passe JAMAIS par les réglages
// globaux de l'app : les réglages Local ont leur propre route. Les images sont désignées par des références serveur
// (« upload:… », « clip:… », « adsheet:… », « preset:… », « gen:… ») — jamais par un chemin.
(function () {
  if (!document.getElementById("local")) return;

  const post = (url, body) => api(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
  });
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const MAX_REFS = 9;
  const LS_KEY = "ugc_local_jobs_v1";
  const STATUS_LABELS = {
    en_attente: "En attente", en_cours: "En cours", termine: "Terminé", echec: "Échec", annule: "Annulé",
  };
  const QUALITY_LABELS = { "0.4": "Rapide (0,4 MP)", "0.6": "Équilibrée (0,6 MP)", "0.9": "Fine (0,9 MP)" };

  // mm:ss (les minutes ne sont pas plafonnées : 75:04 pour 1 h 15).
  function fmtDur(s) {
    s = Math.max(0, Math.round(Number(s) || 0));
    const m = Math.floor(s / 60);
    return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }
  function parseSeed(v) {
    const t = String(v || "").trim();
    if (!t) return null;
    const n = parseInt(t, 10);
    return Number.isFinite(n) && n >= 0 ? n : null;
  }
  function isActive() {
    const sec = $("local");
    return !!(sec && sec.classList.contains("active")) && document.visibilityState !== "hidden";
  }

  // ------------------------------------------------ stockage du navigateur (toujours sous try)
  function lsLoad() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr.filter((j) => j && j.job_id) : [];
    } catch (_) {
      return [];
    }
  }
  function lsSave() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(tracked.map((j) => ({
        job_id: j.job_id, gen_id: j.gen_id, kind: j.kind, label: j.label,
      }))));
    } catch (_) { /* stockage indisponible : le suivi reste en mémoire */ }
  }

  // ------------------------------------------------ état des formulaires
  const slots = { first: null, last: null, src: null };   // {ref, url}
  let refs = [];                                          // [{ref, url}] (≤ 9)

  function slotEl(name) {
    return document.querySelector(`#local .local-slot[data-slot="${name}"]`);
  }
  function renderSlot(name) {
    const el = slotEl(name);
    if (!el) return;
    const v = slots[name];
    const view = el.querySelector(".local-slot-view");
    view.innerHTML = v
      ? `<img src="${esc(v.url)}" alt="image choisie" loading="lazy" />`
      : `<span class="muted small">Aucune image — choisis un plan, une photo ou importe un fichier (glisser-déposer possible).</span>`;
    const clear = el.querySelector('[data-slot-act="clear"]');
    if (clear) clear.classList.toggle("hidden", !v);
  }
  function renderRefs() {
    const box = $("localRefsList");
    if (!box) return;
    box.innerHTML = refs.map((r, i) =>
      `<figure class="local-ref"><img src="${esc(r.url)}" alt="référence ${i + 1}" loading="lazy" />` +
      `<button type="button" class="btn small local-ref-del" data-i="${i}" aria-label="Retirer la référence ${i + 1}">✕</button>` +
      `<figcaption>Réf. ${i + 1}</figcaption></figure>`).join("") ||
      `<span class="muted small">Aucune référence (facultatif) — produit, décor, tenue…</span>`;
    const full = refs.length >= MAX_REFS;
    $("localRefAdd").disabled = full;
    $("localRefUpload").disabled = full;
    $("localRefCount").textContent = `${refs.length}/${MAX_REFS}`;
  }
  function setSlot(name, val) {
    if (name === "ref") {
      if (refs.length >= MAX_REFS) return toast(`${MAX_REFS} références maximum.`);
      if (refs.some((r) => r.ref === val.ref)) return toast("Cette référence est déjà ajoutée.");
      refs.push(val);
      renderRefs();
      return;
    }
    slots[name] = val;
    renderSlot(name);
  }

  // ------------------------------------------------ import d'un fichier (POST /api/local/upload)
  let uploadTarget = null;
  async function uploadFile(file, target) {
    if (!file) return;
    if (!/^image\/(png|jpe?g|webp)$/i.test(file.type || "")) {
      return toast("Format non pris en charge — PNG, JPG ou WEBP.");
    }
    if (file.size > 25 * 1024 * 1024) return toast("Image trop lourde (25 Mo maximum).");
    const fd = new FormData();
    fd.append("file", file);
    toast("Import de l'image…");
    try {
      const r = await api("/api/local/upload", { method: "POST", body: fd });
      setSlot(target, { ref: r.ref, url: r.url });
      toast(`Image importée ✓ (${r.width}×${r.height})`);
    } catch (e) {
      toast(e.message);
    }
  }
  $("localFile").addEventListener("change", (ev) => {
    const f = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (f && uploadTarget) uploadFile(f, uploadTarget);
  });
  function askUpload(target) {
    uploadTarget = target;
    $("localFile").click();
  }

  // ------------------------------------------------ sélecteur d'image (modale pubs → plans, photos, Local)
  const picker = { resolve: null, mode: "all", tab: "plans", src: null, ad: null, items: [] };

  function pickerClose(val) {
    $("localPickerOverlay").classList.add("hidden");
    document.removeEventListener("keydown", pickerKey);
    const res = picker.resolve;
    picker.resolve = null;
    if (res) res(val || null);
  }
  function pickerKey(e) {
    if (e.key === "Escape") pickerClose(null);
  }
  function thumbBtn(item, caption) {
    const i = picker.items.push(item) - 1;
    return `<button type="button" class="local-pick" data-pick="${i}" title="${esc(caption)}">` +
      (item.url ? `<img src="${esc(item.url)}" alt="" loading="lazy" />` : `<span class="local-noimg">—</span>`) +
      `<span>${esc(caption)}</span></button>`;
  }
  function pickerRender() {
    const body = $("localPickerBody");
    const s = picker.src;
    picker.items = [];
    document.querySelectorAll("#localPickerTabs .subtab").forEach((b) => {
      b.classList.toggle("active", b.dataset.ltab === picker.tab);
      b.classList.toggle("hidden", picker.mode === "plans" && b.dataset.ltab !== "plans");
    });
    $("localPickerBack").classList.toggle("hidden", !(picker.tab === "plans" && picker.ad));
    if (!s) {
      body.innerHTML = `<p class="muted">Chargement…</p>`;
      return;
    }
    let html = "";
    if (picker.tab === "plans") {
      // Plans sans image (url null) : seulement comme CIBLE (« Utiliser comme image du plan »).
      const ads = (s.ads || []).filter((a) => (a.plans || []).some((p) => p.url || picker.mode === "plans"));
      if (picker.ad) {
        const a = picker.ad;
        html = `<p class="small"><b>${esc(a.name || "Pub #" + a.id)}</b> — choisis un plan :</p><div class="local-pick-grid">` +
          a.plans.filter((p) => p.url || picker.mode === "plans").map((p) => thumbBtn(
            { ...p, ad_id: a.id, ad_name: a.name },
            (p.label || `Plan ${p.scene_n ?? "?"}`) + (p.url ? "" : " (sans image)"))).join("") + `</div>`;
      } else if (!ads.length) {
        html = `<p class="muted">Aucune pub n'a encore de plan avec une image.</p>`;
      } else {
        html = `<div class="local-ad-list">` + ads.map((a) => {
          const first = a.plans.find((p) => p.url) || a.plans[0];
          return `<button type="button" class="local-ad" data-ad="${esc(a.id)}">` +
            (first.url ? `<img src="${esc(first.url)}" alt="" loading="lazy" />` : `<span class="local-noimg">—</span>`) +
            `<span><b>${esc(a.name || "Pub #" + a.id)}</b><br><span class="muted small">` +
            `${esc(a.kind || "")} · ${a.plans.length} plan${a.plans.length > 1 ? "s" : ""}</span></span></button>`;
        }).join("") + `</div>`;
      }
    } else if (picker.tab === "photos") {
      const groups = [];
      (s.clients || []).forEach((c) => {
        if ((c.photos || []).length) {
          groups.push(`<h4>👥 ${esc(c.name || "Client")}</h4><div class="local-pick-grid">` +
            c.photos.map((p) => thumbBtn(p, p.label || p.angle || "photo")).join("") + `</div>`);
        }
      });
      (s.ads || []).forEach((a) => {
        if ((a.sheet || []).length) {
          groups.push(`<h4>📦 Fiche produit — ${esc(a.name || "Pub #" + a.id)}</h4><div class="local-pick-grid">` +
            a.sheet.map((p) => thumbBtn(p, p.label || p.angle || "vue")).join("") + `</div>`);
        }
      });
      html = groups.join("") || `<p class="muted">Aucune photo produit (clients ou fiches produit des pubs).</p>`;
    } else {
      const loc = s.local || [];
      html = loc.length
        ? `<div class="local-pick-grid">` + loc.map((g) => thumbBtn(g, `Local #${g.gen_id}`)).join("") + `</div>`
        : `<p class="muted">Aucune image générée en local pour l'instant.</p>`;
    }
    body.innerHTML = html;
  }
  // mode "all" : plans + photos + sorties Local → {ref, url, …} ; mode "plans" : plans seulement (clip_id).
  function openPicker({ title = "Choisir une image", mode = "all" } = {}) {
    if (picker.resolve) pickerClose(null);
    picker.mode = mode;
    picker.tab = "plans";
    picker.ad = null;
    picker.src = null;
    $("localPickerTitle").textContent = title;
    $("localPickerOverlay").classList.remove("hidden");
    document.addEventListener("keydown", pickerKey);
    pickerRender();
    api("/api/local/sources").then((s) => {
      picker.src = s || {};
      pickerRender();
    }).catch((e) => {
      $("localPickerBody").innerHTML = `<p class="muted">${esc(e.message)}</p>`;
    });
    return new Promise((resolve) => { picker.resolve = resolve; });
  }
  $("localPickerBody").addEventListener("click", (ev) => {
    const ad = ev.target.closest(".local-ad");
    if (ad && picker.src) {
      picker.ad = (picker.src.ads || []).find((a) => String(a.id) === ad.dataset.ad) || null;
      pickerRender();
      return;
    }
    const pk = ev.target.closest(".local-pick");
    if (pk) pickerClose(picker.items[Number(pk.dataset.pick)]);
  });
  $("localPickerTabs").addEventListener("click", (ev) => {
    const b = ev.target.closest(".subtab");
    if (!b) return;
    picker.tab = b.dataset.ltab;
    picker.ad = null;
    pickerRender();
  });
  $("localPickerBack").addEventListener("click", () => { picker.ad = null; pickerRender(); });
  $("localPickerCancel").addEventListener("click", () => pickerClose(null));
  $("localPickerOverlay").addEventListener("mousedown", (e) => {
    if (e.target === $("localPickerOverlay")) pickerClose(null);
  });

  // ------------------------------------------------ cases d'images (départ, fin, source) + références
  document.querySelectorAll("#local .local-slot").forEach((el) => {
    const name = el.dataset.slot;
    el.addEventListener("click", async (ev) => {
      const b = ev.target.closest("[data-slot-act]");
      if (!b) return;
      const act = b.dataset.slotAct;
      if (act === "upload") askUpload(name);
      else if (act === "clear") setSlot(name, null);
      else if (act === "pick") {
        const it = await openPicker({ title: name === "last" ? "Image de fin" : "Choisir une image" });
        if (it) setSlot(name, { ref: it.ref, url: it.url });
      }
    });
    el.addEventListener("dragover", (e) => { e.preventDefault(); el.classList.add("drag"); });
    el.addEventListener("dragleave", () => el.classList.remove("drag"));
    el.addEventListener("drop", (e) => {
      e.preventDefault();
      el.classList.remove("drag");
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) uploadFile(f, name);
    });
    renderSlot(name);
  });
  $("localRefAdd").addEventListener("click", async () => {
    const it = await openPicker({ title: "Ajouter une référence" });
    if (it) setSlot("ref", { ref: it.ref, url: it.url });
  });
  $("localRefUpload").addEventListener("click", () => askUpload("ref"));
  $("localRefsList").addEventListener("click", (ev) => {
    const b = ev.target.closest(".local-ref-del");
    if (!b) return;
    refs.splice(Number(b.dataset.i), 1);
    renderRefs();
  });
  renderRefs();

  // ------------------------------------------------ onglets Vidéo / Image
  function showTab(tab) {
    document.querySelectorAll("#local [data-localtab]").forEach((b) => {
      b.classList.toggle("active", b.dataset.localtab === tab);
      b.setAttribute("aria-selected", b.dataset.localtab === tab ? "true" : "false");
    });
    document.querySelectorAll("#local [data-localpanel]").forEach((p) => {
      p.classList.toggle("hidden", p.dataset.localpanel !== tab);
    });
  }
  document.querySelectorAll("#local [data-localtab]").forEach((b) => {
    b.addEventListener("click", () => showTab(b.dataset.localtab));
  });

  const secEl = $("localSeconds");
  const secOut = $("localSecondsVal");
  const syncSeconds = () => { secOut.textContent = `${secEl.value} s`; };
  secEl.addEventListener("input", syncSeconds);
  syncSeconds();

  // ------------------------------------------------ lancement : vidéo
  $("localVideoBtn").addEventListener("click", async () => {
    const btn = $("localVideoBtn");
    if (btn.disabled) return;
    if (!slots.first) return toast("Choisis d'abord l'image de départ.");
    const seconds = Math.min(15, Math.max(3, parseInt(secEl.value, 10) || 5));
    const mp = Number($("localMegapixels").value);
    const body = {
      first_frame: slots.first.ref,
      last_frame: slots.last ? slots.last.ref : null,
      dialogue: $("localDialogue").value.trim(),
      direction: $("localDirection").value.trim(),
      seconds,
      megapixels: [0.4, 0.6, 0.9].includes(mp) ? mp : 0.4,
      turbo: $("localTurbo").checked,
      seed: parseSeed($("localVideoSeed").value),
    };
    btn.disabled = true;
    try {
      const r = await post("/api/local/video", body);
      track(r, "video", `Vidéo #${r.gen_id} · ${seconds} s`);
      toast(r.queue_pos ? `Vidéo ajoutée à la file (position ${r.queue_pos})` : "Vidéo lancée ✓");
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
    }
  });

  // ------------------------------------------------ lancement : image
  $("localImageBtn").addEventListener("click", async () => {
    const btn = $("localImageBtn");
    if (btn.disabled) return;
    if (!slots.src) return toast("Choisis d'abord l'image source.");
    const instruction = $("localInstruction").value.trim();
    if (!instruction) return toast("Écris la consigne de retouche.");
    const body = {
      source: slots.src.ref,
      refs: refs.slice(0, MAX_REFS).map((r) => r.ref),
      instruction,
      size: $("localSize").value === "1K" ? "1K" : "source",
      seed: parseSeed($("localImageSeed").value),
    };
    btn.disabled = true;
    try {
      const r = await post("/api/local/image", body);
      track(r, "image", `Image #${r.gen_id}`);
      toast(r.queue_pos ? `Image ajoutée à la file (position ${r.queue_pos})` : "Image lancée ✓");
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
    }
  });

  // ------------------------------------------------ suivi des jobs (GET /api/local/jobs/{id} ~1 s)
  let tracked = lsLoad().map((j) => ({ ...j, info: null }));
  let pollTimer = null;

  function track(r, kind, label) {
    if (!r || !r.job_id || tracked.some((j) => j.job_id === r.job_id)) return;
    tracked.push({ job_id: r.job_id, gen_id: r.gen_id, kind, label,
      info: { state: r.queue_pos ? "en_attente" : "en_cours", queue_pos: r.queue_pos, percent: 0 } });
    lsSave();
    renderJobs();
    schedulePoll(50);
    loadGallery();
  }
  function jobRow(j) {
    const i = j.info || {};
    const st = i.state || "en_attente";
    const pct = Math.max(0, Math.min(100, Math.round(Number(i.percent) || 0)));
    let line;
    if (st === "en_attente") {
      line = `En attente${i.queue_pos ? ` (position ${esc(i.queue_pos)})` : ""}`;
    } else {
      line = `${pct} %` + (i.node_label ? ` · ${esc(i.node_label)}` : "") +
        ` · ${fmtDur(i.elapsed_s)}`;
    }
    return `<div class="local-job ${st === "en_attente" ? "waiting" : "running"}">` +
      `<div class="local-job-head"><b>${j.kind === "image" ? "🖼️" : "🎬"} ${esc(j.label || "Génération")}</b>` +
      `<span class="muted small">${line}</span>` +
      `<button type="button" class="btn small local-cancel" data-job="${esc(j.job_id)}">Annuler</button></div>` +
      (st === "en_attente" ? "" :
        `<div class="local-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}">` +
        `<div style="width:${pct}%"></div></div>`) +
      `</div>`;
  }
  function renderJobs() {
    const box = $("localJobs");
    box.classList.toggle("hidden", !tracked.length);
    const running = tracked.filter((j) => (j.info || {}).state === "en_cours");
    const waiting = tracked.filter((j) => (j.info || {}).state !== "en_cours");
    box.innerHTML = tracked.length
      ? `<h2>⏳ Générations en cours (${tracked.length})</h2>` + running.concat(waiting).map(jobRow).join("")
      : "";
  }
  function finishJob(j, info) {
    tracked = tracked.filter((x) => x.job_id !== j.job_id);
    lsSave();
    const what = j.label || "Génération";
    if (!info) toast(`${what} : suivi interrompu (serveur relancé ?) — vois la galerie.`);
    else if (info.state === "termine") toast(`✓ ${what} terminée en ${fmtDur(info.elapsed_s)}`);
    else if (info.state === "annule") toast(`${what} annulée.`);
    else toast(`✗ ${what} : ${info.error || "échec de la génération"}`);
    loadGallery();
  }
  async function pollJobs() {
    pollTimer = null;
    if (!tracked.length) { renderJobs(); return; }
    await Promise.all(tracked.slice().map(async (j) => {
      try {
        const info = await api(`/api/local/jobs/${encodeURIComponent(j.job_id)}`);
        j.info = info;
        j.fails = 0;
        if (info.gen_id && !j.gen_id) j.gen_id = info.gen_id;
        if (["termine", "echec", "annule"].includes(info.state)) finishJob(j, info);
      } catch (e) {
        // Job inconnu (serveur relancé) : abandon du suivi ; panne passagère : on réessaie (≤ 8 fois).
        j.fails = (j.fails || 0) + 1;
        if (/introuvable|inconnu|not found/i.test(e.message || "") || j.fails >= 8) finishJob(j, null);
      }
    }));
    renderJobs();
    schedulePoll();
  }
  function schedulePoll(ms) {
    if (!tracked.length) return;
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(pollJobs, ms ?? (isActive() ? 1000 : 4000));
  }
  $("localJobs").addEventListener("click", async (ev) => {
    const b = ev.target.closest(".local-cancel");
    if (!b) return;
    const ok = await showModal({
      title: "Annuler la génération ?",
      message: "La génération est arrêtée dans Comfy. Rien n'est perdu côté pubs.",
      confirmText: "Annuler la génération", cancelText: "Continuer", danger: true,
    });
    if (!ok) return;
    b.disabled = true;
    try {
      const r = await post(`/api/local/jobs/${encodeURIComponent(b.dataset.job)}/cancel`);
      toast(r.where === "file" ? "Retirée de la file ✓" : "Annulation demandée…");
      schedulePoll(200);
    } catch (e) {
      b.disabled = false;
      toast(e.message);
    }
  });

  // ------------------------------------------------ statut Comfy
  let lastStatus = null;
  let statusTimer = null;
  let launching = false;
  let settingsLoaded = false;

  function setMsg(txt) {
    $("localStatusMsg").textContent = txt || "";
  }
  // État Comfy (K4) : `state` du serveur (pret | occupe | demarrage | injoignable), sinon déduit
  // des anciens champs (reachable / launching).
  function comfyState(s) {
    if (!s) return "";
    if (["pret", "occupe", "demarrage", "injoignable"].includes(s.state)) {
      return s.state === "injoignable" && launching ? "demarrage" : s.state;
    }
    if (s.busy) return "occupe";
    if (s.reachable) return "pret";
    return s.launching || launching ? "demarrage" : "injoignable";
  }
  function renderStatus(s) {
    const pill = $("localStatusPill");
    pill.classList.remove("ok", "err", "wait", "busy");
    pill.title = "";
    const st = comfyState(s);
    if (!s) {
      pill.textContent = "● Statut inconnu";
      pill.classList.add("wait");
    } else if (st === "pret") {
      pill.textContent = `● Comfy prêt (port ${s.port ?? "?"})`;
      pill.classList.add("ok");
    } else if (st === "occupe") {
      pill.textContent = "● " + (s.busy_label || "Comfy occupé — rendu en cours");
      if (s.busy_detail) pill.title = String(s.busy_detail);
      pill.classList.add("busy");
    } else if (st === "demarrage") {
      pill.textContent = "● Comfy démarre…";
      pill.classList.add("wait");
    } else {
      pill.textContent = "● Comfy ne répond pas";
      pill.classList.add("err");
    }
    const reachable = !!(s && s.reachable);
    // « Lancer Comfy » : seulement quand Comfy ne répond pas (jamais pendant un rendu / un démarrage).
    const noLaunch = st === "pret" || st === "occupe" || st === "demarrage";
    $("localLaunchBtn").classList.toggle("hidden", noLaunch);
    $("localLaunchBtn").disabled = noLaunch || launching;
    $("localFreeBtn").disabled = st !== "pret";   // 409 pendant un rendu
    if (s && !reachable && !launching && s.exe_found === false) {
      setMsg("Comfy Desktop est introuvable : indique le chemin de Comfy Desktop dans les réglages ci-dessous.");
    } else if (reachable && !launching) {
      setMsg("");
    }
  }
  function adoptQueue(s) {
    const q = (s && s.queue) || {};
    const ids = [];
    if (q.running && q.running.job_id) ids.push([q.running.job_id, q.running.kind, q.running.gen_id]);
    (q.waiting || []).forEach((id) => ids.push([id, "", null]));
    let added = false;
    ids.forEach(([id, kind, gen]) => {
      if (tracked.some((j) => j.job_id === id)) return;
      tracked.push({ job_id: id, gen_id: gen, kind: kind || "", info: null,
        label: kind === "image" ? `Image${gen ? " #" + gen : ""}` : kind === "video" ? `Vidéo${gen ? " #" + gen : ""}` : "Génération" });
      added = true;
    });
    if (added) { lsSave(); renderJobs(); schedulePoll(50); }
  }
  async function refreshStatus() {
    try {
      lastStatus = await api("/api/local/status");
    } catch (e) {
      lastStatus = null;
      setMsg(e.message);
    }
    renderStatus(lastStatus);
    adoptQueue(lastStatus);
    return lastStatus;
  }

  $("localLaunchBtn").addEventListener("click", async () => {
    if (launching) return;
    if (lastStatus && lastStatus.exe_found === false) {
      $("localSettings").open = true;
      setMsg("Comfy Desktop est introuvable : indique le chemin de Comfy Desktop dans les réglages ci-dessous.");
      $("localExe").focus();
      return;
    }
    const btn = $("localLaunchBtn");
    launching = true;
    btn.disabled = true;
    try {
      const r = await post("/api/local/launch");
      if (!r.launched) {
        // Refus motivé (occupe | demarrage | deja_lance | exe_introuvable | echec) : message du serveur.
        setMsg(r.message || "Comfy n'a pas pu être lancé : vérifie le chemin de Comfy Desktop dans les réglages ci-dessous.");
        if (r.reason === "exe_introuvable") $("localSettings").open = true;
        refreshStatus();
        return;
      }
      renderStatus(lastStatus ? { ...lastStatus, launching: true } : { launching: true });
      const t0 = Date.now();
      while (Date.now() - t0 < 180000) {
        setMsg(`Lancement de Comfy… ${fmtDur((Date.now() - t0) / 1000)} (le premier démarrage peut prendre 1 à 3 min)`);
        await sleep(3000);
        const s = await refreshStatus();
        if (s && s.reachable) {
          setMsg("");
          toast(`Comfy est prêt ✓ (port ${s.port})`);
          return;
        }
      }
      setMsg("Comfy ne répond toujours pas après 3 minutes. Regarde la fenêtre de Comfy Desktop " +
        "(mise à jour, erreur ?) ou indique son port dans les réglages, puis réessaie.");
    } catch (e) {
      setMsg(e.message);
    } finally {
      launching = false;
      btn.disabled = false;
      renderStatus(lastStatus);
    }
  });

  $("localFreeBtn").addEventListener("click", async () => {
    const btn = $("localFreeBtn");
    btn.disabled = true;
    try {
      await post("/api/local/free");
      toast("Mémoire de Comfy libérée ✓");
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = !(lastStatus && lastStatus.reachable);
    }
  });

  // ------------------------------------------------ réglages Local (GET/POST /api/local/settings)
  function fillSettings(s) {
    if (!s) return;
    $("localPort").value = Number(s.comfy_port) || 0;
    $("localExe").value = s.comfy_exe || "";
    $("localAutoFree").checked = !!s.auto_free;
  }
  async function loadSettings() {
    try {
      fillSettings(await api("/api/local/settings"));
      settingsLoaded = true;
    } catch (e) {
      toast(e.message);
    }
  }
  $("localSettingsSave").addEventListener("click", async () => {
    const port = parseInt($("localPort").value, 10) || 0;
    if (port < 0 || port > 65535) return toast("Port invalide (0 = détection automatique).");
    const btn = $("localSettingsSave");
    btn.disabled = true;
    try {
      const r = await post("/api/local/settings", {
        comfy_port: port, comfy_exe: $("localExe").value.trim(), auto_free: $("localAutoFree").checked,
      });
      fillSettings(r && r.comfy_port !== undefined ? r : null);
      toast("Réglages Local enregistrés ✓");
      refreshStatus();
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
    }
  });

  // ------------------------------------------------ galerie (GET /api/local/gens)
  let gens = [];
  let galLoading = false;

  function qualityLabel(mp) {
    const k = mp === undefined || mp === null ? "" : String(Number(mp));
    return QUALITY_LABELS[k] || (k ? `${k} MP` : "");
  }
  function genCard(g) {
    const p = g.params || {};
    const isVid = g.kind === "video";
    const done = g.status === "termine";
    const media = done && g.url
      ? (isVid
        ? `<video src="${esc(g.url)}" controls preload="metadata" playsinline></video>`
        : `<img src="${esc(g.url)}" alt="image générée #${esc(g.id)}" loading="lazy" />`)
      : `<div class="local-media-ph">${esc(STATUS_LABELS[g.status] || g.status || "—")}</div>`;
    const facts = [];
    if (isVid) {
      if (p.seconds) facts.push(`${esc(p.seconds)} s`);
      if (p.megapixels !== undefined) facts.push(esc(qualityLabel(p.megapixels)));
      if (p.turbo !== undefined) facts.push(`turbo ${p.turbo ? "oui" : "non"}`);
    } else {
      facts.push(p.size === "1K" ? "taille 1K" : "taille source");
      const nRefs = Array.isArray(p.refs) ? p.refs.length : 0;
      if (nRefs) facts.push(`${nRefs} réf.`);
    }
    if (g.seed !== null && g.seed !== undefined) facts.push(`seed ${esc(g.seed)}`);
    if (g.seconds_gen) facts.push(`généré en ${fmtDur(g.seconds_gen)}`);
    let text = "";
    if (isVid) {
      if (p.dialogue) text += `<div class="local-quote">« ${esc(p.dialogue)} »</div>`;
      if (p.direction) text += `<div class="muted small">🎬 ${esc(p.direction)}</div>`;
    } else if (p.instruction) {
      text += `<div class="local-quote">${esc(p.instruction)}</div>`;
    }
    if (!text && g.prompt) {
      text = `<div class="muted small local-prompt" title="${esc(g.prompt)}">${esc(String(g.prompt).slice(0, 220))}</div>`;
    }
    const inputs = (g.inputs || []).filter((i) => i && i.url).map((i) =>
      `<img src="${esc(i.url)}" alt="${esc(i.role || "entrée")}" title="${esc(i.role || "")}" loading="lazy" />`).join("");
    const st = g.status || "";
    const badgeCls = st === "termine" ? "ok" : st === "echec" ? "err" : st === "annule" ? "" : "wait";
    const dl = g.download_url || `/api/local/gens/${encodeURIComponent(g.id)}/download`;
    const busy = st === "en_cours" || st === "en_attente";
    const acts = [];
    if (done) acts.push(`<a class="btn small" href="${esc(dl)}" download>⬇ Télécharger</a>`);
    acts.push(`<button type="button" class="btn small" data-act="reseed" data-id="${esc(g.id)}"${busy ? " disabled" : ""}>🎲 Autre seed</button>`);
    if (done) acts.push(`<button type="button" class="btn small" data-act="folder" data-id="${esc(g.id)}">📂 Dossier</button>`);
    if (done && !isVid) {
      acts.push(`<button type="button" class="btn small" data-act="animate" data-id="${esc(g.id)}">🎬 Animer</button>`);
      acts.push(`<button type="button" class="btn small" data-act="plan" data-id="${esc(g.id)}">🖼️ Utiliser comme image du plan</button>`);
    }
    acts.push(`<button type="button" class="btn small danger-outline" data-act="delete" data-id="${esc(g.id)}"${busy ? " disabled" : ""}>🗑 Supprimer</button>`);
    return `<article class="local-card">` +
      `<div class="local-media">${media}</div>` +
      `<div class="local-card-body">` +
      `<div class="local-card-head"><b>${isVid ? "🎬 Vidéo" : "🖼️ Image"} #${esc(g.id)}</b>` +
      `<span class="local-badge ${badgeCls}">${esc(STATUS_LABELS[st] || st)}</span></div>` +
      (facts.length ? `<div class="muted small">${facts.join(" · ")}</div>` : "") +
      text +
      (g.error ? `<div class="local-error">⚠ ${esc(g.error)}</div>` : "") +
      (inputs ? `<div class="local-inputs">${inputs}</div>` : "") +
      `<div class="local-actions">${acts.join("")}</div>` +
      `</div></article>`;
  }
  async function loadGallery() {
    if (galLoading) return;
    galLoading = true;
    const box = $("localGallery");
    const kind = $("localKindFilter").value;
    try {
      const r = await api(`/api/local/gens${kind ? "?kind=" + encodeURIComponent(kind) : ""}`);
      gens = (r && r.gens) || [];
      box.innerHTML = gens.length ? gens.map(genCard).join("")
        : `<p class="muted">Aucune génération locale pour l'instant.</p>`;
    } catch (e) {
      box.innerHTML = `<p class="muted">${esc(e.message)}</p>`;
    } finally {
      galLoading = false;
    }
  }
  $("localKindFilter").addEventListener("change", loadGallery);
  $("localRefreshGal").addEventListener("click", () => { loadGallery(); refreshStatus(); });

  $("localGallery").addEventListener("click", async (ev) => {
    const b = ev.target.closest("button[data-act]");
    if (!b) return;
    const id = b.dataset.id;
    const g = gens.find((x) => String(x.id) === id);
    if (!g) return;
    const act = b.dataset.act;
    const enc = encodeURIComponent(id);
    if (act === "animate") {
      slots.first = { ref: `gen:${g.id}`, url: g.url };
      renderSlot("first");
      showTab("video");
      const form = document.querySelector('#local [data-localpanel="video"]');
      if (form) form.scrollIntoView({ behavior: "smooth", block: "start" });
      toast("Image placée comme image de départ de la vidéo ✓");
      return;
    }
    if (act === "delete") {
      const ok = await showModal({
        title: `Supprimer ${g.kind === "video" ? "la vidéo" : "l'image"} #${g.id} ?`,
        message: "La génération et son fichier seront supprimés. Les images déjà utilisées dans un plan restent dans l'historique du plan.",
        confirmText: "Supprimer", danger: true,
      });
      if (!ok) return;
      b.disabled = true;
      try {
        await api(`/api/local/gens/${enc}`, { method: "DELETE" });
        toast("Supprimée ✓");
        loadGallery();
      } catch (e) {
        b.disabled = false;
        toast(e.message);
      }
      return;
    }
    if (act === "plan") {
      const plan = await openPicker({ title: "Utiliser comme image de quel plan ?", mode: "plans" });
      if (!plan || !plan.clip_id) return;
      const ok = await showModal({
        title: `Image du plan ${plan.scene_n ?? ""}${plan.ad_name ? " — " + plan.ad_name : ""}`,
        message: "Cela crée une nouvelle version de l'image du plan ; l'actuelle reste dans l'historique.",
        confirmText: "Utiliser cette image",
      });
      if (!ok) return;
      b.disabled = true;
      try {
        const r = await post(`/api/local/gens/${enc}/use-as-plan-image`, { clip_id: plan.clip_id });
        toast(`Image du plan mise à jour ✓ (version v${r.v}) — à revalider dans la pub.`);
      } catch (e) {
        toast(e.message);
      } finally {
        b.disabled = false;
      }
      return;
    }
    b.disabled = true;
    try {
      if (act === "reseed") {
        const r = await post(`/api/local/gens/${enc}/reseed`, {});
        track(r, g.kind === "image" ? "image" : "video",
          `${g.kind === "image" ? "Image" : "Vidéo"} #${r.gen_id} (autre seed)`);
        toast(r.queue_pos ? `Ajoutée à la file (position ${r.queue_pos})` : "Nouvelle version lancée ✓");
      } else if (act === "folder") {
        const r = await post(`/api/local/gens/${enc}/open-folder`);
        if (!r.opened) toast(`Dossier : ${r.path || "introuvable"}`);
      }
    } catch (e) {
      toast(e.message);
    } finally {
      b.disabled = false;
    }
  });

  // ------------------------------------------------ activation de la section
  function onEnter() {
    refreshStatus();
    if (!settingsLoaded) loadSettings();
    loadGallery();
    if (!statusTimer) {
      statusTimer = setInterval(() => {
        if (!isActive()) { clearInterval(statusTimer); statusTimer = null; return; }
        if (!launching) refreshStatus();
      }, 5000);
    }
    schedulePoll(50);
  }
  // Gestionnaire ajouté APRÈS celui d'app.js : la section est déjà marquée « active » ici.
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => { if (btn.dataset.section === "local") onEnter(); });
  });
  document.addEventListener("visibilitychange", () => { if (isActive()) onEnter(); });

  renderJobs();
  if (tracked.length) schedulePoll(50);
  if (isActive()) onEnter();
})();
