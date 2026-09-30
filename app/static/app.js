"use strict";

const $ = (id) => document.getElementById(id);
// Transforme le champ `detail` d'une réponse d'erreur en message lisible, sans code HTTP ni
// JSON brut. FastAPI renvoie `detail` = chaîne (nos messages FR) OU tableau d'objets (validation
// 422) : dans ce dernier cas on affiche un message générique plutôt que « [object Object] ».
function detailToMessage(detail) {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "Requête invalide (un champ manque ou est incorrect).";
  if (typeof detail === "object" && typeof detail.msg === "string") return detail.msg;
  return "";
}
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    throw new Error(detailToMessage(data.detail) || "Le serveur n'a pas pu traiter la demande — réessaie.");
  }
  return data;
};
const toast = (msg) => {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  setTimeout(() => t.classList.add("hidden"), 2600);
};

// Modale intégrée (remplace confirm()/alert() natifs). Retourne une Promise<boolean>.
function showModal({ title = "", message = "", html = "", confirmText = "Continuer", cancelText = "Annuler", danger = false } = {}) {
  return new Promise((resolve) => {
    $("modalTitle").textContent = title;
    // `html` : contenu STATIQUE de confiance (jamais de saisie utilisateur) ; sinon texte échappé.
    if (html) $("modalBody").innerHTML = html;
    else $("modalBody").textContent = message;
    const overlay = $("modalOverlay");
    const okBtn = $("modalConfirm");
    const noBtn = $("modalCancel");
    okBtn.textContent = confirmText;
    noBtn.textContent = cancelText;
    okBtn.classList.toggle("danger", !!danger);
    noBtn.style.display = cancelText ? "" : "none";
    overlay.classList.remove("hidden");
    const done = (val) => {
      overlay.classList.add("hidden");
      okBtn.removeEventListener("click", onOk);
      noBtn.removeEventListener("click", onNo);
      overlay.removeEventListener("mousedown", onBackdrop);
      document.removeEventListener("keydown", onKey);
      resolve(val);
    };
    const onOk = () => done(true);
    const onNo = () => done(false);
    const onBackdrop = (e) => { if (e.target === overlay) done(false); };
    const onKey = (e) => {
      if (e.key === "Escape") done(false);
      else if (e.key === "Enter") done(true);
    };
    okBtn.addEventListener("click", onOk);
    noBtn.addEventListener("click", onNo);
    overlay.addEventListener("mousedown", onBackdrop);
    document.addEventListener("keydown", onKey);
    okBtn.focus();
  });
}

// Simple message d'info (remplace alert()).
function alertModal(message, title = "Information") {
  return showModal({ title, message, confirmText: "OK", cancelText: "" });
}

// ------------------------------------------------ navigation
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    const sec = btn.dataset.section;
    $(sec).classList.add("active");
    if (sec === "dashboard") loadDashboard();
    if (sec === "library") loadLibrary();
    if (sec === "costs") loadCosts();
    if (sec === "settings") loadSettings();
    if (sec === "new") populateNewPubSelectors();
  });
});

function setModeBadge(dryRun) {
  const b = $("modeBadge");
  b.textContent = dryRun ? "Mode : SIMULATION" : "Mode : RÉEL (crédits)";
  b.classList.toggle("sim", dryRun);
  b.classList.toggle("live", !dryRun);
}

// ------------------------------------------------ RÉGLAGES
let currentSettings = null;

function setKeyField(id, isSet) {
  // Champ secret : on n'affiche jamais la clé. Si une clé est enregistrée, on l'indique
  // clairement et un champ laissé vide = « garder la clé actuelle ».
  const el = $(id);
  el.value = "";
  el.placeholder = isSet
    ? "•••••••• clé enregistrée (laisse vide pour la garder)"
    : "colle ta clé ici";
  el.classList.toggle("is-set", !!isSet);
}

async function loadSettings() {
  const s = await api("/api/settings");
  currentSettings = s;
  setKeyField("gradiumKey", s.gradium_api_key_set);
  setKeyField("heygenKey", s.heygen_api_key_set);
  setKeyField("openrouterKey", s.openrouter_api_key_set);
  setKeyField("xaiKey", s.xai_api_key_set);
  setKeyField("anthropicKey", s.anthropic_api_key_set);
  if ($("geminiKey")) setKeyField("geminiKey", s.gemini_api_key_set);
  $("gradiumModel").value = s.gradium_model || "default";
  $("heygenVoiceId").value = s.heygen_voice_id || "";
  $("brainModel").value = s.brain_model || "claude-sonnet-5";
  $("costModeDefault").value = s.cost_mode || "premium";
  // Menu du modèle d'image « Objet animé » (options fournies par le serveur).
  const imgSel = $("objetImageModel");
  imgSel.innerHTML = "";
  (s.objet_image_models || []).forEach((m) => {
    const o = document.createElement("option");
    o.value = m.key;
    o.textContent = m.label;
    if (m.key === s.objet_image_model) o.selected = true;
    imgSel.appendChild(o);
  });
  // Menu du modèle vidéo « Objet animé » (DoP ; l'animation n'est pas encore branchée).
  const vidSel = $("objetVideoModel");
  vidSel.innerHTML = "";
  (s.objet_video_models || []).forEach((m) => {
    const o = document.createElement("option");
    o.value = m.key;
    o.textContent = m.label;
    if (m.key === s.objet_video_model) o.selected = true;
    vidSel.appendChild(o);
  });
  // Menu du modèle vidéo « Mashup IA » (Veo / Seedance / Kling via OpenRouter).
  const mashSel = $("mashupVideoModel");
  if (mashSel) {
    mashSel.innerHTML = "";
    (s.mashup_video_models || []).forEach((m) => {
      const o = document.createElement("option");
      o.value = m.key;
      o.textContent = m.label;
      if (m.key === s.mashup_video_model) o.selected = true;
      mashSel.appendChild(o);
    });
  }
  // Menus du timbre + du débit de voix « Objet animé » (Grok).
  const fillSelect = (id, items, selectedKey) => {
    const sel = $(id);
    if (!sel) return;
    sel.innerHTML = "";
    (items || []).forEach((m) => {
      const o = document.createElement("option");
      o.value = m.key;
      o.textContent = m.label;
      if (m.key === selectedKey) o.selected = true;
      sel.appendChild(o);
    });
  };
  fillSelect("objetVoiceStyle", s.objet_voice_styles, s.objet_voice_style);
  fillSelect("objetVoicePace", s.objet_voice_paces, s.objet_voice_pace);
  fillSelect("objetStyle", s.objet_styles, s.objet_style);
  fillSelect("audioFormat", s.audio_formats, s.audio_format);
  aoFillVoiceSelects();   // timbre/débit de la fiche voix « Avatar IA » (mêmes listes que Grok)
  $("dryRun").checked = !!s.dry_run;
  if ($("spendCap")) $("spendCap").value = s.spend_cap_usd ?? 25;
  setModeBadge(!!s.dry_run);
  renderAvatars(s.avatars || []);
  renderVoices(s.voices || []);
  renderMashStyleChips(s.mashup_style_suggestions || []);
}

// JALON 7 — puces de style « Mashup » : pré-remplissent le champ Style LIBRE (éditable).
function renderMashStyleChips(suggestions) {
  const box = $("mashStyleChips");
  if (!box) return;
  box.innerHTML = "";
  suggestions.forEach((sug) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "ref-chip";
    chip.textContent = sug.label;
    chip.title = sug.value;
    chip.addEventListener("click", () => {
      $("mashStyle").value = sug.value;   // pré-remplit (l'utilisateur peut ensuite éditer)
      $("mashStyle").focus();
    });
    box.appendChild(chip);
  });
}

function renderAvatars(avatars) {
  const ul = $("avatarsList");
  ul.innerHTML = "";
  if (!avatars.length) ul.innerHTML = '<li class="muted">Aucun avatar pour le moment.</li>';
  avatars.forEach((a) => {
    const li = document.createElement("li");
    li.innerHTML =
      `<span class="lab">${esc(a.label)}</span><span class="aid">${esc(a.avatar_id)}</span>` +
      `<button class="del" title="Supprimer">✕</button>`;
    li.querySelector(".del").addEventListener("click", async () => {
      const res = await api("/api/avatars/" + a.id, { method: "DELETE" });
      renderAvatars(res.avatars);
      toast("Avatar supprimé.");
    });
    ul.appendChild(li);
  });
}

function renderVoices(voices) {
  const ul = $("voicesList");
  ul.innerHTML = "";
  if (!voices.length) ul.innerHTML = '<li class="muted">Aucune voix pour le moment.</li>';
  voices.forEach((v) => {
    const li = document.createElement("li");
    li.innerHTML =
      `<span class="lab">${esc(v.label)}</span><span class="aid">${esc(v.voice_id)}</span>` +
      `<button class="del" title="Supprimer">✕</button>`;
    li.querySelector(".del").addEventListener("click", async () => {
      const res = await api("/api/voices/" + v.id, { method: "DELETE" });
      if (currentSettings) currentSettings.voices = res.voices;
      renderVoices(res.voices);
      toast("Voix supprimée.");
    });
    ul.appendChild(li);
  });
}

$("saveSettings").addEventListener("click", async () => {
  const body = {
    gradium_api_key: $("gradiumKey").value.trim(),
    heygen_api_key: $("heygenKey").value.trim(),
    openrouter_api_key: $("openrouterKey").value.trim(),
    xai_api_key: $("xaiKey").value.trim(),
    gradium_model: $("gradiumModel").value.trim(),
    heygen_voice_id: $("heygenVoiceId").value.trim(),
    anthropic_api_key: $("anthropicKey").value.trim(),
    gemini_api_key: ($("geminiKey") && $("geminiKey").value.trim()) || "",   // vide = garder
    brain_model: $("brainModel").value.trim(),
    cost_mode: $("costModeDefault").value,
    objet_image_model: $("objetImageModel").value,
    objet_video_model: $("objetVideoModel").value,
    mashup_video_model: ($("mashupVideoModel") && $("mashupVideoModel").value) || "",
    objet_voice_style: ($("objetVoiceStyle") && $("objetVoiceStyle").value) || "",
    objet_voice_pace: ($("objetVoicePace") && $("objetVoicePace").value) || "",
    objet_style: ($("objetStyle") && $("objetStyle").value) || "",
    audio_format: ($("audioFormat") && $("audioFormat").value) || "",
    dry_run: $("dryRun").checked,
    spend_cap_usd: ($("spendCap") && $("spendCap").value !== "") ? parseFloat($("spendCap").value) : null,
  };
  await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  setModeBadge(body.dry_run);
  await loadSettings(); // rafraîchit les indicateurs « clé enregistrée »
  toast("Réglages enregistrés ✓");
});

$("addAvatar").addEventListener("click", async () => {
  const label = $("newAvatarLabel").value.trim();
  const avatar_id = $("newAvatarId").value.trim();
  if (!label || !avatar_id) return toast("Label et avatar_id requis.");
  const res = await api("/api/avatars", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label, avatar_id }),
  });
  renderAvatars(res.avatars);
  $("newAvatarLabel").value = "";
  $("newAvatarId").value = "";
  toast("Avatar ajouté ✓");
});

// ---- JALON 4 : sélecteur visuel d'avatars HeyGen (grille de vignettes, cache serveur) ----
let heygenAvatars = null;   // cache mémoire du dernier chargement (avatars + talking_photos)

$("browseHeygenBtn").addEventListener("click", async () => {
  const picker = $("heygenPicker");
  picker.classList.toggle("hidden");
  if (!picker.classList.contains("hidden") && heygenAvatars === null) {
    await loadHeygenAvatars(false);
  }
});

$("heygenRefresh").addEventListener("click", () => loadHeygenAvatars(true));
$("heygenSearch").addEventListener("input", renderHeygenGrid);
$("heygenGender").addEventListener("change", renderHeygenGrid);

async function loadHeygenAvatars(refresh) {
  const msg = $("heygenMsg");
  msg.textContent = refresh ? "Rafraîchissement depuis HeyGen (peut prendre jusqu'à 3 min)…" : "Chargement…";
  $("heygenGrid").innerHTML = "";
  try {
    const r = await api("/api/heygen/avatars?refresh=" + (refresh ? "true" : "false"));
    if (r.simulation) {
      msg.textContent = "Mode simulation : liste HeyGen indisponible (désactive « Mode simulation » et ajoute ta clé HeyGen pour parcourir les avatars).";
      heygenAvatars = { avatars: [], talking_photos: [] };
      return;
    }
    if (!r.ok && !r.avatars) {
      msg.textContent = "✗ " + (r.message || r.note || "Échec du chargement des avatars HeyGen.");
      return;
    }
    heygenAvatars = { avatars: r.avatars || [], talking_photos: r.talking_photos || [] };
    const total = (r.count != null) ? r.count : (heygenAvatars.avatars.length + heygenAvatars.talking_photos.length);
    const when = r.cached ? "cache local" : "à l'instant";
    msg.textContent = `${total} avatar(s) — ${when}.` + (r.note ? " ⚠ " + r.note : "");
    renderHeygenGrid();
  } catch (e) {
    msg.textContent = "✗ " + e.message;
  }
}

function renderHeygenGrid() {
  if (!heygenAvatars) return;
  const grid = $("heygenGrid");
  const q = $("heygenSearch").value.trim().toLowerCase();
  const gender = $("heygenGender").value;
  const all = [...heygenAvatars.avatars, ...heygenAvatars.talking_photos];
  const items = all.filter((a) => {
    if (gender && (a.gender || "").toLowerCase() !== gender) return false;
    if (q && !(a.name || "").toLowerCase().includes(q) && !(a.avatar_id || "").toLowerCase().includes(q)) return false;
    return true;
  }).slice(0, 200);   // borne l'affichage (1200+ avatars possibles)
  grid.innerHTML = "";
  if (!items.length) {
    grid.innerHTML = '<p class="muted">Aucun avatar ne correspond.</p>';
    return;
  }
  items.forEach((a) => grid.appendChild(heygenCard(a)));
}

function heygenCard(a) {
  const cell = document.createElement("div");
  cell.className = "heygen-card";
  const img = a.preview_image_url
    ? `<img loading="lazy" src="${esc(a.preview_image_url)}" alt="${esc(a.name)}" />`
    : `<div class="thumb empty">pas d'aperçu</div>`;
  const photoBadge = a.is_photo ? '<span class="badge warn" title="Photo avatar : fonctionne en Avatar IV / mode Classique uniquement">Classique</span>' : "";
  const premBadge = a.premium ? '<span class="badge">Premium</span>' : "";
  cell.innerHTML =
    img +
    `<div class="hg-name" title="${esc(a.avatar_id)}">${esc(a.name || a.avatar_id)}</div>` +
    `<div class="hg-meta">${esc(a.gender || "")} ${photoBadge}${premBadge}</div>` +
    `<button class="btn small hg-pick" type="button">Choisir</button>`;
  cell.querySelector(".hg-pick").addEventListener("click", () => {
    // Pré-remplit label + id ; le photo avatar exige le mode Classique → on avertit.
    const slug = (a.name || a.avatar_id).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
    $("newAvatarLabel").value = slug || "avatar";
    $("newAvatarId").value = a.avatar_id || "";
    if (a.is_photo)
      toast("⚠ Photo avatar : à utiliser en mode Avatar IV / Classique (pas Avatar V/Premium).");
    else toast("Avatar pré-rempli — clique « + Ajouter » pour l'enregistrer.");
    $("newAvatarLabel").scrollIntoView({ behavior: "smooth", block: "center" });
  });
  return cell;
}

$("addVoice").addEventListener("click", async () => {
  const label = $("newVoiceLabel").value.trim();
  const voice_id = $("newVoiceId").value.trim();
  if (!label || !voice_id) return toast("Label et voice_id requis.");
  const res = await api("/api/voices", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label, voice_id }),
  });
  if (currentSettings) currentSettings.voices = res.voices;
  renderVoices(res.voices);
  $("newVoiceLabel").value = "";
  $("newVoiceId").value = "";
  toast("Voix ajoutée ✓");
});

// ---- JALON 6 : aperçu du style « Objet vivant » (généré 1×, mis en cache) ----
$("objetStylePreviewBtn").addEventListener("click", async () => {
  const style = ($("objetStyle") && $("objetStyle").value) || "";
  const msg = $("objetStyleMsg");
  const box = $("objetStylePreview");
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    const ok = await showModal({
      title: "Générer l'aperçu du style", danger: true,
      message: "Aucun aperçu en cache pour ce style : on en génère un (1 image Nano Banana, payante au-delà du quota gratuit). Continuer ?",
      confirmText: "Générer", cancelText: "Annuler",
    });
    if (!ok) return;
  }
  msg.textContent = "Génération de l'aperçu…";
  box.innerHTML = "";
  try {
    const r = await api("/api/objet/style-preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ style, confirm: true }),
    });
    msg.textContent = r.cached ? "Aperçu (cache)." : "Aperçu généré.";
    const bust = "?t=" + Date.now();
    box.innerHTML = `<img src="${esc(r.image_url)}${bust}" alt="aperçu style" />`;
  } catch (e) {
    msg.textContent = "✗ " + e.message;
  }
});

// ---- JALON 5 : sélecteur de voix Gradium (métadonnées, échantillon ▶, étiquetage) ----
let gradiumVoices = null;

$("browseVoicesBtn").addEventListener("click", async () => {
  const picker = $("voicePicker");
  picker.classList.toggle("hidden");
  if (!picker.classList.contains("hidden") && gradiumVoices === null) await loadGradiumVoices(false);
});
$("voiceRefresh").addEventListener("click", () => loadGradiumVoices(true));
$("voiceSearch").addEventListener("input", renderVoiceList);
$("voiceLang").addEventListener("change", renderVoiceList);

async function loadGradiumVoices(refresh) {
  const msg = $("voiceMsg");
  msg.textContent = refresh ? "Rafraîchissement depuis Gradium…" : "Chargement…";
  $("voiceList").innerHTML = "";
  try {
    const r = await api("/api/gradium/voices?refresh=" + (refresh ? "true" : "false"));
    if (r.simulation) {
      msg.textContent = "Mode simulation : catalogue Gradium indisponible (désactive « Mode simulation » + ajoute ta clé Gradium).";
      gradiumVoices = [];
      return;
    }
    if (!r.ok && !(r.voices || []).length) {
      msg.textContent = "✗ " + (r.message || r.note || "Échec du chargement des voix.");
      return;
    }
    gradiumVoices = r.voices || [];
    // Remplit le filtre langue.
    const langs = [...new Set(gradiumVoices.map((v) => v.language).filter(Boolean))].sort();
    const sel = $("voiceLang");
    sel.innerHTML = '<option value="">Toutes langues</option>' +
      langs.map((l) => `<option value="${esc(l)}">${esc(l)}</option>`).join("");
    msg.textContent = `${gradiumVoices.length} voix — ${r.cached ? "cache local" : "à l'instant"}.` + (r.note ? " ⚠ " + r.note : "");
    renderVoiceList();
  } catch (e) {
    msg.textContent = "✗ " + e.message;
  }
}

function renderVoiceList() {
  if (!gradiumVoices) return;
  const box = $("voiceList");
  const q = $("voiceSearch").value.trim().toLowerCase();
  const lang = $("voiceLang").value;
  const items = gradiumVoices.filter((v) => {
    if (lang && v.language !== lang) return false;
    if (q && !(v.name || "").toLowerCase().includes(q) && !(v.description || "").toLowerCase().includes(q)) return false;
    return true;
  }).slice(0, 150);
  box.innerHTML = "";
  if (!items.length) { box.innerHTML = '<p class="muted">Aucune voix ne correspond.</p>'; return; }
  items.forEach((v) => box.appendChild(voiceRow(v)));
}

