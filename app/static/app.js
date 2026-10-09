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
// ------------------------------------------------ serveur déconnecté (bandeau)
// Un fetch qui ÉCHOUE (réseau, pas une réponse HTTP d'erreur) = serveur injoignable. Après
// SRV_FAIL_LIMIT échecs consécutifs → bandeau « Serveur déconnecté — relance l'app » au lieu
// d'erreurs en cascade. Le heartbeat /api/health (10 s) détecte la panne même sans action et
// signale au serveur que la fenêtre est toujours ouverte.
const SRV_FAIL_LIMIT = 2;
let srvFails = 0;
function srvBanner(show) {
  let b = $("srvDownBanner");
  if (!b && show) {
    b = document.createElement("div");
    b.id = "srvDownBanner";
    b.setAttribute("role", "alert");
    b.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:10000;padding:10px 16px;" +
      "background:#b42318;color:#fff;font-weight:600;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.25)";
    b.textContent = "⚠ Serveur déconnecté — relance l'app (LANCER.bat). Tes plans déjà générés sont conservés.";
    document.body.appendChild(b);
  }
  if (b) b.style.display = show ? "block" : "none";
}
function srvOk() {
  if (srvFails) { srvFails = 0; srvBanner(false); }
}
function srvFail() {
  srvFails += 1;
  if (srvFails >= SRV_FAIL_LIMIT) srvBanner(true);
}
async function srvFetch(url, opts) {
  try {
    const r = await fetch(url, opts);
    srvOk();
    return r;
  } catch (e) {
    srvFail();
    throw new Error(srvFails >= SRV_FAIL_LIMIT
      ? "Serveur déconnecté — relance l'app (LANCER.bat)."
      : "Le serveur ne répond pas — réessaie dans un instant.");
  }
}
setInterval(() => { srvFetch("/api/health", { cache: "no-store" }).catch(() => {}); }, 10000);

const api = async (url, opts) => {
  const r = await srvFetch(url, opts);
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
    if (sec === "new") { populateNewPubSelectors(); objClientRefresh(); }
    if (sec === "clients") loadClientsPanel();
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
  setKeyField("claudeCodeToken", s.claude_code_token_set);
  renderBrainEngine(s);
  if ($("geminiKey")) setKeyField("geminiKey", s.gemini_api_key_set);
  if ($("elevenlabsKey")) setKeyField("elevenlabsKey", s.elevenlabs_api_key_set);
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
  if ($("omniDailyLimit")) $("omniDailyLimit").value = s.omni_daily_request_limit ?? 20;
  if ($("omniMaxSpoken")) $("omniMaxSpoken").value = s.omni_max_spoken_clip_seconds ?? 8;
  if (s.avatar_video_models && s.avatar_video_models.length) {
    fillSelect("avatarVideoModel", s.avatar_video_models, s.avatar_video_model);
  } else if ($("avatarVideoModel")) {
    $("avatarVideoModel").value = s.avatar_video_model || "grok";
  }
  if ($("driftThreshold")) $("driftThreshold").value = s.drift_threshold ?? 0.8;
  setModeBadge(!!s.dry_run);
  renderAvatars(s.avatars || []);
  renderVoices(s.voices || []);
  renderMashStyleChips(s.mashup_style_suggestions || []);
}

// Moteur du cerveau : API Anthropic (défaut) ou Claude Code (abonnement). Si `claude` est
// introuvable, l'option est grisée. Le token n'est jamais renvoyé (champ vide = garder).
function brainEngineValue() {
  const r = document.querySelector('input[name="brainEngine"]:checked');
  return r ? r.value : "anthropic_api";
}

function toggleBrainEngineBoxes() {
  const cc = brainEngineValue() === "claude_code";
  $("engineApiBox").classList.toggle("hidden", cc);
  $("engineCcBox").classList.toggle("hidden", !cc);
}

function renderBrainEngine(s) {
  if (!$("engineCcBox")) return;
  const installed = !!s.claude_code_installed;
  const ccRadio = document.querySelector('input[name="brainEngine"][value="claude_code"]');
  ccRadio.disabled = !installed;
  $("brainEngineCcLabel").classList.toggle("disabled", !installed);
  $("ccNotInstalled").classList.toggle("hidden", installed);
  const engine = installed && s.brain_engine === "claude_code" ? "claude_code" : "anthropic_api";
  document.querySelector(`input[name="brainEngine"][value="${engine}"]`).checked = true;
  const sel = $("claudeCodeModel");
  sel.innerHTML = "";
  (s.claude_code_models || []).forEach((m) => {
    const o = document.createElement("option");
    o.value = m.key;
    o.textContent = m.label;
    sel.appendChild(o);
  });
  sel.value = s.claude_code_model || "sonnet";
  toggleBrainEngineBoxes();
}

document.querySelectorAll('input[name="brainEngine"]').forEach((r) =>
  r.addEventListener("change", toggleBrainEngineBoxes)
);

if ($("claudeCodeTestBtn")) {
  $("claudeCodeTestBtn").addEventListener("click", async () => {
    const msg = $("claudeCodeTestMsg");
    msg.textContent = "⏳ Appel « claude -p » en cours… (enregistre d'abord le token)";
    $("claudeCodeTestBtn").disabled = true;
    try {
      const r = await api("/api/claude-code/test", { method: "POST" });
      msg.innerHTML = r.ok
        ? `<span class="ok">✓ ${esc(r.message)} Sortie : « ${esc(r.output)} »</span>`
        : `<span class="ko">✗ ${esc(r.message)}</span>`;
    } catch (e) {
      msg.innerHTML = `<span class="ko">✗ ${esc(e.message)}</span>`;
    } finally {
      $("claudeCodeTestBtn").disabled = false;
    }
  });
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
    brain_engine: brainEngineValue(),
    claude_code_token: $("claudeCodeToken") ? $("claudeCodeToken").value.trim() : "",
    claude_code_model: ($("claudeCodeModel") && $("claudeCodeModel").value) || "",
    gemini_api_key: ($("geminiKey") && $("geminiKey").value.trim()) || "",   // vide = garder
    elevenlabs_api_key: ($("elevenlabsKey") && $("elevenlabsKey").value.trim()) || "",   // vide = garder
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
    omni_daily_request_limit: ($("omniDailyLimit") && $("omniDailyLimit").value !== "")
      ? parseInt($("omniDailyLimit").value, 10) : null,
    omni_max_spoken_clip_seconds: ($("omniMaxSpoken") && $("omniMaxSpoken").value !== "")
      ? Math.min(10, Math.max(3, parseInt($("omniMaxSpoken").value, 10) || 8)) : null,
    avatar_video_model: ($("avatarVideoModel") && $("avatarVideoModel").value) || "",
    drift_threshold: ($("driftThreshold") && $("driftThreshold").value !== "")
      ? Math.min(1, Math.max(0, parseFloat($("driftThreshold").value) || 0)) : null,
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
      message: "Aucun aperçu en cache pour ce style : on en génère un (1 image Nano Banana, payante). Continuer ?",
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
  renderOpenrouterTile($("dashOpenrouter"), d.openrouter);
  renderXaiTile($("dashXai"), d.xai);
  renderElevenlabsTile($("dashElevenlabs"), d.elevenlabs);
  $("totalVideos").textContent = d.total_videos ?? "0";
  const ul = $("activityList");
  ul.innerHTML = "";
  // Stack actuelle : les entrées d'activité liées à Gradium / HeyGen (ancien mode « Avatar ») ne
  // sont plus affichées sur le tableau de bord (toujours en base).
  d.activity = (d.activity || []).filter((a) => !/gradium|heygen/i.test(`${a.kind} ${a.message}`));
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

// Tuile vide/absente/simulation → « — » (jamais d'erreur). Renvoie true si la tuile est traitée.
function dashTileEmpty(el, o) {
  if (!el) return true;
  if (!o || typeof o !== "object" || !Object.keys(o).length) { el.textContent = "—"; return true; }
  if (o.simulation) { el.innerHTML = '— <span class="card-sub">(simulation)</span>'; return true; }
  return false;
}

// OpenRouter : {ok, balance_usd, usage_usd}
function renderOpenrouterTile(el, o) {
  if (dashTileEmpty(el, o)) return;
  const bal = pickNum(o, ["balance_usd", "balance", "remaining_usd"]);
  const use = pickNum(o, ["usage_usd", "usage"]);
  if (bal == null && use == null) return void (el.textContent = o.ok ? "✓" : "—");
  el.innerHTML = (bal != null ? esc(usd(bal)) : "—") +
    (use != null ? `<div class="card-sub">utilisé ${esc(usd(use))}</div>` : "");
}

// xAI : {ok, ...} (contenu variable selon l'API — solde si fourni, sinon état de la clé)
function renderXaiTile(el, o) {
  if (dashTileEmpty(el, o)) return;
  const bal = pickNum(o, ["balance_usd", "remaining_usd", "balance", "credits_usd"]);
  const use = pickNum(o, ["usage_usd", "spent_usd", "usage"]);
  if (bal == null && use == null) {
    el.innerHTML = o.ok ? '✓ <span class="card-sub">clé valide</span>' : "—";
    return;
  }
  el.innerHTML = (bal != null ? esc(usd(bal)) : "—") +
    (use != null ? `<div class="card-sub">utilisé ${esc(usd(use))}</div>` : "");
}

// ElevenLabs : {ok, characters_used, characters_limit}
function renderElevenlabsTile(el, o) {
  if (dashTileEmpty(el, o)) return;
  const used = pickNum(o, ["characters_used", "character_count"]);
  const lim = pickNum(o, ["characters_limit", "character_limit"]);
  if (used == null && lim == null) return void (el.textContent = o.ok ? "✓" : "—");
  el.innerHTML = esc(used != null ? frNum(used) : "—") +
    (lim != null ? `<div class="card-sub">sur ${esc(frNum(lim))}</div>` : "");
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
  keyframe: "keyframe…", omni: "vidéo Omni…", extension: "extension Omni…", assemblage: "assemblage…",
};

// Traduit une erreur brute (Gradium/HeyGen) en message court et lisible.
// Le message complet reste disponible au survol (title).
function prettyError(raw) {
  const m = String(raw || "échec");
  if (/unauthor|invalid api key|authentication|clé.*refus/i.test(m)) return "clé API refusée — vérifie-la dans Réglages";
  // 429 / quota du jour : message tel quel (jamais « crédits insuffisants »).
  if (/quota google du jour|requêtes\/jour|trop de requêtes|rate.?limit|too many requests|\b429\b/i.test(m)) return m;
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

// Avatar IA : jusqu'à 4 personnages → « visage1 » … « visage4 » (« visage » = ancien perso 1).
// Liste propre à l'Avatar IA (REF_KIND_OPTS, partagée Objet/Mashup, ne change pas). Les libellés
// portent le nom court du personnage quand il est connu (aoRefKindOpts).
const AO_REF_KIND_OPTS = [
  { v: "", t: "Type ?" },
  { v: "visage1", t: "Visage perso 1" },
  { v: "visage2", t: "Visage perso 2" },
  { v: "visage3", t: "Visage perso 3" },
  { v: "visage4", t: "Visage perso 4" },
  { v: "planche1", t: "Planche perso 1" },
  { v: "planche2", t: "Planche perso 2" },
  { v: "planche3", t: "Planche perso 3" },
  { v: "planche4", t: "Planche perso 4" },
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
  // Deux ancres de cohérence (seulement si le plan a une image) : ⚓ perso (personne / look) et
  // 📦 produit (plans produit). Une de chaque par pub ; l'une n'écrase jamais l'autre.
  if (s.image_url) {
    [["perso", "is_anchor", "⚓ perso", "Ancre PERSO : la personne / le look de référence des plans suivants"],
     ["produit", "is_product_anchor", "📦 ancre produit", "Ancre PRODUIT : le produit de référence (plans produit seul, et ajoutée quand le produit est visible)"],
    ].forEach(([kind, key, label, title], i) => {
      const anchor = document.createElement("button");
      anchor.type = "button";
      anchor.className = "ref-chip" + (i === 0 ? " anchor" : " anchor-prod") + (s[key] ? " on" : "");
      anchor.title = title;
      anchor.textContent = label;
      anchor.addEventListener("click", async () => {
        try {
          const res = await api("/api/clips/" + s.clip_id + "/anchor", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ is_anchor: !s[key], kind }),
          });
          s.is_anchor = !!res.is_anchor;
          s.is_product_anchor = !!res.is_product_anchor;
          anchor.classList.toggle("on", !!s[key]);
          // Une seule ancre de chaque type par pub : on retire la marque sur les autres cartes.
          if (s[key]) document.querySelectorAll(".ref-chip." + (i === 0 ? "anchor" : "anchor-prod") + ".on")
            .forEach((b) => { if (b !== anchor) b.classList.remove("on"); });
        } catch (e) { toast(e.message); }
      });
      wrap.appendChild(anchor);
    });
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
    `<span class="muted">(Nano Banana ~$${(e.cout_par_image_usd || 0).toFixed(3)}/image · animation Grok ensuite : ~$${(e.usd_video || 0).toFixed(2)} pour les plans validés)</span>` +
    `<div class="card-sub">Payé seulement en mode réel. En simulation : $0.</div>`;
  if (window.renderPubEstimate) window.renderPubEstimate("objet", shots, $("objEstimate"));  // agent C
  $("objPlanArea").classList.remove("hidden");
}

$("objGenImagesBtn").addEventListener("click", async () => {
  if (!objShots.length) return toast("Génère d'abord le plan de tournage.");
  const dryRun = currentSettings && currentSettings.dry_run;
  // Mon image pour le Plan 1 : aucune génération (donc aucun coût) pour ce plan.
  const plan1File = ($("objPlan1File").files || [])[0] || null;
  if (!dryRun && !plan1File) {
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
  fd.append("anchor_edit", $("objAnchorEdit").checked ? "true" : "false");
  if (plan1File) {
    fd.append("plan1_file", plan1File, plan1File.name);
    fd.append("plan1_anchor", $("objPlan1Anchor").checked ? "true" : "false");
  }

  let res;
  try {
    res = await api("/api/objet/generate-images", { method: "POST", body: fd });
  } catch (e) {
    return toast(e.message);
  }
  objAdId = res.ad_id;
  // Client / persos choisis : liés à la pub (persos au format commun, dossier d'export).
  if (objClientPresetId || objPersos.length)
    await clientPresetLinkAd(objAdId, objClientPresetId, objPersos.map((p) => p.id));
  if (!res.job_id) {   // Plan 1 uploadé : rien à générer, on passe direct à la validation
    toast("Plan 1 : ton image est en place (recadrée 9:16 720x1280).");
    return loadObjGallery(objAdId);
  }
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
  objAdState = r;
  $("objValidation").classList.remove("hidden");
  const g = $("objGallery");
  renderOverviewBanner(g, r, "objet", adId);
  renderObjAdPanel(r, adId);
  // Produit et réfs : fiche produit de la pub + « Réfs de la pub » (produit_refs.js).
  if (window.renderAdProductAndRefs) window.renderAdProductAndRefs($("objProductRefs"), adId, () => loadObjGallery(adId));
  g.innerHTML = "";
  (r.shots || []).forEach((s) => g.appendChild(objShotCard(s)));
  if (window.renderPubRealCost) window.renderPubRealCost(adId, $("objCostBox"));  // agent C
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
    lipsyncWarnHtml(s) +
    `<div class="lbl">💬 Dialogue — ce que l'objet DIT (français, verbatim). Grok fait la voix + lip-sync.</div>` +
    `<textarea class="vo" placeholder="Laisse vide = clip sans parole">${esc(s.dialogue || "")}</textarea>` +
    `<div class="actions">` +
    `<button class="btn primary btn-valid">${valid ? "Dévalider" : "Valider"}</button>` +
    `<button class="btn btn-regen">Régénérer</button>` +
    `</div></div>`;

  card.querySelector(".body").insertBefore(
    planRefsControls(s), card.querySelector(".actions")
  );
  // Upload de MON image + retouche de l'ancre / qui parle (Objet animé).
  card.querySelector(".body").insertBefore(objPlanOptions(s, card), card.querySelector(".actions"));
  traceDetails(card.querySelector(".body"), s.clip_id);   // tracabilite.js

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
      traceFeedback(s.clip_id, valid ? "rejeté" : "gardé", "image");
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
        message: "Régénérer cette image via Nano Banana (payant, tarif du modèle choisi dans les Réglages). Continuer ?",
        confirmText: "Régénérer",
        cancelText: "Annuler",
        danger: true,
      });
      if (!ok) return;
    }
    card.classList.add("busy");
    try {
      const t0 = traceNow();
      const res = await api("/api/objet/regenerate-image/" + s.clip_id, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_image, confirm: true }),
      });
      traceFeedback(s.clip_id, "régénéré", "image", { before: t0 });
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

// ---- Objet animé : upload d'image + ancre, retouche de l'ancre, persos parlants, réf principale
let objAdState = null;   // dernière réponse /api/objet/ad (persos, réfs, retouche)

// Aperçu local du Plan 1 (recadrage 9:16 simulé en CSS ; le vrai recadrage est fait côté serveur).
$("objPlan1File").addEventListener("change", () => {
  const f = ($("objPlan1File").files || [])[0];
  const box = $("objPlan1Preview");
  box.classList.toggle("hidden", !f);
  if (!f) return;
  const rd = new FileReader();
  rd.onload = () => (box.querySelector("img").src = String(rd.result));
  rd.readAsDataURL(f);
});

