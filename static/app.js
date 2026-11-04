/* VaaniTTS front-end — plain JS, no build step. */

const $ = (id) => document.getElementById(id);

const els = {
  text: $("text"),
  charCount: $("charCount"),
  wordCount: $("wordCount"),
  estTime: $("estTime"),
  charMeter: $("charMeter"),
  voiceSelect: $("voiceSelect"),
  rate: $("rate"),
  rateLabel: $("rateLabel"),
  convertBtn: $("convertBtn"),
  convertLabel: $("convertLabel"),
  progressWrap: $("progressWrap"),
  progressBar: $("progressBar"),
  progressText: $("progressText"),
  cancelBtn: $("cancelBtn"),
  resultCard: $("resultCard"),
  player: $("player"),
  downloadBtn: $("downloadBtn"),
  resultMeta: $("resultMeta"),
  againBtn: $("againBtn"),
  historyCard: $("historyCard"),
  historyList: $("historyList"),
  refreshHistory: $("refreshHistory"),
  engineBadge: $("engineBadge"),
  engineName: $("engineName"),
  setupBanner: $("setupBanner"),
  setupText: $("setupText"),
  dismissBanner: $("dismissBanner"),
  dropZone: $("dropZone"),
  fileInput: $("fileInput"),
  sampleBtn: $("sampleBtn"),
  clearBtn: $("clearBtn"),
  toasts: $("toasts"),
};

const state = {
  config: null,
  maxChars: 50000,
  busy: false,
  jobId: null,
  pollTimer: null,
};

const SAMPLE = `नमस्ते! यह VaaniTTS है — आपके हिंदी और English टेक्स्ट को natural speech में बदलने का एक आसान तरीका।

Paste up to 50,000 characters at a time. Whether it's a YouTube voice-over, a story, study notes, or a full article — the app splits your text into sentences, converts every part, and gives you one downloadable audio file.

आप नीचे दिए गए controls से voice चुन सकते हैं और speed adjust कर सकते हैं। Hinglish भी काम करता है — जैसे "आज का topic है machine learning ke basics". Enjoy!`;

/* ── Helpers ─────────────────────────────────────────────── */

function toast(message, kind = "") {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  els.toasts.appendChild(node);
  setTimeout(() => {
    node.style.transition = "opacity .25s ease, transform .25s ease";
    node.style.opacity = "0";
    node.style.transform = "translateY(6px)";
    setTimeout(() => node.remove(), 260);
  }, 5200);
}