function voiceRow(v) {
  const row = document.createElement("div");
  row.className = "voice-row";
  const meta = [v.language, v.region, v.is_pro_clone ? "clone pro" : "", v.user_gender, v.user_age]
    .filter(Boolean).join(" · ");
  row.innerHTML =
    `<div class="vr-main"><div class="vr-name">${esc(v.user_label || v.name || v.uid)}</div>` +
    `<div class="vr-meta">${esc(meta)}</div>` +
    (v.description ? `<div class="vr-desc">${esc(v.description)}</div>` : "") + `</div>` +
    `<div class="vr-actions">` +
    `<button class="btn small vr-play" type="button" title="Écouter un échantillon">▶</button>` +
    `<button class="btn small vr-tag" type="button" title="Étiqueter (genre/âge/libellé)">🏷️</button>` +
    `<button class="btn small vr-pick" type="button">Choisir</button></div>` +
    `<audio class="vr-audio hidden" controls preload="none"${v.sample_url ? ` src="${esc(v.sample_url)}"` : ""}></audio>`;
  const audio = row.querySelector(".vr-audio");
  row.querySelector(".vr-play").addEventListener("click", async () => {
    if (audio.getAttribute("src")) { audio.classList.remove("hidden"); audio.play(); return; }
    const dryRun = currentSettings && currentSettings.dry_run;
    if (!dryRun) {
      const ok = await showModal({
        title: "Générer un échantillon", danger: true,
        message: "Aucun échantillon en cache : on en génère un (court appel TTS payant, réécoute gratuite ensuite). Continuer ?",
        confirmText: "Générer", cancelText: "Annuler",
      });
      if (!ok) return;
    }
    try {
      const r = await api("/api/gradium/voices/" + encodeURIComponent(v.uid) + "/sample", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true }),
      });
      v.sample_url = r.sample_url;
      audio.src = r.sample_url;
      audio.classList.remove("hidden");
      audio.play();
    } catch (e) { toast(e.message); }
  });
  row.querySelector(".vr-tag").addEventListener("click", () => tagVoice(v, row));
  row.querySelector(".vr-pick").addEventListener("click", () => {
    const slug = (v.user_label || v.name || v.uid).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
    $("newVoiceLabel").value = slug || "voix";
    $("newVoiceId").value = v.uid || "";
    toast("Voix pré-remplie — clique « + Ajouter » pour l'enregistrer.");
    $("newVoiceLabel").scrollIntoView({ behavior: "smooth", block: "center" });
  });
  return row;
}

async function tagVoice(v, row) {
  const label = prompt("Libellé (ex. « Claire douce ») :", v.user_label || "");
  if (label === null) return;
  const gender = prompt("Genre (male/female/…) :", v.user_gender || "") || "";
  const age = prompt("Tranche d'âge (ex. 30-40) :", v.user_age || "") || "";
  try {
    await api("/api/gradium/voices/" + encodeURIComponent(v.uid) + "/label", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label, gender, age }),
    });
    v.user_label = label; v.user_gender = gender.trim().toLowerCase(); v.user_age = age;
    row.replaceWith(voiceRow(v));
    toast("Étiquette enregistrée ✓");
  } catch (e) { toast(e.message); }
}

$("testConn").addEventListener("click", async () => {
  const el = $("testResult");
  el.innerHTML = "Test en cours…";
  try {
    const r = await api("/api/test-connection", { method: "POST" });
    const g = r.gradium || {};
    const h = r.heygen || {};
    const line = (label, o) => {
      const ok = o.ok !== false;
      const cls = ok ? "ok" : "ko";
      const msg = o.message || (ok ? "OK" : "échec");
      return `<div class="${cls}">${ok ? "✓" : "✗"} ${label} : ${esc(msg)}</div>`;
    };
    const a = r.anthropic || {};
    const nb = r.nano_banana || {};
    const grok = r.grok || {};
    let html = "";
    if (r.dry_run) html += '<div class="muted">Mode simulation : validation réelle désactivée.</div>';
    html += line("Gradium", g);
    html += line("HeyGen", h);
    html += line("Nano Banana (images Objet animé)", nb);
    html += line("Grok (animation Objet animé)", grok);
    if (r.kling) html += line("Kling (Mashup)", r.kling);
    if (r.gemini) html += line("Google Gemini (Avatar IA Omni)", r.gemini);
    html += line("Anthropic (cerveau)", a);
    if (h.avatars && h.avatars.length) {
      html += `<div class="muted">${h.avatars.length} avatars trouvés sur le compte.</div>`;
    }
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = `<div class="ko">✗ ${esc(e.message)}</div>`;
  }
});

// ------------------------------------------------ TABLEAU DE BORD
async function loadDashboard() {
  const d = await api("/api/dashboard");
  setModeBadge(!!d.dry_run);
  renderCredits($("gradiumCredits"), d.gradium_credits);
  renderQuota($("heygenQuota"), d.heygen_quota);
  $("totalVideos").textContent = d.total_videos ?? "0";
  const ul = $("activityList");
  ul.innerHTML = "";
  (d.activity || []).forEach((a) => {
    const li = document.createElement("li");
    li.innerHTML =
      `<span class="kind">${esc(a.kind)}</span><span>${esc(a.message)}</span>` +
      `<span class="when">${fmtDate(a.ts)}</span>`;
    ul.appendChild(li);
  });
  if (!(d.activity || []).length) ul.innerHTML = '<li class="muted">Aucune activité pour l’instant.</li>';
}
$("refreshDash").addEventListener("click", loadDashboard);

// -- Affichage robuste des tuiles crédits/quota : chiffre lisible, JAMAIS de JSON brut --
function frNum(n) {
  return Number(n).toLocaleString("fr-FR"); // 38914 -> "38 914"
}

function pickNum(obj, keys) {
  if (!obj || typeof obj !== "object") return null;
  for (const k of keys) {
    const v = obj[k];
    if (typeof v === "number" && isFinite(v)) return v;
    if (typeof v === "string" && v.trim() !== "" && !isNaN(Number(v))) return Number(v);
  }
  return null;
}

// Écrit dans la tuile : gros nombre + éventuellement « sur N » en dessous.
function setTile(el, remaining, allocated) {
  if (remaining == null && allocated == null) {
    el.textContent = "—"; // rien d'exploitable -> on n'affiche JAMAIS le JSON brut
    return;
  }
  const main = remaining != null ? frNum(remaining) : frNum(allocated);
  const sub = remaining != null && allocated != null ? `sur ${frNum(allocated)}` : "";
  el.innerHTML = esc(main) + (sub ? `<div class="card-sub">${esc(sub)}</div>` : "");
}

function renderCredits(el, c) {
  // Gradium credits() -> {remaining_credits, allocated_credits, ...}
  if (!c) return void (el.textContent = "—");
  if (c.simulation) return void (el.innerHTML = '— <span class="card-sub">(simulation)</span>');
  const remaining = pickNum(c, ["remaining_credits", "remaining", "credits", "balance"]);
  const allocated = pickNum(c, ["allocated_credits", "allocated", "total"]);
  setTile(el, remaining, allocated);
}

function renderQuota(el, q) {
  // HeyGen quota -> {simulation} ou {remaining: <nombre|objet>}
  if (!q) return void (el.textContent = "—");
  if (q.simulation) return void (el.innerHTML = '— <span class="card-sub">(simulation)</span>');
  let remaining = pickNum(q, ["remaining_quota", "remaining", "credits", "balance"]);
  let allocated = pickNum(q, ["allocated_quota", "allocated", "total"]);
  // HeyGen renvoie souvent {remaining: {...}} : on regarde à l'intérieur
  if (remaining == null && q.remaining && typeof q.remaining === "object") {
    remaining = pickNum(q.remaining, ["remaining_quota", "remaining", "credits", "balance"]);
    allocated = allocated ?? pickNum(q.remaining, ["allocated_quota", "allocated", "total"]);
  }
  setTile(el, remaining, allocated);
}

// ------------------------------------------------ NOUVELLE PUB
let parsedAd = null;
let selectedStyle = "avatar";
let selectedMode = "premium";
let lastEstimate = null;

// -- Étape 1 : choix du style --
document.querySelectorAll(".style-card").forEach((card) => {
  card.addEventListener("click", () => {
    if (card.disabled || card.classList.contains("soon")) {
      return toast("Ce style arrive bientôt.");
    }
    document.querySelectorAll(".style-card").forEach((c) => c.classList.remove("active"));
    card.classList.add("active");
    selectedStyle = card.dataset.style;
    applyStyleFlow(selectedStyle);
  });
});

// Bascule l'interface entre les flux Avatar / Objet animé / Voix off.
function applyStyleFlow(style) {
  $("avatarFlow").classList.toggle("hidden", style !== "avatar");
  $("objetFlow").classList.toggle("hidden", style !== "objet_vivant");
  $("voixoffFlow").classList.toggle("hidden", style !== "voix_off");
  $("mashupFlow").classList.toggle("hidden", style !== "mashup");
  $("avatarOmniFlow").classList.toggle("hidden", style !== "avatar_omni");
  if (style === "avatar_omni") aoEnsureVoiceSelects();
}

// -- Étape 3 : cerveau IA --
$("brainBtn").addEventListener("click", async () => {
  const script = $("scriptText").value.trim();
  const brief = $("briefText").value.trim();
  const avatar_label = $("avatarSelect").value;
  const msg = $("brainMsg");
  if (!script) return toast("Colle d'abord ton script.");
  if (!avatar_label) return toast("Choisis un avatar (ou ajoute-en un dans Réglages).");

  msg.innerHTML = "🧠 Découpage en cours…";
  $("brainBtn").disabled = true;
  try {
    const r = await api("/api/brain/generate-scenes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script, brief, style: selectedStyle, avatar_label }),
    });
    parsedAd = { ad: r.ad, avatar: r.avatar, scenes: r.scenes };
    msg.innerHTML = `<div class="ok">✓ ${r.scenes.length} scènes générées${r.dry_run ? " (simulation)" : ""}.</div>`;
    showPreview(parsedAd, r.estimate);
  } catch (e) {
    msg.innerHTML = `<div class="ko">✗ ${esc(e.message)}</div>`;
  } finally {
    $("brainBtn").disabled = false;
  }
});

// -- Import d'un scenes.json (avancé / secours) --
$("importJsonBtn").addEventListener("click", () => $("scenesFile").click());
$("scenesFile").addEventListener("change", (ev) => {
  const f = ev.target.files[0];
  if (!f) return;
  const rd = new FileReader();
  rd.onload = async () => {
    let data;
    try {
      data = JSON.parse(String(rd.result));
    } catch {
      return toast("JSON invalide — vérifie le format.");
    }
    const scenes = data.scenes || [];
    if (!scenes.length) return toast("Aucune scène dans le JSON.");
    parsedAd = { ad: data.ad || "pub", avatar: data.avatar, scenes };
    await populateNewPubSelectors(data.avatar, data.voice);
    const est = await api("/api/estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenes }),
    });
    showPreview(parsedAd, est);
  };
  rd.readAsText(f, "utf-8");
});

function showPreview(ad, est) {
  lastEstimate = est;
  $("adName").value = ad.ad || "pub";
  const prev = $("scenesPreview");
  prev.innerHTML = "";
  (ad.scenes || []).forEach((s, i) => {
    const div = document.createElement("div");
    div.className = "scene-card";
    div.innerHTML =
      `<div><span class="n">#${s.n ?? i + 1}</span></div>` +
      `<div class="script">${esc(s.script || "")}</div>` +
      `<div class="motion">🎭 ${esc(s.motion_prompt || "—")}</div>`;
    prev.appendChild(div);
  });
  renderModeCosts(est);
  // mode par défaut = celui des Réglages
  selectMode((currentSettings && currentSettings.cost_mode) || "premium");
  $("adPreview").classList.remove("hidden");
}

function renderModeCosts(est) {
  const cm = est.credits_par_mode || {};
  const tx = est.taux_par_mode || {};
  $("modeCostPremium").textContent = `≈ ${frNum(cm.premium ?? 0)} crédits  ·  ${tx.premium ?? 4} cr/s`;
  $("modeCostClassique").textContent = `≈ ${frNum(cm.classique ?? 0)} crédits  ·  ${tx.classique ?? 2} cr/s`;
}

function selectMode(mode) {
  selectedMode = ["classique", "voix_seules"].includes(mode) ? mode : "premium";
  document.querySelectorAll(".mode-card").forEach((c) =>
    c.classList.toggle("active", c.dataset.mode === selectedMode)
  );
  updateEstimateLine();
}

function updateEstimateLine() {
  const est = lastEstimate;
  if (!est) return;
  const n = est.scenes || 0;
  if (selectedMode === "voix_seules") {
    $("estimate").innerHTML =
      `Mode <b>Voix seules</b> : <b>0 crédit API</b> ` +
      `<span class="muted">(${n} scène${n > 1 ? "s" : ""} — voix Gradium uniquement)</span>` +
      `<div class="card-sub">Un dossier avec les audios numérotés (1.wav, 2.wav…) + un récap s'ouvrira à la fin. ` +
      `Tu finis la vidéo dans HeyGen à la main. Aucun crédit vidéo dépensé.</div>`;
    return;
  }
  const total = (est.credits_par_mode && est.credits_par_mode[selectedMode]) ?? est.credits_estimes ?? 0;
  const perScene = n ? Math.round(total / n) : 0;
  const label = selectedMode === "classique" ? "Classique" : "Premium";
  $("estimate").innerHTML =
    `Mode <b>${label}</b> : ≈ <b>${frNum(total)} crédit${total > 1 ? "s" : ""} au total</b> ` +
    `<span class="muted">(${n} scène${n > 1 ? "s" : ""}, ~${frNum(perScene)} crédit${perScene > 1 ? "s" : ""}/scène)</span>` +
    `<div class="card-sub">~${est.minutes} min de vidéo · payé seulement en mode réel</div>`;
}

document.querySelectorAll(".mode-card").forEach((card) => {
  card.addEventListener("click", () => selectMode(card.dataset.mode));
});

async function populateAvatarSelect(selected) {
  const s = currentSettings || (await api("/api/settings"));
  currentSettings = s;
  const sel = $("avatarSelect");
  sel.innerHTML = "";
  (s.avatars || []).forEach((a) => {
    const o = document.createElement("option");
    o.value = a.label;
    o.textContent = `${a.label} (${a.avatar_id})`;
    if (a.label === selected) o.selected = true;
    sel.appendChild(o);
  });
  if (!(s.avatars || []).length) {
    const o = document.createElement("option");
    o.value = "";
    o.textContent = "— aucun avatar (ajoute-en dans Réglages) —";
    sel.appendChild(o);
  }
}

async function populateVoiceSelect(selected) {
  const s = currentSettings || (await api("/api/settings"));
  currentSettings = s;
  const sel = $("voiceSelect");
  sel.innerHTML = "";
  (s.voices || []).forEach((v) => {
    const o = document.createElement("option");
    o.value = v.label;               // on choisit par LABEL, l'ID reste interne
    o.textContent = v.label;         // jamais l'ID à l'écran
    if (v.label === selected) o.selected = true;
    sel.appendChild(o);
  });
  if (!(s.voices || []).length) {
    const o = document.createElement("option");
    o.value = "";
    o.textContent = "— aucune voix (ajoute-en dans Réglages) —";
    sel.appendChild(o);
  }
}

async function populateNewPubSelectors(avatarLabel, voiceLabel) {
  await populateAvatarSelect(avatarLabel);
  await populateVoiceSelect(voiceLabel);
  populateSelectFromVoices("voVoiceSelect", voiceLabel);
}

// Remplit un <select> de voix (par label) depuis les réglages déjà chargés.
function populateSelectFromVoices(selectId, selected) {
  const sel = $(selectId);
  if (!sel) return;
  const voices = (currentSettings && currentSettings.voices) || [];
  sel.innerHTML = "";
  voices.forEach((v) => {
    const o = document.createElement("option");
    o.value = v.label;
    o.textContent = v.label;
    if (v.label === selected) o.selected = true;
    sel.appendChild(o);
  });
  if (!voices.length) {
    const o = document.createElement("option");
    o.value = "";
    o.textContent = "— aucune voix (ajoute-en dans Réglages) —";
    sel.appendChild(o);
  }
}

$("generateBtn").addEventListener("click", async () => {
  if (!parsedAd) return;
  const scenes = parsedAd.scenes || [];
  const avatar_label = $("avatarSelect").value;
  const voice_label = $("voiceSelect").value;
  const voixSeules = selectedMode === "voix_seules";
  if (!voixSeules && !avatar_label) return toast("Choisis un avatar (ou ajoute-en un dans Réglages).");
  if (!voice_label) return toast("Choisis une voix (ou ajoute-en une dans Réglages).");

  // Mode « Voix seules » : aucun crédit vidéo → pas de confirmation de dépense.
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!voixSeules && !dryRun) {
    const total =
      (lastEstimate && lastEstimate.credits_par_mode && lastEstimate.credits_par_mode[selectedMode]) ?? "?";
    const label = selectedMode === "classique" ? "Classique" : "Premium";
    const ok = await showModal({
      title: "Mode réel — dépense de crédits",
      message: `Mode ${label} : cette génération va dépenser ≈ ${total === "?" ? "?" : frNum(total)} crédits HeyGen pour de vrai. Continuer ?`,
      confirmText: "Générer",
      cancelText: "Annuler",
      danger: true,
    });
    if (!ok) return;
  }

  let res;
  try {
    res = await api("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ad_name: $("adName").value.trim() || "pub",
        avatar_label,
        voice_label,
        cost_mode: selectedMode,
        scenes,
        confirm: true,
      }),
    });
  } catch (e) {
    return toast(e.message);
  }

  _lastAvatarAdId = res.ad_id;
  $("retryFailedBtn").classList.add("hidden");
  $("progressArea").classList.remove("hidden");
  initSceneProgress(scenes);
  pollJob(res.job_id);
});

// Relance EN PARALLÈLE uniquement les scènes en échec de la dernière pub avatar.
let _lastAvatarAdId = null;
$("retryFailedBtn").addEventListener("click", async () => {
  if (_lastAvatarAdId == null) return;
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    const ok = await showModal({
      title: "Relancer les scènes en échec",
      message: "Cette relance va rappeler HeyGen (crédits) pour les scènes qui ont planté. Continuer ?",
      confirmText: "Réessayer", cancelText: "Annuler", danger: true,
    });
    if (!ok) return;
  }
  let res;
  try {
    res = await api("/api/generate/retry/" + _lastAvatarAdId, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
  } catch (e) {
    return toast(e.message);
  }
  $("retryFailedBtn").classList.add("hidden");
  toast(`Relance de ${res.retry} scène(s) en échec…`);
  pollJob(res.job_id);
});

function initSceneProgress(scenes) {
  const ul = $("sceneProgress");
  ul.innerHTML = "";
  scenes.forEach((s, i) => {
    const n = s.n ?? i + 1;
    const li = document.createElement("li");
    li.id = "sp-" + n;
    li.innerHTML =
      `<div class="sp-row"><span class="dot"></span><span>Scène ${n}</span>` +
      `<span class="phase">en attente</span></div><div class="scene-err"></div>`;
    ul.appendChild(li);
  });
  $("progFill").style.width = "0%";
  $("progCount").textContent = "";
  if ($("progPhase")) {
    $("progPhase").textContent = "Phase 1 — Voix (Gradium, 2 max)…";
    $("progPhase").className = "prog-phase p1";
  }
}

const PHASE_LABEL = {
  en_attente: "en attente", voix: "voix off…", voix_ok: "voix ✓ (attente vidéo)",
  upload: "envoi audio…", rendu: "rendu vidéo…", image: "image…", animation: "animation…",
  clip: "clip ✓", pret: "prêt ✓", erreur: "échec", attente_tier1: "pause Tier 1",
};