async function postJson(url, body) {
  return api(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}

// Panneau de la pub : toggle « Retouche de l'ancre », persos parlants, réf principale + alertes.
function renderObjAdPanel(r, adId) {
  const panel = $("objAdPanel");
  if (!panel) return;
  panel.innerHTML = "";

  // 1) Retouche de l'ancre (niveau pub ; surcharge possible par plan)
  const boxEdit = document.createElement("div");
  boxEdit.className = "box";
  boxEdit.innerHTML =
    `<label class="check"><input type="checkbox" class="ae" ${r.anchor_edit ? "checked" : ""} />` +
    ` <b>Retouche de l'ancre</b> — les plans suivants retouchent l'image ancre (⚓, par défaut le ` +
    `Plan 1) : « EDIT the anchor image… keep … STRICTLY IDENTICAL… Change ONLY … ». Les chips ` +
    `de réfs du plan ajoutent des images après l'ancre (ex. un 2e perso via « Style »).</label>`;
  boxEdit.querySelector(".ae").addEventListener("change", async (ev) => {
    try {
      await postJson("/api/objet/ad/" + adId + "/settings", { anchor_edit: ev.target.checked });
      loadObjGallery(adId);
    } catch (e) { toast(e.message); }
  });
  panel.appendChild(boxEdit);

  // 2) Persos parlants (nom, réf image, description, fiche voix MOT POUR MOT dans le prompt Grok)
  const boxP = document.createElement("div");
  boxP.className = "box";
  boxP.innerHTML =
    `<h3>🗣️ Persos qui parlent</h3><p class="muted small">Facultatif. La <b>fiche voix</b> (âge, ` +
    `timbre, débit, ton) est injectée <b>mot pour mot</b> dans le prompt Grok de chacun de ses ` +
    `plans → voix la plus constante possible. À 2 persos ou plus, choisis « Qui parle » sur ` +
    `chaque plan.</p><div class="persos"></div>`;
  const list = boxP.querySelector(".persos");
  const persos = (r.characters || []).map((p) => ({ ...p }));
  const refOpts = (r.refs || []).map((x, i) =>
    ({ v: x.path, t: `Réf ${i + 1}${x.kind ? " (" + x.kind + ")" : ""}` }));
  const drawPersos = () => {
    list.innerHTML = "";
    persos.forEach((p, idx) => {
      const row = document.createElement("div");
      row.className = "perso-row";
      row.innerHTML =
        `<input type="text" class="nom" placeholder="Nom (ex. Pot)" value="${esc(p.nom || "")}" />` +
        `<select class="img"><option value="">Réf image : aucune</option>` +
        refOpts.map((o) => `<option value="${esc(o.v)}" ${o.v === p.image_ref ? "selected" : ""}>${esc(o.t)}</option>`).join("") +
        `</select>` +
        `<input type="text" class="desc" placeholder="Description (ex. pot en céramique blanc)" value="${esc(p.description || "")}" />` +
        `<button type="button" class="btn small rm">Retirer</button>` +
        `<textarea class="fv" placeholder="Fiche voix — ex. Femme, 45 ans, timbre chaud et posé, débit lent, ton rassurant.">${esc(p.fiche_voix || "")}</textarea>`;
      row.querySelector(".nom").addEventListener("input", (ev) => (p.nom = ev.target.value));
      row.querySelector(".img").addEventListener("change", (ev) => (p.image_ref = ev.target.value));
      row.querySelector(".desc").addEventListener("input", (ev) => (p.description = ev.target.value));
      row.querySelector(".fv").addEventListener("input", (ev) => (p.fiche_voix = ev.target.value));
      row.querySelector(".rm").addEventListener("click", () => { persos.splice(idx, 1); drawPersos(); });
      list.appendChild(row);
    });
  };
  drawPersos();
  const actions = document.createElement("div");
  actions.className = "row";
  actions.innerHTML =
    `<button type="button" class="btn small add">+ Ajouter un perso</button>` +
    `<button type="button" class="btn small primary save">Enregistrer les persos</button>`;
  actions.querySelector(".add").addEventListener("click", () => {
    persos.push({ nom: "", image_ref: "", description: "", fiche_voix: "" });
    drawPersos();
  });
  actions.querySelector(".save").addEventListener("click", async () => {
    try {
      const res = await postJson("/api/objet/ad/" + adId + "/settings", { characters: persos });
      toast(`${res.characters.length} perso(s) enregistré(s).`);
      loadObjGallery(adId);
    } catch (e) { toast(e.message); }
  });
  boxP.appendChild(actions);
  panel.appendChild(boxP);

  // 3) Réf principale (image 1, elle prime sur les planches) + avertissements honnêtes
  if ((r.refs || []).length) {
    const boxR = document.createElement("div");
    boxR.className = "box";
    boxR.innerHTML =
      `<h3>⭐ Réf principale</h3><p class="muted small">Envoyée en <b>image 1</b> avec la consigne ` +
      `« Match reference image 1 exactly; do not add labels, text or logos that are not on it ». ` +
      `Par défaut : la 1re photo « Produit ».</p><div class="main-refs"></div>`;
    const wrap = boxR.querySelector(".main-refs");
    (r.refs || []).forEach((x, i) => {
      const lab = document.createElement("label");
      lab.className = x.is_main ? "on" : "";
      lab.title = x.is_main ? "Réf principale" : "Choisir comme réf principale";
      lab.innerHTML =
        `<img src="${esc(x.url || "")}" alt="réf ${i + 1}" />` +
        `<span><input type="radio" name="objMainRef" ${x.is_main ? "checked" : ""} /> Réf ${i + 1}${x.kind ? " · " + esc(x.kind) : ""}</span>`;
      lab.querySelector("input").addEventListener("change", async () => {
        try {
          await postJson("/api/objet/ad/" + adId + "/main-ref", { ref_id: x.id });
          loadObjGallery(adId);
        } catch (e) { toast(e.message); }
      });
      wrap.appendChild(lab);
    });
    (r.ref_warnings || []).forEach((w) => {
      const d = document.createElement("div");
      d.className = "warn";
      d.textContent = "⚠ " + w;
      boxR.appendChild(d);
    });
    panel.appendChild(boxR);
  }
}

// Plan PARLÉ animé par Grok : le serveur retire du mouvement les gestes de tête qui gênent le
// lip-sync (hochements, tête qui tourne, regards ailleurs…) → message sur la carte du plan.
function lipsyncWarnHtml(s) {
  return s && s.lipsync_warning
    ? `<div class="lipsync-warn" title="Ces gestes ne sont pas envoyés à Grok : ils dégradent la synchro des lèvres.">⚠ ${esc(s.lipsync_warning)}</div>`
    : "";
}

// Par plan : « Uploader mon image » (+ ancre), surcharge de la retouche, « Qui parle ».
function objPlanOptions(s, card) {
  const box = document.createElement("div");
  box.className = "obj-plan-opts";
  const persos = (objAdState && objAdState.characters) || [];
  const up = document.createElement("div");
  up.className = "obj-upload";
  up.innerHTML =
    `<input type="file" class="hidden up-file" accept="image/png,image/jpeg,image/webp" />` +
    `<button type="button" class="btn small up-btn">📤 Uploader mon image</button>` +
    `<label class="check"><input type="checkbox" class="up-anchor" ${s.n === 1 || s.is_anchor ? "checked" : ""} /> utiliser comme ancre</label>` +
    (s.uploaded ? `<span class="muted small">image uploadée (recadrée 9:16 720x1280)</span>` : "");
  const fileEl = up.querySelector(".up-file");
  up.querySelector(".up-btn").addEventListener("click", () => fileEl.click());
  fileEl.addEventListener("change", async () => {
    const f = (fileEl.files || [])[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f, f.name);
    fd.append("anchor", up.querySelector(".up-anchor").checked ? "true" : "false");
    card.classList.add("busy");
    try {
      await api("/api/objet/upload-image/" + s.clip_id, { method: "POST", body: fd });
      toast(`Plan ${s.n} : image en place (recadrée 9:16 720x1280).`);
      await loadObjGallery(objAdId);   // l'ancre a pu changer sur un autre plan
    } catch (e) {
      toast(e.message);
      card.classList.remove("busy");
    }
  });
  box.appendChild(up);

  const opts = document.createElement("div");
  opts.className = "obj-opts";
  opts.innerHTML =
    `<span>Retouche de l'ancre :</span><select class="ae">` +
    [["pub", `comme la pub (${objAdState && objAdState.anchor_edit ? "oui" : "non"})`], ["oui", "oui"], ["non", "non"]]
      .map(([v, t]) => `<option value="${v}" ${s.anchor_edit === v ? "selected" : ""}>${t}</option>`).join("") +
    `</select>` +
    (persos.length >= 2
      ? `<span>Qui parle :</span><select class="spk">` +
        persos.map((p, i) => `<option value="${i + 1}" ${s.speaker === i + 1 ? "selected" : ""}>${esc(p.nom)}</option>`).join("") +
        `</select>`
      : "");
  opts.querySelector(".ae").addEventListener("change", async (ev) => {
    try {
      const res = await postJson("/api/objet/clip/" + s.clip_id + "/options", { anchor_edit: ev.target.value });
      Object.assign(s, res);
    } catch (e) { toast(e.message); }
  });
  const spk = opts.querySelector(".spk");
  if (spk) spk.addEventListener("change", async (ev) => {
    try {
      const res = await postJson("/api/objet/clip/" + s.clip_id + "/options", { speaker: Number(ev.target.value) });
      Object.assign(s, res);
    } catch (e) { toast(e.message); }
  });
  box.appendChild(opts);
  return box;
}

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
        `title="Toutes les pièces de la pub dans un ZIP, numérotées (1, 2, 3…)">⬇ Télécharger tout (ZIP)</a>` +
        // agent C : export des clips validés dans le dossier du client (outils_c.js)
        (asset === "video" ? ` <button class="btn small btn-export-pub" type="button" data-ad-id="${ad.id}">📤 Exporter la pub</button>` : "")
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
    if (ad.kind === "avatar_omni") aoLibAdExtras(block, ad);
    const grid = document.createElement("div");
    grid.className = "clip-grid" + (ad.kind === "avatar_omni" ? " ao-lib-grid" : "");
    ad.clips.forEach((c) => {
      const div = document.createElement("div");
      div.className = "clip" + (c.status === "echec" ? " echec" : "");
      if (ad.kind === "avatar_omni") {
        aoLibClip(div, ad, c);
      } else if (c.media_url && c.status === "pret") {
        div.innerHTML =
          `<video src="${esc(c.media_url)}" controls preload="metadata"></video>` +
          `<div class="meta"><span class="scene-n">#${c.scene_n}</span>${speechCutBadge(c)}` +
          `<a class="dl" href="/api/clips/${c.id}/download">⬇ Télécharger</a></div>` +
          (ad.kind === "objet" ? speechCutActions(c) : "");
        if (ad.kind === "objet") bindSpeechCut(div, c);
      } else {
        div.innerHTML =
          `<div class="meta"><span class="scene-n">#${c.scene_n}</span></div>` +
          `<div class="err">${esc(c.error || "non généré")}</div>`;
      }
      if (ad.kind !== "avatar_omni") traceDetails(div, c.id);   // tracabilite.js (aoLibClip : idem)
      grid.appendChild(div);
    });
    block.appendChild(grid);
    root.appendChild(block);
  });
}

// prompts Omni envoyés : liste (contrat) ; tolère une chaîne JSON ou un texte brut.
function aoPromptList(v) {
  if (Array.isArray(v)) return v;
  if (typeof v === "string" && v.trim()) {
    try { const l = JSON.parse(v); return Array.isArray(l) ? l : [String(l)]; } catch (_) { return [v]; }
  }
  return [];
}

// Clip Avatar IA en Bibliothèque : keyframe à côté de la vidéo + prompts + « Relancer la vidéo seule ».
function aoLibClip(div, ad, c) {
  const ok = c.media_url && c.status === "pret";
  const bust = (u) => (u.includes("?") ? "&" : "?") + "t=" + Date.now();
  const kf = c.image_url
    ? `<figure class="ao-lib-kf"><img src="${esc(c.image_url)}${bust(c.image_url)}" alt="keyframe #${esc(c.scene_n)}" loading="lazy" />` +
      `<figcaption>Keyframe${AO_KF_SOURCE[c.keyframe_source] ? " · " + esc(AO_KF_SOURCE[c.keyframe_source]) : ""}</figcaption></figure>`
    : `<figure class="ao-lib-kf"><div class="ao-lib-empty">${c.keyframe_mode === "texte_seul" ? "Omni texte seul" : "pas de keyframe"}</div>` +
      `<figcaption>Keyframe</figcaption></figure>`;
  const vid = ok
    ? `<figure class="ao-lib-vid"><video src="${esc(c.media_url)}" controls preload="metadata"></video><figcaption>Vidéo</figcaption></figure>`
    : `<figure class="ao-lib-vid"><div class="ao-lib-empty err">${esc(c.error || "non généré")}</div><figcaption>Vidéo</figcaption></figure>`;
  const v2 = Number(ad.pipeline_version) === 2;
  // v2 : frame 0 de la vidéo à côté du keyframe + score de dérive (contrôle obligatoire).
  const frame0 = v2
    ? (c.frame0_url
      ? `<figure class="ao-lib-kf"><img src="${esc(c.frame0_url)}${bust(c.frame0_url)}" alt="frame 0 #${esc(c.scene_n)}" loading="lazy" />` +
        `<figcaption>Frame 0${aoDriftText(c)}</figcaption></figure>`
      : `<figure class="ao-lib-kf"><div class="ao-lib-empty">pas de frame 0</div><figcaption>Frame 0</figcaption></figure>`)
    : "";
  const drift = v2 && Number(c.drift_flag) ? `<span class="badge ko ao-drift" title="Frame 0 trop éloignée du keyframe — relance conseillée">Dérive</span>` : "";
  const omni = aoPromptList(c.omni_prompt);
  const prompts =
    `<details class="ao-lib-prompts"><summary>Prompts</summary>` +
    `<div class="lbl">🖼️ Prompt image</div><div class="pi-ro">${esc(c.prompt_image || "—")}</div>` +
    `<div class="lbl">🎥 Prompt vidéo</div><div class="pi-ro">${esc(c.video_prompt || "—")}</div>` +
    `<div class="lbl">📤 Prompts envoyés à Omni${omni.length ? ` (${omni.length} tour${omni.length > 1 ? "s" : ""})` : ""}</div>` +
    (omni.length
      ? omni.map((t, i) => `<div class="pi-ro">${omni.length > 1 ? `<b>Tour ${i + 1}</b> — ` : ""}${esc(typeof t === "string" ? t : JSON.stringify(t))}</div>`).join("")
      : `<div class="pi-ro">—</div>`) +
    `</details>`;
  div.innerHTML =
    `<div class="ao-lib-media${v2 ? " v2" : ""}">${kf}${frame0}${vid}</div>` +
    `<div class="meta"><span class="scene-n">#${esc(c.scene_n)}</span>${drift}${v2 && ok ? speechCutBadge(c) : ""}` +
    (ok ? `<a class="dl" href="/api/clips/${c.id}/download">⬇ Télécharger</a>` : "") + `</div>` +
    (v2 && ok ? speechCutActions(c) : "") +
    prompts +
    `<div class="ao-lib-actions"><button class="btn small btn-relaunch" type="button" ` +
    (v2
      ? `title="Refait uniquement la vidéo de ce bloc (même keyframe, même voix)">🔁 Relancer la vidéo</button>`
      : `title="Refait uniquement la vidéo Omni avec le même keyframe (aucune nouvelle image)">🔁 Relancer la vidéo seule</button>`) +
    `<span class="ao-lib-state muted small"></span></div>`;
  const btn = div.querySelector(".btn-relaunch");
  const state = div.querySelector(".ao-lib-state");
  btn.addEventListener("click", () => aoLibRelaunch(ad, c, btn, state));
  if (v2 && ok) bindSpeechCut(div, c);
  traceDetails(div, c.id);   // tracabilite.js
}

// ------------------------------------------------ réplique peut-être coupée (voix native Grok)
// Le serveur contrôle chaque clip Grok (niveau sonore de la fin) : si la voix continue jusqu'à la toute
// fin, badge + bouton « Régénérer (+1 s) » (relance la vidéo seule avec 1 s de plus).
function speechCutBadge(c) {
  return c.speech_cut && Number(c.speech_cut)
    ? `<span class="badge ko" title="La voix continue jusqu'à la toute fin du clip : la réplique est peut-être coupée.">Réplique peut-être coupée</span>`
    : "";
}
function speechCutActions(c) {
  if (!(c.speech_cut && Number(c.speech_cut))) return "";
  return `<div class="ao-lib-actions"><button class="btn small btn-speech-longer" type="button" ` +
    `title="Refait uniquement la vidéo de ce plan avec 1 s de plus (même image, même réplique)">⏱ Régénérer (+1 s)</button>` +
    `<span class="speech-state muted small"></span></div>`;
}
function bindSpeechCut(div, c) {
  const btn = div.querySelector(".btn-speech-longer");
  if (!btn) return;
  const state = div.querySelector(".speech-state");
  btn.addEventListener("click", async () => {
    const dryRun = currentSettings && currentSettings.dry_run;
    if (!dryRun) {
      const ok = await showModal({
        title: "Régénérer (+1 s) — coût Grok (réel)",
        message: "Refait UNIQUEMENT la vidéo de ce plan avec 1 seconde de plus (Grok, ~0,14 $/s + 0,01 $ — environ 1 à 1,80 $). Continuer ?",
        confirmText: "Régénérer", cancelText: "Annuler", danger: true,
      });
      if (!ok) return;
    }
    btn.disabled = true;
    try {
      const post = (over) => api("/api/clips/" + c.id + "/regenerate-longer", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true, confirm_over_cap: !!over }),
      });
      let res;
      const t0 = traceNow();
      try {
        res = await post(false);
      } catch (e) {
        if (!/plafond/i.test(e.message)) throw e;
        const over = await showModal({ title: "Plafond de dépense", message: e.message, confirmText: "Confirmer", cancelText: "Annuler", danger: true });
        if (!over) return;
        res = await post(true);
      }
      traceFeedback(c.id, "régénéré", "video", { before: t0, suggest: "replique_coupee" });
      if (state) state.textContent = "⏳ Vidéo en cours (+1 s)…";
      const j = await waitJobDone(res.job_id);
      if (!j) toast("Suivi interrompu — rafraîchis la Bibliothèque.");
      else if (j.state === "echec" || Number((j.summary || {}).echec || 0) > 0) toast(prettyError((j.summary && j.summary.message) || "La relance a échoué."));
      else toast("Vidéo refaite avec 1 s de plus ✓");
      loadLibraryVideos().catch(() => {});
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
    }
  });
}