function formatClock(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function estimateSeconds(chars, rate) {
  // Hindi/English narration averages roughly 14 characters per second.
  return (chars / 14) / Math.max(0.5, rate);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function providerLabel(provider) {
  if (provider === "azure") return `Azure Speech${state.config?.region ? " · " + state.config.region : ""}`;
  if (provider === "sarvam") return `Sarvam AI${state.config?.model ? " · " + state.config.model : ""}`;
  if (provider === "mock") return "Test mode";
  return "Not configured";
}

/* ── Editor ──────────────────────────────────────────────── */

function updateStats() {
  const text = els.text.value;
  const chars = text.length;
  const words = (text.trim().match(/\S+/g) || []).length;
  const rate = Number(els.rate.value);

  els.charCount.textContent = chars.toLocaleString();
  els.charCount.classList.toggle("over", chars > state.maxChars);
  els.wordCount.textContent = words.toLocaleString();
  els.estTime.textContent = formatClock(estimateSeconds(chars, rate));

  const pct = Math.min(100, (chars / state.maxChars) * 100);
  els.charMeter.style.width = pct + "%";
  els.charMeter.classList.toggle("warn", pct > 90);

  localStorage.setItem("vaani.draft", text);
  localStorage.setItem("vaani.voice", els.voiceSelect.value || "");
}

function setText(value) {
  els.text.value = value;
  updateStats();
}

function loadFile(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    let value = String(reader.result || "");
    if (value.length > state.maxChars) {
      value = value.slice(0, state.maxChars);
      toast(`That file is longer than ${state.maxChars.toLocaleString()} characters — trimmed.`, "error");
    }
    setText(value);
    toast(`Loaded ${file.name}`, "ok");
  };
  reader.onerror = () => toast("Could not read that file.", "error");
  reader.readAsText(file);
}

/* ── Config / voices ────────────────────────────────────── */

async function loadConfig() {
  const config = await fetch("/api/config").then((r) => r.json());
  state.config = config;
  state.maxChars = config.max_chars || 50000;
  els.text.maxLength = state.maxChars;

  els.engineBadge.classList.toggle("ok", config.configured);
  els.engineBadge.classList.toggle("bad", !config.configured);
  els.engineName.textContent = providerLabel(config.provider);

  if (!config.configured) {
    els.setupBanner.hidden = false;
    els.setupText.textContent = config.setup || "";
  }

  els.voiceSelect.innerHTML = "";
  const groups = new Map();
  for (const voice of config.voices) {
    if (!groups.has(voice.group)) groups.set(voice.group, []);
    groups.get(voice.group).push(voice);
  }
  for (const [group, voices] of groups) {
    const optgroup = document.createElement("optgroup");
    optgroup.label = group;
    for (const voice of voices) {
      const option = document.createElement("option");
      option.value = voice.id;
      option.textContent = `${voice.label} · ${voice.gender}`;
      optgroup.appendChild(option);
    }
    els.voiceSelect.appendChild(optgroup);
  }

  const saved = localStorage.getItem("vaani.voice");
  const ids = config.voices.map((v) => v.id);
  const preferred = ids.includes("en-US-AvaMultilingualNeural") ? "en-US-AvaMultilingualNeural" : ids[0];
  els.voiceSelect.value = ids.includes(saved) ? saved : preferred || "";

  if (!config.configured) {
    els.text.disabled = false;
    els.convertBtn.disabled = true;
    els.convertLabel.textContent = "Engine not configured";
  }
}

/* ── Conversion ─────────────────────────────────────────── */

function setBusy(busy) {
  state.busy = busy;
  els.convertBtn.disabled = busy || !state.config?.configured;
  els.convertBtn.querySelector("svg").style.display = busy ? "none" : "";
  els.convertLabel.textContent = busy ? "Generating audio…" : "Convert to speech";
  els.text.readOnly = busy;
  els.voiceSelect.disabled = busy;
  els.rate.disabled = busy;
  els.sampleBtn.disabled = busy;
  els.clearBtn.disabled = busy;
}

async function convert() {
  if (state.busy) return;
  const text = els.text.value.trim();
  if (!text) {
    toast("Paste some text first.", "error");
    els.text.focus();
    return;
  }
  if (text.length > state.maxChars) {
    toast(`Text is ${text.length.toLocaleString()} characters — the limit is ${state.maxChars.toLocaleString()}.`, "error");
    return;
  }
  if (!state.config?.configured) {
    toast("Add an API key to .env and restart the server.", "error");
    return;
  }

  setBusy(true);
  els.resultCard.hidden = true;
  els.progressWrap.hidden = false;
  els.progressBar.style.width = "0%";
  els.progressText.textContent = "Starting…";

  try {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        voice: els.voiceSelect.value,
        rate: Number(els.rate.value),
      }),
    });
    const job = await res.json();
    if (!res.ok) throw new Error(job.error || "Could not start the conversion.");
    state.jobId = job.id;
    pollJob(job);
  } catch (error) {
    fail(error.message);
    setBusy(false);
  }
}

function pollJob(initial) {
  clearTimeout(state.pollTimer);
  const tick = async () => {
    if (!state.jobId) return;
    try {
      const res = await fetch(`/api/jobs/${state.jobId}`);
      const job = await res.json();
      if (!res.ok) throw new Error(job.error || "Lost track of the job.");
      renderProgress(job);

      if (job.status === "done") return finish(job);
      if (job.status === "error") return fail(job.error || "Synthesis failed.");
      if (job.status === "cancelled") return cancelDone();

      state.pollTimer = setTimeout(tick, 900);
    } catch (error) {
      fail(error.message);
    }
  };
  renderProgress(initial);
  state.pollTimer = setTimeout(tick, 700);
}

function renderProgress(job) {
  const percent = job.percent || 0;
  els.progressBar.style.width = percent + "%";
  const parts = [`${job.done} / ${job.total} parts`, `${percent}%`];
  if (job.eta > 0) parts.push(`~${formatClock(job.eta)} left`);
  if (job.elapsed > 0) parts.push(`${formatClock(job.elapsed)} elapsed`);
  els.progressText.textContent = parts.join(" · ");
}