// Traduit une erreur brute (Gradium/HeyGen) en message court et lisible.
// Le message complet reste disponible au survol (title).
function prettyError(raw) {
  const m = String(raw || "échec");
  if (/unauthor|invalid api key|authentication|clé.*refus/i.test(m)) return "clé API refusée — vérifie-la dans Réglages";
  if (/quota|insufficient|not enough|no.*credit|crédits insuffisants/i.test(m)) return "crédits insuffisants";
  if (/too long|trop long|max.*char|character limit|1500\s*(car|char)/i.test(m)) return "texte trop long (max 1500 car.)";
  if (/voice.*not found|voix introuvable|invalid voice|unknown voice/i.test(m)) return "voix introuvable";
  if (/content type not match|audio\/x-wav|format audio/i.test(m)) return "format audio refusé par HeyGen";
  if (/avatar.*not found|invalid avatar|avatar introuvable/i.test(m)) return "avatar introuvable";
  // Le backend renvoie désormais un message FR clair → on l'affiche tel quel, SAUF s'il ressemble
  // encore à du brut technique (JSON, trace, code HTTP, balise) → message générique. Le texte
  // complet reste disponible dans l'infobulle (title=) là où les lignes sont rendues.
  if (/[{}]|"message"\s*:|traceback|error code|exception|<\/?[a-z]/i.test(m)) {
    return "erreur inattendue — réessaie ; si ça persiste, vérifie tes clés (Réglages)";
  }
  return m.length > 140 ? m.slice(0, 140) + "…" : m;
}

async function pollJob(jobId) {
  try {
    const j = await api("/api/jobs/" + jobId);
    (j.scenes || []).forEach((sc) => {
      const li = $("sp-" + sc.n);
      if (!li) return;
      const dot = li.querySelector(".dot");
      const phase = li.querySelector(".phase");
      const errEl = li.querySelector(".scene-err");
      dot.className = "dot " + (sc.status === "ok" ? "ok" : sc.status === "echec" ? "echec" : sc.phase === "en_attente" ? "" : "en_cours");
      phase.textContent = PHASE_LABEL[sc.phase] || sc.phase || "";
      // Affiche le VRAI message d'erreur sous la scène (et au survol), pas juste « échec ».
      if (sc.status === "echec") {
        const msg = prettyError(sc.message);
        errEl.textContent = "⚠ " + msg;
        errEl.title = sc.message || msg;
        errEl.style.display = "block";
      } else {
        errEl.textContent = "";
        errEl.style.display = "none";
      }
    });
    // Bannière des 2 phases (avatar) : Phase 1 voix (X/total) → Phase 2 vidéos.
    const phaseEl = $("progPhase");
    if (phaseEl) {
      const vd = j.voices_done ?? 0;
      if (j.phase === "voix") {
        phaseEl.textContent = `Phase 1 — Voix (Gradium, 2 max) : ${vd}/${j.total} générées`;
        phaseEl.className = "prog-phase p1";
      } else if (j.phase === "videos") {
        phaseEl.textContent = `Phase 2 — Vidéos (HeyGen, en parallèle) · voix ${vd}/${j.total} prêtes`;
        phaseEl.className = "prog-phase p2";
      } else {
        phaseEl.textContent = "";
        phaseEl.className = "prog-phase";
      }
    }
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    $("progFill").style.width = pct + "%";
    $("progCount").textContent = `${j.done}/${j.total} vidéos`;

    if (j.state === "en_cours" || j.state === "en_attente") {
      setTimeout(() => pollJob(jobId), 800);
    } else {
      const sm = j.summary || {};
      if (sm.status === "voix_seules" || sm.folder) {
        // Mode « Voix seules » : pas de vidéo, pas de Bibliothèque → message + dossier ouvert.
        showModal({
          title: "🎙️ Voix générées (0 crédit API)",
          message:
            (sm.message || "Voix générées.") +
            (sm.folder ? `\n\nDossier : ${sm.folder}\n(Il vient de s'ouvrir dans l'explorateur.)` : ""),
          confirmText: "OK",
          cancelText: "",
        });
      } else {
        const failed = Number(sm.echec || 0);
        toast(
          `Terminé : ${sm.ok ?? j.done} clip(s) prêt(s)` +
          (failed ? `, ${failed} en échec.` : ".")
        );
        // Bouton « réessayer les échoués » (relance parallèle) si au moins une scène a planté.
        $("retryFailedBtn").classList.toggle("hidden", !(failed > 0 && _lastAvatarAdId != null));
        loadLibrary();
      }
    }
  } catch (e) {
    toast("Suivi interrompu : " + e.message);
  }
}

// ================================================ OBJET ANIMÉ (Nano Banana + Grok)
let objRefsFiles = [];
let objRefsKinds = [];   // type par réf (jalon 2a) : visage / produit / decor / style
let objShots = [];
let objAdId = null;
let lastObjEstimate = null;

// Types de référence (jalon 2) — libellés FR, valeurs envoyées à l'API.
const REF_KIND_OPTS = [
  { v: "", t: "Type ?" },
  { v: "visage", t: "Visage" },
  { v: "produit", t: "Produit" },
  { v: "decor", t: "Décor" },
  { v: "style", t: "Style" },
];

// Avatar IA : deux personnages → « visage » (personnage 1, parle) / « visage2 » (personnage 2).
const AO_REF_KIND_OPTS = [
  { v: "", t: "Type ?" },
  { v: "visage", t: "Visage perso 1" },
  { v: "visage2", t: "Visage perso 2" },
  { v: "produit", t: "Produit" },
  { v: "decor", t: "Décor" },
  { v: "style", t: "Style" },
];

// Contrôles par plan (jalon 2b/2c) : quels types de réfs ce plan utilise + bouton ANCRE.
function planRefsControls(s, opts = REF_KIND_OPTS) {
  const wrap = document.createElement("div");
  wrap.className = "plan-refs";
  const lbl = document.createElement("span");
  lbl.className = "lbl";
  lbl.textContent = "Réfs utilisées :";
  wrap.appendChild(lbl);
  s.refs_needed = Array.isArray(s.refs_needed) ? s.refs_needed : [];
  opts.filter((o) => o.v).forEach((o) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "ref-chip" + (s.refs_needed.includes(o.v) ? " on" : "");
    chip.textContent = o.t;
    chip.addEventListener("click", async () => {
      const on = s.refs_needed.includes(o.v);
      const next = on ? s.refs_needed.filter((k) => k !== o.v) : [...s.refs_needed, o.v];
      try {
        const res = await api("/api/clips/" + s.clip_id + "/refs", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refs_needed: next }),
        });
        s.refs_needed = res.refs_needed;
        chip.classList.toggle("on", s.refs_needed.includes(o.v));
      } catch (e) { toast(e.message); }
    });
    wrap.appendChild(chip);
  });
  // Ancre de cohérence : seulement pertinent si le plan a une image.
  if (s.image_url) {
    const anchor = document.createElement("button");
    anchor.type = "button";
    anchor.className = "ref-chip anchor" + (s.is_anchor ? " on" : "");
    anchor.title = "Utiliser ce plan comme ancre de cohérence (personnage/look de référence)";
    anchor.textContent = s.is_anchor ? "⚓ Ancre" : "⚓";
    anchor.addEventListener("click", async () => {
      try {
        const res = await api("/api/clips/" + s.clip_id + "/anchor", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_anchor: !s.is_anchor }),
        });
        s.is_anchor = res.is_anchor;
        anchor.classList.toggle("on", s.is_anchor);
        anchor.textContent = s.is_anchor ? "⚓ Ancre" : "⚓";
      } catch (e) { toast(e.message); }
    });
    wrap.appendChild(anchor);
  }
  return wrap;
}

function refKindSelect(value, onChange, opts = REF_KIND_OPTS) {
  const sel = document.createElement("select");
  sel.className = "ref-kind";
  sel.title = "À quoi sert cette référence ?";
  opts.forEach((o) => {
    const opt = document.createElement("option");
    opt.value = o.v;
    opt.textContent = o.t;
    if (o.v === (value || "")) opt.selected = true;
    sel.appendChild(opt);
  });
  sel.addEventListener("click", (ev) => ev.stopPropagation());
  sel.addEventListener("change", (ev) => onChange(ev.target.value));
  return sel;
}

// --- Zone de dépôt (drag & drop) des photos produit, + clic de secours ---
function renderObjRefs() {
  const box = $("objRefsPreview");
  box.innerHTML = "";
  objRefsFiles.forEach((f, idx) => {
    const cell = document.createElement("div");
    cell.className = "ref-thumb";
    const img = document.createElement("img");
    img.alt = f.name;
    const rd = new FileReader();
    rd.onload = () => (img.src = String(rd.result));
    rd.readAsDataURL(f);
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "ref-remove";
    rm.title = "Retirer cette image";
    rm.textContent = "×";
    rm.addEventListener("click", () => {
      objRefsFiles.splice(idx, 1);
      objRefsKinds.splice(idx, 1);
      renderObjRefs();
    });
    cell.appendChild(img);
    cell.appendChild(rm);
    cell.appendChild(refKindSelect(objRefsKinds[idx], (v) => { objRefsKinds[idx] = v; }));
    box.appendChild(cell);
  });
}

function addObjRefs(fileList) {
  const imgs = Array.from(fileList || []).filter((f) => f.type.startsWith("image/"));
  imgs.forEach((f) => {
    // dédoublonnage simple (nom + taille) pour éviter les ajouts en double
    if (!objRefsFiles.some((x) => x.name === f.name && x.size === f.size)) {
      objRefsFiles.push(f);
      objRefsKinds.push("");
    }
  });
  renderObjRefs();
}

(function initObjDropzone() {
  const dz = $("objDropzone");
  const input = $("objRefs");
  if (!dz || !input) return;
  const openPicker = () => input.click();
  dz.addEventListener("click", (ev) => {
    if (ev.target === input) return;
    openPicker();
  });
  $("objRefsBtn").addEventListener("click", (ev) => {
    ev.stopPropagation();
    openPicker();
  });
  dz.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      openPicker();
    }
  });
  input.addEventListener("change", (ev) => {
    addObjRefs(ev.target.files);
    input.value = ""; // permet de re-sélectionner le même fichier plus tard
  });
  ["dragenter", "dragover"].forEach((evt) =>
    dz.addEventListener(evt, (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      dz.classList.add("dragover");
    })
  );
  ["dragleave", "dragend"].forEach((evt) =>
    dz.addEventListener(evt, (ev) => {
      ev.preventDefault();
      dz.classList.remove("dragover");
    })
  );
  dz.addEventListener("drop", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    dz.classList.remove("dragover");
    addObjRefs(ev.dataTransfer && ev.dataTransfer.files);
  });
})();

$("objPlanBtn").addEventListener("click", async () => {
  const product_name = $("objProduct").value.trim();
  const ambiance = $("objAmbiance").value.trim();
  const persona = $("objPersona").value.trim();
  const script = $("objScript").value;   // VERBATIM (on n'altère même pas les espaces ici)
  const manual = $("objManual").checked; // je découpe moi-même (blocs) vs cerveau (auto)
  const msg = $("objPlanMsg");
  // Nom du produit FACULTATIF : si vide, le cerveau se base sur les photos de référence.
  if (!script.trim()) return toast("Écris le script (ce que ton objet doit dire).");
  msg.innerHTML = manual ? "🎬 Préparation de tes plans…" : "🎬 Découpage du script en plans…";
  $("objPlanBtn").disabled = true;
  try {
    const r = await api("/api/objet/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_name, ambiance, persona, script, manual }),
    });
    objShots = r.shots || [];
    msg.innerHTML = `<div class="ok">✓ ${objShots.length} plans générés${r.dry_run ? " (simulation)" : ""}.</div>`;
    renderObjPlan(objShots, r.estimate);
  } catch (e) {
    msg.innerHTML = `<div class="ko">✗ ${esc(e.message)}</div>`;
  } finally {
    $("objPlanBtn").disabled = false;
  }
});

$("objManual").addEventListener("change", () => {
  document.querySelectorAll(".objManualOn").forEach((el) =>
    el.classList.toggle("hidden", !$("objManual").checked)
  );
});

function renderObjPlan(shots, est) {
  lastObjEstimate = est || null;
  const list = $("objPlanList");
  list.innerHTML = "";
  shots.forEach((s) => {
    const div = document.createElement("div");
    div.className = "scene-card";
    div.innerHTML =
      `<div><span class="n">#${s.n}</span></div>` +
      `<div class="script">🖼️ ${esc(s.prompt_image)}</div>` +
      `<div class="motion">🎬 ${esc(s.prompt_motion)}</div>` +
      (s.dialogue ? `<div class="motion">💬 ${esc(s.dialogue)}</div>` : "");
    list.appendChild(div);
  });
  const e = est || {};
  $("objEstimate").innerHTML =
    `≈ <b>$${(e.usd_images || 0).toFixed(2)}</b> pour les ${e.shots || shots.length} images ` +
    `<span class="muted">(Nano Banana : gratuit jusqu'à ~500/jour · animation Grok ensuite : ~$${(e.usd_video || 0).toFixed(2)} pour les plans validés)</span>` +
    `<div class="card-sub">Payé seulement en mode réel. En simulation : $0.</div>`;
  $("objPlanArea").classList.remove("hidden");
}

$("objGenImagesBtn").addEventListener("click", async () => {
  if (!objShots.length) return toast("Génère d'abord le plan de tournage.");
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    if (!(currentSettings && currentSettings.openrouter_api_key_set))
      return toast("Ajoute ta clé OpenRouter (Nano Banana) dans Réglages (Objet animé).");
    const perImg = (lastObjEstimate && lastObjEstimate.cout_par_image_usd) || 0.04;
    const ok = await showModal({
      title: "Mode réel — Plan 1 (le personnage)",
      message: `On génère UNIQUEMENT le Plan 1 (≈ $${perImg.toFixed(2)}, 1 image Nano Banana). Tu le valides, puis tu génères les plans suivants. Continuer ?`,
      confirmText: "Générer le Plan 1",
      cancelText: "Annuler",
      danger: true,
    });
    if (!ok) return;
  }
  const fd = new FormData();
  fd.append("ad_name", $("objProduct").value.trim() || "pub");
  fd.append("shots_json", JSON.stringify(objShots));
  fd.append("confirm", "true");
  fd.append("ref_kinds", JSON.stringify(objRefsKinds));
  objRefsFiles.forEach((f) => fd.append("files", f, f.name));

  let res;
  try {
    res = await api("/api/objet/generate-images", { method: "POST", body: fd });
  } catch (e) {
    return toast(e.message);
  }
  objAdId = res.ad_id;
  $("objProgress").classList.remove("hidden");
  initObjProgress(objShots.slice(0, res.generated_now || 1));  // séquentiel : Plan 1 seulement
  pollObjJob(res.job_id, () => loadObjGallery(objAdId));
});

function initObjProgress(shots) {
  const ul = $("objSceneProgress");
  ul.innerHTML = "";
  shots.forEach((s) => {
    const li = document.createElement("li");
    li.id = "osp-" + s.n;
    li.innerHTML =
      `<div class="sp-row"><span class="dot"></span><span>Plan ${s.n}</span>` +
      `<span class="phase">en attente</span></div><div class="scene-err"></div>`;
    ul.appendChild(li);
  });
  $("objProgFill").style.width = "0%";
  $("objProgCount").textContent = "";
}

async function pollObjJob(jobId, onDone) {
  try {
    const j = await api("/api/jobs/" + jobId);
    (j.scenes || []).forEach((sc) => {
      const li = $("osp-" + sc.n);
      if (!li) return;
      const dot = li.querySelector(".dot");
      const phase = li.querySelector(".phase");
      const errEl = li.querySelector(".scene-err");
      dot.className = "dot " + (sc.status === "ok" ? "ok" : sc.status === "echec" ? "echec" : sc.phase === "en_attente" ? "" : "en_cours");
      phase.textContent = PHASE_LABEL[sc.phase] || sc.phase || "";
      if (sc.status === "echec") {
        errEl.textContent = "⚠ " + prettyError(sc.message);
        errEl.title = sc.message || "";
        errEl.style.display = "block";
      } else {
        errEl.textContent = "";
        errEl.style.display = "none";
      }
    });
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    $("objProgFill").style.width = pct + "%";
    $("objProgCount").textContent = `${j.done}/${j.total} images`;
    if (j.state === "en_cours" || j.state === "en_attente") {
      setTimeout(() => pollObjJob(jobId, onDone), 800);
    } else {
      // Échec GLOBAL du job (ex. upload des réfs non calé en mode réel) : la boucle par-plan
      // n'a rien émis → on affiche le message du job, sinon l'utilisateur ne voit rien.
      if (j.state === "echec") {
        const m = (j.summary && j.summary.message) || "Échec de la génération des images.";
        toast(prettyError(m));
      }
      if (onDone) onDone();
    }
  } catch (e) {
    toast("Suivi interrompu : " + e.message);
  }
}

async function loadObjGallery(adId) {
  if (!adId) return;
  const r = await api("/api/objet/ad/" + adId);
  $("objValidation").classList.remove("hidden");
  const g = $("objGallery");
  renderOverviewBanner(g, r, "objet", adId);
  g.innerHTML = "";
  (r.shots || []).forEach((s) => g.appendChild(objShotCard(s)));
}

// JALON 3 — bannière « vue d'ensemble » : coût réel cumulé, échecs, reprise, alerte facturation.
function renderOverviewBanner(gallery, r, kind, adId) {
  const id = kind + "Overview";
  const old = document.getElementById(id);
  if (old) old.remove();
  const banner = document.createElement("div");
  banner.id = id;
  banner.className = "overview";
  const cost = money(r.cost_real_usd || 0);
  const nEchec = r.n_echec || 0;
  let html = `<div class="ov-line"><span class="ov-cost">💸 Coût réel déjà engagé : <strong>${cost}</strong></span>`;
  if (nEchec > 0) html += `<span class="ov-fail">✗ ${nEchec} plan(s) en échec</span>`;
  html += `</div>`;
  if (r.billed_despite_failure)
    html += `<div class="ov-warn">⚠ Des coûts ont pu être facturés MALGRÉ des échecs (certains services facturent l'appel même quand le rendu échoue).</div>`;
  banner.innerHTML = html;
  if (nEchec > 0) {
    const btn = document.createElement("button");
    btn.className = "btn small";
    btn.textContent = "↻ Reprendre les plans en échec";
    btn.addEventListener("click", () => resumeFailedPlans(kind, adId));
    banner.appendChild(btn);
  }
  gallery.before(banner);
}

// Segment d'URL de l'API par kind de pub (le kind « avatar_omni » est servi sous /api/avatar-omni).
const KIND_API = { objet: "objet", mashup: "mashup", avatar_omni: "avatar-omni" };

async function resumeFailedPlans(kind, adId) {
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    const omniNote = kind === "avatar_omni"
      ? "\n\nAvatar IA : si l'animation est relancée, Google Omni facture ~0,10 $/s (quota Tier 1 : 10 $ par tranche de 10 min)."
      : "";
    const ok = await showModal({
      title: "Reprendre les plans en échec",
      message: "Relance UNIQUEMENT les plans en échec (les plans déjà prêts ne sont pas retouchés). Étape payante. Continuer ?" + omniNote,
      confirmText: "Reprendre", cancelText: "Annuler", danger: true,
    });
    if (!ok) return;
  }
  const post = (over) =>
    api("/api/" + (KIND_API[kind] || kind) + "/resume/" + adId, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true, confirm_over_cap: !!over }),
    });
  let res;
  try {
    res = await post(false);
  } catch (e) {
    if (/plafond/i.test(e.message)) {
      const ok = await showModal({
        title: "⚠ Dépassement du plafond de dépense",
        message: e.message + "\n\nConfirmer et reprendre malgré le plafond ?",
        confirmText: "Dépasser et reprendre", cancelText: "Annuler", danger: true,
      });
      if (!ok) return;
      try { res = await post(true); } catch (e2) { return toast(e2.message); }
    } else {
      return toast(e.message);
    }
  }
  toast(`Reprise lancée (${res.phase === "images" ? "régénération d'images" : "animation"}, ${res.n} plan(s)).`);
  const reload = () =>
    kind === "objet" ? loadObjGallery(adId)
    : kind === "avatar_omni" ? (loadAoGallery(adId), loadLibrary())
    : loadMashGallery(adId);
  pollResumeJob(res.job_id, reload);
}