// Relance la vidéo d'UN clip Avatar IA depuis la Bibliothèque (même keyframe, pas de Nano Banana).
async function aoLibRelaunch(ad, c, btn, state) {
  btn.disabled = true;
  try {
    // Durée + tours à jour (estimation de coût) ; la Bibliothèque ne les porte pas.
    let shot = null;
    try {
      const r = await api(AO_API + "/ad/" + ad.id);
      if (!aoOmniDailyLimit && r.omni_daily_limit) aoOmniDailyLimit = r.omni_daily_limit;
      shot = (r.shots || []).find((x) => x.clip_id === c.id) || null;
    } catch (_) { /* estimation approximative */ }
    if (shot && !aoKfOk(shot)) {
      toast("Ce keyframe n'est pas validé : valide-le dans le flux Avatar IA avant de relancer.");
      return;
    }
    const v2 = Number(ad.pipeline_version) === 2;
    if (v2 && shot && !aoVoiceOkShot(shot)) {
      toast("La voix de ce bloc n'est pas validée : valide-la (étape 4b) avant de relancer.");
      return;
    }
    const shots = [Object.assign({ status: "pret", duration_s: 0, segments: [] }, shot || {}, { status: "pret" })];
    const t0 = traceNow();
    const res = await aoPostAnimate(ad.id, shots, c.id, { relaunch: true, v2 });
    if (!res) return;
    traceFeedback(c.id, "régénéré", "video", { before: t0 });
    state.textContent = "⏳ Vidéo en cours…";
    toast("Relance de la vidéo lancée…");
    const j = await waitJobDone(res.job_id);
    if (!j) state.textContent = "Suivi interrompu — rafraîchis la Bibliothèque.";
    else if (j.state === "echec" || Number((j.summary || {}).echec || 0) > 0) {
      state.textContent = "";
      toast(prettyError((j.summary && j.summary.message) || "La relance a échoué."));
    } else {
      toast("Vidéo refaite ✓");
    }
    loadLibraryVideos().catch(() => {});
  } finally {
    btn.disabled = false;
  }
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
  claude_code: "#d97706",
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
  if (window.renderPubEstimate) window.renderPubEstimate("mashup", shots, $("mashEstimate"));  // agent C
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
  if (window.renderPubRealCost) window.renderPubRealCost(adId, $("mashCostBox"));  // agent C
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
  traceDetails(card.querySelector(".body"), s.clip_id);   // tracabilite.js

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
      traceFeedback(s.clip_id, valid ? "rejeté" : "gardé", "image");
      s.status = res.status;
      card.replaceWith(mashShotCard(s));
    } catch (e) { toast(e.message); }
  });

  card.querySelector(".btn-regen").addEventListener("click", async () => {
    const dryRun = currentSettings && currentSettings.dry_run;
    if (!dryRun) {
      const ok = await showModal({
        title: "Régénérer l'image",
        message: "Régénérer cette image via Nano Banana (payant, tarif du modèle choisi dans les Réglages). Continuer ?",
        confirmText: "Régénérer", cancelText: "Annuler", danger: true,
      });
      if (!ok) return;
    }
    card.classList.add("busy");
    try {
      const t0 = traceNow();
      const res = await api("/api/mashup/regenerate-image/" + s.clip_id, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true }),
      });
      traceFeedback(s.clip_id, "régénéré", "image", { before: t0 });
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
      const t0 = traceNow();
      const res = await api("/api/mashup/animate/" + mashAdId, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clip_id: s.clip_id, confirm: true }),
      });
      // Re-test d'un plan déjà animé = vidéo régénérée (1er test : ignoré côté serveur).
      traceFeedback(s.clip_id, "régénéré", "video", { before: t0 });
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
let aoVoiceUnlockedBy = {}; // par personnage : déverrouillage explicite (→ force:true), 1 sauvegarde
let aoOmniDailyLimit = null; // quota Google Omni (requêtes/jour) renvoyé par GET /ad
let aoKeyframesOk = false;   // ads.keyframes_ok : « Valider les keyframes » cliqué (sinon pas de vidéo)
// ---- Pipeline v2 « audio-first » (voix ElevenLabs → keyframes → 1 vidéo par bloc) ----
let aoAdState = null;        // dernière réponse GET /ad (pipeline_version, voices_ok, final_url…)
let aoVoicesOk = false;      // ads.voices_ok : « Valider les voix » cliqué
let aoPresetBible = null;    // bible des persos chargés (preset / bibliothèque) {character1: …}
let aoPresetOptions = null;  // {video_model, voice_mode} du preset chargé (appliqués à la nouvelle pub)
let aoCharSlotIds = {};      // perso N → id du personnage de la bibliothèque (preset / « Utiliser »)
let aoPresetPlanches = {};   // perso N → planche_url (bibliothèque)
let aoLoadedPresetId = null; // preset client chargé (lié à la pub créée)
const aoRefObjUrls = new Map();   // File → objectURL (aperçu planche à côté du keyframe)
const AO_EL_USD_PER_1K = 0.30;    // estimation ElevenLabs ($ / 1000 caractères) — même valeur que le backend
const AO_VIDEO_MODEL_LABEL = { grok: "Grok Imagine", kling: "Kling 3.0", omni: "Omni (Google)" };
const AO_API = "/api/avatar-omni";
// Voix ElevenLabs « maître » : DÉSACTIVÉE (masquée, code conservé). La voix est toujours générée
// nativement par le modèle vidéo. Pour réactiver : true ici + config_app.ACTIVE_VOICE_MODES.
const AO_ELEVENLABS_ENABLED = false;
// La pub utilise-t-elle les voix ElevenLabs (étape 4b + garde-fou « voix validées ») ?
function aoUsesElVoices(ad) {
  const a = ad || aoAdState || {};
  return AO_ELEVENLABS_ENABLED && a.voice_mode === "elevenlabs";
}
const AO_DEFAULT_RATE = 0.10;        // $/s (720p) — même formule que le backend
const AO_TIER1_USD = 10;             // quota Google Tier 1 : 10 $ / 10 min
const AO_DEFAULT_ACCENT = "natural French accent from France";
const AO_VOICE_FIELDS = ["Gender", "Age", "AccentRegion", "Accent", "Tone", "Pace", "Extra", "VoiceId", "VoiceSel"];

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
  ["aoV", "aoEV", "aoV2", "aoV3", "aoV4", "aoEV2", "aoEV3", "aoEV4"].forEach((p) => {
    fill(p + "Tone", s.objet_voice_styles, ["douce", s.objet_voice_style]);
    fill(p + "Pace", s.objet_voice_paces, ["naturel", s.objet_voice_pace]);
  });
  aoFillElSelects();
}

// ---- Voix ElevenLabs (pipeline v2) : voice ID par personnage, sauvé dans voice_profile.voice_id ----
let aoElVoices = null;        // cache GET /api/elevenlabs/voices
let aoElVoicesMsg = "";
let aoElAudio = null;         // lecteur partagé des extraits

function aoVoiceIdHtml(prefix) {
  return `<label class="ao-elv">Voice ID ElevenLabs <span class="muted">(voix de ce perso, pipeline v2)</span>` +
    `<span class="ao-elv-row"><select id="${prefix}VoiceSel" class="ao-el-sel" data-prefix="${prefix}">` +
    `<option value="">— voix ElevenLabs —</option></select>` +
    `<input type="text" id="${prefix}VoiceId" maxlength="64" placeholder="ou colle un voice ID" />` +
    `<button type="button" class="btn small ao-el-play" data-prefix="${prefix}">▶ Écouter un extrait</button></span>` +
    `<span class="muted small ao-el-hint"></span></label>`;
}

async function aoLoadElVoices(refresh) {
  if (!AO_ELEVENLABS_ENABLED) return [];
  if (aoElVoices && !refresh) return aoElVoices;
  try {
    const r = await api("/api/elevenlabs/voices");
    aoElVoices = Array.isArray(r.voices) ? r.voices : [];
    aoElVoicesMsg = r.message || (aoElVoices.length ? "" : "Aucune voix ElevenLabs (clé absente ou simulation) — colle un voice ID.");
  } catch (e) {
    aoElVoices = [];
    aoElVoicesMsg = "Liste ElevenLabs indisponible : " + e.message;
  }
  aoFillElSelects();
  return aoElVoices;
}

// Remplit tous les sélecteurs de voix ElevenLabs ; la sélection suit le voice ID saisi.
function aoFillElSelects() {
  document.querySelectorAll("select.ao-el-sel").forEach((sel) => {
    const input = $(sel.dataset.prefix + "VoiceId");
    const cur = input ? input.value.trim() : "";
    const list = aoElVoices || [];
    sel.innerHTML = `<option value="">— voix ElevenLabs —</option>` + list.map((v) => {
      const lab = v.labels && typeof v.labels === "object"
        ? Object.values(v.labels).filter((x) => typeof x === "string").slice(0, 3).join(", ") : "";
      return `<option value="${esc(v.voice_id)}">${esc(v.name || v.voice_id)}${lab ? " — " + esc(lab) : ""}</option>`;
    }).join("");
    if (cur && !list.some((v) => v.voice_id === cur)) {
      sel.insertAdjacentHTML("beforeend", `<option value="${esc(cur)}">${esc(cur)} (saisi)</option>`);
    }
    sel.value = cur;
    const hint = sel.closest(".ao-elv") && sel.closest(".ao-elv").querySelector(".ao-el-hint");
    if (hint) hint.textContent = aoElVoicesMsg;
  });
}

function aoPlayElPreview(voiceId) {
  if (!voiceId) return toast("Choisis ou colle d'abord un voice ID ElevenLabs.");
  if (!aoElAudio) aoElAudio = new Audio();
  aoElAudio.pause();
  aoElAudio.src = "/api/elevenlabs/preview/" + encodeURIComponent(voiceId);
  aoElAudio.play().catch((e) => toast("Lecture impossible : " + e.message));
}

document.addEventListener("change", (ev) => {
  const sel = ev.target;
  if (!(sel instanceof HTMLSelectElement) || !sel.classList.contains("ao-el-sel")) return;
  const input = $(sel.dataset.prefix + "VoiceId");
  if (input && sel.value) input.value = sel.value;
});
document.addEventListener("input", (ev) => {
  const el = ev.target;
  if (!(el instanceof HTMLInputElement) || !/VoiceId$/.test(el.id || "")) return;
  const sel = $(el.id.replace(/VoiceId$/, "VoiceSel"));
  if (sel && [...sel.options].some((o) => o.value === el.value.trim())) sel.value = el.value.trim();
});
document.addEventListener("click", (ev) => {
  const btn = ev.target instanceof Element ? ev.target.closest(".ao-el-play") : null;
  if (!btn) return;
  const input = $(btn.dataset.prefix + "VoiceId");
  aoPlayElPreview(input ? input.value.trim() : "");
});

// Formulaires statiques (perso 1 avant génération : aoV* ; en galerie : aoEV*) → champ voice ID.
(function initAoVoiceIdFields() {
  if (!AO_ELEVENLABS_ENABLED) return;
  ["aoV", "aoEV"].forEach((p) => {
    const extra = $(p + "Extra");
    const sheet = extra && extra.closest(".voice-sheet");
    if (sheet && !$(p + "VoiceId")) sheet.insertAdjacentHTML("beforeend", aoVoiceIdHtml(p));
  });
})();

// Formulaire de fiche voix (mêmes champs que aoV* / aoEV*) pour un préfixe d'ids donné.
function aoVoiceFormHtml(prefix) {
  const regions = [["france", "France"], ["quebec", "Québec"], ["belgique", "Belgique"], ["suisse", "Suisse"]];
  return `<div class="voice-sheet">` +
    `<label>Genre <select id="${prefix}Gender"><option value="">Non précisé</option>` +
    `<option value="female">Femme</option><option value="male">Homme</option></select></label>` +
    `<label>Âge <input type="text" id="${prefix}Age" maxlength="120" placeholder="Ex. 35-45" /></label>` +
    `<label>Accent <select id="${prefix}AccentRegion">` +
    regions.map(([v, t]) => `<option value="${v}">${t}</option>`).join("") + `</select></label>` +
    `<label>Accent libre <span class="muted">(optionnel, en anglais)</span>` +
    `<input type="text" id="${prefix}Accent" maxlength="120" /></label>` +
    `<label>Timbre <select id="${prefix}Tone"></select></label>` +
    `<label>Débit <select id="${prefix}Pace"></select></label>` +
    `<label>Précision libre <span class="muted">(optionnel, en anglais)</span>` +
    `<input type="text" id="${prefix}Extra" maxlength="120" /></label>` + (AO_ELEVENLABS_ENABLED ? aoVoiceIdHtml(prefix) : "") + `</div>`;
}

// ---- Personnages 1..4 (nom court + description FR + parle/muet) ----
const AO_MAX_CHARS = 4;

function aoCharRowVisible(n) {
  const row = $("aoCharRow" + n);
  return !!row && !row.classList.contains("hidden");
}

// Personnages saisis : le 1 toujours, les autres s'ils ont un nom ou une description.
function aoReadCharacters() {
  const out = [];
  for (let n = 1; n <= AO_MAX_CHARS; n++) {
    if (!aoCharRowVisible(n)) continue;
    const name = ($("aoCharName" + n).value || "").trim();
    const fr = ($("aoPersona" + n).value || "").trim();
    if (n > 1 && !name && !fr) continue;
    out.push({ n, name, fr, speaks: $("aoCharSpeaks" + n).value === "1" });
  }
  return out;
}

function aoSpeakingChars() {
  return aoReadCharacters().filter((c) => c.speaks).map((c) => c.n);
}

// Nom affichable d'un personnage : réponse serveur (personas.characters), sinon champs saisis.
function aoCharName(n) {
  n = Number(n) || 1;
  const list = (aoPersonas && Array.isArray(aoPersonas.characters)) ? aoPersonas.characters : [];
  const c = list.find((x) => Number(x.n) === n);
  if (c && c.name) return c.name;
  const el = $("aoCharName" + n);
  return el && el.value.trim() ? el.value.trim() : `Perso ${n}`;
}

// Options de type de réf Avatar IA, avec le nom des personnages (« Visage perso 2 (Julie) »).
function aoRefKindOpts() {
  return AO_REF_KIND_OPTS.map((o) => {
    const m = /^(?:visage|planche)(\d)$/.exec(o.v);
    if (!m) return o;
    const nm = aoCharName(m[1]);
    return { v: o.v, t: nm.startsWith("Perso ") ? o.t : `${o.t} (${nm})` };
  });
}

// Fiches voix des personnages 2..4 qui parlent (le perso 1 = formulaire aoV* existant).
function aoRenderVoiceForms() {
  const box = $("aoVoiceExtra");
  if (!box) return;
  const want = aoSpeakingChars().filter((n) => n > 1);
  // garder les valeurs déjà saisies
  const keep = {};
  for (let n = 2; n <= AO_MAX_CHARS; n++) if ($("aoV" + n + "Gender")) keep[n] = aoReadVoice("aoV" + n);
  box.innerHTML = want.map((n) =>
    `<div class="lbl ao-voice-extra-title">🎙️ Personnage ${n}${aoCharName(n).startsWith("Perso ") ? "" : " (" + esc(aoCharName(n)) + ")"}</div>` +
    aoVoiceFormHtml("aoV" + n)
  ).join("");
  $("aoVoiceTitle1").textContent = `🎙️ Personnage 1${aoCharName(1).startsWith("Perso ") ? "" : " (" + aoCharName(1) + ")"}` +
    (aoSpeakingChars().includes(1) ? "" : " — muet (fiche gardée par défaut)");
  aoFillVoiceSelects();
  want.forEach((n) => { if (keep[n]) aoWriteVoice("aoV" + n, keep[n]); });
}

// Fiches voix envoyées : {"1": …, "n": …} pour chaque personnage qui parle (le 1 toujours).
function aoReadVoiceProfiles() {
  const out = { 1: aoReadVoice("aoV") };
  aoSpeakingChars().filter((n) => n > 1).forEach((n) => {
    if ($("aoV" + n + "Gender")) out[n] = aoReadVoice("aoV" + n);
  });
  return out;
}

function aoRefreshCharsUi() {
  aoRenderVoiceForms();
  renderAoRefs();
  const visible = [1, 2, 3, 4].filter(aoCharRowVisible).length;
  $("aoCharAddBtn").classList.toggle("hidden", visible >= AO_MAX_CHARS);
}

(function initAoChars() {
  if (!$("aoChars")) return;
  $("aoCharAddBtn").addEventListener("click", () => {
    for (let n = 3; n <= AO_MAX_CHARS; n++) {
      if (!aoCharRowVisible(n)) { $("aoCharRow" + n).classList.remove("hidden"); break; }
    }
    aoRefreshCharsUi();
  });
  document.querySelectorAll(".ao-char-rm").forEach((b) => b.addEventListener("click", () => {
    const n = b.dataset.n;
    $("aoCharName" + n).value = "";
    $("aoPersona" + n).value = "";
    $("aoCharSpeaks" + n).value = "0";
    $("aoCharRow" + n).classList.add("hidden");
    aoRefreshCharsUi();
  }));
  for (let n = 1; n <= AO_MAX_CHARS; n++) {
    $("aoCharSpeaks" + n).addEventListener("change", aoRefreshCharsUi);
    $("aoCharName" + n).addEventListener("change", aoRefreshCharsUi);
  }
})();

function aoStyle() {
  const r = document.querySelector('input[name="aoStyle"]:checked');
  return r ? r.value : "realiste";
}

document.querySelectorAll('input[name="aoStyle"]').forEach((r) =>
  r.addEventListener("change", () => $("aoStyleHint").classList.toggle("hidden", aoStyle() !== "3d"))
);

async function aoEnsureVoiceSelects() {
  try {
    if (!currentSettings) currentSettings = await api("/api/settings");
    if (!$("aoVTone").options.length) aoFillVoiceSelects();
    aoRenderVoiceForms();
  } catch (e) { toast(e.message); }
  aoLoadElVoices();          // liste ElevenLabs (non bloquant)
  aoLoadPresetList();        // presets client + bibliothèque de personnages
  aoLoadCharLib();
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
    voice_id: v("VoiceId").trim(),   // ElevenLabs (v2) — jamais injecté dans un prompt
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
  set("VoiceId", p.voice_id || "");
  const sel = $(prefix + "VoiceSel");
  if (sel) aoFillElSelects();
}

// ---- Fiches voix en galerie : une par personnage qui parle (perso 1 = bloc aoEV* existant).
// Ids : perso 1 → aoEV*, aoVoiceLock, aoVoiceSheet, aoVoiceSaveBtn, aoVoiceUnlockBtn ;
//       perso n → aoEV{n}*, aoVoiceLock{n}, aoVoiceSheet{n}, aoVoiceSave{n}, aoVoiceUnlock{n}.
function aoVoiceIds(sp) {
  sp = Number(sp) || 1;
  return sp === 1
    ? { prefix: "aoEV", lock: "aoVoiceLock", sheet: "aoVoiceSheet", save: "aoVoiceSaveBtn", unlock: "aoVoiceUnlockBtn" }
    : { prefix: "aoEV" + sp, lock: "aoVoiceLock" + sp, sheet: "aoVoiceSheet" + sp, save: "aoVoiceSave" + sp, unlock: "aoVoiceUnlock" + sp };
}

function aoSetVoiceEditable(editable, sp = 1) {
  const ids = aoVoiceIds(sp);
  AO_VOICE_FIELDS.forEach((f) => { const el = $(ids.prefix + f); if (el) el.disabled = !editable; });
  if ($(ids.save)) $(ids.save).disabled = !editable;
}

// État d'UNE fiche voix (verrou si des tours de CE personnage sont déjà animés avec cette voix).
function aoRenderSpeakerVoice(sp, profile, sheet, locked) {
  const ids = aoVoiceIds(sp);
  if (!locked) delete aoVoiceUnlockedBy[sp];
  const unlocked = !!aoVoiceUnlockedBy[sp];
  aoWriteVoice(ids.prefix, profile || {});
  if ($(ids.sheet)) $(ids.sheet).textContent = sheet ? "Consigne envoyée à Google : " + sheet : "";
  const lock = $(ids.lock);
  const unlockBtn = $(ids.unlock);
  if (!lock || !unlockBtn) return;
  if (locked && !unlocked) {
    lock.textContent = "🔒 Verrouillée — des tours sont déjà animés avec cette voix";
    lock.className = "voice-lock on";
    unlockBtn.classList.remove("hidden");
    aoSetVoiceEditable(false, sp);
  } else {
    lock.textContent = unlocked ? "🔓 Déverrouillée — les tours déjà faits garderont l'ancienne voix" : "Modifiable";
    lock.className = "voice-lock" + (unlocked ? " warn" : "");
    unlockBtn.classList.add("hidden");
    aoSetVoiceEditable(true, sp);
  }
}

// Personnages qui parlent d'après la réponse GET /ad (fiches voix + personnages « speaks »).
function aoGallerySpeakers(r) {
  const set = new Set([1]);
  Object.keys(r.voice_profiles || {}).forEach((k) => { if (Number(k) >= 1 && Number(k) <= 4) set.add(Number(k)); });
  const chars = (r.personas && Array.isArray(r.personas.characters)) ? r.personas.characters : [];
  chars.forEach((c) => { if (c.speaks && Number(c.n) >= 1 && Number(c.n) <= 4) set.add(Number(c.n)); });
  return [...set].sort((x, y) => x - y);
}

function aoLockedFor(r, sp) {
  const v = r.voice_locked;
  if (v && typeof v === "object") return !!v[String(sp)];
  return sp === 1 ? !!v : false;   // ancienne réponse : un seul booléen (perso 1)
}