function finish(job) {
  clearTimeout(state.pollTimer);
  state.pollTimer = null;
  state.jobId = null;
  els.progressBar.style.width = "100%";
  els.progressText.textContent = `Done in ${formatClock(job.elapsed)} · ${job.total} parts`;
  els.resultCard.hidden = false;
  const src = `/api/jobs/${job.id}/audio?v=${Date.now()}`;
  els.player.src = src;
  els.downloadBtn.href = `/api/jobs/${job.id}/audio?download=1`;
  els.downloadBtn.setAttribute("download", `vaani-${job.id}.mp3`);
  els.resultMeta.textContent = `${job.chars.toLocaleString()} chars · ${job.voice.label}`;
  setBusy(false);
  els.progressWrap.hidden = false;
  toast("Audio ready 🎧", "ok");
  loadHistory();
  els.resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function fail(message) {
  clearTimeout(state.pollTimer);
  state.pollTimer = null;
  state.jobId = null;
  els.progressWrap.hidden = true;
  setBusy(false);
  toast(message || "Something went wrong.", "error");
}

function cancelDone() {
  state.jobId = null;
  els.progressWrap.hidden = true;
  setBusy(false);
  toast("Conversion cancelled.");
}

async function cancel() {
  if (!state.jobId) return;
  try {
    await fetch(`/api/jobs/${state.jobId}/cancel`, { method: "POST" });
  } catch {
    /* ignore — polling will notice */
  }
  cancelDone();
}

/* ── History ────────────────────────────────────────────── */

const ICONS = {
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m-9 0 1 14h8l1-14"/></svg>',
};

async function loadHistory() {
  try {
    const { items } = await fetch("/api/history").then((r) => r.json());
    els.historyCard.hidden = items.length === 0;

    if (!items.length) {
      els.historyList.innerHTML = '<li class="history-empty">Your finished conversions will appear here.</li>';
      return;
    }

    els.historyList.innerHTML = items.map((item) => {
      const when = new Date(item.created_at).toLocaleString(undefined, {
        day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
      });
      return `
        <li class="history-item" data-id="${escapeHtml(item.id)}">
          <div class="history-main">
            <div class="history-title">${escapeHtml(item.preview || "(no preview)")}</div>
            <div class="history-meta">
              <span>${when}</span>
              <span>${Number(item.chars || 0).toLocaleString()} chars</span>
              <span>${escapeHtml(item.voice?.label || "")}</span>
              <span>${escapeHtml(providerLabel(item.provider))}</span>
            </div>
          </div>
          <div class="history-actions">
            <button class="icon-btn" data-action="play" title="Play" aria-label="Play">${ICONS.play}</button>
            <a class="icon-btn" href="/api/jobs/${escapeHtml(item.id)}/audio?download=1" download title="Download" aria-label="Download">${ICONS.download}</a>
            <button class="icon-btn" data-action="delete" title="Delete" aria-label="Delete">${ICONS.trash}</button>
          </div>
        </li>`;
    }).join("");
  } catch {
    els.historyCard.hidden = true;
  }
}

async function onHistoryClick(event) {
  const item = event.target.closest(".history-item");
  if (!item) return;
  const id = item.dataset.id;
  const action = event.target.closest("[data-action]")?.dataset.action;

  if (action === "play") {
    els.resultCard.hidden = false;
    els.player.src = `/api/jobs/${id}/audio?v=${Date.now()}`;
    els.downloadBtn.href = `/api/jobs/${id}/audio?download=1`;
    els.resultMeta.textContent = "Saved conversion";
    els.resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
    els.player.play().catch(() => {});
  }

  if (action === "delete") {
    item.style.opacity = "0.4";
    await fetch(`/api/jobs/${id}`, { method: "DELETE" }).catch(() => {});
    loadHistory();
  }
}

/* ── Wiring ─────────────────────────────────────────────── */

function wire() {
  els.text.addEventListener("input", updateStats);
  els.rate.addEventListener("input", () => {
    els.rateLabel.textContent = Number(els.rate.value).toFixed(2).replace(/0$/, "") + "×";
    updateStats();
  });
  els.voiceSelect.addEventListener("change", updateStats);
  els.convertBtn.addEventListener("click", convert);
  els.cancelBtn.addEventListener("click", cancel);
  els.clearBtn.addEventListener("click", () => {
    setText("");
    els.text.focus();
  });
  els.sampleBtn.addEventListener("click", () => {
    setText(SAMPLE);
    toast("Sample loaded — try converting it.", "ok");
  });
  els.againBtn.addEventListener("click", () => {
    els.text.scrollIntoView({ behavior: "smooth", block: "center" });
    els.text.focus();
  });
  els.refreshHistory.addEventListener("click", loadHistory);
  els.historyList.addEventListener("click", onHistoryClick);
  els.dismissBanner.addEventListener("click", () => (els.setupBanner.hidden = true));

  els.fileInput.addEventListener("change", (event) => loadFile(event.target.files[0]));

  ["dragenter", "dragover"].forEach((type) => {
    els.dropZone.addEventListener(type, (event) => {
      event.preventDefault();
      els.dropZone.classList.add("drag");
    });
  });
  ["dragleave", "drop"].forEach((type) => {
    els.dropZone.addEventListener(type, (event) => {
      event.preventDefault();
      els.dropZone.classList.remove("drag");
    });
  });
  els.dropZone.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    loadFile(file);
  });

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      convert();
    }
  });

  window.addEventListener("beforeunload", (event) => {
    if (state.busy) event.preventDefault();
  });
}

async function init() {
  wire();
  const draft = localStorage.getItem("vaani.draft");
  if (draft) els.text.value = draft;
  try {
    await loadConfig();
  } catch (error) {
    els.engineBadge.classList.add("bad");
    els.engineName.textContent = "Server offline";
    toast("Could not reach the server. Is server.py running?", "error");
  }
  updateStats();
  loadHistory();
}

init();