async function pollResumeJob(jobId, onDone) {
  try {
    const j = await api("/api/jobs/" + jobId);
    if (j.state === "en_cours" || j.state === "en_attente") {
      setTimeout(() => pollResumeJob(jobId, onDone), 800);
    } else {
      if (j.state === "echec") toast(prettyError((j.summary && j.summary.message) || "Reprise en échec."));
      if (onDone) onDone();
    }
  } catch (e) {
    toast("Suivi de la reprise interrompu : " + e.message);
  }
}

function objShotCard(s) {
  const card = document.createElement("div");
  const valid = s.status === "valide";
  card.className = "obj-shot" + (valid ? " valide" : "");
  const badge = valid
    ? '<span class="badge ok">validé ✓</span>'
    : s.status === "echec"
    ? '<span class="badge ko">échec</span>'
    : '<span class="badge">à valider</span>';
  // cache-buster : l'image régénérée réutilise la même URL (même chemin) → sans ça, le
  // navigateur resservirait l'ancienne image depuis son cache.
  const bust = s.image_url ? (s.image_url.includes("?") ? "&" : "?") + "t=" + Date.now() : "";
  const thumb = s.image_url
    ? `<img class="thumb" src="${esc(s.image_url)}${bust}" alt="plan ${s.n}" />`
    : `<div class="thumb empty">${esc(s.error || "pas d'image")}</div>`;
  card.innerHTML =
    thumb +
    `<div class="body">` +
    `<div class="head"><span class="n">Plan ${s.n}</span>${badge}</div>` +
    `<div class="lbl">Mise en scène (prompt image, éditable)</div>` +
    `<textarea class="pi">${esc(s.prompt_image)}</textarea>` +
    `<div class="motion">🎬 ${esc(s.prompt_motion)}</div>` +
    `<div class="lbl">💬 Dialogue — ce que l'objet DIT (français, verbatim). Grok fait la voix + lip-sync.</div>` +
    `<textarea class="vo" placeholder="Laisse vide = clip sans parole">${esc(s.dialogue || "")}</textarea>` +
    `<div class="actions">` +
    `<button class="btn primary btn-valid">${valid ? "Dévalider" : "Valider"}</button>` +
    `<button class="btn btn-regen">Régénérer</button>` +
    `</div></div>`;

  card.querySelector(".body").insertBefore(
    planRefsControls(s), card.querySelector(".actions")
  );

  // Sauvegarde du DIALOGUE (verbatim, jamais modifié) à la perte de focus.
  const voEl = card.querySelector(".vo");
  voEl.addEventListener("blur", async () => {
    const text = voEl.value;
    if (text === (s.dialogue || "")) return;
    try {
      await api("/api/objet/dialogue/" + s.clip_id, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      s.dialogue = text;
    } catch (e) {
      toast(e.message);
    }
  });

  card.querySelector(".btn-valid").addEventListener("click", async () => {
    try {
      const res = await api("/api/objet/validate/" + s.clip_id, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ valide: !valid }),
      });
      s.status = res.status;
      card.replaceWith(objShotCard(s));
    } catch (e) {
      toast(e.message);
    }
  });

  card.querySelector(".btn-regen").addEventListener("click", async () => {
    const prompt_image = card.querySelector(".pi").value.trim();
    const dryRun = currentSettings && currentSettings.dry_run;
    if (!dryRun) {
      const ok = await showModal({
        title: "Régénérer l'image",
        message: "Régénérer cette image via Nano Banana (payant au-delà du quota gratuit ~500/jour). Continuer ?",
        confirmText: "Régénérer",
        cancelText: "Annuler",
        danger: true,
      });
      if (!ok) return;
    }
    card.classList.add("busy");
    try {
      const res = await api("/api/objet/regenerate-image/" + s.clip_id, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_image, confirm: true }),
      });
      await waitJobDone(res.job_id);
      // Ne recharge QUE cette carte (préserve les prompts édités non régénérés des autres).
      const ad = await api("/api/objet/ad/" + objAdId);
      const updated = (ad.shots || []).find((x) => x.clip_id === s.clip_id);
      if (updated) card.replaceWith(objShotCard(updated));
      else card.classList.remove("busy");
    } catch (e) {
      toast(e.message);
      card.classList.remove("busy");
    }
  });

  return card;
}

function waitJobDone(jobId) {
  return new Promise((resolve) => {
    const tick = async () => {
      try {
        const j = await api("/api/jobs/" + jobId);
        if (j.state === "en_cours" || j.state === "en_attente") setTimeout(tick, 700);
        else resolve(j);
      } catch {
        resolve(null);
      }
    };
    tick();
  });
}

$("objRefreshBtn").addEventListener("click", () => loadObjGallery(objAdId));

// Uniformiser le personnage : régénère les autres plans depuis le Plan 1 validé.
$("objConsistencyBtn").addEventListener("click", async () => {
  if (!objAdId) return toast("Génère et valide d'abord le Plan 1.");
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    if (!(currentSettings && currentSettings.openrouter_api_key_set))
      return toast("Ajoute ta clé OpenRouter (Nano Banana) dans Réglages.");
    const ok = await showModal({
      title: "Générer les plans suivants",
      message: "Génère les plans suivants à partir de ton Plan 1 validé (MÊME personnage) + tes photos produit, via Nano Banana. Continuer ?",
      confirmText: "Générer",
      cancelText: "Annuler",
      danger: true,
    });
    if (!ok) return;
  }
  let res;
  try {
    res = await api("/api/objet/consistency/" + objAdId, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
  } catch (e) {
    return toast(e.message);
  }
  const targets = (objShots || []).filter((s) => s.n !== res.ref_plan);
  const progList = targets.length ? targets : Array.from({ length: res.n }, (_, i) => ({ n: i + 1 }));
  $("objProgress").classList.remove("hidden");
  initObjProgress(progList);
  pollObjJob(res.job_id, () => loadObjGallery(objAdId));
});

// --- Animation (phase 2) : anime les plans VALIDÉS → clips en Bibliothèque ---
$("objAnimateBtn").addEventListener("click", async () => {
  if (!objAdId) return toast("Génère et valide d'abord des plans.");
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    if (!(currentSettings && currentSettings.xai_api_key_set))
      return toast("Ajoute ta clé xAI (Grok) dans Réglages.");
    const usdVid = (lastObjEstimate && lastObjEstimate.usd_video) || 0;
    const ok = await showModal({
      title: "Animer — coût Grok (réel)",
      message: `Cette étape anime les plans VALIDÉS (image → vidéo Grok Imagine). Grok facture à la seconde (~$4,20/min à 720p) — estimé ≈ $${usdVid.toFixed(2)} pour tous les plans. Continuer ?`,
      confirmText: "Animer",
      cancelText: "Annuler",
      danger: true,
    });
    if (!ok) return;
  }
  let res;
  try {
    res = await api("/api/objet/animate/" + objAdId, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
  } catch (e) {
    // Plafond de dépense dépassé → confirmation explicite du dépassement.
    if (/plafond/i.test(e.message)) {
      const ok = await showModal({
        title: "⚠ Dépassement du plafond de dépense",
        message: e.message + "\n\nConfirmer et animer malgré le plafond ?",
        confirmText: "Dépasser et animer", cancelText: "Annuler", danger: true,
      });
      if (!ok) return;
      try {
        res = await api("/api/objet/animate/" + objAdId, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirm: true, confirm_over_cap: true }),
        });
      } catch (e2) { return toast(e2.message); }
    } else {
      return toast(e.message);
    }
  }
  $("objAnimProgress").classList.remove("hidden");
  initAnimProgress(res.n_plans || 1);
  pollAnimJob(res.job_id);
});

function initAnimProgress(count) {
  const ul = $("objAnimSceneProgress");
  ul.innerHTML = "";
  for (let i = 1; i <= count; i++) {
    const li = document.createElement("li");
    li.id = "anim-" + i;
    li.innerHTML =
      `<div class="sp-row"><span class="dot"></span><span>Plan ${i}</span>` +
      `<span class="phase">en attente</span></div><div class="scene-err"></div>`;
    ul.appendChild(li);
  }
  $("objAnimProgFill").style.width = "0%";
  $("objAnimProgCount").textContent = "";
}

async function pollAnimJob(jobId) {
  try {
    const j = await api("/api/jobs/" + jobId);
    (j.scenes || []).forEach((sc) => {
      const li = $("anim-" + sc.n);
      if (!li) return;
      const dot = li.querySelector(".dot");
      dot.className = "dot " + (sc.status === "ok" ? "ok" : sc.status === "echec" ? "echec" : sc.phase === "en_attente" ? "" : "en_cours");
      li.querySelector(".phase").textContent = PHASE_LABEL[sc.phase] || sc.phase || "";
      const errEl = li.querySelector(".scene-err");
      if (sc.status === "echec") {
        errEl.textContent = "⚠ " + prettyError(sc.message);
        errEl.title = sc.message || "";
        errEl.style.display = "block";
      } else {
        errEl.textContent = "";
        errEl.style.display = "none";
      }
    });
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    $("objAnimProgFill").style.width = pct + "%";
    $("objAnimProgCount").textContent = `${j.done}/${j.total} clips`;
    if (j.state === "en_cours" || j.state === "en_attente") {
      setTimeout(() => pollAnimJob(jobId), 800);
    } else if (j.state === "echec") {
      const sm = j.summary || {};
      showModal({ title: "Animation — échec", message: prettyError(sm.message || "L'animation a échoué."), confirmText: "OK", cancelText: "" });
    } else {
      const sm = j.summary || {};
      showModal({
        title: "🎬 Clips animés",
        message: `${sm.ok ?? j.done} clip(s) prêt(s) → disponibles dans la Bibliothèque.`,
        confirmText: "OK",
        cancelText: "",
      });
      loadObjGallery(objAdId);
    }
  } catch (e) {
    toast("Suivi interrompu : " + e.message);
  }
}

// ================================================ VOIX OFF (voix Gradium seule)
$("voPreviewBtn").addEventListener("click", async () => {
  const script = $("voScript").value;
  if (!script.trim()) return toast("Colle d'abord ton script.");
  try {
    const r = await api("/api/voiceover/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script }),
    });
    const box = $("voPreview");
    const parts = r.count === 1 ? "1 fichier audio" : `${r.count} fichiers audio numérotés`;
    box.innerHTML =
      `Découpage : <b>${parts}</b> ` +
      `<span class="muted">(${frNum(r.total_chars)} caractères, limite 1500/segment)</span>` +
      `<div class="card-sub">${r.segments.map((s) => `#${s.n} — ${frNum(s.chars)} car.`).join(" · ")}</div>`;
    box.classList.remove("hidden");
  } catch (e) {
    toast(e.message);
  }
});

$("voGenBtn").addEventListener("click", async () => {
  const script = $("voScript").value;
  const voice_label = $("voVoiceSelect").value;
  const ad_name = $("voAdName").value.trim() || "voix_off";
  if (!script.trim()) return toast("Colle d'abord ton script.");
  if (!voice_label) return toast("Choisis une voix (ou ajoute-en une dans Réglages).");
  $("voMsg").innerHTML = "";
  let res;
  try {
    res = await api("/api/voiceover/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ad_name, voice_label, script }),
    });
  } catch (e) {
    return toast(e.message);
  }
  $("voProgress").classList.remove("hidden");
  initVoProgress(res.segments);
  pollVoJob(res.job_id);
});

function initVoProgress(count) {
  const ul = $("voSceneProgress");
  ul.innerHTML = "";
  for (let i = 1; i <= count; i++) {
    const li = document.createElement("li");
    li.id = "vosp-" + i;
    li.innerHTML =
      `<div class="sp-row"><span class="dot"></span><span>Segment ${i}</span>` +
      `<span class="phase">en attente</span></div><div class="scene-err"></div>`;
    ul.appendChild(li);
  }
  $("voProgFill").style.width = "0%";
  $("voProgCount").textContent = "";
}

async function pollVoJob(jobId) {
  try {
    const j = await api("/api/jobs/" + jobId);
    (j.scenes || []).forEach((sc) => {
      const li = $("vosp-" + sc.n);
      if (!li) return;
      const dot = li.querySelector(".dot");
      const phase = li.querySelector(".phase");
      const errEl = li.querySelector(".scene-err");
      dot.className = "dot " + (sc.status === "ok" ? "ok" : sc.status === "echec" ? "echec" : sc.phase === "en_attente" ? "" : "en_cours");
      phase.textContent = PHASE_LABEL[sc.phase] || sc.phase || "";
      if (sc.status === "echec") {
        errEl.textContent = "⚠ " + prettyError(sc.message);
        errEl.title = sc.message || "";
        errEl.style.display = "block";
      } else {
        errEl.textContent = "";
        errEl.style.display = "none";
      }
    });
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    $("voProgFill").style.width = pct + "%";
    $("voProgCount").textContent = `${j.done}/${j.total} segments`;
    if (j.state === "en_cours" || j.state === "en_attente") {
      setTimeout(() => pollVoJob(jobId), 800);
    } else if (j.state === "echec") {
      // Échec GLOBAL du job (rare) : afficher l'erreur, pas une fausse réussite.
      const sm = j.summary || {};
      showModal({
        title: "Voix off — échec",
        message: prettyError(sm.message || "La génération de la voix off a échoué."),
        confirmText: "OK",
        cancelText: "",
      });
    } else {
      const sm = j.summary || {};
      showModal({
        title: "🎙️ Voix off générée",
        message:
          (sm.message || "Voix off générée.") +
          (sm.folder ? `\n\nDossier : ${sm.folder}\n(Il vient de s'ouvrir dans l'explorateur.)` : ""),
        confirmText: "OK",
        cancelText: "",
      });
    }
  } catch (e) {
    toast("Suivi interrompu : " + e.message);
  }
}

// ------------------------------------------------ BIBLIOTHÈQUE (sous-sections)
let _libTab = "avatar";

// En-tête d'un « dossier » de pub : titre + bouton « Télécharger tout (ZIP) ». `asset` cible le
// type de fichier (video | audio | image) ; le bouton n'apparaît que s'il y a quelque chose à zipper.
function libAdHeader(ad, asset, hasFiles) {
  const dl =
    hasFiles && ad.id != null
      ? `<a class="btn small dl-all" href="/api/ads/${ad.id}/download?asset=${asset}" ` +
        `title="Toutes les pièces de la pub dans un ZIP, numérotées (1, 2, 3…)">⬇ Télécharger tout (ZIP)</a>`
      : "";
  return (
    `<div class="lib-ad-head"><h2>${esc(ad.name)} ` +
    `<span class="date">${fmtDate(ad.created_at)} · ${esc(ad.status)}</span></h2>${dl}</div>`
  );
}

function renderClipAds(root, ads, emptyMsg) {
  root.innerHTML = "";
  if (!ads.length) {
    root.innerHTML = `<p class="muted">${esc(emptyMsg)}</p>`;
    return;
  }
  ads.forEach((ad) => {
    const block = document.createElement("div");
    block.className = "lib-ad";
    const hasFiles = (ad.clips || []).some((c) => c.media_url && c.status === "pret");
    block.innerHTML = libAdHeader(ad, "video", hasFiles);
    const grid = document.createElement("div");
    grid.className = "clip-grid";
    ad.clips.forEach((c) => {
      const div = document.createElement("div");
      div.className = "clip" + (c.status === "echec" ? " echec" : "");
      if (c.media_url && c.status === "pret") {
        div.innerHTML =
          `<video src="${esc(c.media_url)}" controls preload="metadata"></video>` +
          `<div class="meta"><span class="scene-n">#${c.scene_n}</span>` +
          `<a class="dl" href="/api/clips/${c.id}/download">⬇ Télécharger</a></div>`;
      } else {
        div.innerHTML =
          `<div class="meta"><span class="scene-n">#${c.scene_n}</span></div>` +
          `<div class="err">${esc(c.error || "non généré")}</div>`;
      }
      grid.appendChild(div);
    });
    block.appendChild(grid);
    root.appendChild(block);
  });
}

// Avatar (HeyGen) + Objet animé (Grok) partagent /api/library ; on filtre par ad.kind.
async function loadLibraryVideos() {
  const r = await api("/api/library");
  const avatar = r.ads.filter((a) => a.kind === "avatar");
  const objet = r.ads.filter((a) => a.kind === "objet");
  const mashup = r.ads.filter((a) => a.kind === "mashup");
  const omni = r.ads.filter((a) => a.kind === "avatar_omni");
  renderClipAds($("libAvatarContent"), avatar, "Aucune vidéo avatar (HeyGen) pour l’instant.");
  renderClipAds($("libObjetContent"), objet, "Aucun clip objet animé (Grok) pour l’instant.");
  renderClipAds($("libMashupContent"), mashup, "Aucun clip Mashup IA pour l’instant.");
  if ($("libAvatarOmniContent"))
    renderClipAds($("libAvatarOmniContent"), omni, "Aucun clip Avatar IA (Omni) pour l’instant.");
}

// Voix off : pubs audio (Voix seules + Voix off) avec lecteur + téléchargement du .wav.
async function loadVoicesLibrary() {
  const r = await api("/api/library/voices");
  const root = $("libVoicesContent");
  root.innerHTML = "";
  if (!r.ads.length) {
    root.innerHTML = '<p class="muted">Aucune voix off générée pour l’instant.</p>';
    return;
  }
  r.ads.forEach((ad) => {
    const block = document.createElement("div");
    block.className = "lib-ad";
    const hasFiles = (ad.clips || []).some((c) => c.audio_url);
    block.innerHTML = libAdHeader(ad, "audio", hasFiles);
    const list = document.createElement("div");
    list.className = "voice-list";
    ad.clips.forEach((c) => {
      const div = document.createElement("div");
      div.className = "voice-item" + (c.status === "echec" ? " echec" : "");
      if (c.audio_url) {
        div.innerHTML =
          `<div class="meta"><span class="scene-n">#${c.scene_n}</span>` +
          `<a class="dl" href="/api/clips/${c.clip_id}/audio">⬇ Télécharger</a></div>` +
          `<audio controls preload="none" src="${esc(c.audio_url)}"></audio>` +
          (c.script ? `<div class="voice-script">${esc(c.script)}</div>` : "");
      } else {
        div.innerHTML =
          `<div class="meta"><span class="scene-n">#${c.scene_n}</span></div>` +
          `<div class="err">${esc(c.error || "non généré")}</div>`;
      }
      list.appendChild(div);
    });
    block.appendChild(list);
    root.appendChild(block);
  });
}

async function loadLibTab(tab) {
  if (tab === "avatar" || tab === "objet" || tab === "mashup" || tab === "avatar_omni") await loadLibraryVideos();
  else if (tab === "voices") await loadVoicesLibrary();
  else if (tab === "photos") await loadPhotos();
}

function showLibTab(tab) {
  _libTab = tab;
  document.querySelectorAll("#library .subtab").forEach((b) =>
    b.classList.toggle("active", b.dataset.libtab === tab)
  );
  document.querySelectorAll("#library .lib-panel").forEach((p) =>
    p.classList.toggle("hidden", p.dataset.libpanel !== tab)
  );
  loadLibTab(tab);
}

document.querySelectorAll("#library .subtab").forEach((b) =>
  b.addEventListener("click", () => showLibTab(b.dataset.libtab))
);

// Ouverture de la Bibliothèque : on affiche l’onglet courant (défaut : Avatar).
function loadLibrary() {
  showLibTab(_libTab);
}
$("refreshLib").addEventListener("click", () => loadLibTab(_libTab));