function aoRenderVoiceBlock(r) {
  const profiles = r.voice_profiles || {};
  const sheets = r.voice_sheets || {};
  $("aoEVoiceTitle1").textContent = `🎙️ Fiche voix — personnage 1${aoCharName(1).startsWith("Perso ") ? "" : " (" + aoCharName(1) + ")"}`;
  aoRenderSpeakerVoice(1, profiles["1"] || r.voice_profile || {}, sheets["1"] || r.voice_sheet || "", aoLockedFor(r, 1));
  const box = $("aoEVoiceExtra");
  const extra = aoGallerySpeakers(r).filter((n) => n > 1);
  box.innerHTML = extra.map((n) => {
    const ids = aoVoiceIds(n);
    return `<div class="card-block ao-voice-block">` +
      `<div class="ao-voice-head"><b>🎙️ Fiche voix — personnage ${n}${aoCharName(n).startsWith("Perso ") ? "" : " (" + esc(aoCharName(n)) + ")"}</b>` +
      `<span id="${ids.lock}" class="voice-lock"></span></div>` +
      aoVoiceFormHtml(ids.prefix) +
      `<div class="muted small" id="${ids.sheet}"></div>` +
      `<div class="row"><button class="btn small" id="${ids.save}" type="button">💾 Enregistrer la voix</button>` +
      `<button class="btn small danger-outline hidden" id="${ids.unlock}" type="button">🔓 Déverrouiller</button></div></div>`;
  }).join("");
  aoFillVoiceSelects();
  extra.forEach((n) => {
    const ids = aoVoiceIds(n);
    $(ids.save).addEventListener("click", () => aoSaveVoice(n));
    $(ids.unlock).addEventListener("click", () => aoUnlockVoice(n));
    aoRenderSpeakerVoice(n, profiles[String(n)] || {}, sheets[String(n)] || "", aoLockedFor(r, n));
  });
}

async function aoConfirmUnlock() {
  return showModal({
    title: "Déverrouiller la fiche voix ?",
    message:
      "Des tours sont déjà animés avec la voix actuelle de ce personnage. Si tu la modifies, les tours " +
      "déjà faits auront une autre voix que les suivants (il faudrait les réanimer pour tout harmoniser).\n\nDéverrouiller quand même ?",
    confirmText: "Déverrouiller", cancelText: "Annuler", danger: true,
  });
}

async function aoUnlockVoice(sp) {
  if (!(await aoConfirmUnlock())) return;
  aoVoiceUnlockedBy[sp] = true;
  const ids = aoVoiceIds(sp);
  const sheet = $(ids.sheet) ? $(ids.sheet).textContent : "";
  aoRenderSpeakerVoice(sp, aoReadVoice(ids.prefix), "", true);
  if ($(ids.sheet)) $(ids.sheet).textContent = sheet;   // on garde la consigne actuelle affichée
  toast("Fiche voix déverrouillée : modifie-la puis « Enregistrer la voix ».");
}

async function aoSaveVoice(sp) {
  if (!aoAdId) return toast("Génère d'abord le Plan 1.");
  const ids = aoVoiceIds(sp);
  const patch = (force) =>
    api(AO_API + "/voice/" + aoAdId, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice_profile: aoReadVoice(ids.prefix), speaker: sp, force: !!force }),
    });
  let res;
  try {
    res = await patch(!!aoVoiceUnlockedBy[sp]);
  } catch (e) {
    if (!/verrouill/i.test(e.message)) return toast(e.message);
    if (!(await aoConfirmUnlock())) return;
    aoVoiceUnlockedBy[sp] = true;
    try { res = await patch(true); } catch (e2) { return toast(e2.message); }
  }
  toast(`Fiche voix du personnage ${sp} enregistrée ✓`);
  // Déverrouillage valable pour CETTE sauvegarde seulement.
  delete aoVoiceUnlockedBy[sp];
  const locked = (res.voice_locked && typeof res.voice_locked === "object")
    ? !!res.voice_locked[String(sp)] : !!res.voice_locked;
  const sheet = res.voice_sheet || (res.voice_sheets && res.voice_sheets[String(sp)]) || "";
  const profile = res.voice_profile || (res.voice_profiles && res.voice_profiles[String(sp)]) || aoReadVoice(ids.prefix);
  aoRenderSpeakerVoice(sp, profile, sheet, locked);
  // Le débit change la durée des tours → durées + estimation SANS re-rendre les cartes.
  aoRefreshDurations();
}

$("aoVoiceUnlockBtn").addEventListener("click", () => aoUnlockVoice(1));
$("aoVoiceSaveBtn").addEventListener("click", () => aoSaveVoice(1));

