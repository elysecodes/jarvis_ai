/* ==========================================================================
   J.A.R.V.I.S interface logic
   Talks to the local Python server only (127.0.0.1). The AI, the allowlist and
   every safety check stay in Python; this file is presentation + transport.
   ========================================================================== */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);

  const app = {
    view: "dashboard",
    /** idle | listening | processing | speaking | offline */
    assistant: "idle",
    micActive: false,
    listeningOnce: false,
    wakeMode: false,
    tts: localStorage.getItem("jarvis.tts") !== "off",
    inFlight: false,
    turns: 0,
    started: Date.now(),
    info: null,
    cpuHist: [],
    ramHist: [],
    confirmTimer: null,
    toastTimer: null,
  };

  const LABELS = {
    idle: "READY FOR COMMAND",
    listening: "LISTENING…",
    processing: "PROCESSING…",
    speaking: "SPEAKING…",
    offline: "SYSTEM ONLINE · AI OFFLINE",
  };

  /* ------------------------------------------------------------------ utils */
  const api = {
    async get(path) {
      const res = await fetch(path, { cache: "no-store" });
      if (!res.ok) throw new Error(`${res.status}`);
      return res.json();
    },
    async post(path, body) {
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Jarvis-Client": "1" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      return data;
    },
  };

  function toast(text, warn = false) {
    const box = $("toast");
    box.textContent = text;
    box.classList.toggle("is-warn", warn);
    box.hidden = false;
    clearTimeout(app.toastTimer);
    app.toastTimer = setTimeout(() => { box.hidden = true; }, 4200);
  }

  function setAssistantState(name, note) {
    app.assistant = name;
    const label = note || LABELS[name] || name;
    const core = $("coreStatus");
    core.textContent = label;
    core.dataset.state = name === "idle" ? "idle" : name;
    const mini = $("composerState");
    mini.textContent = name === "idle" ? "READY" : name.toUpperCase();
    mini.dataset.state = name;
  }

  function clock() {
    const now = new Date();
    $("clockTime").textContent = now.toLocaleTimeString([], { hour12: false });
    $("clockDate").textContent = now
      .toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short", year: "numeric" })
      .toUpperCase();

    // Session timer: mm:ss, growing to hh:mm:ss after an hour.
    const elapsed = Math.max(0, Math.floor((Date.now() - app.started) / 1000));
    const hours = Math.floor(elapsed / 3600);
    const minutes = Math.floor((elapsed % 3600) / 60);
    const seconds = elapsed % 60;
    const parts = hours > 0 ? [hours, minutes, seconds] : [minutes, seconds];
    $("sessionTime").textContent = parts.map((n) => String(n).padStart(2, "0")).join(":");
  }
  /* ------------------------------------------------------- holographic core */
  const core = {
    canvas: $("coreCanvas"),
    ctx: null,
    dpr: 1,
    particles: [],
    last: 0,
    sweep: 0,
  };

  function initCore() {
    const ctx = core.canvas.getContext("2d");
    if (!ctx) return;
    core.ctx = ctx;
    core.particles = Array.from({ length: 54 }, () => ({
      angle: Math.random() * Math.PI * 2,
      radius: 0.55 + Math.random() * 0.42,
      speed: (Math.random() - 0.5) * 0.00016,
      size: 0.6 + Math.random() * 1.8,
      alpha: 0.25 + Math.random() * 0.6,
    }));
    resizeCore();
    window.addEventListener("resize", resizeCore, { passive: true });
  }

  function resizeCore() {
    if (!core.ctx) return;
    const rect = core.canvas.getBoundingClientRect();
    core.dpr = Math.min(window.devicePixelRatio || 1, 2);
    core.canvas.width = Math.max(1, Math.round(rect.width * core.dpr));
    core.canvas.height = Math.max(1, Math.round(rect.height * core.dpr));
  }

  const STATE_COLORS = {
    idle: [34, 211, 238],
    listening: [125, 211, 252],
    processing: [96, 165, 250],
    speaking: [165, 243, 252],
    offline: [251, 191, 36],
  };

  function level() {
    // 0..1 live input level while the mic is open, otherwise a calm idle pulse.
    if (mic.level > 0.02) return mic.level;
    return 0;
  }

  function drawCore(now) {
    if (!core.ctx) return;
    const ctx = core.ctx;
    const w = core.canvas.width;
    const h = core.canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const R = Math.min(w, h) * 0.44;
    const [r, g, b] = STATE_COLORS[app.assistant] || STATE_COLORS.idle;
    const t = now / 1000;
    const energy = app.assistant === "listening" || app.assistant === "speaking" ? level() : 0;
    const pulse = 0.5 + 0.5 * Math.sin(t * 1.7);

    ctx.clearRect(0, 0, w, h);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.translate(cx, cy);

    // --- outer tick ring -------------------------------------------------
    const ticks = 120;
    for (let i = 0; i < ticks; i++) {
      const a = (i / ticks) * Math.PI * 2 + t * 0.08;
      const major = i % 10 === 0;
      const len = major ? R * 0.055 : R * 0.026;
      ctx.strokeStyle = `rgba(${r},${g},${b},${major ? 0.5 : 0.2})`;
      ctx.lineWidth = major ? 1.6 * core.dpr : 1 * core.dpr;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * R, Math.sin(a) * R);
      ctx.lineTo(Math.cos(a) * (R - len), Math.sin(a) * (R - len));
      ctx.stroke();
    }

    // --- rotating dashed rings -------------------------------------------
    const rings = [
      { rad: 0.94, speed: 0.12, dash: [18, 26], width: 1.8, alpha: 0.55 },
      { rad: 0.86, speed: -0.2, dash: [6, 14], width: 1.2, alpha: 0.45 },
      { rad: 0.72, speed: 0.34, dash: [40, 18, 8, 18], width: 1, alpha: 0.35 },
    ];
    rings.forEach((ring) => {
      ctx.save();
      ctx.rotate(t * ring.speed);
      ctx.setLineDash(ring.dash);
      ctx.strokeStyle = `rgba(${r},${g},${b},${ring.alpha})`;
      ctx.lineWidth = ring.width * core.dpr;
      ctx.beginPath();
      ctx.arc(0, 0, R * ring.rad, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    });

    // --- segmented inner arc (counter-rotating) --------------------------
    const segs = 28;
    const gap = 0.06;
    for (let i = 0; i < segs; i++) {
      const start = (i / segs) * Math.PI * 2 - t * 0.45;
      const end = start + (Math.PI * 2) / segs - gap;
      const hot = (i + Math.floor(t * 14)) % 7 === 0;
      ctx.strokeStyle = `rgba(${r},${g},${b},${hot ? 0.75 : 0.22})`;
      ctx.lineWidth = (hot ? 2.4 : 1.4) * core.dpr;
      ctx.beginPath();
      ctx.arc(0, 0, R * 0.63, start, end);
      ctx.stroke();
    }

    // --- radar sweep ------------------------------------------------------
    const sweepAngle = t * 1.15;
    const sweepGrad = ctx.createConicGradient
      ? ctx.createConicGradient(sweepAngle, 0, 0)
      : null;
    if (sweepGrad) {
      sweepGrad.addColorStop(0, `rgba(${r},${g},${b},0.30)`);
      sweepGrad.addColorStop(0.16, `rgba(${r},${g},${b},0)`);
      sweepGrad.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = sweepGrad;
      ctx.beginPath();
      ctx.arc(0, 0, R * 0.98, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.strokeStyle = `rgba(${r},${g},${b},0.55)`;
    ctx.lineWidth = 1.2 * core.dpr;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(Math.cos(sweepAngle) * R * 0.98, Math.sin(sweepAngle) * R * 0.98);
    ctx.stroke();

    // --- sound-wave ring (real mic level while listening) ----------------
    if (energy > 0.015) {
      const bars = 72;
      for (let i = 0; i < bars; i++) {
        const a = (i / bars) * Math.PI * 2;
        const wobble = 0.55 + 0.45 * Math.sin(t * 6 + i * 0.55);
        const len = R * (0.06 + energy * 0.30 * wobble);
        ctx.strokeStyle = `rgba(${r},${g},${b},${0.25 + energy * 0.6})`;
        ctx.lineWidth = 1.8 * core.dpr;
        ctx.beginPath();
        ctx.moveTo(Math.cos(a) * R * 0.55, Math.sin(a) * R * 0.55);
        ctx.lineTo(Math.cos(a) * (R * 0.55 + len), Math.sin(a) * (R * 0.55 + len));
        ctx.stroke();
      }
    }

    // --- orbit particles --------------------------------------------------
    core.particles.forEach((p) => {
      p.angle += p.speed * 16;
      const rad = R * p.radius * (1 + 0.012 * Math.sin(t * 2 + p.angle * 3));
      const x = Math.cos(p.angle) * rad;
      const y = Math.sin(p.angle) * rad;
      ctx.fillStyle = `rgba(${r},${g},${b},${p.alpha * (0.55 + 0.45 * pulse)})`;
      ctx.beginPath();
      ctx.arc(x, y, p.size * core.dpr, 0, Math.PI * 2);
      ctx.fill();
    });

    // --- glowing core -----------------------------------------------------
    const coreR = R * (0.30 + 0.022 * pulse + energy * 0.06);
    const glow = ctx.createRadialGradient(0, 0, coreR * 0.15, 0, 0, coreR * 2.5);
    glow.addColorStop(0, `rgba(255,255,255,${0.55 + 0.12 * pulse})`);
    glow.addColorStop(0.28, `rgba(${r},${g},${b},0.55)`);
    glow.addColorStop(0.62, `rgba(${r},${g},${b},0.12)`);
    glow.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(0, 0, coreR * 2.5, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "rgba(4,16,26,0.92)";
    ctx.beginPath();
    ctx.arc(0, 0, coreR, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = `rgba(${r},${g},${b},0.9)`;
    ctx.lineWidth = 1.6 * core.dpr;
    ctx.beginPath();
    ctx.arc(0, 0, coreR, 0, Math.PI * 2);
    ctx.stroke();

    // inner scanning line inside the core
    ctx.save();
    ctx.beginPath();
    ctx.arc(0, 0, coreR * 0.92, 0, Math.PI * 2);
    ctx.clip();
    const scanY = Math.sin(t * 0.9) * coreR * 0.9;
    const scan = ctx.createLinearGradient(0, scanY - 8 * core.dpr, 0, scanY + 8 * core.dpr);
    scan.addColorStop(0, "rgba(0,0,0,0)");
    scan.addColorStop(0.5, `rgba(${r},${g},${b},0.5)`);
    scan.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = scan;
    ctx.fillRect(-coreR, scanY - 8 * core.dpr, coreR * 2, 16 * core.dpr);
    ctx.restore();

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.setLineDash([]);
  }
  /* ---------------------------------------------------- ambient particle field */
  const bg = {
    canvas: $("bgCanvas"),
    ctx: null,
    dpr: 1,
    dots: [],
    reduced: false,
  };

  function initBackdrop() {
    if (!bg.canvas) return;
    bg.ctx = bg.canvas.getContext("2d");
    if (!bg.ctx) return;
    // Respect the operating-system "reduce motion" setting.
    bg.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    resizeBackdrop();
    window.addEventListener("resize", resizeBackdrop, { passive: true });
  }

  function resizeBackdrop() {
    if (!bg.ctx) return;
    bg.dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = window.innerWidth;
    const h = window.innerHeight;
    bg.canvas.width = Math.round(w * bg.dpr);
    bg.canvas.height = Math.round(h * bg.dpr);
    // More dots on bigger screens, but capped so weak laptops stay smooth.
    const count = Math.max(28, Math.min(110, Math.round((w * h) / 22000)));
    bg.dots = Array.from({ length: count }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.16,
      vy: (Math.random() - 0.5) * 0.16,
      r: 0.5 + Math.random() * 1.5,
      a: 0.12 + Math.random() * 0.45,
    }));
  }

  function drawBackdrop() {
    if (!bg.ctx || bg.reduced) return;
    const ctx = bg.ctx;
    const w = window.innerWidth;
    const h = window.innerHeight;
    ctx.setTransform(bg.dpr, 0, 0, bg.dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const linkDist = 118;
    for (let i = 0; i < bg.dots.length; i++) {
      const p = bg.dots[i];
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < -20) p.x = w + 20;
      if (p.x > w + 20) p.x = -20;
      if (p.y < -20) p.y = h + 20;
      if (p.y > h + 20) p.y = -20;

      ctx.fillStyle = `rgba(103, 232, 249, ${p.a})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();

      // Faint links between nearby dots give the "hologram mesh" feel.
      for (let j = i + 1; j < bg.dots.length; j++) {
        const q = bg.dots[j];
        const dx = p.x - q.x;
        const dy = p.y - q.y;
        const d2 = dx * dx + dy * dy;
        if (d2 > linkDist * linkDist) continue;
        const alpha = (1 - Math.sqrt(d2) / linkDist) * 0.07;
        ctx.strokeStyle = `rgba(56, 189, 248, ${alpha})`;
        ctx.lineWidth = 0.6;
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(q.x, q.y);
        ctx.stroke();
      }
    }
  }

  /* ------------------------------------------------------------- mic level */
  const mic = {
    stream: null,
    analyser: null,
    data: null,
    level: 0,
    ctx: null,
    async open() {
      if (this.stream) return true;
      if (!navigator.mediaDevices?.getUserMedia) return false;
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.ctx = new (window.AudioContext || window.webkitAudioContext)();
        const source = this.ctx.createMediaStreamSource(this.stream);
        this.analyser = this.ctx.createAnalyser();
        this.analyser.fftSize = 512;
        this.analyser.smoothingTimeConstant = 0.7;
        this.data = new Uint8Array(this.analyser.frequencyBinCount);
        source.connect(this.analyser);
        $("levelBar").style.width = "6%";
        return true;
      } catch (err) {
        this.stream = null;
        return false;
      }
    },
    read() {
      if (!this.analyser) { this.level = 0; return 0; }
      this.analyser.getByteTimeDomainData(this.data);
      let sum = 0;
      for (let i = 0; i < this.data.length; i++) {
        const v = (this.data[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / this.data.length);
      // A little headroom so normal speech fills the meter nicely.
      this.level = Math.min(1, rms * 3.4);
      return this.level;
    },
    close() {
      if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
      if (this.ctx && this.ctx.state !== "closed") this.ctx.close().catch(() => {});
      this.stream = null;
      this.analyser = null;
      this.ctx = null;
      this.level = 0;
      $("levelBar").style.width = "0%";
    },
  };
  /* ---------------------------------------------------------------- speech */
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognizer = null;

  function speechSupported() {
    return Boolean(Recognition);
  }

  function buildRecognizer(continuous) {
    const rec = new Recognition();
    rec.lang = "en-US";
    rec.continuous = continuous;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    return rec;
  }

  function speak(text) {
    if (!app.tts || !window.speechSynthesis || !text) return;
    try {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      utter.rate = 1.02;
      utter.pitch = 0.95;
      utter.onstart = () => setAssistantState("speaking");
      utter.onend = () => setAssistantState("idle");
      utter.onerror = () => setAssistantState("idle");
      window.speechSynthesis.speak(utter);
    } catch (err) {
      setAssistantState("idle");
    }
  }

  function stopSpeaking() {
    try { window.speechSynthesis?.cancel(); } catch (err) { /* ignore */ }
  }

  function startListening() {
    if (!speechSupported()) {
      toast("This browser has no speech recognition. Type instead, or run python main.py for offline Vosk.", true);
      return;
    }
    if (app.wakeMode) return;
    stopSpeaking();
    recognizer = buildRecognizer(false);
    app.listeningOnce = true;

    recognizer.onstart = async () => {
      await mic.open(); // local mic level, never uploaded
      app.micActive = true;
      $("micBtn").classList.add("is-live");
      $("micBadge").classList.add("is-live");
      $("micBadgeText").textContent = "MIC LIVE";
      $("dashMic").textContent = "LIVE";
      setAssistantState("listening");
    };

    recognizer.onresult = (event) => {
      let text = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        text += event.results[i][0].transcript;
      }
      $("cmdInput").value = text.trim();
    };

    recognizer.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        toast("Microphone blocked. Allow it in the browser's site settings, then try again.", true);
      } else if (event.error !== "aborted" && event.error !== "no-speech") {
        toast(`Speech recognition: ${event.error}`, true);
      }
    };

    recognizer.onend = () => {
      app.micActive = false;
      $("micBtn").classList.remove("is-live");
      $("micBadge").classList.remove("is-live");
      $("micBadgeText").textContent = "MIC OFF";
      $("dashMic").textContent = "OFF";
      setAssistantState(app.inFlight ? "processing" : "idle");
      const value = $("cmdInput").value.trim();
      if (app.listeningOnce) {
        app.listeningOnce = false;
        if (value) {
          $("cmdInput").value = "";
          sendCommand(value);
        } else {
          toast("I did not catch that. Try again, or type it.");
        }
      }
    };

    try {
      recognizer.start();
    } catch (err) {
      toast("Could not start the microphone.", true);
      setAssistantState("idle");
    }
  }
  /* ------------------------------------------------------------ wake word */
  function startWakeMode() {
    if (!speechSupported()) {
      toast("Wake word needs browser speech recognition, which this browser does not offer.", true);
      return;
    }
    stopSpeaking();
    app.wakeMode = true;
    $("voiceWakeBtn").textContent = "Stop wake word";
    $("voiceStatus").textContent = "waiting for wake word";
    $("micBadge").classList.add("is-live");
    $("micBadgeText").textContent = "MIC LIVE";
    setAssistantState("listening");

    const wake = (app.info?.wake_word || "jarvis").toLowerCase();
    const words = wake.split(/\s+/);

    recognizer = buildRecognizer(true);

    recognizer.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (!event.results[i].isFinal) continue;
        const heard = event.results[i][0].transcript.toLowerCase().replace(/[^a-z0-9' ]+/g, " ").trim();
        const index = heard.indexOf(words[words.length - 1]);
        if (index === -1) continue;
        const command = heard.slice(index + words[words.length - 1].length).trim();
        $("voiceStatus").textContent = "wake word heard";
        if (command) {
          sendCommand(command);
        } else {
          toast("Yes? Say your command after the wake word.");
        }
      }
    };

    recognizer.onerror = (event) => {
      if (event.error === "not-allowed") stopWakeMode(true);
    };

    recognizer.onend = () => {
      // Chrome stops continuous recognition now and then: restart while enabled.
      if (app.wakeMode) {
        setTimeout(() => {
          if (!app.wakeMode) return;
          try { recognizer.start(); } catch (err) { /* already running */ }
        }, 350);
      } else {
        $("micBadge").classList.remove("is-live");
        $("micBadgeText").textContent = "MIC OFF";
        $("voiceStatus").textContent = "idle";
        setAssistantState("idle");
      }
    };

    try {
      recognizer.start();
      mic.open();
    } catch (err) {
      stopWakeMode(true);
      toast("Could not start the wake word listener.", true);
    }
  }

  function stopWakeMode(silent = false) {
    app.wakeMode = false;
    if (recognizer) {
      try { recognizer.stop(); } catch (err) { /* ignore */ }
    }
    $("voiceWakeBtn").textContent = "Start wake word";
    $("voiceStatus").textContent = "idle";
    if (!silent) toast("Wake word listening stopped.");
  }
  /* ----------------------------------------------------------- transcript */
  function renderRich(target, text) {
    // Split on ``` fences so code is shown in a real <pre>, with no innerHTML.
    const parts = String(text).split(/```(?:[a-zA-Z0-9]*)?\n?/);
    parts.forEach((part, index) => {
      if (!part.trim()) return;
      if (index % 2 === 1) {
        const pre = document.createElement("pre");
        pre.textContent = part.replace(/\s+$/, "");
        target.appendChild(pre);
      } else {
        target.appendChild(document.createTextNode(part));
      }
    });
  }

  function appendMessage(role, text, source) {
    const transcript = $("transcript");
    const wrap = document.createElement("div");
    wrap.className = `msg ${role}`;
    if (source === "error") wrap.classList.add("error");

    const meta = document.createElement("div");
    meta.className = "msg-meta";
    const who = document.createElement("span");
    who.textContent = role === "user" ? "YOU" : "JARVIS";
    meta.appendChild(who);
    if (source && role !== "user") {
      const badge = document.createElement("span");
      badge.className = `badge ${source}`;
      badge.textContent = source.toUpperCase();
      meta.appendChild(badge);
    }
    const stamp = document.createElement("span");
    stamp.textContent = new Date().toLocaleTimeString([], { hour12: false });
    meta.appendChild(stamp);

    const body = document.createElement("div");
    body.className = "msg-body";
    renderRich(body, text);

    wrap.append(meta, body);
    transcript.appendChild(wrap);
    transcript.scrollTop = transcript.scrollHeight;
    return wrap;
  }

  function logLine(role, text) {
    const log = $("log");
    $("logEmpty")?.remove();
    const line = document.createElement("div");
    line.className = `log-line ${role}`;
    const tag = document.createElement("b");
    tag.textContent = role === "user" ? "You" : role === "error" ? "Error" : "JARVIS";
    const body = document.createElement("span");
    const flat = String(text).replace(/\s+/g, " ").trim();
    body.textContent = flat.length > 220 ? `${flat.slice(0, 220)}…` : flat;
    line.append(tag, body);
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }
  /* ------------------------------------------------- confirmations (modal) */
  function showConfirm(pending) {
    $("confirmDetail").textContent = pending.detail
      ? `${pending.action} — ${pending.detail}`
      : pending.action;
    $("confirmModal").hidden = false;
    $("confirmYes").focus();
  }

  function hideConfirm() {
    $("confirmModal").hidden = true;
  }

  function startConfirmPolling() {
    stopConfirmPolling();
    app.confirmTimer = setInterval(async () => {
      try {
        const data = await api.get("/api/pending");
        if (data.pending && $("confirmModal").hidden) showConfirm(data.pending);
      } catch (err) { /* server busy: try again next tick */ }
    }, 600);
  }

  function stopConfirmPolling() {
    if (app.confirmTimer) clearInterval(app.confirmTimer);
    app.confirmTimer = null;
    hideConfirm();
  }

  async function answerConfirm(yes) {
    hideConfirm();
    try {
      await api.post("/api/confirm", { yes });
    } catch (err) {
      toast("That confirmation expired.", true);
    }
  }

  /* -------------------------------------------------------------- commands */
  async function sendCommand(raw) {
    const text = String(raw || "").trim();
    if (!text) return;
    if (app.inFlight) {
      toast("One moment — JARVIS is still working on the last command.");
      return;
    }

    app.inFlight = true;
    if (app.assistant !== "listening") setAssistantState("processing");
    logLine("user", text);
    appendMessage("user", text);
    $("cmdInput").value = "";
    const thinking = appendMessage("jarvis", "Thinking…", null);
    thinking.classList.add("thinking");
    startConfirmPolling();

    try {
      const data = await api.post("/api/command", { text });
      thinking.remove();
      const source = data.source || "rule";
      appendMessage("jarvis", data.answer || "(no answer)", source);
      logLine(source === "error" ? "error" : "jarvis", data.answer || "");
      if (source !== "error") speak(data.answer);
      else setAssistantState("idle");
      app.turns += 1;
      $("dashTurns").textContent = String(app.turns);
      if (data.exit) {
        toast("JARVIS acknowledged the shutdown command. The interface stays open.");
      }
    } catch (err) {
      thinking.remove();
      const message = `The local server did not answer (${err.message}). Is the Python window still running?`;
      appendMessage("jarvis", message, "error");
      logLine("error", message);
      setAssistantState("idle");
    } finally {
      stopConfirmPolling();
      app.inFlight = false;
      if (app.assistant !== "speaking") setAssistantState(app.micActive ? "listening" : "idle");
    }
  }
  /* ------------------------------------------------------- system telemetry */
  function bar(el, percent) {
    const value = Math.max(0, Math.min(100, Number(percent) || 0));
    el.style.width = `${value}%`;
    el.classList.toggle("is-hot", value >= 75 && value < 90);
    el.classList.toggle("is-critical", value >= 90);
  }

  function drawSpark(canvas, values) {
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = canvas.clientWidth || 260;
    const h = canvas.clientHeight || 34;
    if (canvas.width !== Math.round(w * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (values.length < 2) return;

    const max = 100;
    ctx.beginPath();
    values.forEach((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - (Math.max(0, Math.min(max, v)) / max) * (h - 3) - 1.5;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, "rgba(34,211,238,0.32)");
    grad.addColorStop(1, "rgba(34,211,238,0)");
    ctx.lineTo(w, h);
    ctx.lineTo(0, h);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    ctx.beginPath();
    values.forEach((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - (Math.max(0, Math.min(max, v)) / max) * (h - 3) - 1.5;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "rgba(103,232,249,0.9)";
    ctx.lineWidth = 1.4;
    ctx.stroke();
  }

  function pushHistory(list, value) {
    if (typeof value !== "number" || Number.isNaN(value)) return;
    list.push(value);
    if (list.length > 60) list.shift();
  }

  const monitorCards = {};

  function buildMonitorCards() {
    const grid = $("monitorGrid");
    const specs = [
      ["cpu", "CPU LOAD"],
      ["ram", "MEMORY"],
      ["disk", "STORAGE"],
      ["temp", "CPU TEMP"],
    ];
    specs.forEach(([key, label]) => {
      const card = document.createElement("article");
      card.className = "monitor-card";
      card.id = `mon-${key}`;
      const h4 = document.createElement("h4");
      h4.textContent = label;
      const value = document.createElement("strong");
      value.textContent = "—";
      const canvas = document.createElement("canvas");
      card.append(h4, value, canvas);
      grid.appendChild(card);
      monitorCards[key] = { card, value, canvas };
    });
  }

  function applySystem(data) {
    const cpu = data.cpu;
    const ram = data.ram;
    const disk = data.storage;
    const temp = data.temperature;
    const ollama = data.ollama || {};

    // right panel
    $("cpuValue").textContent = cpu == null ? "n/a" : `${cpu.toFixed(0)}%`;
    bar($("cpuBar"), cpu);
    $("ramValue").textContent = ram ? `${ram.percent.toFixed(0)}%` : "n/a";
    bar($("ramBar"), ram?.percent);
    $("ramSub").textContent = ram ? `${ram.used_gb} of ${ram.total_gb} GB in use` : "not available";
    $("diskValue").textContent = disk ? `${disk.percent.toFixed(0)}%` : "n/a";
    bar($("diskBar"), disk?.percent);
    $("diskSub").textContent = disk ? `${disk.free_gb} GB free of ${disk.total_gb} GB (${disk.drive})` : "not available";

    $("statTemp").hidden = temp == null;
    if (temp != null) {
      $("tempValue").textContent = `${temp.toFixed(0)}°C`;
      bar($("tempBar"), (temp / 100) * 100);
    }

    $("netValue").textContent = "LOCAL";
    $("netSub").textContent = "No internet traffic";
    $("coreValue").textContent = ollama.reachable ? "ONLINE" : "OFFLINE";
    $("coreSub").textContent = ollama.reachable ? ollama.model : "Ollama not running";

    $("dashModel").textContent = data.ollama?.model || app.info?.model || "—";
    $("dashCore").textContent = ollama.reachable ? "OLLAMA" : "RULE ONLY";

    const online = $("onlineBadge");
    const isOnline = Boolean(ollama.reachable);
    online.classList.toggle("is-offline", !isOnline);
    $("onlineText").textContent = isOnline ? "SYSTEM ONLINE" : "SYSTEM ONLINE · AI OFFLINE";
    if (!isOnline && app.assistant === "idle") {
      $("coreStatus").textContent = LABELS.offline;
      $("coreStatus").dataset.state = "offline";
    }

    $("hostName").textContent = data.host?.hostname || "—";
    $("hostUptime").textContent = data.time || "—";

    // monitor view
    pushHistory(app.cpuHist, cpu);
    pushHistory(app.ramHist, ram?.percent);
    drawSpark($("cpuSpark"), app.cpuHist);
    drawSpark($("ramSpark"), app.ramHist);
    if (monitorCards.cpu) {
      monitorCards.cpu.value.textContent = cpu == null ? "n/a" : `${cpu.toFixed(1)}%`;
      monitorCards.ram.value.textContent = ram ? `${ram.used_gb} / ${ram.total_gb} GB` : "n/a";
      monitorCards.disk.value.textContent = disk ? `${disk.used_gb} / ${disk.total_gb} GB` : "n/a";
      drawSpark(monitorCards.cpu.canvas, app.cpuHist);
      drawSpark(monitorCards.ram.canvas, app.ramHist);
      monitorCards.temp.card.hidden = temp == null;
      monitorCards.temp.value.textContent = temp == null ? "n/a" : `${temp.toFixed(1)}°C`;
    }

    renderHostFacts(data.host, data);
  }

  function renderHostFacts(host, data) {
    const list = $("hostFacts");
    if (!host) return;
    list.replaceChildren();
    const rows = [
      ["Host", host.hostname],
      ["Logical cores", host.cores],
      ["Platform", host.platform],
      ["Python", host.python],
      ["Drive", data.storage?.drive || "—"],
      ["Temperature", data.temperature == null ? "sensor not exposed" : `${data.temperature}°C`],
    ];
    rows.forEach(([key, value]) => {
      const row = document.createElement("div");
      const dt = document.createElement("dt");
      dt.textContent = key;
      const dd = document.createElement("dd");
      dd.textContent = String(value);
      row.append(dt, dd);
      list.appendChild(row);
    });
  }
  /* -------------------------------------------------------------- views/UI */
  function showView(name) {
    if (!document.getElementById(`view-${name}`)) return;
    app.view = name;
    document.querySelectorAll(".view").forEach((view) => {
      view.classList.toggle("is-active", view.id === `view-${name}`);
    });
    document.querySelectorAll(".rail-btn").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.view === name);
    });
    if (name === "voice") refreshVoicePanel();
    if (name === "monitor") { requestSystem(); }
    if (name === "apps") renderApps();
    if (name === "settings") renderSettings();
    if (name === "assistant") {
      const transcript = $("transcript");
      transcript.scrollTop = transcript.scrollHeight;
    }
  }

  function renderApps() {
    const grid = $("appGrid");
    if (!grid || !app.info) return;
    grid.replaceChildren();
    app.info.apps.forEach((name) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "app-card";
      const title = document.createElement("span");
      title.textContent = name;
      const sub = document.createElement("span");
      sub.textContent = "LAUNCH";
      card.append(title, sub);
      card.addEventListener("click", () => {
        showView("dashboard");
        sendCommand(`open ${name}`);
      });
      grid.appendChild(card);
    });
  }

  function renderSettings() {
    if (!app.info) return;
    $("setModel").textContent = app.info.model;
    $("setOllama").textContent = app.info.ollama_url;
    $("setTts").textContent = app.info.tts_enabled ? "enabled in config" : "disabled in config";

    const folders = $("setFolders");
    folders.replaceChildren();
    const dirs = app.info.approved_directories || [];
    if (!dirs.length) {
      const row = document.createElement("div");
      const dt = document.createElement("dt");
      dt.textContent = "Approved folders";
      const dd = document.createElement("dd");
      dd.textContent = "none";
      row.append(dt, dd);
      folders.appendChild(row);
    }
    dirs.forEach((dir) => {
      const row = document.createElement("div");
      const dt = document.createElement("dt");
      dt.textContent = "Folder";
      const dd = document.createElement("dd");
      dd.textContent = dir;
      row.append(dt, dd);
      folders.appendChild(row);
    });
    const saved = app.info.generated_code || [];
    const row = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = "Saved code";
    const dd = document.createElement("dd");
    dd.textContent = saved.length ? saved.join(", ") : "none yet";
    row.append(dt, dd);
    folders.appendChild(row);
  }

  function refreshVoicePanel() {
    $("voiceEngine").textContent = speechSupported()
      ? "browser speech recognition"
      : "not available in this browser";
    $("voiceWake").textContent = app.info?.wake_word || "—";
    $("voiceStatus").textContent = app.wakeMode ? "waiting for wake word" : app.micActive ? "listening" : "idle";
    $("ttsToggle").checked = app.tts;
    if (!speechSupported()) {
      $("voiceListenBtn").disabled = true;
      $("voiceWakeBtn").disabled = true;
    }
  }

  /* ------------------------------------------------------------- bootstrap */
  let systemTimer = null;

  async function requestSystem() {
    try {
      const data = await api.get("/api/system");
      applySystem(data);
    } catch (err) {
      $("onlineBadge").classList.add("is-offline");
      $("onlineText").textContent = "SERVER OFFLINE";
    }
  }

  async function loadInfo() {
    try {
      app.info = await api.get("/api/info");
      $("dashModel").textContent = app.info.model;
      $("dashWake") && ($("dashWake").textContent = app.info.wake_word);
      renderApps();
      renderSettings();
      refreshVoicePanel();
    } catch (err) {
      toast("Could not read the JARVIS settings from the server.", true);
    }
  }
  /* --------------------------------------------------------------- wiring */
  function wire() {
    document.querySelectorAll(".rail-btn").forEach((btn) => {
      btn.addEventListener("click", () => showView(btn.dataset.view));
    });
    $("settingsBtn").addEventListener("click", () => showView("settings"));

    // Suggested-command pills send straight through the normal command path,
    // so the same safety checks and confirmations still apply.
    document.querySelectorAll(".quick-chip").forEach((chip) => {
      chip.addEventListener("click", () => sendCommand(chip.dataset.cmd || ""));
    });

    $("cmdForm").addEventListener("submit", (event) => {
      event.preventDefault();
      sendCommand($("cmdInput").value);
    });

    $("micBtn").addEventListener("click", () => {
      if (app.micActive || app.wakeMode) {
        app.listeningOnce = false;
        stopWakeMode(true);
        recognizer?.stop();
        mic.close();
        return;
      }
      startListening();
    });

    $("voiceListenBtn").addEventListener("click", startListening);
    $("voiceWakeBtn").addEventListener("click", () => {
      if (app.wakeMode) stopWakeMode();
      else startWakeMode();
    });

    $("ttsToggle").addEventListener("change", (event) => {
      app.tts = event.target.checked;
      localStorage.setItem("jarvis.tts", app.tts ? "on" : "off");
      if (!app.tts) stopSpeaking();
      toast(app.tts ? "Spoken replies on." : "Spoken replies off.");
    });

    $("confirmYes").addEventListener("click", () => answerConfirm(true));
    $("confirmNo").addEventListener("click", () => answerConfirm(false));
    $("confirmModal").addEventListener("click", (event) => {
      if (event.target === $("confirmModal")) answerConfirm(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !$("confirmModal").hidden) answerConfirm(false);
      if (event.key === "/" && document.activeElement !== $("cmdInput")) {
        event.preventDefault();
        $("cmdInput").focus();
      }
    });

    $("clearChat").addEventListener("click", () => {
      $("transcript").replaceChildren();
      toast("Transcript cleared.");
    });

    $("refreshBtn").addEventListener("click", () => {
      requestSystem();
      loadInfo();
      toast("Re-checked the system.");
    });

    $("clearLocalBtn").addEventListener("click", () => {
      localStorage.removeItem("jarvis.tts");
      app.tts = true;
      $("ttsToggle").checked = true;
      toast("Local preferences reset.");
    });
  }

  /* ----------------------------------------------------------- animation loop */
  let lastFrame = 0;

  function frame(now) {
    if (document.hidden) {
      requestAnimationFrame(frame);
      return;
    }
    const delta = now - lastFrame;
    if (delta > 22) { // ~45 fps cap keeps laptops cool
      lastFrame = now;
      mic.read();
      drawBackdrop();
      if (app.view === "dashboard" && core.ctx) drawCore(now);
      drawWave(now);
      if (app.micActive || app.wakeMode) {
        $("levelBar").style.width = `${Math.round(mic.level * 100)}%`;
      }
    }
    requestAnimationFrame(frame);
  }

  const waveCanvas = $("waveCanvas");
  const waveCtx = waveCanvas.getContext("2d");

  function drawWave(now) {
    if (!waveCtx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = waveCanvas.clientWidth || 400;
    const h = waveCanvas.clientHeight || 26;
    if (waveCanvas.width !== Math.round(w * dpr)) {
      waveCanvas.width = Math.round(w * dpr);
      waveCanvas.height = Math.round(h * dpr);
    }
    waveCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    waveCtx.clearRect(0, 0, w, h);

    const bars = Math.floor(w / 7);
    const active = app.micActive || app.wakeMode || app.assistant === "speaking";
    const amp = active ? Math.max(0.12, mic.level) : 0.05;
    const t = now / 240;

    for (let i = 0; i < bars; i++) {
      const phase = Math.sin(t + i * 0.42) * 0.5 + 0.5;
      const height = active
        ? (h * 0.22) + phase * amp * h * 1.1
        : 1.2 + phase * 1.4;
      const x = i * 7 + 2;
      const y = (h - Math.min(h - 1, height)) / 2;
      waveCtx.fillStyle = active
        ? `rgba(103, 232, 249, ${0.35 + phase * 0.55})`
        : "rgba(56, 189, 248, 0.16)";
      waveCtx.fillRect(x, y, 3, Math.min(h - 1, height));
    }
  }
  async function init() {
    initCore();
    initBackdrop();
    buildMonitorCards();
    wire();
    clock();
    setInterval(clock, 1000);
    setAssistantState("idle");

    await loadInfo();
    await requestSystem();
    systemTimer = setInterval(requestSystem, 2200);

    $("cmdInput").focus();
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) requestSystem();
    });

    // ?view=monitor deep-links straight to a section.
    const wanted = params.get("view");
    if (wanted) showView(wanted);

    requestAnimationFrame(frame);
  }

  init();
})();