// ------------------------------------------------ PHOTOS (objet animé) — sous-onglet
async function loadPhotos() {
  const r = await api("/api/photos");
  const root = $("photosContent");
  root.innerHTML = "";
  if (!r.ads.length) {
    root.innerHTML = '<p class="muted">Aucune image générée pour l’instant (objet animé, mashup, avatar IA).</p>';
    return;
  }
  r.ads.forEach((ad) => {
    const block = document.createElement("div");
    block.className = "lib-ad";
    const hasFiles = (ad.images || []).some((im) => im.image_url);
    block.innerHTML = libAdHeader(ad, "image", hasFiles);
    const grid = document.createElement("div");
    grid.className = "photo-grid";
    ad.images.forEach((im) => {
      const div = document.createElement("div");
      div.className = "photo";
      // cache-buster : une image régénérée réutilise la même URL (même chemin).
      const bust = im.image_url ? (im.image_url.includes("?") ? "&" : "?") + "t=" + Date.now() : "";
      const clipLink = im.video_url
        ? `<a class="dl vid" href="${esc(im.video_url)}" target="_blank" rel="noopener">🎬 clip animé</a>`
        : `<span class="muted small">clip : non animé</span>`;
      const thumb = im.image_url
        ? `<img src="${esc(im.image_url)}${bust}" alt="plan ${im.scene_n}" loading="lazy" />`
        : `<div class="thumb empty">pas d'image</div>`;
      div.innerHTML =
        thumb +
        `<div class="meta"><span class="scene-n">#${im.scene_n}</span>` +
        `<a class="dl" href="/api/clips/${im.clip_id}/image">⬇ Télécharger</a>${clipLink}</div>` +
        `<details class="pi"><summary>prompt image (réutiliser)</summary>` +
        `<div class="pi-text">${esc(im.prompt_image || "—")}</div></details>`;
      grid.appendChild(div);
    });
    block.appendChild(grid);
    root.appendChild(block);
  });
}

// ------------------------------------------------ COÛTS / DÉPENSES
// $ pur (utilisé par les estimations « Nouvelle pub », toujours en dollars).
function usd(n) {
  return "$" + (Number(n) || 0).toFixed(2);
}

// Devise d'AFFICHAGE de la section Coûts ($/€) — les montants restent stockés en USD en base ;
// on convertit seulement à l'affichage via _usdToEur. Choix persisté côté serveur.
let _costCurrency = "usd";
let _usdToEur = 0.92;

function money(n) {
  const v = Number(n) || 0;
  if (_costCurrency === "eur") return (v * _usdToEur).toFixed(2) + " €";
  return "$" + v.toFixed(2);
}

// -------- Graphique de pilotage (série temporelle, barres empilées par service)
let _costPeriod = "day";
let _costView = "both";
const COST_COLORS = {
  openrouter: "#5b8cff",
  grok: "#22c55e",
  kling: "#06b6d4",
  heygen: "#f59e0b",
  gradium: "#a855f7",
  anthropic: "#ec4899",
  gemini: "#84cc16",
};
const COST_COLOR_FALLBACK = ["#14b8a6", "#eab308", "#f97316", "#64748b"];

function costColor(service, i) {
  return COST_COLORS[service] || COST_COLOR_FALLBACK[i % COST_COLOR_FALLBACK.length];
}

// État d'affichage des courbes (toggle via la légende) + dernière donnée reçue (re-render sans refetch).
const COST_TOTAL_KEY = "__total__";
const _costHidden = new Set();
let _costData = null;

function applyCostView() {
  const chart = $("costChartBlock");
  const table = $("costTableBlock");
  chart.classList.toggle("hidden", _costView === "table");
  table.classList.toggle("hidden", _costView === "chart");
}

function renderCostChart(d, opt = {}) {
  const host = opt.host || $("costChart");
  const legend = opt.legend || $("costChartLegend");
  const totalEl = opt.totalEl || $("costPeriodTotal");
  const hiddenSet = opt.hidden || _costHidden;
  const buckets = d.buckets || [];
  const services = d.services || [];
  const series = d.series || {};
  totalEl.innerHTML = `Total période : <b>${money(d.total_usd || 0)}</b>`;

  const totals = d.totals_per_bucket || [];
  const dataMax = Math.max(0, ...totals);
  if (!services.length || dataMax <= 0) {
    host.innerHTML =
      '<p class="muted" style="padding:24px 8px">Aucune dépense estimée sur cette période (la simulation ne compte pas).</p>';
    legend.innerHTML = "";
    return;
  }

  const showTotal = services.length > 1;
  const isHidden = (key) => hiddenSet.has(key);
  // Échelle Y calée sur les courbes VISIBLES uniquement (comme Chart.js).
  let visMax = 0;
  services.forEach((s) => {
    if (!isHidden(s.service)) visMax = Math.max(visMax, ...(series[s.service] || [0]));
  });
  if (showTotal && !isHidden(COST_TOTAL_KEY)) visMax = Math.max(visMax, ...totals);

  // Géométrie du SVG (responsive via viewBox + width:100%).
  const W = 680, H = 280, padL = 48, padR = 14, padT = 16, padB = 30;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const n = buckets.length;
  // X : points centrés dans chaque intervalle (un point par bucket).
  const px = (i) => padL + (n === 1 ? plotW / 2 : (plotW * i) / (n - 1));
  // Échelle Y : arrondir le max vers un « joli » plafond (1 si tout est masqué).
  const niceMax = niceCeil(visMax);
  const y = (v) => padT + plotH - (v / niceMax) * plotH;

  let svg = `<svg viewBox="0 0 ${W} ${H}" class="cost-svg" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Évolution des coûts estimés (courbes)">`;
  // Gridlines + libellés Y (0, ¼, ½, ¾, max)
  for (let g = 0; g <= 4; g++) {
    const v = (niceMax * g) / 4;
    const gy = y(v);
    svg += `<line x1="${padL}" y1="${gy}" x2="${W - padR}" y2="${gy}" class="grid" />`;
    svg += `<text x="${padL - 6}" y="${gy + 3}" class="axis-y">${money(v)}</text>`;
  }
  // Libellés X (allégés en vue « jour »)
  buckets.forEach((b, i) => {
    if (n <= 8 || i % 2 === 0) {
      svg += `<text x="${px(i)}" y="${H - 10}" class="axis-x">${esc(b.label)}</text>`;
    }
  });

  // Une COURBE (ligne) par service, + une courbe « Total » en surbrillance.
  const drawLine = (vals, color, cls, dash) => {
    const pts = vals.map((v, i) => `${px(i).toFixed(1)},${y(v).toFixed(1)}`);
    const dashAttr = dash ? ` stroke-dasharray="${dash}"` : "";
    let s = `<polyline points="${pts.join(" ")}" fill="none" stroke="${color}" class="${cls}"${dashAttr} />`;
    // marqueurs + info-bulles natives
    vals.forEach((v, i) => {
      s += `<circle cx="${px(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3" fill="${color}" class="pt"><title>${esc(buckets[i].label)} : ${money(v)}</title></circle>`;
    });
    return s;
  };
  // Services d'abord (courbes fines colorées) — masquées si désactivées via la légende…
  services.forEach((s, si) => {
    if (!isHidden(s.service)) svg += drawLine(series[s.service] || [], costColor(s.service, si), "line");
  });
  // …puis le Total par-dessus (courbe épaisse pointillée, couleur accent).
  const totalColor = getVar("--accent", "#5b8cff");
  if (showTotal && !isHidden(COST_TOTAL_KEY)) {
    svg += drawLine(totals, totalColor, "line total", "5 4");
  }
  svg += "</svg>";
  host.innerHTML = svg;

  // Légende cliquable : chaque entrée affiche/masque sa courbe (indicateur d'état via .off).
  const items = services.map((s, si) => {
    const tot = (d.by_service_usd || {})[s.service] || 0;
    const off = isHidden(s.service) ? " off" : "";
    return `<button type="button" class="lg${off}" data-svc="${esc(s.service)}" aria-pressed="${!isHidden(s.service)}"><i style="background:${costColor(s.service, si)}"></i>${esc(shortServiceLabel(s.label))} <b>${money(tot)}</b></button>`;
  });
  if (showTotal) {
    const off = isHidden(COST_TOTAL_KEY) ? " off" : "";
    items.push(`<button type="button" class="lg${off}" data-svc="${COST_TOTAL_KEY}" aria-pressed="${!isHidden(COST_TOTAL_KEY)}" style="color:${totalColor}"><i class="dashed"></i><span style="color:var(--muted)">Total</span> <b>${money(d.total_usd || 0)}</b></button>`);
  }
  legend.innerHTML = items.join("");
}

function getVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function shortServiceLabel(label) {
  return String(label).split("—")[0].trim();
}

function niceCeil(v) {
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const norm = v / mag;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return step * mag;
}

async function loadCostChart() {
  try {
    const d = await api("/api/costs/timeseries?period=" + encodeURIComponent(_costPeriod));
    _costData = d;
    renderCostChart(d);
  } catch (e) {
    $("costChart").innerHTML = `<p class="err">${esc(String(e))}</p>`;
  }
}

// Légende cliquable : bascule l'affichage d'une courbe (état conservé au changement de période).
$("costChartLegend").addEventListener("click", (e) => {
  const btn = e.target.closest(".lg");
  if (!btn || !btn.dataset.svc) return;
  const key = btn.dataset.svc;
  if (_costHidden.has(key)) _costHidden.delete(key);
  else _costHidden.add(key);
  if (_costData) renderCostChart(_costData);
});

async function loadCosts() {
  applyCostView();
  await Promise.all([loadCostTable(), loadCostChart(), loadArchives()]);
}

// Rapport chiffré (par service / par pub / total) → chaîne HTML, réutilisée pour les archives.
function costReportHTML(r, opts = {}) {
  const t = r.totals || { usd: 0, credits: 0, events: 0 };
  const emptySvc = opts.emptyMsg || "Aucune génération réelle pour l’instant (la simulation ne compte pas).";
  // Total DÉJÀ en USD (HeyGen converti à l'enregistrement) → un seul montant, devise au choix.
  let html =
    `<div class="cost-total">Total estimé : <b>${money(t.usd)}</b>` +
    (t.credits ? ` <span class="muted">(dont ${frNum(t.credits)} crédits HeyGen)</span>` : "") +
    `<span class="muted"> · ${t.events || 0} génération(s) réelle(s)</span></div>`;

  html += `<h3>Par service</h3>`;
  if (!(r.services || []).length) {
    html += `<p class="muted">${esc(emptySvc)}</p>`;
  } else {
    html += '<table class="cost-table"><thead><tr><th>Service</th><th>Généré</th><th>Coût estimé</th></tr></thead><tbody>';
    (r.services || []).forEach((s) => {
      // Montant dans la devise choisie ; crédits en indice pour HeyGen (info).
      const c = money(s.usd) + (s.credits ? ` <span class="muted">(${frNum(s.credits)} cr)</span>` : "");
      html += `<tr><td>${esc(s.label)}</td><td>${esc(s.units)}</td><td class="num">${c}</td></tr>`;
    });
    html += "</tbody></table>";
  }

  html += `<h3>Par pub</h3>`;
  if (!(r.by_ad || []).length) {
    html += '<p class="muted">Aucune pub facturée sur cette période.</p>';
  } else {
    html += '<table class="cost-table"><thead><tr><th>Pub</th><th>Coût total estimé</th></tr></thead><tbody>';
    (r.by_ad || []).forEach((a) => {
      const c = money(a.usd) + (a.credits ? ` <span class="muted">(${frNum(a.credits)} cr)</span>` : "");
      html += `<tr><td>${esc(a.name)} <span class="muted">(${esc(a.kind || "")})</span></td><td class="num">${c}</td></tr>`;
    });
    html += "</tbody></table>";
  }
  if (opts.note !== false) html += `<p class="muted cost-note">⚠ ${esc(r.note || "")}</p>`;
  return html;
}

function applyCurrencyButtons() {
  document.querySelectorAll("#costCurrencySeg .seg-btn").forEach((x) =>
    x.classList.toggle("active", x.dataset.currency === _costCurrency)
  );
}

async function loadCostTable() {
  const r = await api("/api/costs");
  // Devise + taux persistés côté serveur → l'affichage convertit ($/€), la base reste en USD.
  if (r.currency) _costCurrency = r.currency;
  if (r.usd_to_eur) _usdToEur = r.usd_to_eur;
  applyCurrencyButtons();
  $("costsContent").innerHTML = costReportHTML(r);
}
$("refreshCosts").addEventListener("click", loadCosts);

// « Réinitialiser » = ARCHIVER (non destructif) : range les coûts actifs dans les Archives.
$("resetCosts").addEventListener("click", async () => {
  const ok = await showModal({
    title: "Archiver les coûts actuels et repartir de zéro ?",
    message:
      "Rien n'est perdu : l'historique en cours est RANGÉ dans les Archives (avec ses dates, " +
      "son total et le détail par service), consultable à tout moment. Le compteur et le " +
      "graphique repartent de zéro. Tes pubs, images, clips et voix restent intacts.",
    confirmText: "Archiver et repartir de zéro",
    cancelText: "Annuler",
    danger: false,
  });
  if (!ok) return;
  try {
    const r = await api("/api/costs/archive", { method: "POST" });
    _costHidden.clear();
    _costData = null;
    await loadCosts();
    if (r.archived) toast(`Période archivée (${r.archived} événement(s)). Compteur remis à zéro.`);
    else toast("Aucun coût actif à archiver.");
  } catch (e) {
    alertModal(String(e), "Échec de l'archivage");
  }
});

// -------- Archives (périodes clôturées)
function fmtDay(ts) {
  if (!ts) return "?";
  return new Date(ts * 1000).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

async function loadArchives() {
  const root = $("costArchivesList");
  let r;
  try {
    r = await api("/api/costs/archives");
  } catch (e) {
    root.innerHTML = `<p class="err">${esc(String(e))}</p>`;
    return;
  }
  const arr = r.archives || [];
  if (!arr.length) {
    root.innerHTML =
      '<p class="muted">Aucune archive pour l’instant. Clique « 🗄 Archiver &amp; repartir de zéro » pour clôturer la période en cours.</p>';
    return;
  }
  root.innerHTML = "";
  arr.forEach((a) => {
    const item = document.createElement("div");
    item.className = "archive-item";
    const credits = a.credits ? ` + ${frNum(a.credits)} cr` : "";
    item.innerHTML =
      `<div class="archive-head">` +
      `<div class="archive-period"><b>Période</b> du ${fmtDay(a.started_at)} au ${fmtDay(a.ended_at)}` +
      `<span class="muted"> · ${a.events} évént.</span></div>` +
      `<div class="archive-right"><span class="archive-total">${money(a.usd)}${credits}</span>` +
      `<button type="button" class="btn small archive-toggle">Voir le détail</button></div>` +
      `</div><div class="archive-detail hidden"></div>`;
    const detail = item.querySelector(".archive-detail");
    const btn = item.querySelector(".archive-toggle");
    btn.addEventListener("click", async () => {
      const open = !detail.classList.contains("hidden");
      if (open) {
        detail.classList.add("hidden");
        btn.textContent = "Voir le détail";
        return;
      }
      detail.classList.remove("hidden");
      btn.textContent = "Masquer le détail";
      if (!detail.dataset.loaded) {
        detail.innerHTML = '<p class="muted">Chargement…</p>';
        try {
          await renderArchiveDetail(detail, a.id);
          detail.dataset.loaded = "1";
        } catch (e) {
          detail.innerHTML = `<p class="err">${esc(String(e))}</p>`;
        }
      }
    });
    root.appendChild(item);
  });
}

// Détail d'une archive : sélecteur de période + graphique (courbes) + tableau chiffré.
async function renderArchiveDetail(container, aid) {
  const d = await api("/api/costs/archives/" + aid);
  container.innerHTML =
    `<div class="arch-chartwrap card-block">` +
    `<div class="chart-head"><div class="seg arch-period"></div>` +
    `<div class="chart-period-total arch-total"></div></div>` +
    `<div class="cost-chart arch-chart"></div><div class="chart-legend arch-legend"></div></div>` +
    `<div class="arch-table"></div>`;
  container.querySelector(".arch-table").innerHTML = costReportHTML(d.report, { note: false });

  const host = container.querySelector(".arch-chart");
  const legend = container.querySelector(".arch-legend");
  const totalEl = container.querySelector(".arch-total");
  const seg = container.querySelector(".arch-period");
  const hidden = new Set();
  let period = "day";
  let data = null;

  const rerender = () => data && renderCostChart(data, { host, legend, totalEl, hidden });
  const loadArch = async (p) => {
    period = p;
    seg.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.p === p));
    data = await api(`/api/costs/timeseries?archive_id=${aid}&period=${encodeURIComponent(p)}`);
    rerender();
  };
  [["day", "Par jour"], ["month", "Par mois"], ["quarter", "Par 3 mois"]].forEach(([p, lbl]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "seg-btn" + (p === "day" ? " active" : "");
    b.dataset.p = p;
    b.textContent = lbl;
    b.addEventListener("click", () => loadArch(p));
    seg.appendChild(b);
  });
  // Toggle de légende propre à cette archive.
  legend.addEventListener("click", (e) => {
    const btn = e.target.closest(".lg");
    if (!btn || !btn.dataset.svc) return;
    const k = btn.dataset.svc;
    if (hidden.has(k)) hidden.delete(k);
    else hidden.add(k);
    rerender();
  });
  await loadArch(period);
}

// Sélecteur de période (jour / mois / 3 mois) → recharge le graphique
document.querySelectorAll("#costPeriodSeg .seg-btn").forEach((b) => {
  b.addEventListener("click", () => {
    _costPeriod = b.dataset.period;
    document.querySelectorAll("#costPeriodSeg .seg-btn").forEach((x) =>
      x.classList.toggle("active", x === b)
    );
    loadCostChart();
  });
});

// Bascule d'affichage (graphique / classique / les deux)
document.querySelectorAll("#costViewSeg .seg-btn").forEach((b) => {
  b.addEventListener("click", () => {
    _costView = b.dataset.costview;
    document.querySelectorAll("#costViewSeg .seg-btn").forEach((x) =>
      x.classList.toggle("active", x === b)
    );
    applyCostView();
  });
});

// Sélecteur de DEVISE $ / € — conversion purement d'affichage (base toujours en USD).
document.querySelectorAll("#costCurrencySeg .seg-btn").forEach((b) => {
  b.addEventListener("click", async () => {
    const cur = b.dataset.currency === "eur" ? "eur" : "usd";
    if (cur === _costCurrency) return;
    _costCurrency = cur;
    applyCurrencyButtons();
    try {
      const r = await api("/api/costs/currency", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ currency: cur }),
      });
      if (r.usd_to_eur) _usdToEur = r.usd_to_eur;
    } catch (e) {
      toast("Devise non enregistrée : " + e.message);
    }
    // Redessine TOUTE la section (courbe + rapports + archives) dans la nouvelle devise.
    if (_costData) renderCostChart(_costData);
    await Promise.all([loadCostTable(), loadArchives()]);
  });
});