async function aoRefreshDurations() {
  try {
    const ad = await api(AO_API + "/ad/" + aoAdId);
    aoGalleryShots = ad.shots || [];
    aoGalleryShots.forEach((s) => {
      const card = document.querySelector(`#aoGallery .obj-shot[data-clip="${s.clip_id}"]`);
      const dur = card && card.querySelector(".ao-dur");
      if (dur) dur.textContent = `⏱️ ~${s.duration_s || "?"} s`;
    });
    aoRenderWarnings("aoWarnings", ad.warnings, ad.max_words, ad.alerts, ad.max_spoken);
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
    cell.appendChild(refKindSelect(aoRefsKinds[idx], (v) => { aoRefsKinds[idx] = v; }, aoRefKindOpts()));
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
  character3: "aoBibleCharacter3", character4: "aoBibleCharacter4",
  set: "aoBibleSet", product: "aoBibleProduct", positions: "aoBiblePositions" };

// Tours Omni d'un plan : qui parle, durée chronométrée, mots max, avant / pendant / après,
// badge « muet », avertissements du tour, tour déjà fait. Rétrocompat : ancien tour {text, motion}.
function aoSegmentsHtml(segs) {
  if (!Array.isArray(segs) || !segs.length) return "";
  return `<ul class="ao-segs">` + segs.map((x, i) => {
    const mute = !!x.mute || !String(x.text || "").trim();
    const who = x.speaker_name || (x.speaker ? aoCharName(x.speaker) : "");
    const gest = (lbl, txt, beats) => (txt || (beats && beats.length))
      ? `<div class="ao-seg-gest">${lbl} ${esc(txt || "")}${beats && beats.length ? ` <span class="muted">[${esc(beats.join(", "))}]</span>` : ""}</div>`
      : "";
    const warns = Array.isArray(x.warnings) ? x.warnings.filter(Boolean) : [];
    return `<li class="${x.done ? "done" : ""}"><div class="ao-seg-head"><b>${x.done ? "✓" : "○"} Tour ${i + 1}</b>` +
      (mute ? `<span class="ao-turn-badge mute">muet</span>` : (who ? `<span class="ao-turn-badge">🗣️ ${esc(who)}</span>` : "")) +
      `<span>~${esc(x.seconds ?? "?")} s</span>` +
      (!mute && x.max_words != null ? `<span class="muted small">max ${esc(x.max_words)} mots</span>` : "") +
      `</div>` +
      (mute ? "" : `<div>💬 ${aoHighlightBrackets(x.text)}</div>`) +
      gest("⏮ avant :", x.avant, x.beats_avant) +
      gest("🎥 pendant :", x.pendant || x.motion, null) +
      gest("⏭ après :", x.apres, x.beats_apres) +
      warns.map((w) => `<div class="ao-seg-warn">⚠ ${esc(w)}</div>`).join("") + `</li>`;
  }).join("") + `</ul>`;
}

function aoPlanTitle(s) {
  if (s.block_n && Array.isArray(s.segments) && s.segments.length) {
    return `Bloc ${esc(s.block_n)}` + (s.block_title ? ` · ${esc(s.block_title)}` : "") +
      (s.timecode ? ` <span class="muted">[${esc(s.timecode)}]</span>` : "");
  }
  return `Plan ${esc(s.label || s.n)}`;
}

// Bible : personnages 1..4 — seuls ceux décrits (ou présents dans la pub) sont affichés.
function aoRenderBible(bible) {
  const box = $("aoBibleBox");
  const has = bible && bible.character1;
  box.classList.toggle("hidden", !has);
  if (!has) return;
  Object.entries(AO_BIBLE_FIELDS).forEach(([k, id]) => { $(id).value = bible[k] || ""; });
  const chars = (aoPersonas && Array.isArray(aoPersonas.characters)) ? aoPersonas.characters : [];
  for (let n = 1; n <= 4; n++) {
    const c = chars.find((x) => Number(x.n) === n);
    const used = n <= 2 || !!bible["character" + n] || !!c;
    $("aoBibleWrap" + n).classList.toggle("hidden", !used);
    const role = c ? (c.speaks ? "parle" : "muet") : (n === 1 ? "parle" : "muet");
    $("aoBibleLbl" + n).textContent = `Personnage ${n}${c && c.name ? " (" + c.name + ")" : ""} — ${role}`;
  }
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

// Deux sections : « Répliques trop longues » (mots PAR TOUR) seulement s'il y en a ; les autres
// alertes (durée, valeurs [à valider], fiche voix…) sous leur propre titre.
function aoRenderWarnings(boxId, warnings, maxWords, alerts, maxSpoken) {
  const box = $(boxId);
  const list = (warnings || []).filter(Boolean);
  const other = (alerts || []).filter(Boolean);
  if (!list.length && !other.length) { box.classList.add("hidden"); box.innerHTML = ""; return; }
  const ul = (items) => "<ul>" + items.map((w) => `<li>${esc(w)}</li>`).join("") + "</ul>";
  box.innerHTML =
    (list.length
      ? `<div class="ao-w-title">⚠ Répliques trop longues${maxWords ? ` (max ~${esc(maxWords)} mots par tour` +
        `${maxSpoken ? ` de ${esc(maxSpoken)} s` : ""}, moins si le tour a des gestes)` : ""}</div>` +
        ul(list) +
        `<div class="muted small">Au-delà, Google risque de couper la phrase. Raccourcis le dialogue ou découpe-le.</div>`
      : "") +
    (other.length ? `<div class="ao-w-title">⚠ À vérifier</div>` + ul(other) : "");
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

// Photo réduite (≤ 1024 px, JPEG) pour la bible : Claude la VOIT (visage / visage2 / produit).
async function aoPhotoDataUrl(file, max = 1024) {
  const url = await new Promise((res, rej) => {
    const rd = new FileReader();
    rd.onload = () => res(String(rd.result));
    rd.onerror = rej;
    rd.readAsDataURL(file);
  });
  try {
    const img = await new Promise((res, rej) => {
      const i = new Image();
      i.onload = () => res(i);
      i.onerror = rej;
      i.src = url;
    });
    const k = Math.min(1, max / Math.max(img.width, img.height));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(img.width * k));
    c.height = Math.max(1, Math.round(img.height * k));
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", 0.85);
  } catch (_) { return url; }
}

// Une photo par type (visage1..4, planche1..4, produit) : celles que Claude regarde pour la bible.
async function aoBiblePhotos() {
  const out = [];
  const seen = new Set();
  for (let i = 0; i < aoRefsFiles.length; i++) {
    const kind = aoRefsKinds[i] === "visage" ? "visage1" : aoRefsKinds[i];
    if (!/^(visage[1-4]|planche[1-4]|produit)$/.test(kind || "") || seen.has(kind)) continue;
    seen.add(kind);
    out.push({ kind, data: await aoPhotoDataUrl(aoRefsFiles[i]) });
  }
  return out;
}

// Corps commun à /plan et /validate-doc (style, personnages 1..4, fiches voix par personnage).
// Anciens champs persona1/persona2/voice_profile envoyés aussi (rétrocompat serveur).
async function aoPlanBody(mode, script, withPhotos) {
  return {
    script,
    persona: $("aoPersona").value.trim(),
    characters: aoReadCharacters(),
    persona1: $("aoPersona1").value.trim(),
    persona2: $("aoPersona2").value.trim(),
    product: $("aoProduct").value.trim(),
    ambiance: $("aoAmbiance").value.trim(),
    style: aoStyle(),
    manual: mode === "manual",
    mode,
    voice_profile: aoReadVoice("aoV"),
    voice_profiles: aoReadVoiceProfiles(),
    ref_photos: withPhotos ? await aoBiblePhotos() : [],
  };
}

function aoAcceptPlan(r, msg) {
  aoShots = r.shots || [];
  aoPersonas = r.personas || null;
  aoPlanBible = r.bible || null;
  // Preset / bibliothèque : la bible validée des personnages chargés prime sur celle du plan.
  if (aoPlanBible && aoPresetBible) {
    Object.entries(aoPresetBible).forEach(([k, v]) => { if (v && String(v).trim()) aoPlanBible[k] = v; });
  }
  if (r.ad && !$("aoAdName").value.trim()) $("aoAdName").value = r.ad;
  msg.innerHTML = `<div class="ok">✓ ${aoShots.length} plan(s)${r.dry_run ? " (simulation)" : ""}.</div>`;
  renderAoPlan(aoShots, r);
}

// -- Étape 3 : plan de tournage (auto → document à relire ; client/manuel → plan direct) --
$("aoPlanBtn").addEventListener("click", async () => {
  const script = $("aoScript").value;   // VERBATIM
  const mode = aoMode();
  const manual = mode === "manual";
  const msg = $("aoPlanMsg");
  if (!script.trim()) return toast(mode === "client" ? "Colle le document du client." : "Écris le script (ce que la personne doit dire).");
  msg.innerHTML = mode === "client" ? "🎬 Lecture du document client + traduction des mises en scène…"
    : manual ? "🎬 Préparation de tes plans…" : "🎬 Le réalisateur écrit le découpage par idée…";
  $("aoPlanBtn").disabled = true;
  $("aoPlanArea").classList.add("hidden");
  $("aoReviewArea").classList.add("hidden");
  try {
    const body = await aoPlanBody(mode, script, mode === "client");
    const r = await api(AO_API + "/plan", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (r.review) {
      // Mode auto : document à RELIRE, aucun plan ni image avant « Valider le découpage ».
      aoPersonas = r.personas || null;
      aoShots = [];
      $("aoReviewDoc").value = r.doc || "";
      $("aoReviewMsg").textContent = "";
      aoRenderWarnings("aoPlanWarnings", r.warnings, null, r.alerts);
      $("aoReviewArea").classList.remove("hidden");
      msg.innerHTML = `<div class="ok">✓ Découpage écrit : ${esc(r.blocks ?? "?")} bloc(s)${r.dry_run ? " (simulation)" : ""} — relis-le ci-dessous puis valide.</div>`;
      return;
    }
    aoAcceptPlan(r, msg);
  } catch (e) {
    msg.innerHTML = `<div class="ko">✗ ${esc(e.message)}</div>`;
  } finally {
    $("aoPlanBtn").disabled = false;
  }
});

// Mode auto : le document relu/édité part au pipeline « Découpage client » (bible avec photos,
// tours chronométrés, réfs). Rien n'est généré en images avant cette validation.
$("aoValidateDocBtn").addEventListener("click", async () => {
  const doc = $("aoReviewDoc").value;
  if (!doc.trim()) return toast("Le document de découpage est vide.");
  const msg = $("aoPlanMsg");
  $("aoValidateDocBtn").disabled = true;
  $("aoReviewMsg").textContent = "⏳ Bible + tours chronométrés…";
  try {
    const body = await aoPlanBody("client", $("aoScript").value, true);
    body.doc = doc;
    const r = await api(AO_API + "/validate-doc", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    $("aoReviewMsg").textContent = "✓ Découpage validé.";
    aoAcceptPlan(r, msg);
  } catch (e) {
    $("aoReviewMsg").textContent = "";
    msg.innerHTML = `<div class="ko">✗ ${esc(e.message)}</div>`;
  } finally {
    $("aoValidateDocBtn").disabled = false;
  }
});

const AO_REF_LABEL = { visage: "Visage perso 1", visage1: "Visage perso 1", visage2: "Visage perso 2",
  visage3: "Visage perso 3", visage4: "Visage perso 4", planche1: "Planche perso 1", planche2: "Planche perso 2",
  planche3: "Planche perso 3", planche4: "Planche perso 4", produit: "Produit", decor: "Décor", style: "Style" };

// Libellé d'un type de réf avec le nom du personnage (« Visage perso 2 (Julie) », « Planche perso 1 »).
function aoRefLabel(k) {
  const m = /^(visage|planche)(\d?)$/.exec(k || "");
  if (m && (m[2] || m[1] === "visage")) {
    const n = m[2] || "1";
    const nm = aoCharName(n);
    return `${m[1] === "planche" ? "Planche" : "Visage"} perso ${n}` + (nm.startsWith("Perso ") ? "" : ` (${nm})`);
  }
  return AO_REF_LABEL[k] || k;
}

function renderAoPlan(shots, r) {
  aoLastEstimate = r.estimate || null;
  const list = $("aoPlanList");
  list.innerHTML = "";
  let prevBlock = null;
  shots.forEach((s) => {
    const refs = Array.isArray(s.refs_needed) ? s.refs_needed : [];
    const refsTxt = refs.length ? refs.map(aoRefLabel).join(", ") : "plan neutre";
    const segs = Array.isArray(s.segments) ? s.segments : [];
    if (!segs.length && s.block_n && s.block_count > 1 && s.block_n !== prevBlock) {
      const head = document.createElement("div");
      head.className = "ao-block-head";
      head.innerHTML = aoBlockHead(s);
      list.appendChild(head);
    }
    prevBlock = s.block_n || null;
    const div = document.createElement("div");
    // Pipeline v2 : 1 bloc = 1 réplique d'UN perso (speaker) → qui parle + durée estimée en tête.
    const v2 = !segs.length && s.speaker != null;
    div.className = "scene-card" + (v2 ? " ao-v2-block" : "");
    const v2Head = v2
      ? ` · <span class="ao-turn-badge">🗣️ ${esc(s.dialogue && String(s.dialogue).trim() ? aoCharName(s.speaker) : "muet")}</span>` +
        ` · ~${esc(s.duration_s ?? "?")} s`
      : "";
    div.innerHTML =
      `<div><span class="n">${aoPlanTitle(s)}</span>${v2Head} <span class="muted">réfs : ${esc(refsTxt)}` +
      (segs.length ? ` · ${segs.length} tour(s) · ~${esc(s.duration_s)} s` : "") + `</span></div>` +
      (s.direction ? `<div class="ao-direction">🎬 Client : ${esc(s.direction)}</div>` : "") +
      (segs.length
        ? aoSegmentsHtml(segs) + `<div class="script"><b>🖼️ Image :</b> ${esc(s.shot_prompt || s.prompt_image)}</div>` +
          (s.video_prompt ? `<div class="motion"><b>🎥 Vidéo :</b> ${esc(s.video_prompt)}</div>` : "")
        : `<div class="motion">💬 ${s.dialogue ? aoHighlightBrackets(s.dialogue) : "<i>(sans parole)</i>"}</div>` +
          `<div class="script"><b>🖼️ Image :</b> ${esc(s.prompt_image)}</div>` +
          `<div class="motion"><b>🎥 Vidéo :</b> ${esc(s.video_prompt || s.prompt_motion || "")}</div>`);
    list.appendChild(div);
  });
  aoRenderWarnings("aoPlanWarnings", r.warnings, r.max_words, r.alerts, r.max_spoken);
  const e = r.estimate || {};
  $("aoEstimate").innerHTML =
    `<b>Coût estimé :</b> ${usd(e.usd_total)} ` +
    `<span class="muted">(images ${usd(e.usd_images)} · vidéo + voix Omni ${usd(e.usd_video)} ` +
    `pour ~${Math.round(e.seconds_total || 0)} s, ${e.shots || shots.length} plan(s) à ~${usd(aoRate())}/s)</span>` +
    (r.max_words ? `<div class="card-sub">Max ~${esc(r.max_words)} mots par tour${r.max_spoken ? ` de ${esc(r.max_spoken)} s` : ""} avec ce débit (moins si le tour a des gestes).</div>` : "") +
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
  fd.append("voice_profiles", JSON.stringify(aoReadVoiceProfiles()));
  fd.append("style", aoStyle());
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
  aoVoiceUnlockedBy = {};
  aoAdState = null;
  // Preset chargé : modèle vidéo + mode voix appliqués à la nouvelle pub (v2).
  if (aoPresetOptions && Object.keys(aoPresetOptions).length) {
    api(AO_API + "/options/" + aoAdId, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(aoPresetOptions),
    }).catch(() => { /* pub v1 ou options refusées : sans effet */ });
  }
  // Preset client chargé : la pub est liée à son client (persos + dossier d'export).
  if (aoLoadedPresetId) clientPresetLinkAd(aoAdId, aoLoadedPresetId);
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
  aoOmniDailyLimit = r.omni_daily_limit || null;
  if ($("aoResolution") && (r.omni_resolution === "720p" || r.omni_resolution === "1080p"))
    $("aoResolution").value = r.omni_resolution;
  $("aoKfMsg").innerHTML = "";
  if (r.personas) aoPersonas = r.personas;   // noms des personnages (tours, réfs, fiches voix)
  aoRenderBible(r.bible);
  // Produit et réfs : fiche produit de la pub + « Réfs de la pub » (produit_refs.js).
  if (window.renderAdProductAndRefs) window.renderAdProductAndRefs($("aoProductRefs"), adId);
  aoRenderVoiceBlock(r);
  aoAdState = r;
  aoRenderVoicesStep(r);
  aoRenderWarnings("aoWarnings", r.warnings, r.max_words, r.alerts, r.max_spoken);
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
  aoApplyAdState(r);
}

// ---- Étape Keyframes : état par plan + verrou global avant toute vidéo ----
// keyframe validé pour CE plan (réponse sans keyframe_ok = ancien backend : statut valide/pret).
function aoKfOk(s) {
  return s.keyframe_ok != null ? !!Number(s.keyframe_ok) : (s.status === "valide" || s.status === "pret");
}

function aoKfMode(s) {
  return s.keyframe_mode === "texte_seul" ? "texte_seul" : "start_frame";
}

// Animable côté départ : une image, ou le mode « Omni texte seul » (pas de start frame).
function aoHasStart(s) {
  return !!s.image_url || aoKfMode(s) === "texte_seul";
}

function aoResolutionValue() {
  const el = $("aoResolution");
  return el && el.value === "1080p" ? "1080p" : "720p";
}

// Applique la réponse GET /ad : plans, verrou « keyframes validées », bouton vidéo, estimation.
function aoApplyAdState(ad) {
  if (!ad) return;
  aoAdState = ad;
  aoGalleryShots = ad.shots || aoGalleryShots;
  aoKeyframesOk = ad.keyframes_ok == null ? true : !!Number(ad.keyframes_ok);
  aoVoicesOk = !!Number(ad.voices_ok || 0);
  aoRenderV2Options(ad);
  aoUpdateAnimGate();
  aoRenderAnimEstimate();
  aoRenderFinal(ad);
}

async function aoReloadAd() {
  const ad = await api(AO_API + "/ad/" + aoAdId);
  aoApplyAdState(ad);
  return ad;
}

function aoUpdateAnimGate() {
  const btn = $("aoAnimateBtn");
  const gate = $("aoKfGate");
  if (aoIsV2()) {
    // v2 : keyframes validés (+ voix validées en mode ElevenLabs), sinon bouton désactivé.
    const missing = [];
    if (aoUsesElVoices() && !aoVoicesOk) missing.push("les voix (étape 4b, « ✅ Valider les voix »)");
    if (!aoKeyframesOk) missing.push("les keyframes (« ✅ Valider les keyframes »)");
    if (btn) {
      btn.disabled = missing.length > 0;
      btn.textContent = "🎬 Générer les vidéos (1 appel par bloc)";
    }
    if (gate) {
      gate.textContent = missing.length ? "🔒 Génération vidéo verrouillée : valide d'abord " + missing.join(" et ") + "." : "";
      gate.classList.toggle("hidden", !missing.length);
    }
    const allV = $("aoKfValidateAllBtn");
    if (allV) allV.textContent = aoKeyframesOk ? "✅ Keyframes validés (revalider)" : "✅ Valider les keyframes";
    return;
  }
  if (btn) btn.textContent = "🎬 Animer les plans validés";
  if (btn) btn.disabled = !aoKeyframesOk;
  if (gate) {
    gate.textContent = aoKeyframesOk ? ""
      : "🔒 Génération vidéo verrouillée : vérifie chaque keyframe puis clique « ✅ Valider les keyframes ».";
    gate.classList.toggle("hidden", aoKeyframesOk);
  }
  const all = $("aoKfValidateAllBtn");
  if (all) all.textContent = aoKeyframesOk ? "✅ Keyframes validés (revalider)" : "✅ Valider les keyframes";
}

// Recharge l'ad puis remplace UNE carte (préserve les prompts édités des autres cartes).
async function aoRefreshCard(card, clipId) {
  const ad = await aoReloadAd();
  const updated = (ad.shots || []).find((x) => x.clip_id === clipId);
  if (updated) card.replaceWith(aoShotCard(updated));
  else card.classList.remove("busy");
}

// Re-rend toutes les cartes depuis une réponse GET /ad en gardant les saisies non envoyées.
function aoRerenderCards(ad) {
  (ad.shots || []).forEach((s) => {
    const card = document.querySelector(`#aoGallery .obj-shot[data-clip="${s.clip_id}"]`);
    if (!card) return;
    const keep = {};
    [".pi", ".kf-corr"].forEach((sel) => { const el = card.querySelector(sel); if (el) keep[sel] = el.value; });
    const fresh = aoShotCard(s);
    Object.keys(keep).forEach((sel) => { const el = fresh.querySelector(sel); if (el) el.value = keep[sel]; });
    card.replaceWith(fresh);
  });
}

// Bouton global : valide tous les keyframes (409 + `missing` si un plan start_frame n'a pas d'image).
async function aoValidateAllKeyframes() {
  if (!aoAdId) return toast("Génère d'abord les keyframes.");
  const msg = $("aoKfMsg");
  const btn = $("aoKfValidateAllBtn");
  btn.disabled = true;
  msg.innerHTML = "";
  document.querySelectorAll("#aoGallery .obj-shot.kf-missing").forEach((c) => c.classList.remove("kf-missing"));
  try {
    const r = await fetch(AO_API + "/keyframes/validate-all/" + aoAdId, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      // FastAPI : {detail: "...", missing:[…]} ou {detail: {detail|message, missing}}.
      const d = data.detail;
      const missing = Array.isArray(data.missing) ? data.missing
        : (d && typeof d === "object" && Array.isArray(d.missing) ? d.missing : []);
      const text = detailToMessage(d) || (d && typeof d === "object" && (d.detail || d.message)) ||
        "Validation impossible.";
      msg.innerHTML = `<div class="ko">✗ ${esc(text)}` +
        (missing.length ? `<br>Plans sans image de départ : <b>${esc(missing.map((n) => "Plan " + n).join(", "))}</b> — ` +
          `régénère, importe ton image ou passe-les en « Omni texte seul ».` : "") + `</div>`;
      missing.forEach((n) => {
        const s = aoGalleryShots.find((x) => String(x.n) === String(n));
        const card = s && document.querySelector(`#aoGallery .obj-shot[data-clip="${s.clip_id}"]`);
        if (card) card.classList.add("kf-missing");
      });
      return;
    }
    msg.innerHTML = `<div class="ok">✓ ${esc(data.validated ?? "")} keyframe(s) validé(s) — tu peux générer la vidéo.</div>`;
    const ad = await aoReloadAd();
    aoRerenderCards(ad);
  } catch (e) {
    msg.innerHTML = `<div class="ko">✗ ${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

// Plans candidats à l'animation = comme le backend : keyframe validé + départ dispo + valide/echec.
function aoCandidates() {
  return aoGalleryShots.filter((s) => aoKfOk(s) && aoHasStart(s) && (s.status === "valide" || s.status === "echec"));
}

function aoSumSeconds(shots) {
  return shots.reduce((t, s) => t + (Number(s.duration_s) || 0), 0);
}

// Requêtes Google Omni = somme des tours RESTANTS (1 par plan sans tours) — même calcul que le backend.
function aoRequests(shots) {
  return shots.reduce((t, s) => {
    const segs = Array.isArray(s.segments) ? s.segments : [];
    // Plan déjà « pret » relancé (vidéo seule) : tous ses tours sont refaits.
    if (s.status === "pret") return t + (segs.length || 1);
    return t + (segs.length ? segs.filter((x) => !x.done).length : 1);
  }, 0);
}

function aoDailyLimit() {
  return Number(aoOmniDailyLimit || (currentSettings && currentSettings.omni_daily_request_limit)) || 20;
}

function aoQuotaText(shots) {
  const req = aoRequests(shots);
  const lim = aoDailyLimit();
  return req > lim
    ? `${req} requêtes Google nécessaires (1 par tour) > quota de ${lim}/jour (Réglages) : l'animation s'arrêtera au quota — les tours faits sont gardés, reprends le lendemain.`
    : "";
}

function aoRenderAnimEstimate() {
  if (aoIsV2()) return void aoRenderV2Estimate();
  const c = aoCandidates();
  const secs = aoSumSeconds(c);
  const usdVid = secs * aoRate();
  const quota = aoQuotaText(c);
  $("aoAnimEstimate").innerHTML = c.length
    ? `≈ <b>${usd(usdVid)}</b> <span class="muted">(${c.length} plan(s) · ~${secs} s de vidéo + voix à ~${usd(aoRate())}/s · ` +
      `${aoResolutionValue()} · ` +
      `${aoRequests(c)} requête(s) Google, quota ${aoDailyLimit()}/jour)</span>` +
      aoTier1Html(usdVid, false) +
      (quota ? `<div class="ao-tier1">🚦 ${esc(quota)}</div>` : "")
    : `<span class="muted">Aucun keyframe validé pour l'instant.</span>`;
}

const AO_KF_SOURCE = { nano_banana_pro: "Nano Banana Pro", upload: "Mon image" };

// Carte d'un plan à l'étape Keyframes : image de départ + prompts image/vidéo + actions.
function aoShotCard(s) {
  const card = document.createElement("div");
  const done = s.status === "pret";
  const kfOk = aoKfOk(s);
  const mode = aoKfMode(s);
  card.className = "obj-shot" + (kfOk ? " valide" : "");
  card.dataset.clip = String(s.clip_id);
  const isClient = Array.isArray(s.segments) && s.segments.length > 0;
  const badge = done
    ? '<span class="badge ok">animé ✓</span>'
    : kfOk
    ? '<span class="badge ok">keyframe ✓</span>'
    : s.status === "echec"
    ? '<span class="badge ko">échec</span>'
    : '<span class="badge">à valider</span>';
  const bust = s.image_url ? (s.image_url.includes("?") ? "&" : "?") + "t=" + Date.now() : "";
  const thumb = s.image_url
    ? `<img class="thumb" src="${esc(s.image_url)}${bust}" alt="keyframe plan ${esc(s.n)}" />`
    : `<div class="thumb empty">${esc(s.error || (mode === "texte_seul" ? "Omni texte seul (pas d'image)" : "pas d'image"))}</div>`;
  const src = AO_KF_SOURCE[s.keyframe_source] || "";
  const srcBadge = s.image_url && src
    ? `<span class="kf-src${s.keyframe_source === "upload" ? " up" : ""}">${esc(src)}</span>` : "";
  const vbust = s.video_url ? (s.video_url.includes("?") ? "&" : "?") + "t=" + Date.now() : "";
  const clip = s.video_url
    ? `<a class="dl" href="${esc(s.video_url)}${vbust}" target="_blank" rel="noopener">🎬 Voir le clip</a>`
    : "";
  const err = s.image_url && s.error ? `<div class="ao-err" title="${esc(s.error)}">⚠ ${esc(prettyError(s.error))}</div>` : "";
  const v2 = aoIsV2();
  const canTest = kfOk && aoHasStart(s) && (!v2 || aoVoiceOkShot(s));
  card.innerHTML =
    `<div class="kf-thumb">${thumb}${srcBadge}${v2 ? aoPlancheCompareHtml(s) : ""}</div>` +
    `<div class="body">` +
    `<div class="head"><span class="n">${aoPlanTitle(s)}</span>${badge}</div>` +
    `<div class="ao-meta"><span class="ao-dur">⏱️ ~${esc(s.duration_s || "?")} s</span>${clip}</div>` +
    (Array.isArray(s.refs_sent) && s.refs_sent.length
      ? `<div class="muted small" title="Réfs réellement envoyées à Nano Banana, dans l'ordre">📎 Réfs envoyées : ` +
        `${esc(s.refs_sent.map((k) => (k === "ancre" ? "Ancre" : AO_REF_LABEL[k] || "sans type")).join(" › "))}</div>`
      : "") +
    err +
    (s.direction ? `<div class="ao-direction" title="Mise en scène du client">🎬 ${esc(s.direction)}</div>` : "") +
    (isClient
      ? `<div class="lbl">🖼️ Prompt image — ce qui change dans ce plan (la bible est ajoutée automatiquement)</div>` +
        `<textarea class="pi">${esc(s.shot_prompt || "")}</textarea>` +
        (s.prompt_image
          ? `<details class="kf-full"><summary>Prompt image complet envoyé à Nano Banana Pro</summary>` +
            `<div class="pi-ro">${esc(s.prompt_image)}</div></details>` : "")
      : `<div class="lbl">🖼️ Prompt image (éditable — pris en compte à la régénération)</div>` +
        `<textarea class="pi">${esc(s.prompt_image)}</textarea>`) +
    `<div class="lbl">🎥 Prompt vidéo Omni (mouvement + qui parle)</div>` +
    `<div class="pi-ro">${esc(s.video_prompt || s.prompt_motion || "—")}</div>` +
    lipsyncWarnHtml(s) +
    (isClient
      ? `<div class="lbl">Tours Omni (1 vidéo continue${s.segments.length > 1 ? `, ${s.segments.length} extensions enchaînées` : ""})</div>` +
        aoSegmentsHtml(s.segments)
      : "") +
    `<div class="lbl">💬 Dialogue — ce que la personne DIT (verbatim)</div>` +
    `<textarea class="vo" placeholder="Laisse vide = plan sans parole">${esc(s.dialogue || "")}</textarea>` +
    aoBracketValuesHtml(s.dialogue) +
    `<label class="kf-mode-lbl">Départ vidéo <select class="kf-mode">` +
    `<option value="start_frame"${mode === "start_frame" ? " selected" : ""}>Omni avec start frame</option>` +
    `<option value="texte_seul"${mode === "texte_seul" ? " selected" : ""}>Omni texte seul</option>` +
    `</select></label>` +
    `<input type="text" class="kf-corr" maxlength="500" placeholder="Correction (optionnel) — ex. « sourire plus léger, main gauche visible »" />` +
    `<input type="file" class="kf-file hidden" accept="image/png,image/jpeg,image/webp" />` +
    `<div class="actions">` +
    (done && kfOk ? "" : `<button class="btn primary btn-valid">${kfOk ? "Dévalider" : "Valider"}</button>`) +
    `<button class="btn btn-regen" title="Nouvelle image Nano Banana Pro (avec la correction si remplie)">Regénérer</button>` +
    `<button class="btn btn-upload" title="Remplacer le keyframe par ta propre image (PNG, JPG, WebP)">Uploader mon image</button>` +
    `<button class="btn small btn-test"${canTest ? "" : " disabled"} title="${canTest
      ? "Anime uniquement ce plan" : v2 ? "Valide d'abord ce keyframe et la voix de ce bloc" : "Valide d'abord ce keyframe"}">Tester ce plan</button>` +
    `</div></div>`;

  // Anciennes pubs : « visage » = visage1 (même puce) ; le serveur accepte les deux.
  if (Array.isArray(s.refs_needed)) s.refs_needed = s.refs_needed.map((k) => (k === "visage" ? "visage1" : k));
  card.querySelector(".body").insertBefore(planRefsControls(s, aoRefKindOpts()), card.querySelector(".kf-mode-lbl"));
  traceDetails(card.querySelector(".body"), s.clip_id);   // tracabilite.js

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

  // Valider / Dévalider CE keyframe (dévalider re-verrouille la génération vidéo).
  const validBtn = card.querySelector(".btn-valid");
  if (validBtn) validBtn.addEventListener("click", async () => {
    card.classList.add("busy");
    try {
      await api(AO_API + "/validate/" + s.clip_id, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ valide: !kfOk }),
      });
      traceFeedback(s.clip_id, kfOk ? "rejeté" : "gardé", "image");
      await aoRefreshCard(card, s.clip_id);
    } catch (e) {
      card.classList.remove("busy");
      toast(e.message);
    }
  });

  card.querySelector(".btn-regen").addEventListener("click", async () => {
    const prompt_image = card.querySelector(".pi").value.trim();
    const correction = card.querySelector(".kf-corr").value.trim();
    const dryRun = currentSettings && currentSettings.dry_run;
    if (!dryRun) {
      const ok = await showModal({
        title: "Regénérer le keyframe",
        message: "Regénérer cette image via Nano Banana Pro (payant)" +
          (correction ? ` avec la correction : « ${correction} »` : "") +
          ". Le keyframe devra être revalidé. Continuer ?",
        confirmText: "Regénérer", cancelText: "Annuler", danger: true,
      });
      if (!ok) return;
    }
    card.classList.add("busy");
    try {
      const t0 = traceNow();
      const res = await api(AO_API + "/regenerate-image/" + s.clip_id, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_image, confirm: true, correction }),
      });
      traceFeedback(s.clip_id, "régénéré", "image", { before: t0 });
      const j = await waitJobDone(res.job_id);
      if (j && j.state === "echec") toast(prettyError((j.summary && j.summary.message) || "Régénération en échec."));
      // Ne recharge QUE cette carte (préserve les prompts édités des autres).
      await aoRefreshCard(card, s.clip_id);
    } catch (e) {
      card.classList.remove("busy");
      toast(e.message);
    }
  });

  // Uploader mon image : remplace le keyframe sans appel Nano Banana.
  const fileIn = card.querySelector(".kf-file");
  card.querySelector(".btn-upload").addEventListener("click", () => fileIn.click());
  fileIn.addEventListener("change", async () => {
    const f = fileIn.files && fileIn.files[0];
    if (!f) return;
    if (!/^image\/(png|jpeg|webp)$/.test(f.type)) {
      fileIn.value = "";
      return toast("Format accepté : PNG, JPG ou WebP.");
    }
    const fd = new FormData();
    fd.append("file", f, f.name);
    card.classList.add("busy");
    try {
      await api(AO_API + "/keyframe/upload/" + s.clip_id, { method: "POST", body: fd });
      toast("Image importée ✓ — valide ce keyframe.");
      await aoRefreshCard(card, s.clip_id);
    } catch (e) {
      card.classList.remove("busy");
      fileIn.value = "";
      toast(e.message);
    }
  });

  // Mode de départ Omni : avec start frame (défaut) ou texte seul.
  const modeSel = card.querySelector(".kf-mode");
  modeSel.addEventListener("change", async () => {
    card.classList.add("busy");
    try {
      await api(AO_API + "/keyframe/mode/" + s.clip_id, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: modeSel.value }),
      });
      await aoRefreshCard(card, s.clip_id);
    } catch (e) {
      modeSel.value = mode;
      card.classList.remove("busy");
      toast(e.message);
    }
  });

  card.querySelector(".btn-test").addEventListener("click", () => {
    if (!canTest) return toast(v2 ? "Valide d'abord ce keyframe et la voix de ce bloc." : "Valide d'abord ce keyframe.");
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
      if (g) { g.duration_s = fresh.duration_s; g.dialogue = fresh.dialogue; g.segments = fresh.segments; }
      // Tours re-chronométrés après édition du dialogue → liste des tours mise à jour.
      const segsEl = card.querySelector(".ao-segs");
      if (segsEl && Array.isArray(fresh.segments) && fresh.segments.length) {
        s.segments = fresh.segments;
        segsEl.outerHTML = aoSegmentsHtml(fresh.segments);
      }
    }
    const dur = card.querySelector(".ao-dur");
    if (dur) dur.textContent = `⏱️ ~${s.duration_s || "?"} s`;
    aoRenderWarnings("aoWarnings", ad.warnings, ad.max_words, ad.alerts, ad.max_spoken);
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
  if (!aoAdId) return toast("Génère et valide d'abord tes keyframes.");
  if (aoIsV2()) {
    if (!aoVoicesOk) return toast("Clique d'abord « ✅ Valider les voix » (étape 4b).");
    if (!aoKeyframesOk) return toast("Clique d'abord « ✅ Valider les keyframes ».");
    return aoLaunchAnimation(aoV2Candidates(), null);
  }
  if (!aoKeyframesOk) return toast("Clique d'abord « ✅ Valider les keyframes ».");
  const c = aoCandidates();
  if (!c.length) return toast("Aucun keyframe validé à animer.");
  aoLaunchAnimation(c, null);
});