// ------------------------------------------------ util
function esc(s) {
  return String(s ?? "").replace(/[&<>"'`]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" }[c])
  );
}
function fmtDate(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

// ================================================ MASHUP IA (Nano Banana -> Kling)
let mashRefsFiles = [];
let mashRefsKinds = [];
let mashShots = [];
let mashAdId = null;
let mashLastEstimate = null;

(function initMashRatios() {
  const sel = $("mashRatio");
  if (!sel) return;
  ["9:16", "1:1", "4:5", "16:9", "3:2"].forEach((r) => {
    const o = document.createElement("option");
    o.value = r;
    o.textContent = r + (r === "9:16" ? " (vertical, défaut)" : "");
    sel.appendChild(o);
  });
})();

function renderMashRefs() {
  const box = $("mashRefsPreview");
  box.innerHTML = "";
  mashRefsFiles.forEach((f, idx) => {
    const cell = document.createElement("div");
    cell.className = "ref-thumb";
    const img = document.createElement("img");
    img.alt = f.name;
    const rd = new FileReader();
    rd.onload = () => (img.src = String(rd.result));
    rd.readAsDataURL(f);
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "ref-remove";
    rm.title = "Retirer cette image";
    rm.textContent = "×";
    rm.addEventListener("click", () => {
      mashRefsFiles.splice(idx, 1);
      mashRefsKinds.splice(idx, 1);
      renderMashRefs();
    });
    cell.appendChild(img);
    cell.appendChild(rm);
    cell.appendChild(refKindSelect(mashRefsKinds[idx], (v) => { mashRefsKinds[idx] = v; }));
    box.appendChild(cell);
  });
}

function addMashRefs(fileList) {
  Array.from(fileList || [])
    .filter((f) => f.type.startsWith("image/"))
    .forEach((f) => {
      if (!mashRefsFiles.some((x) => x.name === f.name && x.size === f.size)) {
        mashRefsFiles.push(f);
        mashRefsKinds.push("");
      }
    });
  renderMashRefs();
}

(function initMashDropzone() {
  const dz = $("mashDropzone");
  const input = $("mashRefs");
  if (!dz || !input) return;
  const open = () => input.click();
  dz.addEventListener("click", (ev) => { if (ev.target !== input) open(); });
  $("mashRefsBtn").addEventListener("click", (ev) => { ev.stopPropagation(); open(); });
  dz.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); }
  });
  input.addEventListener("change", (ev) => { addMashRefs(ev.target.files); input.value = ""; });
  ["dragenter", "dragover"].forEach((e) =>
    dz.addEventListener(e, (ev) => { ev.preventDefault(); ev.stopPropagation(); dz.classList.add("dragover"); })
  );
  ["dragleave", "dragend"].forEach((e) =>
    dz.addEventListener(e, (ev) => { ev.preventDefault(); dz.classList.remove("dragover"); })
  );
  dz.addEventListener("drop", (ev) => {
    ev.preventDefault(); ev.stopPropagation(); dz.classList.remove("dragover");
    addMashRefs(ev.dataTransfer && ev.dataTransfer.files);
  });
})();

$("mashManual").addEventListener("change", () => {
  document.querySelectorAll(".mashManualOn").forEach((el) =>
    el.classList.toggle("hidden", !$("mashManual").checked)
  );
});

$("mashPlanBtn").addEventListener("click", async () => {
  const brief = $("mashBrief").value.trim();
  const style = $("mashStyle").value.trim();
  const ratio = $("mashRatio").value;
  const manual = $("mashManual").checked;
  const count = parseInt($("mashCount").value, 10) || 0;
  const msg = $("mashPlanMsg");
  if (!brief) return toast("Décris les plans à générer (ou colle tes prompts).");
  msg.innerHTML = manual ? "🎬 Préparation de tes plans…" : "🎬 Décomposition de ton idée…";
  $("mashPlanBtn").disabled = true;
  try {
    const r = await api("/api/mashup/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brief, style, ratio, manual, count }),
    });
    mashShots = r.shots || [];
    msg.innerHTML = `<div class="ok">✓ ${mashShots.length} plan(s)${r.dry_run ? " (simulation)" : ""}.</div>`;
    renderMashPlan(mashShots, r.estimate);
  } catch (e) {
    msg.innerHTML = `<div class="ko">✗ ${esc(e.message)}</div>`;
  } finally {
    $("mashPlanBtn").disabled = false;
  }
});

function renderMashPlan(shots, est) {
  mashLastEstimate = est || null;
  const list = $("mashPlanList");
  list.innerHTML = "";
  shots.forEach((s) => {
    const div = document.createElement("div");
    div.className = "scene-card";
    div.innerHTML =
      `<div><span class="n">Plan ${s.n}</span> <span class="muted">${s.duration_s || 5}s</span></div>` +
      `<div class="script">🖼️ ${esc(s.prompt_image)}</div>` +
      `<div class="motion">🎥 ${esc(s.prompt_motion)}</div>`;
    list.appendChild(div);
  });
  if (est) {
    $("mashEstimate").innerHTML =
      `<b>Coût estimé :</b> ${usd(est.usd_total)} <span class="muted">(images ${usd(est.usd_images)} · ` +
      `animation vidéo ${usd(est.usd_video)} pour les plans validés)</span>`;
  }
  $("mashPlanArea").classList.remove("hidden");
}

$("mashGenImagesBtn").addEventListener("click", async () => {
  if (!mashShots.length) return toast("Prévisualise d'abord les plans.");
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    if (!(currentSettings && currentSettings.openrouter_api_key_set))
      return toast("Ajoute ta clé OpenRouter (Nano Banana / Kling) dans Réglages.");
    const perImg = (mashLastEstimate && mashLastEstimate.cout_par_image_usd) || 0.04;
    const ok = await showModal({
      title: "Mode réel — Plan 1",
      message: `On génère UNIQUEMENT le Plan 1 (≈ ${usd(perImg)}, 1 image Nano Banana). Tu le valides, puis les suivants. Continuer ?`,
      confirmText: "Générer le Plan 1", cancelText: "Annuler", danger: true,
    });
    if (!ok) return;
  }
  const fd = new FormData();
  fd.append("ad_name", ($("mashBrief").value.trim().slice(0, 40) || "mashup"));
  fd.append("shots_json", JSON.stringify(mashShots));
  fd.append("confirm", "true");
  fd.append("ref_kinds", JSON.stringify(mashRefsKinds));
  mashRefsFiles.forEach((f) => fd.append("files", f, f.name));
  let res;
  try {
    res = await api("/api/mashup/generate-images", { method: "POST", body: fd });
  } catch (e) {
    return toast(e.message);
  }
  mashAdId = res.ad_id;
  $("mashProgress").classList.remove("hidden");
  initMashProgress(mashShots.slice(0, res.generated_now || 1));
  pollMashJob(res.job_id, () => loadMashGallery(mashAdId));
});

function initMashProgress(shots) {
  const ul = $("mashSceneProgress");
  ul.innerHTML = "";
  shots.forEach((s) => {
    const li = document.createElement("li");
    li.id = "msp-" + s.n;
    li.innerHTML =
      `<div class="sp-row"><span class="dot"></span><span>Plan ${s.n}</span>` +
      `<span class="phase">en attente</span></div><div class="scene-err"></div>`;
    ul.appendChild(li);
  });
  $("mashProgFill").style.width = "0%";
  $("mashProgCount").textContent = "";
}

async function pollMashJob(jobId, onDone) {
  try {
    const j = await api("/api/jobs/" + jobId);
    (j.scenes || []).forEach((sc) => {
      const li = $("msp-" + sc.n);
      if (!li) return;
      const dot = li.querySelector(".dot");
      dot.className = "dot " + (sc.status === "ok" ? "ok" : sc.status === "echec" ? "echec" : sc.phase === "en_attente" ? "" : "en_cours");
      li.querySelector(".phase").textContent = PHASE_LABEL[sc.phase] || sc.phase || "";
      const errEl = li.querySelector(".scene-err");
      if (sc.status === "echec") {
        errEl.textContent = "⚠ " + prettyError(sc.message);
        errEl.title = sc.message || "";
        errEl.style.display = "block";
      } else {
        errEl.style.display = "none";
      }
    });
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    $("mashProgFill").style.width = pct + "%";
    $("mashProgCount").textContent = `${j.done}/${j.total}`;
    if (j.state === "en_cours" || j.state === "en_attente") {
      setTimeout(() => pollMashJob(jobId, onDone), 800);
    } else {
      if (j.state === "echec") {
        const m = (j.summary && j.summary.message) || "Échec de la génération.";
        toast(prettyError(m));
      }
      if (onDone) onDone();
    }
  } catch (e) {
    toast("Suivi interrompu : " + e.message);
  }
}

async function loadMashGallery(adId) {
  if (!adId) return;
  const r = await api("/api/mashup/ad/" + adId);
  $("mashValidation").classList.remove("hidden");
  const g = $("mashGallery");
  renderOverviewBanner(g, r, "mashup", adId);
  g.innerHTML = "";
  (r.shots || []).forEach((s) => g.appendChild(mashShotCard(s)));
}

function mashShotCard(s) {
  const card = document.createElement("div");
  const valid = s.status === "valide";
  card.className = "obj-shot" + (valid ? " valide" : "");
  const badge = valid
    ? '<span class="badge ok">validé ✓</span>'
    : s.status === "echec"
    ? '<span class="badge ko">échec</span>'
    : '<span class="badge">à valider</span>';
  const bust = s.image_url ? (s.image_url.includes("?") ? "&" : "?") + "t=" + Date.now() : "";
  const thumb = s.image_url
    ? `<img class="thumb" src="${esc(s.image_url)}${bust}" alt="plan ${s.n}" />`
    : `<div class="thumb empty">${esc(s.error || "pas d'image")}</div>`;
  const dur = s.duration_s || 5;
  card.innerHTML =
    thumb +
    `<div class="body">` +
    `<div class="head"><span class="n">Plan ${s.n}</span>${badge}</div>` +
    `<div class="lbl">Prompt image (lecture seule)</div>` +
    `<div class="pi-ro">${esc(s.prompt_image)}</div>` +
    `<div class="lbl">🎥 Mouvement (lecture seule)</div>` +
    `<div class="motion">${esc(s.prompt_motion)}</div>` +
    `<div class="lbl">⏱️ Durée du clip (3–10 s)</div>` +
    `<input class="mash-dur" type="number" min="3" max="10" step="1" value="${dur}" />` +
    `<div class="actions">` +
    `<button class="btn primary btn-valid">${valid ? "Dévalider" : "Valider"}</button>` +
    `<button class="btn btn-regen">Régénérer</button>` +
    `<button class="btn small btn-test" title="Anime uniquement ce plan">Tester ce plan</button>` +
    `</div></div>`;

  card.querySelector(".body").insertBefore(
    planRefsControls(s), card.querySelector(".actions")
  );

  // Durée éditable -> POST /api/mashup/duration
  const durEl = card.querySelector(".mash-dur");
  durEl.addEventListener("blur", async () => {
    const d = parseInt(durEl.value, 10) || 5;
    try {
      const res = await api("/api/mashup/duration/" + s.clip_id, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ duration_s: d }),
      });
      s.duration_s = res.duration_s;
      durEl.value = res.duration_s;
    } catch (e) { toast(e.message); }
  });

  card.querySelector(".btn-valid").addEventListener("click", async () => {
    try {
      const res = await api("/api/mashup/validate/" + s.clip_id, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ valide: !valid }),
      });
      s.status = res.status;
      card.replaceWith(mashShotCard(s));
    } catch (e) { toast(e.message); }
  });

  card.querySelector(".btn-regen").addEventListener("click", async () => {
    const dryRun = currentSettings && currentSettings.dry_run;
    if (!dryRun) {
      const ok = await showModal({
        title: "Régénérer l'image",
        message: "Régénérer cette image via Nano Banana (payant au-delà du quota gratuit ~500/jour). Continuer ?",
        confirmText: "Régénérer", cancelText: "Annuler", danger: true,
      });
      if (!ok) return;
    }
    card.classList.add("busy");
    try {
      const res = await api("/api/mashup/regenerate-image/" + s.clip_id, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true }),
      });
      await waitJobDone(res.job_id);
      const ad = await api("/api/mashup/ad/" + mashAdId);
      const updated = (ad.shots || []).find((x) => x.clip_id === s.clip_id);
      if (updated) card.replaceWith(mashShotCard(updated));
      else card.classList.remove("busy");
    } catch (e) {
      card.classList.remove("busy");
      toast(e.message);
    }
  });

  card.querySelector(".btn-test").addEventListener("click", async () => {
    if (!["valide", "echec", "pret"].includes(s.status))
      return toast("Valide ce plan avant de le tester.");
    const dryRun = currentSettings && currentSettings.dry_run;
    if (!dryRun) {
      const ok = await showModal({
        title: "Tester ce plan",
        message: "Anime UNIQUEMENT ce plan (payant). Continuer ?",
        confirmText: "Tester", cancelText: "Annuler", danger: true,
      });
      if (!ok) return;
    }
    try {
      const res = await api("/api/mashup/animate/" + mashAdId, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clip_id: s.clip_id, confirm: true }),
      });
      toast("Animation du plan lancée…");
      await waitJobDone(res.job_id);
      loadMashGallery(mashAdId);
      loadLibrary();
    } catch (e) { toast(e.message); }
  });

  return card;
}

$("mashRefreshBtn").addEventListener("click", () => loadMashGallery(mashAdId));

$("mashConsistencyBtn").addEventListener("click", async () => {
  if (!mashAdId) return toast("Génère d'abord le Plan 1.");
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    const ok = await showModal({
      title: "Générer les plans suivants",
      message: "Régénère les autres plans à partir du Plan 1 validé (images Nano Banana, payant). Continuer ?",
      confirmText: "Générer", cancelText: "Annuler", danger: true,
    });
    if (!ok) return;
  }
  let res;
  try {
    res = await api("/api/mashup/consistency/" + mashAdId, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
  } catch (e) { return toast(e.message); }
  toast(`Génération de ${res.n} plan(s) suivant(s)…`);
  // Affiche la progression pour les plans régénérés (n >= 2 : le Plan 1 reste la référence).
  $("mashProgress").classList.remove("hidden");
  initMashProgress(mashShots.filter((s) => s.n !== (res.ref_plan || 1)));
  pollMashJob(res.job_id, () => loadMashGallery(mashAdId));
});

$("mashAnimateBtn").addEventListener("click", async () => {
  if (!mashAdId) return toast("Génère et valide d'abord tes plans.");
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    const ok = await showModal({
      title: "Animer les plans validés",
      message: "Anime tous les plans validés avec le modèle vidéo choisi (payant, à la seconde). Continuer ?",
      confirmText: "Animer", cancelText: "Annuler", danger: true,
    });
    if (!ok) return;
  }
  let res;
  try {
    res = await api("/api/mashup/animate/" + mashAdId, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
  } catch (e) {
    // Plafond de dépense dépassé → confirmation explicite du dépassement.
    if (/plafond/i.test(e.message)) {
      const ok = await showModal({
        title: "⚠ Dépassement du plafond de dépense",
        message: e.message + "\n\nConfirmer et animer malgré le plafond ?",
        confirmText: "Dépasser et animer", cancelText: "Annuler", danger: true,
      });
      if (!ok) return;
      try {
        res = await api("/api/mashup/animate/" + mashAdId, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirm: true, confirm_over_cap: true }),
        });
      } catch (e2) { return toast(e2.message); }
    } else {
      return toast(e.message);
    }
  }
  $("mashAnimProgress").classList.remove("hidden");
  initMashAnimProgress(res.n_plans || 1);
  pollMashAnimJob(res.job_id);
});

function initMashAnimProgress(n) {
  const ul = $("mashAnimSceneProgress");
  ul.innerHTML = "";
  $("mashAnimProgFill").style.width = "0%";
  $("mashAnimProgCount").textContent = `0/${n} clips`;
}

async function pollMashAnimJob(jobId) {
  try {
    const j = await api("/api/jobs/" + jobId);
    const ul = $("mashAnimSceneProgress");
    ul.innerHTML = "";
    (j.scenes || []).forEach((sc) => {
      const li = document.createElement("li");
      const cls = sc.status === "ok" ? "ok" : sc.status === "echec" ? "echec" : sc.phase === "en_attente" ? "" : "en_cours";
      li.innerHTML =
        `<div class="sp-row"><span class="dot ${cls}"></span><span>Plan ${sc.n}</span>` +
        `<span class="phase">${esc(PHASE_LABEL[sc.phase] || sc.phase || "")}</span></div>` +
        (sc.status === "echec" ? `<div class="scene-err">⚠ ${esc(prettyError(sc.message))}</div>` : "");
      ul.appendChild(li);
    });
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    $("mashAnimProgFill").style.width = pct + "%";
    $("mashAnimProgCount").textContent = `${j.done}/${j.total} clips`;
    if (j.state === "en_cours" || j.state === "en_attente") {
      setTimeout(() => pollMashAnimJob(jobId), 800);
    } else {
      const sm = j.summary || {};
      toast(`Animation terminée : ${sm.ok ?? j.done} clip(s). → Bibliothèque`);
      loadMashGallery(mashAdId);
      loadLibrary();
    }
  } catch (e) {
    toast("Suivi interrompu : " + e.message);
  }
}

// ================================================ AVATAR IA (Omni : Nano Banana -> Google Gemini Omni)
// Une personne IA (adulte, visage générique) dit le script VERBATIM ; Omni fait vidéo + voix.
// Préfixe d'ids « ao ». Fiche voix : « aoV* » (avant génération) et « aoEV* » (éditable en galerie).
let aoRefsFiles = [];
let aoRefsKinds = [];
let aoShots = [];            // plan de tournage (réponse /plan)
let aoAdId = null;
let aoLastEstimate = null;   // estimation du plan (cout_omni_par_seconde_usd, …)
let aoGalleryShots = [];     // derniers plans reçus de GET /ad (durées Omni réelles)
let aoVoiceLocked = false;   // au moins un clip « pret » → fiche voix verrouillée
let aoVoiceUnlocked = false; // l'utilisateur a explicitement déverrouillé (→ force:true)
const AO_API = "/api/avatar-omni";
const AO_DEFAULT_RATE = 0.10;        // $/s (720p) — même formule que le backend
const AO_TIER1_USD = 10;             // quota Google Tier 1 : 10 $ / 10 min
const AO_DEFAULT_ACCENT = "natural French accent from France";
const AO_VOICE_FIELDS = ["Gender", "Age", "AccentRegion", "Accent", "Tone", "Pace", "Extra"];

function aoRate() {
  const r = aoLastEstimate && Number(aoLastEstimate.cout_omni_par_seconde_usd);
  return r > 0 ? r : AO_DEFAULT_RATE;
}

// Remplit les menus timbre/débit des deux fiches voix (listes serveur objet_voice_styles/paces).
function aoFillVoiceSelects() {
  const s = currentSettings;
  if (!s) return;
  const fill = (id, items, preferred) => {
    const sel = $(id);
    if (!sel) return;
    const keep = sel.value;
    sel.innerHTML = "";
    (items || []).forEach((m) => {
      const o = document.createElement("option");
      o.value = m.key;
      o.textContent = m.label;
      sel.appendChild(o);
    });
    const keys = (items || []).map((m) => m.key);
    const want = [keep, ...preferred].find((k) => k && keys.includes(k));
    if (want) sel.value = want;
  };
  ["aoV", "aoEV"].forEach((p) => {
    fill(p + "Tone", s.objet_voice_styles, ["douce", s.objet_voice_style]);
    fill(p + "Pace", s.objet_voice_paces, ["naturel", s.objet_voice_pace]);
  });
}

async function aoEnsureVoiceSelects() {
  try {
    if (!currentSettings) currentSettings = await api("/api/settings");
    if (!$("aoVTone").options.length) aoFillVoiceSelects();
  } catch (e) { toast(e.message); }
}

function aoReadVoice(prefix) {
  const v = (f) => ($(prefix + f) ? $(prefix + f).value : "");
  return {
    gender: v("Gender"),
    age: v("Age").trim(),
    accent_region: v("AccentRegion") || "france",
    accent: v("Accent").trim(),   // libre, prioritaire s'il est rempli (vide = accent choisi)
    tone: v("Tone"),
    pace: v("Pace"),
    extra: v("Extra").trim(),
  };
}

function aoWriteVoice(prefix, p) {
  p = p || {};
  const set = (f, val) => {
    const el = $(prefix + f);
    if (!el || val == null) return;
    if (el.tagName === "SELECT" && ![...el.options].some((o) => o.value === String(val))) return;
    el.value = String(val);
  };
  set("Gender", p.gender || "");
  set("Age", p.age || "");
  set("AccentRegion", p.accent_region || "france");
  // L'ancien accent France pré-rempli n'est pas un choix libre → champ vide.
  set("Accent", p.accent && p.accent !== AO_DEFAULT_ACCENT ? p.accent : "");
  if (p.tone) set("Tone", p.tone);
  if (p.pace) set("Pace", p.pace);
  set("Extra", p.extra || "");
}

function aoSetVoiceEditable(editable) {
  AO_VOICE_FIELDS.forEach((f) => { const el = $("aoEV" + f); if (el) el.disabled = !editable; });
  $("aoVoiceSaveBtn").disabled = !editable;
}

// État de la fiche voix en galerie (verrou si des clips sont déjà animés avec cette voix).
function aoRenderVoiceBlock(r) {
  aoVoiceLocked = !!r.voice_locked;
  if (!aoVoiceLocked) aoVoiceUnlocked = false;
  aoWriteVoice("aoEV", r.voice_profile || {});
  $("aoVoiceSheet").textContent = r.voice_sheet ? "Consigne envoyée à Google : " + r.voice_sheet : "";
  const lock = $("aoVoiceLock");
  const unlockBtn = $("aoVoiceUnlockBtn");
  if (aoVoiceLocked && !aoVoiceUnlocked) {
    lock.textContent = "🔒 Verrouillée — des clips sont déjà animés avec cette voix";
    lock.className = "voice-lock on";
    unlockBtn.classList.remove("hidden");
    aoSetVoiceEditable(false);
  } else {
    lock.textContent = aoVoiceUnlocked ? "🔓 Déverrouillée — les clips déjà faits garderont l'ancienne voix" : "Modifiable";
    lock.className = "voice-lock" + (aoVoiceUnlocked ? " warn" : "");
    unlockBtn.classList.add("hidden");
    aoSetVoiceEditable(true);
  }
}

async function aoConfirmUnlock() {
  return showModal({
    title: "Déverrouiller la fiche voix ?",
    message:
      "Des clips sont déjà animés avec la voix actuelle. Si tu la modifies, les clips déjà faits " +
      "auront une autre voix que les suivants (il faudrait les réanimer pour tout harmoniser).\n\nDéverrouiller quand même ?",
    confirmText: "Déverrouiller", cancelText: "Annuler", danger: true,
  });
}

$("aoVoiceUnlockBtn").addEventListener("click", async () => {
  if (!(await aoConfirmUnlock())) return;
  aoVoiceUnlocked = true;
  const sheet = $("aoVoiceSheet").textContent;
  aoRenderVoiceBlock({ voice_locked: true, voice_profile: aoReadVoice("aoEV"), voice_sheet: "" });
  $("aoVoiceSheet").textContent = sheet;   // on garde la consigne actuelle affichée
  toast("Fiche voix déverrouillée : modifie-la puis « Enregistrer la voix ».");
});

$("aoVoiceSaveBtn").addEventListener("click", async () => {
  if (!aoAdId) return toast("Génère d'abord le Plan 1.");
  const patch = (force) =>
    api(AO_API + "/voice/" + aoAdId, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice_profile: aoReadVoice("aoEV"), force: !!force }),
    });
  let res;
  try {
    res = await patch(aoVoiceUnlocked);
  } catch (e) {
    if (!/verrouill/i.test(e.message)) return toast(e.message);
    if (!(await aoConfirmUnlock())) return;
    aoVoiceUnlocked = true;
    try { res = await patch(true); } catch (e2) { return toast(e2.message); }
  }
  toast("Fiche voix enregistrée ✓");
  // Déverrouillage valable pour CETTE sauvegarde seulement : la prochaine modification d'une
  // voix déjà utilisée redemandera confirmation.
  aoVoiceUnlocked = false;
  aoRenderVoiceBlock({
    voice_locked: res.voice_locked, voice_profile: res.voice_profile, voice_sheet: res.voice_sheet,
  });
  // Le débit change la durée Omni des plans → on met à jour durées + estimation SANS re-rendre
  // les cartes (préserve les prompts image édités et pas encore régénérés).
  aoRefreshDurations();
});

async function aoRefreshDurations() {
  try {
    const ad = await api(AO_API + "/ad/" + aoAdId);
    aoGalleryShots = ad.shots || [];
    aoGalleryShots.forEach((s) => {
      const card = document.querySelector(`#aoGallery .obj-shot[data-clip="${s.clip_id}"]`);
      const dur = card && card.querySelector(".ao-dur");
      if (dur) dur.textContent = `⏱️ ~${s.duration_s || "?"} s`;
    });
    aoRenderWarnings("aoWarnings", ad.warnings, ad.max_words);
    aoRenderAnimEstimate();
  } catch (_) { /* non bloquant */ }
}

// --- Réfs typées (visage / produit / décor / style) : dropzone + vignettes ---
function renderAoRefs() {
  const box = $("aoRefsPreview");
  box.innerHTML = "";
  aoRefsFiles.forEach((f, idx) => {
    const cell = document.createElement("div");
    cell.className = "ref-thumb";
    const img = document.createElement("img");
    img.alt = f.name;
    const rd = new FileReader();
    rd.onload = () => (img.src = String(rd.result));
    rd.readAsDataURL(f);
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "ref-remove";
    rm.title = "Retirer cette image";
    rm.textContent = "×";
    rm.addEventListener("click", () => {
      aoRefsFiles.splice(idx, 1);
      aoRefsKinds.splice(idx, 1);
      renderAoRefs();
    });
    cell.appendChild(img);
    cell.appendChild(rm);
    cell.appendChild(refKindSelect(aoRefsKinds[idx], (v) => { aoRefsKinds[idx] = v; }, AO_REF_KIND_OPTS));
    box.appendChild(cell);
  });
}

function addAoRefs(fileList) {
  Array.from(fileList || [])
    .filter((f) => f.type.startsWith("image/"))
    .forEach((f) => {
      if (!aoRefsFiles.some((x) => x.name === f.name && x.size === f.size)) {
        aoRefsFiles.push(f);
        aoRefsKinds.push("");
      }
    });
  renderAoRefs();
}

(function initAoDropzone() {
  const dz = $("aoDropzone");
  const input = $("aoRefs");
  if (!dz || !input) return;
  const open = () => input.click();
  dz.addEventListener("click", (ev) => { if (ev.target !== input) open(); });
  $("aoRefsBtn").addEventListener("click", (ev) => { ev.stopPropagation(); open(); });
  dz.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); }
  });
  input.addEventListener("change", (ev) => { addAoRefs(ev.target.files); input.value = ""; });
  ["dragenter", "dragover"].forEach((e) =>
    dz.addEventListener(e, (ev) => { ev.preventDefault(); ev.stopPropagation(); dz.classList.add("dragover"); })
  );
  ["dragleave", "dragend"].forEach((e) =>
    dz.addEventListener(e, (ev) => { ev.preventDefault(); dz.classList.remove("dragover"); })
  );
  dz.addEventListener("drop", (ev) => {
    ev.preventDefault(); ev.stopPropagation(); dz.classList.remove("dragover");
    addAoRefs(ev.dataTransfer && ev.dataTransfer.files);
  });
})();

function aoMode() {
  const r = document.querySelector('input[name="aoMode"]:checked');
  return r ? r.value : "auto";
}

document.querySelectorAll('input[name="aoMode"]').forEach((r) =>
  r.addEventListener("change", () => {
    const mode = aoMode();
    document.querySelectorAll(".aoModeHint").forEach((el) =>
      el.classList.toggle("hidden", el.dataset.mode !== mode)
    );
    $("aoScriptLabel").textContent = mode === "client"
      ? "Document du client (BLOC N · [timecode] — TITRE dialogue, puis 🎬 mise en scène)"
      : "Script — ce que la personne DIT (VERBATIM, jamais réécrit)";
    $("aoScript").placeholder = mode === "client"
      ? "BLOC 1 · [0:00–0:08] — HOOK Le dialogue exact…\n🎬 La mise en scène du client…"
      : "Colle ici le texte exact de ta pub.";
    $("aoScript").rows = mode === "client" ? 14 : 6;
  })
);

// Valeurs « [à valider] » surlignées (texte échappé, crochets gardés à l'affichage).
function aoHighlightBrackets(text) {
  return esc(text || "").replace(/\[([^\[\]]*)\]/g,
    '<mark class="ao-val" title="valeur à valider">[$1]</mark>');
}

function aoBracketValuesHtml(text) {
  const vals = (String(text || "").match(/\[[^\[\]]*\]/g) || []);
  if (!vals.length) return "";
  return `<div class="ao-vals">⚠ À valider : ${vals.map((v) => `<mark class="ao-val">${esc(v)}</mark>`).join(" ")}` +
    ` <span class="muted">(dit sans les crochets)</span></div>`;
}

function aoBlockHead(s) {
  const bits = [`Bloc ${esc(s.block_n)}`];
  if (s.block_title) bits.push(esc(s.block_title));
  const tc = s.timecode ? ` <span class="muted">[${esc(s.timecode)}]</span>` : "";
  const n = s.block_count > 1 ? ` <span class="muted">· ${esc(s.block_count)} sous-plans</span>` : "";
  return bits.join(" · ") + tc + n;
}

let aoPersonas = null;   // personnages du dernier plan {p1, p2, p1_en, p2_en} (EN = Claude)
let aoPlanBible = null;  // bible visuelle du dernier plan (découpage client), renvoyée au Plan 1
const AO_BIBLE_FIELDS = { character1: "aoBibleCharacter1", character2: "aoBibleCharacter2",
  set: "aoBibleSet", product: "aoBibleProduct", positions: "aoBiblePositions" };

// Segments (tours Omni) d'un plan client : texte, durée, mouvement, tour déjà fait.
function aoSegmentsHtml(segs) {
  if (!Array.isArray(segs) || !segs.length) return "";
  return `<ul class="ao-segs">` + segs.map((x, i) =>
    `<li class="${x.done ? "done" : ""}"><div class="ao-seg-head"><b>${x.done ? "✓" : "○"} Tour ${i + 1}</b>` +
    `<span>~${esc(x.seconds ?? "?")} s</span></div>` +
    `<div>💬 ${aoHighlightBrackets(x.text)}</div>` +
    (x.motion ? `<div class="ao-seg-motion">🎥 ${esc(x.motion)}</div>` : "") + `</li>`
  ).join("") + `</ul>`;
}

function aoPlanTitle(s) {
  if (s.block_n && Array.isArray(s.segments) && s.segments.length) {
    return `Bloc ${esc(s.block_n)}` + (s.block_title ? ` · ${esc(s.block_title)}` : "") +
      (s.timecode ? ` <span class="muted">[${esc(s.timecode)}]</span>` : "");
  }
  return `Plan ${esc(s.label || s.n)}`;
}

function aoRenderBible(bible) {
  const box = $("aoBibleBox");
  const has = bible && bible.character1;
  box.classList.toggle("hidden", !has);
  if (!has) return;
  Object.entries(AO_BIBLE_FIELDS).forEach(([k, id]) => { $(id).value = bible[k] || ""; });
  $("aoBibleMsg").textContent = "";
}

$("aoBibleSaveBtn").addEventListener("click", async () => {
  if (!aoAdId) return;
  const bible = {};
  Object.entries(AO_BIBLE_FIELDS).forEach(([k, id]) => { bible[k] = $(id).value.trim(); });
  try {
    const r = await api(AO_API + "/bible/" + aoAdId, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bible }),
    });
    toast(`Bible enregistrée ✓ — ${r.updated} prompt(s) image recomposé(s)`);
    await loadAoGallery(aoAdId);
    $("aoBibleMsg").textContent = "Images inchangées : « Régénérer » un plan pour lui appliquer la nouvelle bible.";
  } catch (e) { toast(e.message); }
});

function aoRenderWarnings(boxId, warnings, maxWords) {
  const box = $(boxId);
  const list = (warnings || []).filter(Boolean);
  if (!list.length) { box.classList.add("hidden"); box.innerHTML = ""; return; }
  box.innerHTML =
    `<div class="ao-w-title">⚠ Répliques trop longues${maxWords ? ` (max ~${esc(maxWords)} mots par plan, soit 10 s)` : ""}</div>` +
    "<ul>" + list.map((w) => `<li>${esc(w)}</li>`).join("") + "</ul>" +
    `<div class="muted small">Au-delà, Google risque de couper la phrase. Raccourcis le dialogue ou découpe-le.</div>`;
  box.classList.remove("hidden");
}

// Pauses (min) pour rester sous le plafond Tier 1 — même formule que cost.tier1_wait_minutes.
function aoTier1WaitMin(usdVideo) {
  return usdVideo > AO_TIER1_USD ? (Math.ceil(usdVideo / AO_TIER1_USD) - 1) * 10 : 0;
}

function aoTier1Text(usdVideo) {
  return `Plus de ${AO_TIER1_USD} $ de vidéo : au Tier 1, Google limite à ${AO_TIER1_USD} $ par tranche ` +
    `de 10 min. Les plans seront ESPACÉS automatiquement (≈ ${aoTier1WaitMin(usdVideo)} min de pause ` +
    `au total, « prochain plan dans X min » dans le suivi) — laisse l'app ouverte.`;
}

function aoTier1Html(usdVideo, flag) {
  if (!(flag || usdVideo > AO_TIER1_USD)) return "";
  return `<div class="ao-tier1">⏳ ${esc(aoTier1Text(usdVideo))}</div>`;
}

// -- Étape 3 : plan de tournage --
$("aoPlanBtn").addEventListener("click", async () => {
  const script = $("aoScript").value;   // VERBATIM
  const mode = aoMode();
  const manual = mode === "manual";
  const msg = $("aoPlanMsg");
  if (!script.trim()) return toast(mode === "client" ? "Colle le document du client." : "Écris le script (ce que la personne doit dire).");
  msg.innerHTML = mode === "client" ? "🎬 Lecture du document client + traduction des mises en scène…"
    : manual ? "🎬 Préparation de tes plans…" : "🎬 Découpage du script en plans…";
  $("aoPlanBtn").disabled = true;
  try {
    const r = await api(AO_API + "/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        script,
        persona: $("aoPersona").value.trim(),
        persona1: $("aoPersona1").value.trim(),
        persona2: $("aoPersona2").value.trim(),
        product: $("aoProduct").value.trim(),
        ambiance: $("aoAmbiance").value.trim(),
        manual,
        mode,
        voice_profile: aoReadVoice("aoV"),
      }),
    });
    aoShots = r.shots || [];
    aoPersonas = r.personas || null;
    aoPlanBible = r.bible || null;
    if (r.ad && !$("aoAdName").value.trim()) $("aoAdName").value = r.ad;
    msg.innerHTML = `<div class="ok">✓ ${aoShots.length} plan(s)${r.dry_run ? " (simulation)" : ""}.</div>`;
    renderAoPlan(aoShots, r);
  } catch (e) {
    msg.innerHTML = `<div class="ko">✗ ${esc(e.message)}</div>`;
  } finally {
    $("aoPlanBtn").disabled = false;
  }
});

const AO_REF_LABEL = { visage: "Visage perso 1", visage2: "Visage perso 2", produit: "Produit", decor: "Décor", style: "Style" };

function renderAoPlan(shots, r) {
  aoLastEstimate = r.estimate || null;
  const list = $("aoPlanList");
  list.innerHTML = "";
  let prevBlock = null;
  shots.forEach((s) => {
    const refs = Array.isArray(s.refs_needed) ? s.refs_needed : [];
    const refsTxt = refs.length ? refs.map((k) => AO_REF_LABEL[k] || k).join(", ") : "plan neutre";
    const segs = Array.isArray(s.segments) ? s.segments : [];
    if (!segs.length && s.block_n && s.block_count > 1 && s.block_n !== prevBlock) {
      const head = document.createElement("div");
      head.className = "ao-block-head";
      head.innerHTML = aoBlockHead(s);
      list.appendChild(head);
    }
    prevBlock = s.block_n || null;
    const div = document.createElement("div");
    div.className = "scene-card";
    div.innerHTML =
      `<div><span class="n">${aoPlanTitle(s)}</span> <span class="muted">réfs : ${esc(refsTxt)}` +
      (segs.length ? ` · ${segs.length} tour(s) · ~${esc(s.duration_s)} s` : "") + `</span></div>` +
      (s.direction ? `<div class="ao-direction">🎬 Client : ${esc(s.direction)}</div>` : "") +
      (segs.length
        ? aoSegmentsHtml(segs) + `<div class="script">🖼️ ${esc(s.shot_prompt || s.prompt_image)}</div>`
        : `<div class="motion">💬 ${s.dialogue ? aoHighlightBrackets(s.dialogue) : "<i>(sans parole)</i>"}</div>` +
          `<div class="script">🖼️ ${esc(s.prompt_image)}</div>` +
          `<div class="motion">🎥 ${esc(s.prompt_motion)}</div>`);
    list.appendChild(div);
  });
  aoRenderWarnings("aoPlanWarnings", r.warnings, r.max_words);
  const e = r.estimate || {};
  $("aoEstimate").innerHTML =
    `<b>Coût estimé :</b> ${usd(e.usd_total)} ` +
    `<span class="muted">(images ${usd(e.usd_images)} · vidéo + voix Omni ${usd(e.usd_video)} ` +
    `pour ~${Math.round(e.seconds_total || 0)} s, ${e.shots || shots.length} plan(s) à ~${usd(aoRate())}/s)</span>` +
    (r.max_words ? `<div class="card-sub">Max ~${esc(r.max_words)} mots par plan avec ce débit.</div>` : "") +
    `<div class="card-sub">Payé seulement en mode réel. En simulation : $0. La vidéo n'est payée que sur les plans validés.</div>` +
    aoTier1Html(Number(e.usd_video) || 0, e.tier1_warning);
  $("aoPlanArea").classList.remove("hidden");
}

// -- Étape 4 : Plan 1 (la personne) --
$("aoGenImagesBtn").addEventListener("click", async () => {
  if (!aoShots.length) return toast("Génère d'abord le plan.");
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    if (!(currentSettings && currentSettings.openrouter_api_key_set))
      return toast("Ajoute ta clé OpenRouter (Nano Banana) dans Réglages.");
    const perImg = (aoLastEstimate && aoLastEstimate.usd_images && aoShots.length)
      ? aoLastEstimate.usd_images / aoShots.length : 0.04;
    const ok = await showModal({
      title: "Mode réel — Plan 1 (la personne)",
      message: `On génère UNIQUEMENT le Plan 1 (≈ ${usd(perImg)}, 1 image Nano Banana). Tu le valides, puis tu génères les plans suivants. Continuer ?`,
      confirmText: "Générer le Plan 1", cancelText: "Annuler", danger: true,
    });
    if (!ok) return;
  }
  const fd = new FormData();
  fd.append("ad_name", $("aoAdName").value.trim() || "avatar_ia");
  fd.append("shots_json", JSON.stringify(aoShots));
  fd.append("confirm", "true");
  fd.append("ref_kinds", JSON.stringify(aoRefsKinds));
  fd.append("voice_profile", JSON.stringify(aoReadVoice("aoV")));
  fd.append("personas", JSON.stringify(aoPersonas || {}));
  if (aoPlanBible) fd.append("bible", JSON.stringify(aoPlanBible));
  aoRefsFiles.forEach((f) => fd.append("files", f, f.name));
  let res;
  try {
    res = await api(AO_API + "/generate-images", { method: "POST", body: fd });
  } catch (e) {
    return toast(e.message);
  }
  aoAdId = res.ad_id;
  aoVoiceUnlocked = false;
  aoShowImgProgress();
  pollSceneJob(res.job_id, {
    ul: "aoSceneProgress", fill: "aoProgFill", count: "aoProgCount", unit: "images",
    onEnd: () => loadAoGallery(aoAdId),
  });
});

function aoShowImgProgress() {
  $("aoProgress").classList.remove("hidden");
  $("aoSceneProgress").innerHTML = "";
  $("aoProgFill").style.width = "0%";
  $("aoProgCount").textContent = "";
}