$("aoKfValidateAllBtn").addEventListener("click", aoValidateAllKeyframes);
$("aoResolution").addEventListener("change", aoRenderAnimEstimate);

// Modale de coût (mode réel) puis POST /animate/{adId} (+ reprise 402 « plafond »).
// Partagée par la galerie (Animer / Tester ce plan) et la Bibliothèque (Relancer la vidéo seule).
// Retourne la réponse du backend, ou null si annulé / erreur (déjà signalée).
async function aoPostAnimate(adId, shots, clipId, opt = {}) {
  if (opt.v2) return aoPostAnimateV2(adId, shots, clipId, opt);
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    if (!(currentSettings && currentSettings.gemini_api_key_set)) {
      toast("Ajoute ta clé API Google (Gemini) dans Réglages.");
      return null;
    }
    const secs = aoSumSeconds(shots);
    const usdVid = secs * aoRate();
    const tier1 = usdVid > AO_TIER1_USD ? `\n\n⏳ ${aoTier1Text(usdVid)}` : "";
    const quota = aoQuotaText(shots);
    const reqLine = `\n\n🚦 ${aoRequests(shots)} requête(s) Google (1 par tour) — quota ${aoDailyLimit()}/jour.` +
      (quota ? `\n⚠ ${quota}` : "");
    const resLine = opt.resolution ? ` en ${opt.resolution}` : "";
    const ok = await showModal({
      title: opt.relaunch ? "Relancer la vidéo seule — coût Google Omni (réel)"
        : clipId ? "Tester ce plan — coût Google Omni (réel)" : "Animer — coût Google Omni (réel)",
      message:
        (opt.relaunch ? "Refait UNIQUEMENT la vidéo de ce plan (même keyframe, aucune nouvelle image)"
          : clipId ? "Anime UNIQUEMENT ce plan" : `Anime ${shots.length} plan(s) validé(s)`) + resLine +
        ` (vidéo + voix Google Omni, ~${usd(aoRate())}/s) — estimé ≈ ${usd(usdVid)} pour ~${secs} s. Continuer ?` + tier1 + reqLine,
      confirmText: opt.relaunch ? "Relancer" : clipId ? "Tester" : "Animer", cancelText: "Annuler", danger: true,
    });
    if (!ok) return null;
  }
  const post = (over) =>
    api(AO_API + "/animate/" + adId, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign(
        { confirm: true, confirm_over_cap: !!over },
        clipId ? { clip_id: clipId } : {},
        opt.resolution ? { resolution: opt.resolution } : {}
      )),
    });
  try {
    return await post(false);
  } catch (e) {
    if (!/plafond/i.test(e.message)) { toast(e.message); return null; }
    const ok = await showModal({
      title: "⚠ Dépassement du plafond de dépense",
      message: e.message + "\n\nConfirmer et animer malgré le plafond ?",
      confirmText: "Dépasser et animer", cancelText: "Annuler", danger: true,
    });
    if (!ok) return null;
    try { return await post(true); } catch (e2) { toast(e2.message); return null; }
  }
}

// Lance l'animation Omni (tous les candidats, ou un seul plan si clipId) — modale de coût AVANT
// l'appel payant (estimation = Σ durées Omni × $/s, même formule que le backend), puis 402 plafond.
async function aoLaunchAnimation(shots, clipId) {
  // Galerie RELUE juste avant la modale : statuts et durées à jour (validations faites depuis,
  // régénérations…) → l'estimation affichée correspond à ce que le backend va réellement animer.
  let v2 = false;
  try {
    await aoReloadAd();
    v2 = aoIsV2();
    shots = v2
      ? (clipId ? aoGalleryShots.filter((s) => s.clip_id === clipId && aoKfOk(s) && aoVoiceOkShot(s)) : aoV2Candidates())
      : clipId
      ? aoGalleryShots.filter((s) => s.clip_id === clipId && aoKfOk(s) && aoHasStart(s) &&
          ["valide", "echec", "pret"].includes(s.status))
      : aoCandidates();
  } catch (e) {
    return toast(e.message);
  }
  if (v2 && !clipId && !aoVoicesOk) return toast("Clique d'abord « ✅ Valider les voix » (étape 4b).");
  if (!clipId && !aoKeyframesOk) return toast("Clique d'abord « ✅ Valider les keyframes ».");
  if (!shots.length) {
    return toast(v2 ? (clipId ? "Valide d'abord le keyframe et la voix de ce bloc." : "Aucun bloc à générer (tous déjà prêts ?).")
      : clipId ? "Valide d'abord ce keyframe." : "Aucun keyframe validé à animer.");
  }
  const t0 = traceNow();
  const res = await aoPostAnimate(aoAdId, shots, clipId, { resolution: aoResolutionValue(), v2 });
  if (!res) return;
  // « Tester ce plan » sur un plan déjà animé = vidéo régénérée (1er test : ignoré côté serveur).
  if (clipId) traceFeedback(clipId, "régénéré", "video", { before: t0 });
  if (v2 && res.estimate) {
    $("aoAnimEstimate").innerHTML = "Lancé : " + aoV2EstimateHtml(res.estimate);
  }
  // Coût revérifié par le backend (vraies durées Omni).
  if (!v2 && res.usd_video != null) {
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

// ================================================ AVATAR IA v2 : voix, vidéo par bloc, assemblage
function aoIsV2(ad = aoAdState) {
  return !!ad && Number(ad.pipeline_version) === 2;
}

function aoVoiceOkShot(s) {
  if (!aoUsesElVoices()) return !!s;      // voix native : aucune voix à valider
  return !!s && !!Number(s.voice_ok || 0);
}

function aoIsSpoken(s) {
  return !!String((s && s.dialogue) || "").trim();
}

// Blocs à générer en vidéo (v2) : keyframe + voix validés, pas encore prêts.
function aoV2Candidates() {
  return aoGalleryShots.filter((s) => aoKfOk(s) && aoVoiceOkShot(s) && s.status !== "pret");
}

function aoSpeakerLabel(s) {
  return aoIsSpoken(s) ? aoCharName(s.speaker || 1) : "muet";
}

// ---- Étape 4b : voix ElevenLabs par bloc ----
function aoRenderVoicesStep(ad) {
  const box = $("aoVoices");
  if (!box) return;
  // Étape sautée en voix native (seul mode actif) : la voix vient du modèle vidéo.
  const v2 = aoIsV2(ad) && aoUsesElVoices(ad);
  box.classList.toggle("hidden", !v2);
  if (!v2) return;
  aoVoicesOk = !!Number(ad.voices_ok || 0);
  const list = $("aoVoicesList");
  list.innerHTML = "";
  (ad.shots || []).forEach((s) => list.appendChild(aoVoiceRow(s)));
  $("aoVoicesValidateAllBtn").textContent = aoVoicesOk ? "✅ Voix validées (revalider)" : "✅ Valider les voix";
}

function aoVoiceRow(s) {
  const row = document.createElement("div");
  const ok = aoVoiceOkShot(s);
  const hasAudio = !!s.voice_url;
  const spoken = aoIsSpoken(s);
  row.className = "ao-voice-row" + (ok ? " valide" : "");
  row.dataset.clip = String(s.clip_id);
  row.dataset.n = String(s.n);
  const badge = ok ? '<span class="badge ok">voix ✓</span>'
    : hasAudio ? '<span class="badge">à valider</span>'
    : spoken ? '<span class="badge">pas d\'audio</span>' : '<span class="badge">muet</span>';
  const wav = Number(s.wav_seconds) || 0;
  const dur = wav > 0
    ? `⏱️ ${wav.toFixed(1).replace(".", ",")} s réels → clip ${esc(s.clip_seconds || "?")} s`
    : `⏱️ ~${esc(s.duration_s ?? "?")} s estimés`;
  const bust = hasAudio ? (s.voice_url.includes("?") ? "&" : "?") + "t=" + Date.now() : "";
  row.innerHTML =
    `<div class="ao-vr-head"><b>${aoPlanTitle(s)}</b>` +
    `<span class="ao-turn-badge">🗣️ ${esc(aoSpeakerLabel(s))}</span>${badge}<span class="muted small">${dur}</span></div>` +
    `<div class="ao-vr-text">💬 ${spoken ? aoHighlightBrackets(s.dialogue) : "<i>(sans parole)</i>"}</div>` +
    `<div class="ao-vr-player">` +
    (hasAudio ? `<audio controls preload="none" src="${esc(s.voice_url)}${bust}"></audio>`
      : `<span class="muted small">${spoken ? "Pas encore d'audio — « Générer les voix »." : "Aucune voix pour ce bloc."}</span>`) +
    `</div>` +
    `<div class="actions">` +
    (spoken ? `<button class="btn small btn-vregen" type="button">Regénérer</button>` : "") +
    `<button class="btn small primary btn-vvalid" type="button"${hasAudio || ok ? "" : " disabled"}>${ok ? "Dévalider" : "Valider"}</button>` +
    `</div>`;
  const regen = row.querySelector(".btn-vregen");
  if (regen) regen.addEventListener("click", () => aoRegenerateVoice(s, row));
  row.querySelector(".btn-vvalid").addEventListener("click", async () => {
    row.classList.add("busy");
    try {
      await api(AO_API + "/voices/validate/" + s.clip_id, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ valide: !ok }),
      });
      await aoReloadVoices();
    } catch (e) {
      row.classList.remove("busy");
      toast(e.message);
    }
  });
  return row;
}

async function aoReloadVoices() {
  const ad = await aoReloadAd();
  aoRenderVoicesStep(ad);
  aoRerenderCards(ad);   // « Tester ce plan » dépend aussi de la voix du bloc
  return ad;
}

function aoVoiceCostUsd(shots) {
  const chars = shots.reduce((t, s) => t + String(s.dialogue || "").trim().length, 0);
  return { chars, usd: (chars / 1000) * AO_EL_USD_PER_1K };
}

async function aoConfirmVoiceCost(shots, title) {
  const dryRun = currentSettings && currentSettings.dry_run;
  if (dryRun) return true;
  if (!(currentSettings && currentSettings.elevenlabs_api_key_set)) {
    toast("Ajoute ta clé ElevenLabs dans Réglages.");
    return false;
  }
  const c = aoVoiceCostUsd(shots);
  return showModal({
    title,
    message: `${shots.length} réplique(s), ${c.chars} caractères — ElevenLabs V3, estimé ≈ ${usd(c.usd)}. Continuer ?`,
    confirmText: "Générer", cancelText: "Annuler", danger: true,
  });
}

async function aoGenerateVoices() {
  if (!aoAdId) return toast("Génère d'abord le Plan 1 (la pub est créée à ce moment-là).");
  let ad;
  try { ad = await aoReloadAd(); } catch (e) { return toast(e.message); }
  const spoken = (ad.shots || []).filter(aoIsSpoken);
  if (!spoken.length) return toast("Aucune réplique à dire dans cette pub.");
  const missing = spoken.filter((s) => !s.voice_url);
  let force = false;
  let target = missing;
  if (!missing.length) {
    const again = await showModal({
      title: "Toutes les voix existent",
      message: "Chaque bloc a déjà son audio. Tout regénérer (les validations seront perdues) ?",
      confirmText: "Tout regénérer", cancelText: "Annuler", danger: true,
    });
    if (!again) return;
    force = true;
    target = spoken;
  }
  if (!(await aoConfirmVoiceCost(target, "Mode réel — voix ElevenLabs"))) return;
  const btn = $("aoVoicesGenBtn");
  btn.disabled = true;
  $("aoVoicesMsg").innerHTML = "";
  try {
    const res = await api(AO_API + "/voices/generate/" + aoAdId, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true, force }),
    });
    $("aoVoicesProgress").classList.remove("hidden");
    $("aoVoicesSceneProgress").innerHTML = "";
    $("aoVoicesProgFill").style.width = "0%";
    $("aoVoicesProgCount").textContent = `0/${res.n ?? target.length} voix`;
    pollSceneJob(res.job_id, {
      ul: "aoVoicesSceneProgress", fill: "aoVoicesProgFill", count: "aoVoicesProgCount", unit: "voix",
      onEnd: () => { btn.disabled = false; aoReloadVoices().catch((e) => toast(e.message)); },
    });
  } catch (e) {
    btn.disabled = false;
    $("aoVoicesMsg").innerHTML = `<div class="ko">✗ ${esc(e.message)}</div>`;
  }
}