// Suivi générique d'un job : la liste est RECONSTRUITE depuis j.scenes (vrais numéros de plan).
async function pollSceneJob(jobId, o) {
  try {
    const j = await api("/api/jobs/" + jobId);
    const ul = $(o.ul);
    ul.innerHTML = "";
    (j.scenes || []).forEach((sc) => {
      const li = document.createElement("li");
      const cls = sc.status === "ok" ? "ok" : sc.status === "echec" ? "echec" : sc.phase === "en_attente" ? "" : "en_cours";
      li.innerHTML =
        `<div class="sp-row"><span class="dot ${cls}"></span><span>Plan ${esc(sc.n)}</span>` +
        `<span class="phase">${esc(PHASE_LABEL[sc.phase] || sc.phase || "")}</span></div>` +
        (sc.status === "echec"
          ? `<div class="scene-err" style="display:block" title="${esc(sc.message || "")}">⚠ ${esc(prettyError(sc.message))}</div>`
          : sc.phase === "attente_tier1" && sc.message
            ? `<div class="scene-wait">⏳ ${esc(sc.message)}</div>`
            : "");
      ul.appendChild(li);
    });
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    $(o.fill).style.width = pct + "%";
    $(o.count).textContent = `${j.done ?? 0}/${j.total ?? 0} ${o.unit || ""}`;
    if (j.state === "en_cours" || j.state === "en_attente") {
      setTimeout(() => pollSceneJob(jobId, o), 800);
    } else {
      if (j.state === "echec" && !o.onFail) {
        toast(prettyError((j.summary && j.summary.message) || "Échec de la génération."));
      }
      if (j.state === "echec" && o.onFail) o.onFail(j);
      if (o.onEnd) o.onEnd(j);
    }
  } catch (e) {
    toast("Suivi interrompu : " + e.message);
  }
}

// -- Étape 5 : galerie de validation --
async function loadAoGallery(adId) {
  if (!adId) return;
  let r;
  try {
    r = await api(AO_API + "/ad/" + adId);
  } catch (e) {
    return toast(e.message);
  }
  $("aoValidation").classList.remove("hidden");
  aoGalleryShots = r.shots || [];
  aoRenderBible(r.bible);
  aoRenderVoiceBlock(r);
  aoRenderWarnings("aoWarnings", r.warnings, r.max_words);
  const g = $("aoGallery");
  renderOverviewBanner(g, r, "avatar_omni", adId);
  g.innerHTML = "";
  let prevBlock = null;
  aoGalleryShots.forEach((s) => {
    const hasSegs = Array.isArray(s.segments) && s.segments.length;
    if (!hasSegs && s.block_n && s.block_count > 1 && s.block_n !== prevBlock) {
      const head = document.createElement("div");
      head.className = "ao-block-head";
      head.innerHTML = aoBlockHead(s);
      g.appendChild(head);
    }
    prevBlock = s.block_n || null;
    g.appendChild(aoShotCard(s));
  });
  aoRenderAnimEstimate();
}

// Plans candidats à l'animation = comme le backend : image + statut valide/echec.
function aoCandidates() {
  return aoGalleryShots.filter((s) => s.image_url && (s.status === "valide" || s.status === "echec"));
}

function aoSumSeconds(shots) {
  return shots.reduce((t, s) => t + (Number(s.duration_s) || 0), 0);
}

function aoRenderAnimEstimate() {
  const c = aoCandidates();
  const secs = aoSumSeconds(c);
  const usdVid = secs * aoRate();
  $("aoAnimEstimate").innerHTML = c.length
    ? `≈ <b>${usd(usdVid)}</b> <span class="muted">(${c.length} plan(s) · ~${secs} s de vidéo + voix à ~${usd(aoRate())}/s)</span>` +
      aoTier1Html(usdVid, false)
    : `<span class="muted">Aucun plan validé pour l'instant.</span>`;
}

function aoShotCard(s) {
  const card = document.createElement("div");
  const valid = s.status === "valide";
  const done = s.status === "pret";
  card.className = "obj-shot" + (valid || done ? " valide" : "");
  card.dataset.clip = String(s.clip_id);
  const isClient = Array.isArray(s.segments) && s.segments.length > 0;
  const badge = done
    ? '<span class="badge ok">animé ✓</span>'
    : valid
    ? '<span class="badge ok">validé ✓</span>'
    : s.status === "echec"
    ? '<span class="badge ko">échec</span>'
    : '<span class="badge">à valider</span>';
  const bust = s.image_url ? (s.image_url.includes("?") ? "&" : "?") + "t=" + Date.now() : "";
  const thumb = s.image_url
    ? `<img class="thumb" src="${esc(s.image_url)}${bust}" alt="plan ${esc(s.n)}" />`
    : `<div class="thumb empty">${esc(s.error || "pas d'image")}</div>`;
  const vbust = s.video_url ? (s.video_url.includes("?") ? "&" : "?") + "t=" + Date.now() : "";
  const clip = s.video_url
    ? `<a class="dl" href="${esc(s.video_url)}${vbust}" target="_blank" rel="noopener">🎬 Voir le clip</a>`
    : "";
  const err = s.image_url && s.error ? `<div class="ao-err" title="${esc(s.error)}">⚠ ${esc(prettyError(s.error))}</div>` : "";
  card.innerHTML =
    thumb +
    `<div class="body">` +
    `<div class="head"><span class="n">${aoPlanTitle(s)}</span>${badge}</div>` +
    `<div class="ao-meta"><span class="ao-dur">⏱️ ~${esc(s.duration_s || "?")} s</span>${clip}</div>` +
    err +
    (s.direction ? `<div class="ao-direction" title="Mise en scène du client">🎬 ${esc(s.direction)}</div>` : "") +
    (isClient
      ? `<div class="lbl">Ce qui change dans ce plan (image de départ — la bible est ajoutée automatiquement)</div>` +
        `<textarea class="pi">${esc(s.shot_prompt || "")}</textarea>` +
        `<div class="lbl">Tours Omni (1 vidéo continue${s.segments.length > 1 ? `, ${s.segments.length} extensions enchaînées` : ""})</div>` +
        aoSegmentsHtml(s.segments)
      : `<div class="lbl">Visuel (prompt image, éditable — pris en compte à la régénération)</div>` +
        `<textarea class="pi">${esc(s.prompt_image)}</textarea>` +
        `<div class="motion">🎬 ${esc(s.prompt_motion)}</div>`) +
    `<div class="lbl">💬 Dialogue — ce que la personne DIT (verbatim)</div>` +
    `<textarea class="vo" placeholder="Laisse vide = plan sans parole">${esc(s.dialogue || "")}</textarea>` +
    aoBracketValuesHtml(s.dialogue) +
    `<div class="actions">` +
    (done ? "" : `<button class="btn primary btn-valid">${valid ? "Dévalider" : "Valider"}</button>`) +
    `<button class="btn btn-regen">Régénérer</button>` +
    `<button class="btn small btn-test" title="Anime uniquement ce plan">Tester ce plan</button>` +
    `</div></div>`;

  card.querySelector(".body").insertBefore(planRefsControls(s, AO_REF_KIND_OPTS), card.querySelector(".actions"));

  // Dialogue (verbatim) enregistré à la perte de focus ; la durée Omni est recalculée côté serveur.
  const voEl = card.querySelector(".vo");
  voEl.addEventListener("blur", async () => {
    const text = voEl.value;
    if (text === (s.dialogue || "")) return;
    try {
      const res = await api(AO_API + "/dialogue/" + s.clip_id, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      s.dialogue = text;
      if (res && res.duration_s) s.duration_s = res.duration_s;
      await aoRefreshMeta(s, card);
      if (s.status === "pret") toast("Dialogue enregistré — ce clip est déjà animé : « Tester ce plan » pour le réanimer avec ce texte.");
    } catch (e) { toast(e.message); }
  });

  const validBtn = card.querySelector(".btn-valid");
  if (validBtn) validBtn.addEventListener("click", async () => {
    try {
      const res = await api(AO_API + "/validate/" + s.clip_id, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ valide: !valid }),
      });
      s.status = res.status;
      // Garde la liste de la galerie synchrone (elle peut contenir un autre objet pour ce plan).
      const g = aoGalleryShots.find((x) => x.clip_id === s.clip_id);
      if (g) g.status = res.status;
      card.replaceWith(aoShotCard(s));
      aoRenderAnimEstimate();
    } catch (e) { toast(e.message); }
  });

  card.querySelector(".btn-regen").addEventListener("click", async () => {
    const prompt_image = card.querySelector(".pi").value.trim();
    const dryRun = currentSettings && currentSettings.dry_run;
    if (!dryRun) {
      const ok = await showModal({
        title: "Régénérer l'image",
        message: "Régénérer cette image via Nano Banana (payant au-delà du quota gratuit ~500/jour). Continuer ?",
        confirmText: "Régénérer", cancelText: "Annuler", danger: true,
      });
      if (!ok) return;
    }
    card.classList.add("busy");
    try {
      const res = await api(AO_API + "/regenerate-image/" + s.clip_id, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_image, confirm: true }),
      });
      const j = await waitJobDone(res.job_id);
      if (j && j.state === "echec") toast(prettyError((j.summary && j.summary.message) || "Régénération en échec."));
      // Ne recharge QUE cette carte (préserve les prompts édités des autres).
      const ad = await api(AO_API + "/ad/" + aoAdId);
      aoGalleryShots = ad.shots || aoGalleryShots;
      const updated = (ad.shots || []).find((x) => x.clip_id === s.clip_id);
      if (updated) card.replaceWith(aoShotCard(updated));
      else card.classList.remove("busy");
      aoRenderAnimEstimate();
    } catch (e) {
      card.classList.remove("busy");
      toast(e.message);
    }
  });

  card.querySelector(".btn-test").addEventListener("click", () => {
    if (!s.image_url || !["valide", "echec", "pret"].includes(s.status))
      return toast("Valide ce plan avant de le tester.");
    aoLaunchAnimation([s], s.clip_id);
  });

  return card;
}

// Rafraîchit durée + avertissements après une édition de dialogue, sans re-rendre la galerie.
async function aoRefreshMeta(s, card) {
  try {
    const ad = await api(AO_API + "/ad/" + aoAdId);
    const fresh = (ad.shots || []).find((x) => x.clip_id === s.clip_id);
    if (fresh) {
      s.duration_s = fresh.duration_s;
      const g = aoGalleryShots.find((x) => x.clip_id === s.clip_id);
      if (g) { g.duration_s = fresh.duration_s; g.dialogue = fresh.dialogue; }
    }
    const dur = card.querySelector(".ao-dur");
    if (dur) dur.textContent = `⏱️ ~${s.duration_s || "?"} s`;
    aoRenderWarnings("aoWarnings", ad.warnings, ad.max_words);
    aoRenderAnimEstimate();
  } catch (_) { /* non bloquant */ }
}

$("aoRefreshBtn").addEventListener("click", () => loadAoGallery(aoAdId));

// Plans suivants : depuis l'ancre (ou le 1er plan validé) — même personne, cadrages variés.
$("aoConsistencyBtn").addEventListener("click", async () => {
  if (!aoAdId) return toast("Génère et valide d'abord le Plan 1.");
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    if (!(currentSettings && currentSettings.openrouter_api_key_set))
      return toast("Ajoute ta clé OpenRouter (Nano Banana) dans Réglages.");
    const ok = await showModal({
      title: "Générer les plans suivants",
      message: "Génère les plans suivants à partir de ton plan validé (MÊME personne) + tes photos de référence, via Nano Banana. Continuer ?",
      confirmText: "Générer", cancelText: "Annuler", danger: true,
    });
    if (!ok) return;
  }
  let res;
  try {
    res = await api(AO_API + "/consistency/" + aoAdId, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
  } catch (e) { return toast(e.message); }
  toast(`Génération de ${res.n ?? "?"} plan(s) suivant(s)…`);
  aoShowImgProgress();
  pollSceneJob(res.job_id, {
    ul: "aoSceneProgress", fill: "aoProgFill", count: "aoProgCount", unit: "images",
    onEnd: () => loadAoGallery(aoAdId),
  });
});

$("aoAnimateBtn").addEventListener("click", () => {
  if (!aoAdId) return toast("Génère et valide d'abord tes plans.");
  const c = aoCandidates();
  if (!c.length) return toast("Aucun plan validé à animer (valide d'abord les images).");
  aoLaunchAnimation(c, null);
});

// Lance l'animation Omni (tous les candidats, ou un seul plan si clipId) — modale de coût AVANT
// l'appel payant (estimation = Σ durées Omni × $/s, même formule que le backend), puis 402 plafond.
async function aoLaunchAnimation(shots, clipId) {
  // Galerie RELUE juste avant la modale : statuts et durées à jour (validations faites depuis,
  // régénérations…) → l'estimation affichée correspond à ce que le backend va réellement animer.
  try {
    const ad = await api(AO_API + "/ad/" + aoAdId);
    aoGalleryShots = ad.shots || [];
    shots = clipId
      ? aoGalleryShots.filter((s) => s.clip_id === clipId && s.image_url && ["valide", "echec", "pret"].includes(s.status))
      : aoCandidates();
    aoRenderAnimEstimate();
  } catch (e) {
    return toast(e.message);
  }
  if (!shots.length) {
    return toast(clipId ? "Valide ce plan avant de le tester." : "Aucun plan validé à animer (valide d'abord les images).");
  }
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    if (!(currentSettings && currentSettings.gemini_api_key_set))
      return toast("Ajoute ta clé API Google (Gemini) dans Réglages.");
    const secs = aoSumSeconds(shots);
    const usdVid = secs * aoRate();
    const tier1 = usdVid > AO_TIER1_USD ? `\n\n⏳ ${aoTier1Text(usdVid)}` : "";
    const ok = await showModal({
      title: clipId ? "Tester ce plan — coût Google Omni (réel)" : "Animer — coût Google Omni (réel)",
      message:
        (clipId ? "Anime UNIQUEMENT ce plan" : `Anime ${shots.length} plan(s) validé(s)`) +
        ` (vidéo + voix Google Omni, ~${usd(aoRate())}/s) — estimé ≈ ${usd(usdVid)} pour ~${secs} s. Continuer ?` + tier1,
      confirmText: clipId ? "Tester" : "Animer", cancelText: "Annuler", danger: true,
    });
    if (!ok) return;
  }
  const post = (over) =>
    api(AO_API + "/animate/" + aoAdId, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign(
        { confirm: true, confirm_over_cap: !!over }, clipId ? { clip_id: clipId } : {}
      )),
    });
  let res;
  try {
    res = await post(false);
  } catch (e) {
    if (!/plafond/i.test(e.message)) return toast(e.message);
    const ok = await showModal({
      title: "⚠ Dépassement du plafond de dépense",
      message: e.message + "\n\nConfirmer et animer malgré le plafond ?",
      confirmText: "Dépasser et animer", cancelText: "Annuler", danger: true,
    });
    if (!ok) return;
    try { res = await post(true); } catch (e2) { return toast(e2.message); }
  }
  // Coût revérifié par le backend (vraies durées Omni).
  if (res.usd_video != null) {
    $("aoAnimEstimate").innerHTML =
      `Lancé : ≈ <b>${usd(res.usd_video)}</b> <span class="muted">(${res.n_plans ?? shots.length} plan(s) · ` +
      `~${res.seconds_total ?? aoSumSeconds(shots)} s${res.dry_run ? " · simulation : $0" : ""})</span>` +
      (res.dry_run ? "" : aoTier1Html(Number(res.usd_video) || 0, res.tier1_warning));
  }
  toast(clipId ? "Animation du plan lancée…" : "Animation lancée…");
  $("aoAnimProgress").classList.remove("hidden");
  $("aoAnimSceneProgress").innerHTML = "";
  $("aoAnimProgFill").style.width = "0%";
  $("aoAnimProgCount").textContent = `0/${res.n_plans || shots.length} clips`;
  pollSceneJob(res.job_id, {
    ul: "aoAnimSceneProgress", fill: "aoAnimProgFill", count: "aoAnimProgCount", unit: "clips",
    onFail: (j) => showModal({
      title: "Animation — échec",
      message: prettyError((j.summary && j.summary.message) || "L'animation a échoué."),
      confirmText: "OK", cancelText: "",
    }),
    onEnd: (j) => {
      if (j.state !== "echec") {
        const sm = j.summary || {};
        const nFail = Number(sm.echec || 0);
        showModal({
          title: "🎬 Clips Avatar IA",
          message:
            `${sm.ok ?? j.done ?? 0} clip(s) prêt(s) → Bibliothèque, onglet « 🧑 Avatar IA ».` +
            (nFail ? `\n${nFail} plan(s) en échec : utilise « Reprendre les plans en échec » au-dessus de la galerie.` : ""),
          confirmText: "OK", cancelText: "",
        });
      }
      loadAoGallery(aoAdId);
      loadLibrary();
    },
  });
}

// Navigue vers une section en réutilisant le gestionnaire de clic de la barre latérale.
function gotoSection(sec) {
  const btn = document.querySelector(`.nav-item[data-section="${sec}"]`);
  if (btn) btn.click();
}

// Écran d'accueil au TOUT PREMIER lancement (base neuve) : quoi créer, où mettre les clés,
// et surtout qu'on peut TOUT tester en simulation sans aucune clé. Ne réapparaît plus ensuite.
async function maybeOnboarding() {
  try {
    const o = await api("/api/onboarding");
    if (!o.show) return;
    const goSettings = await showModal({
      title: "Bienvenue dans Pipeline UGC 👋",
      html:
        "<p>Cette app fabrique des pubs vidéo verticales (avatar, objet animé, mashup, voix off).</p>" +
        "<p><b>Tu peux tout tester tout de suite en MODE SIMULATION</b> — aucune clé, aucun crédit : " +
        "de vraies étapes, des fichiers de démonstration en sortie.</p>" +
        "<p>Pour générer <b>pour de vrai</b>, crée un compte chez les fournisseurs que tu utilises " +
        "et colle leurs clés dans <b>Réglages</b> :</p>" +
        "<ul style='margin:6px 0 6px 18px'>" +
        "<li><b>Anthropic (Claude)</b> — le « cerveau » qui découpe tes scripts</li>" +
        "<li><b>Gradium</b> — les voix</li>" +
        "<li><b>HeyGen</b> — les vidéos avatar</li>" +
        "<li><b>OpenRouter</b> — images (Nano Banana) + vidéos mashup (Kling/Veo)</li>" +
        "<li><b>xAI (Grok)</b> — animation « objet » (voix + lip-sync)</li>" +
        "<li><b>Google (Gemini)</b> — « Avatar IA » Omni (vidéo + voix ; clé Google AI Studio, tier payant)</li>" +
        "</ul>" +
        "<p class='muted'>Tu ne paies que ce que TU génères en mode réel. Décoche « simulation » " +
        "dans Réglages seulement quand tu es prêt.</p>",
      confirmText: "Ouvrir les Réglages",
      cancelText: "Plus tard",
    });
    await api("/api/onboarding/seen", { method: "POST" }).catch(() => {});
    if (goSettings) gotoSection("settings");
  } catch (_) {
    /* non bloquant : l'accueil ne doit jamais empêcher l'app de démarrer */
  }
}

// Affiche la version de l'app (sidebar) — utile pour le support / les mises à jour.
async function loadHealth() {
  try {
    const h = await api("/api/health");
    const el = $("appVersion");
    if (el && h.version) el.textContent = "v" + h.version;
    const warn = $("ffmpegWarn");   // ffmpeg absent → avertissement visible en haut du contenu
    if (warn) warn.classList.toggle("hidden", h.ffmpeg !== false);
  } catch (_) {
    /* non bloquant : la version reste vide si la santé n'est pas joignable */
  }
}

// ------------------------------------------------ démarrage
loadHealth();
loadDashboard().catch(() => {});
maybeOnboarding();