async function aoRegenerateVoice(s, row) {
  if (!(await aoConfirmVoiceCost([s], "Regénérer la voix de ce bloc"))) return;
  row.classList.add("busy");
  try {
    const res = await api(AO_API + "/voices/regenerate/" + s.clip_id, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
    const j = await waitJobDone(res.job_id);
    if (j && (j.state === "echec" || Number((j.summary || {}).echec || 0) > 0))
      toast(prettyError((j.summary && j.summary.message) || "Voix en échec."));
    await aoReloadVoices();
  } catch (e) {
    row.classList.remove("busy");
    toast(e.message);
  }
}

// Bouton global : 409 {missing:[n]} si un bloc n'a pas d'audio → blocs surlignés.
async function aoValidateAllVoices() {
  if (!aoAdId) return;
  const msg = $("aoVoicesMsg");
  const btn = $("aoVoicesValidateAllBtn");
  btn.disabled = true;
  msg.innerHTML = "";
  document.querySelectorAll("#aoVoicesList .ao-voice-row.kf-missing").forEach((r) => r.classList.remove("kf-missing"));
  try {
    const r = await fetch(AO_API + "/voices/validate-all/" + aoAdId, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const d = data.detail;
      const missing = Array.isArray(data.missing) ? data.missing
        : (d && typeof d === "object" && Array.isArray(d.missing) ? d.missing : []);
      const text = detailToMessage(d) || (d && typeof d === "object" && (d.detail || d.message)) || "Validation impossible.";
      msg.innerHTML = `<div class="ko">✗ ${esc(text)}` +
        (missing.length ? `<br>Blocs sans audio : <b>${esc(missing.map((n) => "Plan " + n).join(", "))}</b> — « Générer les voix » ou « Regénérer ».` : "") +
        `</div>`;
      missing.forEach((n) => {
        const el = document.querySelector(`#aoVoicesList .ao-voice-row[data-n="${CSS.escape(String(n))}"]`);
        if (el) el.classList.add("kf-missing");
      });
      return;
    }
    msg.innerHTML = `<div class="ok">✓ ${esc(data.validated ?? "")} voix validée(s) — durées des clips fixées.</div>`;
    await aoReloadVoices();
  } catch (e) {
    msg.innerHTML = `<div class="ko">✗ ${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

if ($("aoVoicesGenBtn")) $("aoVoicesGenBtn").addEventListener("click", aoGenerateVoices);
if ($("aoVoicesValidateAllBtn")) $("aoVoicesValidateAllBtn").addEventListener("click", aoValidateAllVoices);

// ---- Keyframes v2 : planche perso à côté du keyframe du Plan 1 (ancre) ----
function aoIsAnchorShot(s) {
  if (s.is_anchor) return true;
  const first = aoGalleryShots[0];
  return !aoGalleryShots.some((x) => x.is_anchor) && !!first && first.clip_id === s.clip_id;
}

// URL de la planche du perso N : réfs de l'ad (si le serveur les renvoie), photos uploadées
// (type plancheN), ou planche de la bibliothèque (preset / « Utiliser comme perso N »).
function aoPlancheUrl(n) {
  const kind = "planche" + n;
  const ad = aoAdState || {};
  const refs = [].concat(Array.isArray(ad.ref_images) ? ad.ref_images : [], Array.isArray(ad.refs) ? ad.refs : []);
  const hit = refs.find((r) => r && r.kind === kind && (r.url || r.media_url || r.image_url));
  if (hit) return hit.url || hit.media_url || hit.image_url;
  const i = aoRefsKinds.indexOf(kind);
  if (i >= 0 && aoRefsFiles[i]) {
    const f = aoRefsFiles[i];
    if (!aoRefObjUrls.has(f)) aoRefObjUrls.set(f, URL.createObjectURL(f));
    return aoRefObjUrls.get(f);
  }
  return aoPresetPlanches[n] || "";
}

function aoPlancheCompareHtml(s) {
  if (!aoIsAnchorShot(s)) return "";
  const ns = new Set();
  if (s.speaker) ns.add(Number(s.speaker));
  (Array.isArray(s.refs_needed) ? s.refs_needed : []).forEach((k) => {
    const m = /^(?:planche|visage)(\d)$/.exec(k || "");
    if (m) ns.add(Number(m[1]));
  });
  if (!ns.size) ns.add(1);
  const figs = [...ns].sort().map((n) => {
    const url = aoPlancheUrl(n);
    return url
      ? `<figure class="ao-planche"><img src="${esc(url)}" alt="planche perso ${n}" /><figcaption>Planche ${esc(aoCharName(n))}</figcaption></figure>`
      : `<figure class="ao-planche"><div class="thumb empty">pas de planche</div><figcaption>${esc(aoCharName(n))}</figcaption></figure>`;
  }).join("");
  return `<div class="ao-planche-cmp">${figs}<div class="ao-planche-tip">👀 Vérifie la ressemblance avec la planche avant de valider.</div></div>`;
}

// ---- Génération vidéo v2 : options, estimation, lancement, assemblage ----
// Réglages Google Omni de la pub : start frame seule, caméra, découpage auto, chaîne voix identique.
function aoRenderOmniOptions(ad) {
  const box = $("aoOmniOptions");
  if (!box || !ad) return;
  const vm = ad.video_model || (currentSettings && currentSettings.avatar_video_model) || "grok";
  const omni = !aoIsV2(ad) || vm === "omni";   // ancien pipeline = toujours Omni
  box.classList.toggle("hidden", !omni);
  if (!omni) return;
  $("aoOmniStartFrameOnly").checked = ad.omni_start_frame_only !== false;
  $("aoOmniCamera").value = ad.omni_camera || "";
  $("aoOmniAutoTurns").checked = !!ad.omni_auto_turns;
  $("aoOmniVoiceChain").checked = !!ad.omni_voice_chain;
  // Découpage en tours : ancien pipeline seulement ; chaîne voix identique : v2 seulement.
  $("aoOmniAutoTurns").parentElement.classList.toggle("hidden", aoIsV2(ad));
  $("aoOmniVoiceChain").parentElement.classList.toggle("hidden", !aoIsV2(ad));
}

if ($("aoOmniStartFrameOnly")) $("aoOmniStartFrameOnly").addEventListener("change", () =>
  aoPatchOptions({ omni_start_frame_only: $("aoOmniStartFrameOnly").checked }));
if ($("aoOmniCamera")) $("aoOmniCamera").addEventListener("change", () =>
  aoPatchOptions({ omni_camera: $("aoOmniCamera").value }));
if ($("aoOmniAutoTurns")) $("aoOmniAutoTurns").addEventListener("change", () =>
  aoPatchOptions({ omni_auto_turns: $("aoOmniAutoTurns").checked }));
if ($("aoOmniVoiceChain")) $("aoOmniVoiceChain").addEventListener("change", () =>
  aoPatchOptions({ omni_voice_chain: $("aoOmniVoiceChain").checked }));

function aoRenderV2Options(ad) {
  aoRenderOmniOptions(ad);
  const box = $("aoV2Options");
  if (!box) return;
  const v2 = aoIsV2(ad);
  box.classList.toggle("hidden", !v2);
  if (!v2) return;
  const vm = ad.video_model || (currentSettings && currentSettings.avatar_video_model) || "grok";
  if ([...$("aoVideoModel").options].some((o) => o.value === vm)) $("aoVideoModel").value = vm;
  $("aoVoiceMode").value = aoUsesElVoices(ad) ? "elevenlabs" : "native";
  if ($("aoVoiceModeLabel")) $("aoVoiceModeLabel").classList.toggle("hidden", !AO_ELEVENLABS_ENABLED);
}

async function aoPatchOptions(body) {
  if (!aoAdId) return;
  try {
    await api(AO_API + "/options/" + aoAdId, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (aoAdState) Object.assign(aoAdState, body);
    if (aoAdState && "video_model" in body) aoRenderOmniOptions(aoAdState);
    toast("Option enregistrée ✓");
    aoRenderAnimEstimate();
  } catch (e) { toast(e.message); }
}

if ($("aoVideoModel")) $("aoVideoModel").addEventListener("change", () => aoPatchOptions({ video_model: $("aoVideoModel").value }));
if ($("aoVoiceMode")) $("aoVoiceMode").addEventListener("change", () => aoPatchOptions({ voice_mode: $("aoVoiceMode").value }));

function aoV2EstimateHtml(e) {
  e = e || {};
  const model = AO_VIDEO_MODEL_LABEL[e.video_model] || e.video_model || "";
  const native = e.voice_mode !== "elevenlabs";
  const mode = native ? "voix native du modèle" : "voix ElevenLabs";
  const detail = `${esc(e.n_clips ?? "?")} clip(s) · ~${esc(Math.round(Number(e.seconds_total) || 0))} s` +
    (model ? ` · ${esc(model)}` : "") + ` · ${esc(mode)}`;
  if (e.dry_run) return `<b>0 $ (simulation)</b> <span class="muted">(${detail})</span>`;
  if (native) return `Vidéo (voix incluse) <b>${usd(e.usd_total)}</b> <span class="muted">(${detail})</span>`;
  return `Voix ${usd(e.usd_voice)} + vidéo ${usd(e.usd_video)} = <b>${usd(e.usd_total)}</b> ` +
    `<span class="muted">(${detail})</span>`;
}

let _aoEstSeq = 0;
async function aoRenderV2Estimate() {
  const el = $("aoAnimEstimate");
  if (!aoAdId || !el) return;
  const seq = ++_aoEstSeq;
  try {
    const e = await api(AO_API + "/video/estimate/" + aoAdId);
    if (seq !== _aoEstSeq) return;
    el.innerHTML = "Estimation : " + aoV2EstimateHtml(e);
  } catch (e) {
    if (seq === _aoEstSeq) el.innerHTML = `<span class="muted">Estimation indisponible : ${esc(e.message)}</span>`;
  }
}

function aoVideoKeyOk(model) {
  const s = currentSettings || {};
  if (model === "omni") return s.gemini_api_key_set ? "" : "Ajoute ta clé API Google (Gemini) dans Réglages.";
  if (model === "kling") return s.openrouter_api_key_set ? "" : "Ajoute ta clé OpenRouter (Kling) dans Réglages.";
  return s.xai_api_key_set ? "" : "Ajoute ta clé xAI (Grok) dans Réglages.";
}

// v2 : modale de coût (GET /video/estimate) puis POST /video/animate (+ clip_id) ; 402 plafond.
async function aoPostAnimateV2(adId, shots, clipId, opt = {}) {
  const dryRun = currentSettings && currentSettings.dry_run;
  if (!dryRun) {
    let e = {};
    try { e = await api(AO_API + "/video/estimate/" + adId); } catch (_) { /* estimation absente */ }
    const keyMsg = aoVideoKeyOk(e.video_model || (aoAdState && aoAdState.video_model) || "grok");
    if (keyMsg) { toast(keyMsg); return null; }
    let usdLine;
    if (clipId) {
      const s = shots[0] || {};
      const secs = Number(s.clip_seconds) || 0;
      const part = Number(e.seconds_total) > 0 && secs ? (Number(e.usd_video) || 0) * secs / Number(e.seconds_total) : null;
      usdLine = part != null ? `estimé ≈ ${usd(part)} pour ${secs} s` : "coût d'un clip";
    } else {
      usdLine = `estimé ≈ ${usd(e.usd_video)} de vidéo (${usd(e.usd_total)} voix comprises) pour ~${Math.round(Number(e.seconds_total) || 0)} s`;
    }
    const model = AO_VIDEO_MODEL_LABEL[e.video_model] || e.video_model || "modèle vidéo";
    const ok = await showModal({
      title: opt.relaunch ? "Relancer la vidéo — coût réel" : clipId ? "Tester ce plan — coût réel" : "Générer les vidéos — coût réel",
      message: (opt.relaunch ? "Refait UNIQUEMENT la vidéo de ce bloc (même keyframe, même voix)"
        : clipId ? "Génère UNIQUEMENT la vidéo de ce bloc" : `Génère ${shots.length} vidéo(s) (1 appel par bloc)`) +
        ` avec ${model} — ${usdLine}. Continuer ?`,
      confirmText: opt.relaunch ? "Relancer" : clipId ? "Tester" : "Générer", cancelText: "Annuler", danger: true,
    });
    if (!ok) return null;
  }
  const post = (over) =>
    api(AO_API + "/video/animate/" + adId, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign(
        { confirm: true, confirm_over_cap: !!over },
        clipId ? { clip_id: clipId } : {},
        opt.resolution ? { resolution: opt.resolution } : {}
      )),
    });
  try {
    return await post(false);
  } catch (e) {
    if (!/plafond/i.test(e.message)) { toast(e.message); return null; }
    const ok = await showModal({
      title: "⚠ Dépassement du plafond de dépense",
      message: e.message + "\n\nConfirmer et générer malgré le plafond ?",
      confirmText: "Dépasser et générer", cancelText: "Annuler", danger: true,
    });
    if (!ok) return null;
    try { return await post(true); } catch (e2) { toast(e2.message); return null; }
  }
}

function aoRenderFinal(ad) {
  const box = $("aoFinalBox");
  if (!box) return;
  const v2 = aoIsV2(ad);
  box.classList.toggle("hidden", !v2);
  if (!v2) return;
  aoRenderFinalLinks(ad.final_url, ad.final_audio_url);
}

function aoRenderFinalLinks(finalUrl, audioUrl) {
  const links = $("aoFinalLinks");
  const bust = (u) => (u.includes("?") ? "&" : "?") + "t=" + Date.now();
  links.innerHTML =
    (finalUrl ? `<a class="btn small" href="${esc(finalUrl)}${bust(finalUrl)}" target="_blank" rel="noopener">🎬 Vidéo assemblée</a>` : "") +
    (audioUrl ? `<a class="btn small" href="${esc(audioUrl)}${bust(audioUrl)}" target="_blank" rel="noopener">🎧 Voix complète</a>` : "") +
    (!finalUrl && !audioUrl ? `<span class="muted small">Pas encore assemblée (automatique quand tous les clips sont prêts).</span>` : "");
}

if ($("aoAssembleBtn")) $("aoAssembleBtn").addEventListener("click", async () => {
  if (!aoAdId) return;
  const btn = $("aoAssembleBtn");
  btn.disabled = true;
  $("aoAssembleMsg").textContent = "⏳ Assemblage…";
  try {
    const r = await api(AO_API + "/video/assemble/" + aoAdId, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    aoRenderFinalLinks(r.final_url, r.audio_url || r.final_audio_url);
    $("aoAssembleMsg").textContent = "✓ Vidéo assemblée.";
  } catch (e) {
    $("aoAssembleMsg").textContent = "";
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
});

// ---- Bibliothèque v2 : dérive + badge « ancien pipeline » ----
function aoDriftText(c) {
  if (c.drift_score == null || c.drift_score === "") return "";
  const pct = Math.round(Number(c.drift_score) * 100);
  return isFinite(pct) ? ` · ressemblance ${pct} %` : "";
}

function aoLibAdExtras(block, ad) {
  const h2 = block.querySelector(".lib-ad-head h2");
  if (Number(ad.pipeline_version) === 1 && h2) {
    h2.insertAdjacentHTML("beforeend", ` <span class="badge ao-old-pipe" title="Pub créée avec l'ancien pipeline Omni (tours) — clips consultables">ancien pipeline</span>`);
  }
  if (Number(ad.pipeline_version) === 2 && (ad.final_url || ad.final_audio_url)) {
    const d = document.createElement("div");
    d.className = "row ao-lib-final";
    d.innerHTML =
      (ad.final_url ? `<a class="btn small" href="${esc(ad.final_url)}" target="_blank" rel="noopener">🎬 Vidéo assemblée</a>` : "") +
      (ad.final_audio_url ? `<a class="btn small" href="${esc(ad.final_audio_url)}" target="_blank" rel="noopener">🎧 Voix complète</a>` : "");
    block.appendChild(d);
  }
}

// ================================================ PRESETS CLIENT + BIBLIOTHÈQUE DE PERSONNAGES
async function aoUrlToFile(url, base) {
  const r = await fetch(url);
  if (!r.ok) throw new Error("Photo introuvable : " + url);
  const blob = await r.blob();
  const ext = { "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp" }[blob.type] || ".png";
  return new File([blob], base + ext, { type: blob.type || "image/png" });
}

// Remplace (ou ajoute) la photo de réf d'un type donné (planche1, decor…).
function aoSetRefOfKind(kind, file) {
  for (let i = aoRefsKinds.length - 1; i >= 0; i--) {
    if (aoRefsKinds[i] === kind) { aoRefsFiles.splice(i, 1); aoRefsKinds.splice(i, 1); }
  }
  aoRefsFiles.push(file);
  aoRefsKinds.push(kind);
}

function aoRefFileOfKind(kind) {
  const i = aoRefsKinds.indexOf(kind);
  return i >= 0 ? aoRefsFiles[i] : null;
}

// Fiche voix saisie pour le perso N (perso 1 = aoV*, sinon aoV{n}* s'il parle).
function aoFormVoice(n) {
  const p = n === 1 ? "aoV" : "aoV" + n;
  return $(p + "Gender") ? aoReadVoice(p) : null;
}

function aoFormBible(n) {
  const el = $("aoBibleCharacter" + n);
  const fromBox = el && !$("aoBibleBox").classList.contains("hidden") ? el.value.trim() : "";
  return fromBox || (aoPlanBible && aoPlanBible["character" + n]) || (aoPresetBible && aoPresetBible["character" + n]) || "";
}

// Crée (ou met à jour s'il vient de la bibliothèque) le personnage N du formulaire → id.
async function aoUpsertCharacterFromForm(n) {
  const name = ($("aoCharName" + n).value || "").trim() || `Perso ${n}`;
  const voice = aoFormVoice(n);   // null = perso muet (pas de fiche voix affichée)
  const fd = new FormData();
  fd.append("name", name);
  fd.append("description", ($("aoPersona" + n).value || "").trim());
  fd.append("voice_id", (voice && voice.voice_id) || "");
  fd.append("voice_profile", voice ? JSON.stringify(voice) : "");
  fd.append("bible", aoFormBible(n));
  const planche = aoRefFileOfKind("planche" + n);
  if (planche) fd.append("file", planche, planche.name);
  const id = aoCharSlotIds[n];
  let ch;
  if (id) {
    try {
      ch = await api("/api/characters/" + id, { method: "PATCH", body: fd });
    } catch (e) {
      if (!/introuvable/i.test(e.message)) throw e;
      ch = await api("/api/characters", { method: "POST", body: fd });   // supprimé entre-temps
    }
  } else {
    ch = await api("/api/characters", { method: "POST", body: fd });
  }
  aoCharSlotIds[n] = ch.id;
  if (ch.planche_url) aoPresetPlanches[n] = ch.planche_url;
  return ch;
}

async function aoLoadPresetList(selectId) {
  const sel = $("aoPresetSel");
  if (!sel) return;
  try {
    const r = await api("/api/presets");
    const keep = selectId != null ? String(selectId) : sel.value;
    sel.innerHTML = `<option value="">— Charger un preset —</option>` +
      (r.presets || []).map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
    if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
  } catch (_) { /* non bloquant */ }
}

async function aoSavePreset() {
  const sel = $("aoPresetSel");
  const cur = sel.value ? sel.options[sel.selectedIndex].textContent : "";
  const pending = showModal({
    title: "Enregistrer comme preset",
    html: `<label>Nom du preset (client) <input type="text" id="aoPresetNameIn" maxlength="80" /></label>` +
      `<p class="muted small">Enregistre les personnages (nom, description, planche, voice ID, fiche voix, bible), ` +
      `le décor, le produit, le style et les options vidéo. Même nom = mise à jour.</p>`,
    confirmText: "Enregistrer", cancelText: "Annuler",
  });
  // Contenu statique de la modale ; la saisie est remplie/lue par le DOM (jamais injectée en HTML).
  if ($("aoPresetNameIn")) { $("aoPresetNameIn").value = cur; $("aoPresetNameIn").focus(); }
  const ok = await pending;
  const name = ($("aoPresetNameIn") && $("aoPresetNameIn").value.trim()) || "";
  if (!ok) return;
  if (!name) return toast("Donne un nom au preset.");
  const msg = $("aoPresetMsg");
  msg.textContent = "⏳ Enregistrement des personnages…";
  try {
    const chars = [];
    for (const c of aoReadCharacters()) {
      const ch = await aoUpsertCharacterFromForm(c.n);
      chars.push({ n: c.n, character_id: ch.id, speaks: !!c.speaks });
    }
    const bible = {};
    [["set", "aoBibleSet"], ["product", "aoBibleProduct"], ["positions", "aoBiblePositions"]].forEach(([k, id]) => {
      const v = ($(id) && !$("aoBibleBox").classList.contains("hidden") ? $(id).value.trim() : "") ||
        (aoPlanBible && aoPlanBible[k]) || (aoPresetBible && aoPresetBible[k]) || "";
      if (v) bible[k] = v;
    });
    const data = {
      characters: chars,
      style: aoStyle(),
      ambiance: $("aoAmbiance").value.trim(),
      product: $("aoProduct").value.trim(),
      bible,
      voice_mode: aoIsV2() ? $("aoVoiceMode").value : ((aoPresetOptions && aoPresetOptions.voice_mode) || "native"),
      video_model: aoIsV2() ? $("aoVideoModel").value
        : ((aoPresetOptions && aoPresetOptions.video_model) || (currentSettings && currentSettings.avatar_video_model) || "grok"),
    };
    const fd = new FormData();
    fd.append("name", name);
    fd.append("data", JSON.stringify(data));
    ["decor", "produit", "style"].forEach((k) => {
      const f = aoRefFileOfKind(k);
      if (f) fd.append(k, f, f.name);
    });
    const p = await api("/api/presets", { method: "POST", body: fd });
    msg.textContent = `✓ Preset « ${p.name} » enregistré (${chars.length} personnage(s)).`;
    await aoLoadPresetList(p.id);
    aoLoadCharLib();
  } catch (e) {
    msg.textContent = "";
    toast(e.message);
  }
}

// Remplit le perso N depuis un personnage de la bibliothèque (nom, description, voix, planche, bible).
async function aoApplyCharacter(n, ch, speaks) {
  const row = $("aoCharRow" + n);
  if (!row) return;
  row.classList.remove("hidden");
  $("aoCharName" + n).value = ch.name || "";
  $("aoPersona" + n).value = ch.description || "";
  const vp = ch.voice_profile || {};
  const talks = speaks != null ? !!speaks : (!!ch.voice_id || $("aoCharSpeaks" + n).value === "1");
  $("aoCharSpeaks" + n).value = talks ? "1" : "0";
  aoRefreshCharsUi();
  const prefix = n === 1 ? "aoV" : "aoV" + n;
  if ($(prefix + "Gender")) aoWriteVoice(prefix, Object.assign({}, vp, { voice_id: ch.voice_id || vp.voice_id || "" }));
  aoCharSlotIds[n] = ch.id;
  if (ch.bible) {
    aoPresetBible = aoPresetBible || {};
    aoPresetBible["character" + n] = ch.bible;
  }
  if (ch.planche_url) {
    aoPresetPlanches[n] = ch.planche_url;
    try { aoSetRefOfKind("planche" + n, await aoUrlToFile(ch.planche_url, "planche" + n)); }
    catch (e) { toast(e.message); }
  }
}

async function aoLoadPreset() {
  const id = $("aoPresetSel").value;
  if (!id) return toast("Choisis un preset.");
  const msg = $("aoPresetMsg");
  msg.textContent = "⏳ Chargement du preset…";
  try {
    const p = await api("/api/presets/" + id);
    const d = p.data || {};
    // Persos : on repart des lignes du preset (les autres sont vidées).
    aoCharSlotIds = {};
    aoPresetPlanches = {};
    aoPresetBible = Object.assign({}, d.bible || {});
    for (let n = 1; n <= AO_MAX_CHARS; n++) {
      if (n > 1) {
        $("aoCharName" + n).value = "";
        $("aoPersona" + n).value = "";
        $("aoCharSpeaks" + n).value = "0";
        if (n > 2) $("aoCharRow" + n).classList.add("hidden");
      }
    }
    for (const item of d.characters || []) {
      if (item.character) await aoApplyCharacter(Number(item.n), item.character, item.speaks);
    }
    // Photos décor / produit / style du preset (les autres photos déjà déposées sont gardées).
    for (const k of ["decor", "produit", "style"]) {
      if (d[k + "_url"]) {
        try { aoSetRefOfKind(k, await aoUrlToFile(d[k + "_url"], k)); } catch (e) { toast(e.message); }
      }
    }
    if (d.style) {
      const radio = document.querySelector(`input[name="aoStyle"][value="${CSS.escape(d.style)}"]`);
      if (radio) { radio.checked = true; radio.dispatchEvent(new Event("change", { bubbles: true })); }
    }
    if (d.ambiance != null) $("aoAmbiance").value = d.ambiance;
    if (d.product != null) $("aoProduct").value = d.product;
    aoPresetOptions = {};
    if (d.video_model) aoPresetOptions.video_model = d.video_model;
    if (d.voice_mode) aoPresetOptions.voice_mode = d.voice_mode;
    aoRefreshCharsUi();
    // aoRefreshCharsUi re-rend les fiches 2..4 en gardant les valeurs : on réécrit les voix.
    for (const item of d.characters || []) {
      const ch = item.character;
      const n = Number(item.n);
      const prefix = n === 1 ? "aoV" : "aoV" + n;
      if (ch && $(prefix + "Gender"))
        aoWriteVoice(prefix, Object.assign({}, ch.voice_profile || {}, { voice_id: ch.voice_id || "" }));
    }
    aoLoadedPresetId = p.id;
    msg.textContent = `✓ Preset « ${p.name} » chargé — il ne reste qu'à coller le script.`;
    $("aoScript").focus();
  } catch (e) {
    msg.textContent = "";
    toast(e.message);
  }
}

async function aoDeletePreset() {
  const sel = $("aoPresetSel");
  if (!sel.value) return toast("Choisis un preset.");
  const ok = await showModal({
    title: "Supprimer le preset ?",
    message: `Supprimer « ${sel.options[sel.selectedIndex].textContent} » ? Les personnages restent dans la bibliothèque.`,
    confirmText: "Supprimer", cancelText: "Annuler", danger: true,
  });
  if (!ok) return;
  try {
    await api("/api/presets/" + sel.value, { method: "DELETE" });
    $("aoPresetMsg").textContent = "Preset supprimé.";
    aoLoadPresetList("");
  } catch (e) { toast(e.message); }
}

async function aoLoadCharLib() {
  const box = $("aoCharLibList");
  if (!box) return;
  let list = [];
  try { list = (await api("/api/characters")).characters || []; } catch (e) {
    box.innerHTML = `<p class="muted small">${esc(e.message)}</p>`;
    return;
  }
  if (!list.length) {
    box.innerHTML = `<p class="muted small">Aucun personnage enregistré — « Enregistrer ce perso » depuis le formulaire.</p>`;
    return;
  }
  box.innerHTML = "";
  list.forEach((ch) => {
    const card = document.createElement("div");
    card.className = "ao-charlib-card";
    card.innerHTML =
      (ch.planche_url ? `<img src="${esc(ch.planche_url)}" alt="planche ${esc(ch.name)}" loading="lazy" />`
        : `<div class="thumb empty">pas de planche</div>`) +
      `<div class="ao-charlib-info"><b>${esc(ch.name)}</b>` +
      `<span class="muted small">${ch.voice_id ? "🎙️ " + esc(ch.voice_id) : "sans voice ID"}</span></div>` +
      `<div class="row"><select class="ao-charlib-n">${[1, 2, 3, 4].map((n) => `<option value="${n}">perso ${n}</option>`).join("")}</select>` +
      `<button class="btn small ao-charlib-use" type="button">Utiliser comme perso N</button>` +
      `<button class="btn small danger-outline ao-charlib-del" type="button" title="Supprimer de la bibliothèque">🗑</button></div>`;
    card.querySelector(".ao-charlib-use").addEventListener("click", async () => {
      const n = Number(card.querySelector(".ao-charlib-n").value);
      await aoApplyCharacter(n, ch, null);
      aoRefreshCharsUi();
      const prefix = n === 1 ? "aoV" : "aoV" + n;
      if ($(prefix + "Gender")) aoWriteVoice(prefix, Object.assign({}, ch.voice_profile || {}, { voice_id: ch.voice_id || "" }));
      toast(`« ${ch.name} » → personnage ${n} ✓`);
    });
    card.querySelector(".ao-charlib-del").addEventListener("click", async () => {
      const ok = await showModal({
        title: "Supprimer ce personnage ?",
        message: `Supprimer « ${ch.name} » de la bibliothèque (et sa planche) ? Les presets qui l'utilisent ne le chargeront plus.`,
        confirmText: "Supprimer", cancelText: "Annuler", danger: true,
      });
      if (!ok) return;
      try {
        await api("/api/characters/" + ch.id, { method: "DELETE" });
        Object.keys(aoCharSlotIds).forEach((k) => { if (aoCharSlotIds[k] === ch.id) delete aoCharSlotIds[k]; });
        aoLoadCharLib();
      } catch (e) { toast(e.message); }
    });
    box.appendChild(card);
  });
}

if ($("aoPresetSaveBtn")) {
  $("aoPresetSaveBtn").addEventListener("click", aoSavePreset);
  $("aoPresetLoadBtn").addEventListener("click", aoLoadPreset);
  $("aoPresetDelBtn").addEventListener("click", aoDeletePreset);
  $("aoCharLibSaveBtn").addEventListener("click", async () => {
    const n = Number($("aoCharLibSaveN").value);
    if (!aoCharRowVisible(n) || !(($("aoCharName" + n).value || "").trim() || ($("aoPersona" + n).value || "").trim()))
      return toast(`Le personnage ${n} est vide.`);
    try {
      const ch = await aoUpsertCharacterFromForm(n);
      toast(`« ${ch.name} » enregistré dans la bibliothèque ✓`);
      aoLoadCharLib();
    } catch (e) { toast(e.message); }
  });
}

// ================================================ CLIENTS (presets) & BIBLIOTHÈQUE DE PERSONNAGES
// Communs à tous les modes. Perso au format {nom, image_ref, description, fiche_voix}.
let charLibCache = [];          // personnages de la bibliothèque (GET /api/characters)
let clientLoaded = null;        // preset client ouvert dans l'éditeur (réponse GET /api/presets/{id})
let objClientPresetId = null;   // client choisi dans le formulaire Objet animé
let objPersos = [];             // persos de la pub Objet animé [{id, nom, image_ref, description, fiche_voix, file}]
let objClientRefFiles = [];     // photos de réf ajoutées par le client (retirées si on change de client)
const CLIENT_PHOTO_KINDS = [["decor", "Décor"], ["produit", "Produit"], ["style", "Style"]];

async function fetchCharLib() {
  try { charLibCache = (await api("/api/characters")).characters || []; } catch (_) { charLibCache = []; }
  return charLibCache;
}

async function fetchPresets() {
  try { return (await api("/api/presets")).presets || []; } catch (_) { return []; }
}

function fillPresetSelect(sel, presets, emptyLabel, keep) {
  if (!sel) return;
  sel.innerHTML = `<option value="">${esc(emptyLabel)}</option>` +
    presets.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
  const k = keep != null ? String(keep) : "";
  if ([...sel.options].some((o) => o.value === k)) sel.value = k;
}

// Lie une pub à son client (persos + dossier d'export) — non bloquant.
// Renvoie une promesse : l'attendre AVANT d'afficher la pub (sinon les persos n'y sont pas encore).
function clientPresetLinkAd(adId, presetId, characterIds) {
  if (!adId) return Promise.resolve();
  const body = { preset_id: presetId || null };
  if (Array.isArray(characterIds)) body.character_ids = characterIds;
  return api("/api/ads/" + adId + "/client-preset", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }).catch((e) => toast("Client non lié à la pub : " + e.message));
}

// ---- Page « Clients & persos »
async function loadClientsPanel() {
  await fetchCharLib();
  renderCharLibGrid();
  fillPresetSelect($("clientEditSel"), await fetchPresets(), "— Nouveau client —", $("clientEditSel").value);
  await clientEditLoad($("clientEditSel").value);
}

function renderCharLibGrid() {
  const box = $("charLibGrid");
  if (!box) return;
  box.innerHTML = "";
  if (!charLibCache.length) {
    box.innerHTML = '<p class="muted small">Aucun personnage pour l’instant — crée le premier ci-dessus.</p>';
    return;
  }
  charLibCache.forEach((ch) => {
    const card = document.createElement("div");
    card.className = "ao-charlib-card";
    card.innerHTML =
      (ch.planche_url ? `<img src="${esc(ch.planche_url)}" alt="${esc(ch.name)}" loading="lazy" />`
        : `<div class="thumb empty">pas d'image</div>`) +
      `<div class="ao-charlib-info"><b>${esc(ch.name)}</b>` +
      (ch.description ? `<span class="muted small">${esc(ch.description)}</span>` : "") +
      (ch.fiche_voix ? `<span class="muted small">🎙️ ${esc(ch.fiche_voix)}</span>` : "") + `</div>` +
      `<div class="row"><button class="btn small" data-act="edit" type="button">✏️ Modifier</button>` +
      `<button class="btn small danger-outline" data-act="del" type="button" title="Supprimer">🗑</button></div>`;
    card.querySelector('[data-act="edit"]').addEventListener("click", () => charEditFill(ch));
    card.querySelector('[data-act="del"]').addEventListener("click", async () => {
      const ok = await showModal({
        title: "Supprimer ce personnage ?",
        message: `Supprimer « ${ch.name} » de la bibliothèque (et son image) ? Les clients qui l'utilisent ne le chargeront plus.`,
        confirmText: "Supprimer", cancelText: "Annuler", danger: true,
      });
      if (!ok) return;
      try {
        await api("/api/characters/" + ch.id, { method: "DELETE" });
        if (String($("charEditId").value) === String(ch.id)) charEditFill(null);
        loadClientsPanel();
      } catch (e) { toast(e.message); }
    });
    box.appendChild(card);
  });
}

function charEditFill(ch) {
  $("charEditId").value = ch ? ch.id : "";
  $("charEditName").value = ch ? ch.name || "" : "";
  $("charEditDesc").value = ch ? ch.description || "" : "";
  $("charEditVoice").value = ch ? ch.fiche_voix || "" : "";
  $("charEditFile").value = "";
  $("charEditMsg").textContent = ch ? `Modification de « ${ch.name} »` : "";
  if (ch) $("charEditName").focus();
}

async function clientEditLoad(id) {
  clientLoaded = null;
  if (id) {
    try { clientLoaded = await api("/api/presets/" + id); } catch (e) { toast(e.message); }
  }
  const d = (clientLoaded && clientLoaded.data) || {};
  $("clientName").value = clientLoaded ? clientLoaded.name : "";
  $("clientExportDir").value = d.export_dir || "";
  $("clientProduct").value = d.product || "";
  $("clientStyle").value = ["realiste", "3d"].includes(d.style) ? d.style : "";
  $("clientAmbiance").value = d.ambiance || "";
  $("clientPersona").value = d.persona || "";
  const ph = $("clientPhotos");
  ph.innerHTML = "";
  CLIENT_PHOTO_KINDS.forEach(([k, label]) => {
    const cell = document.createElement("div");
    cell.className = "client-photo";
    cell.innerHTML = `<label>Photo ${esc(label)} <input type="file" accept="image/*" id="clientPhoto_${k}" /></label>` +
      (d[k + "_url"] ? `<div class="client-photo-cur"><img src="${esc(d[k + "_url"])}" alt="${esc(label)}" />` +
        `<label class="check"><input type="checkbox" id="clientPhotoKeep_${k}" checked /> garder</label></div>` : "");
    ph.appendChild(cell);
  });
  const cur = {};
  (d.characters || []).forEach((c) => { cur[Number(c.n)] = c; });
  const box = $("clientChars");
  box.innerHTML = "";
  for (let n = 1; n <= 4; n++) {
    const row = document.createElement("div");
    row.className = "row";
    const opts = `<option value="">—</option>` +
      charLibCache.map((ch) => `<option value="${esc(ch.id)}">${esc(ch.name)}</option>`).join("");
    row.innerHTML = `<label class="inline">Perso ${n} <select id="clientChar${n}">${opts}</select></label>` +
      `<label class="check"><input type="checkbox" id="clientCharSpeaks${n}" /> parle</label>`;
    box.appendChild(row);
    const c = cur[n];
    if (c) $("clientChar" + n).value = String(c.character_id);
    $("clientCharSpeaks" + n).checked = c ? c.speaks !== false : n === 1;
    // Choisir un perso le fait parler par défaut (décochable) ; le retirer décoche.
    $("clientChar" + n).addEventListener("change", (ev) => {
      $("clientCharSpeaks" + n).checked = !!ev.target.value;
    });
  }
  $("clientDelBtn").disabled = !clientLoaded;
  // Fiche produit du client (produit_refs.js) : copiée dans chaque pub à l'application du client.
  if (window.renderProductSheetEditor)
    window.renderProductSheetEditor($("clientProductSheet"), clientLoaded ? "/api/presets/" + clientLoaded.id : null);
}

async function clientSave() {
  const name = $("clientName").value.trim();
  if (!name) return toast("Donne un nom au client.");
  const base = Object.assign({}, (clientLoaded && clientLoaded.data) || {});
  const characters = [];
  for (let n = 1; n <= 4; n++) {
    const id = $("clientChar" + n).value;
    if (id) characters.push({ n, character_id: Number(id), speaks: $("clientCharSpeaks" + n).checked });
  }
  const data = Object.assign(base, {
    characters,
    export_dir: $("clientExportDir").value.trim(),
    product: $("clientProduct").value.trim(),
    style: $("clientStyle").value,
    ambiance: $("clientAmbiance").value.trim(),
    persona: $("clientPersona").value.trim(),
  });
  const fd = new FormData();
  fd.append("name", name);
  CLIENT_PHOTO_KINDS.forEach(([k]) => {
    const input = $("clientPhoto_" + k);
    const keep = $("clientPhotoKeep_" + k);
    if (input && input.files && input.files[0]) fd.append(k, input.files[0], input.files[0].name);
    if (!(keep && keep.checked)) delete data[k + "_url"];   // décoché / absent → photo retirée
  });
  fd.append("data", JSON.stringify(data));
  try {
    const p = await api("/api/presets", { method: "POST", body: fd });
    $("clientMsg").textContent = `✓ Client « ${p.name} » enregistré (${characters.length} perso(s)).`;
    fillPresetSelect($("clientEditSel"), await fetchPresets(), "— Nouveau client —", p.id);
    await clientEditLoad(String(p.id));
    aoLoadPresetList();
    objClientRefresh();
  } catch (e) { toast(e.message); }
}

if ($("charEditSave")) {
  $("refreshClients").addEventListener("click", loadClientsPanel);
  $("charEditReset").addEventListener("click", () => charEditFill(null));
  $("charEditSave").addEventListener("click", async () => {
    const name = $("charEditName").value.trim();
    if (!name) return toast("Donne un nom au personnage.");
    const fd = new FormData();
    fd.append("name", name);
    fd.append("description", $("charEditDesc").value.trim());
    fd.append("fiche_voix", $("charEditVoice").value.trim());
    const f = $("charEditFile").files && $("charEditFile").files[0];
    if (f) fd.append("file", f, f.name);
    const id = $("charEditId").value;
    try {
      const ch = await api("/api/characters" + (id ? "/" + id : ""), { method: id ? "PATCH" : "POST", body: fd });
      charEditFill(null);
      $("charEditMsg").textContent = `✓ « ${ch.name} » enregistré.`;
      await loadClientsPanel();
      aoLoadCharLib();
      objClientRefresh();
    } catch (e) { toast(e.message); }
  });
  $("clientEditSel").addEventListener("change", (ev) => { $("clientMsg").textContent = ""; clientEditLoad(ev.target.value); });
  $("clientSaveBtn").addEventListener("click", clientSave);
  $("clientDelBtn").addEventListener("click", async () => {
    if (!clientLoaded) return;
    const ok = await showModal({
      title: "Supprimer ce client ?",
      message: `Supprimer « ${clientLoaded.name} » ? Ses personnages restent dans la bibliothèque.`,
      confirmText: "Supprimer", cancelText: "Annuler", danger: true,
    });
    if (!ok) return;
    try {
      await api("/api/presets/" + clientLoaded.id, { method: "DELETE" });
      if (String(objClientPresetId) === String(clientLoaded.id)) objClientPresetId = null;
      if (String(aoLoadedPresetId) === String(clientLoaded.id)) aoLoadedPresetId = null;
      $("clientEditSel").value = "";
      $("clientMsg").textContent = "Client supprimé.";
      await loadClientsPanel();
      aoLoadPresetList("");
      objClientRefresh();
    } catch (e) { toast(e.message); }
  });
}

// ---- Objet animé : sélecteur « Client » + persos de la bibliothèque
async function objClientRefresh() {
  if (!$("objClientSel")) return;
  fillPresetSelect($("objClientSel"), await fetchPresets(), "— Aucun client —", objClientPresetId);
  await fetchCharLib();
  $("objCharLibSel").innerHTML = `<option value="">— Choisir —</option>` +
    charLibCache.map((ch) => `<option value="${esc(ch.id)}">${esc(ch.name)}</option>`).join("");
}

function objRemoveRefFile(file) {
  const i = objRefsFiles.indexOf(file);
  if (i >= 0) { objRefsFiles.splice(i, 1); objRefsKinds.splice(i, 1); }
}

function objAddRefFile(file, kind) {
  objRefsFiles.push(file);
  objRefsKinds.push(kind);
}

async function objAddPerso(p) {
  if (objPersos.some((x) => String(x.id) === String(p.id))) return;
  const perso = Object.assign({}, p, { file: null });
  if (p.image_ref) {
    try {
      perso.file = await aoUrlToFile(p.image_ref, "perso_" + p.id);
      objAddRefFile(perso.file, "visage");   // image du perso = réf « Visage » (apparence fidèle)
    } catch (e) { toast(e.message); }
  }
  objPersos.push(perso);
}

function renderObjPersos() {
  const box = $("objPersosList");
  if (!box) return;
  box.innerHTML = "";
  objPersos.forEach((p, idx) => {
    const chip = document.createElement("span");
    chip.className = "ref-chip on";
    chip.title = [p.description, p.fiche_voix ? "Voix : " + p.fiche_voix : ""].filter(Boolean).join(" — ");
    chip.textContent = "👤 " + (p.nom || "Perso") + " ";
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "ref-remove-inline";
    rm.title = "Retirer ce perso de la pub";
    rm.textContent = "×";
    rm.addEventListener("click", () => {
      if (p.file) objRemoveRefFile(p.file);
      objPersos.splice(idx, 1);
      renderObjPersos();
      renderObjRefs();
    });
    chip.appendChild(rm);
    box.appendChild(chip);
  });
}

async function objApplyClient(id) {
  const msg = $("objClientMsg");
  // On retire ce que l'ancien client avait ajouté (photos + persos), le reste du formulaire est gardé.
  objClientRefFiles.forEach(objRemoveRefFile);
  objClientRefFiles = [];
  objPersos.forEach((p) => { if (p.file) objRemoveRefFile(p.file); });
  objPersos = [];
  objClientPresetId = null;
  if (!id) {
    msg.textContent = "";
    renderObjRefs();
    renderObjPersos();
    return;
  }
  msg.textContent = "⏳ Chargement du client…";
  try {
    const p = await api("/api/presets/" + id);
    const d = p.data || {};
    if (d.product) $("objProduct").value = d.product;
    if (d.ambiance) $("objAmbiance").value = d.ambiance;
    if (d.persona) $("objPersona").value = d.persona;
    for (const [k] of CLIENT_PHOTO_KINDS) {
      if (!d[k + "_url"]) continue;
      try {
        const f = await aoUrlToFile(d[k + "_url"], "client_" + k);
        objAddRefFile(f, k);
        objClientRefFiles.push(f);
      } catch (e) { toast(e.message); }
    }
    const items = (d.characters || []).slice().sort((a, b) => Number(a.n) - Number(b.n));
    for (const item of items) {
      if (item.perso) await objAddPerso(Object.assign({ id: item.character_id }, item.perso));
    }
    objClientPresetId = p.id;
    msg.textContent = `✓ Client « ${p.name} » chargé (${objPersos.length} perso(s))` +
      (d.export_dir ? ` · export : ${d.export_dir}` : "") + " — il ne reste qu'à coller le script.";
    $("objScript").focus();
  } catch (e) {
    msg.textContent = "";
    toast(e.message);
  }
  renderObjRefs();
  renderObjPersos();
}

if ($("objClientSel")) {
  $("objClientSel").addEventListener("change", (ev) => objApplyClient(ev.target.value));
  $("objCharLibSel").addEventListener("change", async (ev) => {
    const ch = charLibCache.find((c) => String(c.id) === ev.target.value);
    ev.target.value = "";
    if (!ch) return;
    await objAddPerso({ id: ch.id, nom: ch.name, image_ref: ch.planche_url, description: ch.description, fiche_voix: ch.fiche_voix });
    renderObjRefs();
    renderObjPersos();
    toast(`« ${ch.name} » ajouté à la pub ✓`);
  });
  $("objClientManageBtn").addEventListener("click", () => gotoSection("clients"));
  objClientRefresh();
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
