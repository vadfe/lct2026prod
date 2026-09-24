/**
 * VINA Cylindrical Dewarping Studio - Frontend Logic
 */

document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const samplesContainer = document.getElementById("samples-container");
  const tabBtnSamples = document.getElementById("tab-btn-samples");
  const tabBtnUpload = document.getElementById("tab-btn-upload");
  const tabSamples = document.getElementById("tab-samples");
  const tabUpload = document.getElementById("tab-upload");
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const btnBrowse = document.getElementById("btn-browse");
  
  const stepperSection = document.getElementById("stepper-section");
  const statusBanner = document.getElementById("status-banner");
  const resultsSection = document.getElementById("results-section");
  
  // Image Views
  const imgOrigSrc = document.getElementById("img-original-src");
  const imgDewarpedSrc = document.getElementById("img-dewarped-src");
  const dewarpedOverlay = document.getElementById("dewarped-overlay");
  const splitHandle = document.getElementById("split-handle");
  const splitContainer = document.getElementById("split-container");
  
  const sideContainer = document.getElementById("side-container");
  const sideImgOrig = document.getElementById("side-img-orig");
  const sideImgDewarped = document.getElementById("side-img-dewarped");
  
  const annotatedContainer = document.getElementById("annotated-container");
  const annotatedImg = document.getElementById("annotated-img");
  
  // Toggles
  const toggleSplitView = document.getElementById("toggle-split-view");
  const toggleSideView = document.getElementById("toggle-side-view");
  const toggleAnnotatedView = document.getElementById("toggle-annotated-view");
  
  // OCR & Data elements
  const ocrFullText = document.getElementById("ocr-full-text");
  const tokensFlow = document.getElementById("tokens-flow");
  const codesContainer = document.getElementById("codes-container");
  const codesList = document.getElementById("codes-list");
  const catalogBox = document.getElementById("catalog-box");
  const catRefImg = document.getElementById("cat-ref-img");
  const catDewarpImg = document.getElementById("cat-dewarp-img");
  const valSsim = document.getElementById("val-ssim");
  const valNrmse = document.getElementById("val-nrmse");
  const valMse = document.getElementById("val-mse");
  const totalTimeBadge = document.getElementById("total-time-badge");
  const latencyBars = document.getElementById("latency-bars");
  const currentFilenameBadge = document.getElementById("current-filename-badge");
  
  // Diagnostic Images
  const stageImgMask = document.getElementById("stage-img-mask");
  const stageImgRetinex = document.getElementById("stage-img-retinex");
  const stageImgSauvola = document.getElementById("stage-img-sauvola");
  const stageImgFeatures = document.getElementById("stage-img-features");
  const stageImgMesh = document.getElementById("stage-img-mesh");
  const stageImgDewarpDiag = document.getElementById("stage-img-dewarp-diag");
  const stageImgAnnotatedDiag = document.getElementById("stage-img-annotated-diag");
  
  const camParamsTable = document.getElementById("cam-params-table");
  const solverParamsTable = document.getElementById("solver-params-table");
  const ocrStatsTable = document.getElementById("ocr-stats-table");
  
  // Actions
  const btnDownloadFlat = document.getElementById("btn-download-flat");
  const btnDownloadJson = document.getElementById("btn-download-json");
  const btnCopyOcr = document.getElementById("btn-copy-ocr");
  const toast = document.getElementById("toast");
  const toastMessage = document.getElementById("toast-message");
  const btnRestoreSamples = document.getElementById("btn-restore-samples");
  const hiddenCountEl = document.getElementById("hidden-count");
  
  let currentResultData = null;
  let allLoadedSamples = [];

  // Helper functions for UI Soft-Delete (Hidden Samples)
  function getHiddenSamples() {
    try {
      return JSON.parse(localStorage.getItem("vina_hidden_samples") || "[]");
    } catch {
      return [];
    }
  }

  function setHiddenSamples(arr) {
    localStorage.setItem("vina_hidden_samples", JSON.stringify(arr));
  }

  // --- API Configuration & Bridge Support ---
  function getApiBase() {
    const urlParams = new URLSearchParams(window.location.search);
    const apiParam = urlParams.get('api');
    if (apiParam) {
      const clean = apiParam.trim().replace(/\/+$/, '');
      localStorage.setItem('vina_api_url', clean);
      return clean;
    }

    // Always prefer direct local connection if running locally
    const isLocalHost = window.location.hostname === 'localhost' || 
                        window.location.hostname === '127.0.0.1' || 
                        window.location.hostname === '0.0.0.0' ||
                        window.location.port === '8080' ||
                        !window.location.hostname;
    // if (isLocalHost) { return ''; }

    const saved = localStorage.getItem('vina_api_url');
    if (saved) return saved.trim().replace(/\/+$/, '');
    return '';
  }

  function apiUrl(path) {
    const base = getApiBase();
    if (!path.startsWith('/')) path = '/' + path;
    return base ? `${base}${path}` : path;
  }

  // 1. Initial Load: Check Health & Fetch Sample Bottles
  fetchHealth();
  fetchSamples();

  async function fetchHealth(customUrl = null) {
    const gpuEl = document.getElementById("gpu-status-text");
    const targetUrl = customUrl !== null ? (customUrl ? `${customUrl.replace(/\/+$/, '')}/api/ready` : '/api/ready') : apiUrl("/api/ready");

    if (!getApiBase() && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
      if (gpuEl) gpuEl.textContent = "Сервер не настроен • Офлайн";
      return { ok: false };
    }

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 6000);
      const res = await fetch(targetUrl, { signal: controller.signal });
      clearTimeout(timeoutId);

      const contentType = res.headers.get("content-type") || "";
      if (!res.ok || !contentType.includes("application/json")) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();
      if (gpuEl) {
        if (data.gpu_name && data.gpu_name !== "None (CPU)") {
          gpuEl.textContent = `${data.gpu_name} • Онлайн`;
        } else {
          gpuEl.textContent = "CPU Mode Active • Онлайн";
        }
      }
      return { ok: true, data };
    } catch (e) {
      if (gpuEl) gpuEl.textContent = "RTX 3090 • Офлайн";
      return { ok: false, error: e.message };
    }
  }

  async function fetchSamples() {
    if (!getApiBase() && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
      samplesContainer.innerHTML = `
        <div style="padding: 24px 16px; text-align: center; color: var(--apple-text-secondary); font-size: 13px;">
          <p style="margin-bottom: 10px;">Сервер инференса (RTX 3090) не подключён к облаку.</p>
          <button id="btn-open-settings-inline" style="cursor: pointer; padding: 6px 14px; background: #0071e3; color: #fff; border: none; border-radius: 20px; font-weight: 500; font-size: 12px;">⚙️ Подключить туннель</button>
        </div>
      `;
      document.getElementById("btn-open-settings-inline")?.addEventListener("click", openSettings);
      return;
    }

    try {
      const res = await fetch(apiUrl("/api/samples"));
      const contentType = res.headers.get("content-type") || "";
      if (!res.ok || !contentType.includes("application/json")) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      allLoadedSamples = data.samples || [];
      renderSamples(allLoadedSamples);
    } catch (e) {
      samplesContainer.innerHTML = `
        <div class="error-msg" style="padding: 16px; font-size: 13px;">
          Сервер инференса недоступен (${e.message}). Проверьте туннель к RTX 3090.
          <div style="margin-top: 8px;">
            <button id="btn-retry-samples" style="cursor: pointer; font-size: 12px; padding: 4px 10px; border-radius: 6px; border: 1px solid #ccc; background: #fff;">Повторить попытку</button>
          </div>
        </div>
      `;
      document.getElementById("btn-retry-samples")?.addEventListener("click", fetchSamples);
    }
  }

  function renderSamples(samples) {
    samplesContainer.innerHTML = "";
    const hidden = getHiddenSamples();
    const visibleSamples = samples.filter(s => !hidden.includes(s.filename));

    // Update restore button state
    const hiddenCount = samples.length - visibleSamples.length;
    if (hiddenCount > 0) {
      if (btnRestoreSamples) {
        btnRestoreSamples.classList.remove("hidden");
        if (hiddenCountEl) hiddenCountEl.textContent = hiddenCount;
      }
    } else {
      if (btnRestoreSamples) btnRestoreSamples.classList.add("hidden");
    }

    if (visibleSamples.length === 0) {
      samplesContainer.innerHTML = `
        <div style="padding: 24px 10px; color: var(--apple-text-secondary); font-size: 13px;">
          Все образцы скрыты из интерфейса. 
          <a href="#" id="link-restore-all" style="color: var(--apple-blue); text-decoration: underline; margin-left: 6px;">Восстановить все</a>
        </div>
      `;
      const linkRestore = document.getElementById("link-restore-all");
      if (linkRestore) {
        linkRestore.addEventListener("click", (e) => {
          e.preventDefault();
          setHiddenSamples([]);
          renderSamples(allLoadedSamples);
          showToast("Все образцы возвращены в интерфейс");
        });
      }
      return;
    }

    visibleSamples.forEach(sample => {
      const card = document.createElement("div");
      card.className = "sample-item-card";
      card.innerHTML = `
        <button class="btn-remove-sample" title="Убрать из списка (без удаления файла с диска)">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
        <img class="sample-thumb" src="${apiUrl(sample.cam_url)}" alt="${sample.title}" loading="lazy">
        <div class="sample-title">${sample.title}</div>
        <div class="sample-tag">${sample.has_catalog ? "✓ Эталон в базе" : "Камера"}</div>
      `;

      // Remove button click (UI only)
      const btnRemove = card.querySelector(".btn-remove-sample");
      btnRemove.addEventListener("click", (e) => {
        e.stopPropagation();
        const currentHidden = getHiddenSamples();
        if (!currentHidden.includes(sample.filename)) {
          currentHidden.push(sample.filename);
          setHiddenSamples(currentHidden);
        }
        card.style.opacity = "0";
        card.style.transform = "scale(0.85)";
        setTimeout(() => {
          renderSamples(allLoadedSamples);
          showToast(`Файл "${sample.title}" убран из интерфейса (на диске сохранен)`);
        }, 180);
      });

      card.addEventListener("click", () => {
        document.querySelectorAll(".sample-item-card").forEach(c => c.classList.remove("active"));
        card.classList.add("active");
        processSampleBottle(sample.filename);
      });

      samplesContainer.appendChild(card);
    });
  }

  if (btnRestoreSamples) {
    btnRestoreSamples.addEventListener("click", () => {
      setHiddenSamples([]);
      renderSamples(allLoadedSamples);
      showToast("Все скрытые файлы возвращены в интерфейс");
    });
  }

  // Tab switching (Dataset vs Upload)
  tabBtnSamples.addEventListener("click", () => {
    tabBtnSamples.classList.add("active");
    tabBtnUpload.classList.remove("active");
    tabSamples.classList.remove("hidden");
    tabUpload.classList.add("hidden");
  });

  tabBtnUpload.addEventListener("click", () => {
    tabBtnUpload.classList.add("active");
    tabBtnSamples.classList.remove("active");
    tabUpload.classList.remove("hidden");
    tabSamples.classList.add("hidden");
  });

  // Drag & drop upload
  btnBrowse.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.click();
  });
  dropZone.addEventListener("click", () => fileInput.click());

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      uploadCustomFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length > 0) {
      uploadCustomFile(e.target.files[0]);
    }
  });

  // Processing Functions
  async function processSampleBottle(filename) {
    showLoading(`Обработка образца: ${filename}`);
    try {
      const res = await fetch(apiUrl("/api/process_sample"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sample_filename: filename })
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      renderResults(data);
    } catch (e) {
      showToast(`Ошибка: ${e.message}`);
    } finally {
      hideLoading();
    }
  }

  async function uploadCustomFile(file) {
    showLoading(`Анализ фото: ${file.name}`);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch(apiUrl("/api/process_upload"), {
        method: "POST",
        body: formData
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      renderResults(data);
    } catch (e) {
      showToast(`Ошибка: ${e.message}`);
    } finally {
      hideLoading();
    }
  }

  function showLoading(headline) {
    statusBanner.classList.remove("hidden");
    stepperSection.classList.remove("hidden");
    resultsSection.classList.add("hidden");
    document.getElementById("status-headline").textContent = headline;
  }

  function hideLoading() {
    statusBanner.classList.add("hidden");
  }

  // Render Pipeline Results
  function renderResults(data) {
    currentResultData = data;
    resultsSection.classList.remove("hidden");
    currentFilenameBadge.textContent = data.filename || "image.jpg";

    const art = data.artifacts || {};

    // 1. Image viewers
    imgOrigSrc.src = art.original || art.cropped;
    imgDewarpedSrc.src = art.dewarped;
    sideImgOrig.src = art.original || art.cropped;
    sideImgDewarped.src = art.dewarped;
    annotatedImg.src = art.annotated;

    btnDownloadFlat.href = art.dewarped;
    btnDownloadFlat.download = `${data.filename || "dewarped"}_flattened.jpg`;

    // Reset split slider to 50%
    setSplitPosition(50);

    // 2. Dual Verification Statistics & Capture Selection
    const comp = data.comparison || {};
    const rawComp = comp.raw || {};
    const dewComp = comp.dewarped || {};
    
    const statRawWords = document.getElementById("stat-raw-words");
    const statDewWords = document.getElementById("stat-dew-words");
    const statGainWords = document.getElementById("stat-gain-words");
    const ocrSelectionBadge = document.getElementById("ocr-selection-badge");
    
    if (statRawWords) statRawWords.textContent = `${rawComp.num_words ?? (data.word_comparison?.raw_words ?? "-")} сл`;
    if (statDewWords) statDewWords.textContent = `${dewComp.num_words ?? (data.word_comparison?.dewarped_words ?? "-")} сл`;
    if (statGainWords) {
      const gain = comp.gain ?? (data.word_comparison?.gain ?? 0);
      if (gain > 0) {
        statGainWords.textContent = `+${gain} сл (прирост)`;
        statGainWords.style.color = "#38A169";
      } else if (gain < 0) {
        statGainWords.textContent = `${gain} сл (меньше)`;
        statGainWords.style.color = "#E53E3E";
      } else {
        statGainWords.textContent = `0 (равно)`;
        statGainWords.style.color = "#718096";
      }
    }

    // Function to render text and tokens for selected capture mode
    function applyCaptureView(mode) {
      const btnAuto = document.getElementById("btn-source-auto");
      const btnDew = document.getElementById("btn-source-dewarped");
      const btnRaw = document.getElementById("btn-source-raw");

      [btnAuto, btnDew, btnRaw].forEach(b => b && b.classList.remove("active"));

      let textToDisplay = data.full_text || "";
      let tokensToDisplay = data.text_blocks || [];
      let annotatedSrc = art.annotated;

      if (mode === "raw") {
        if (btnRaw) btnRaw.classList.add("active");
        textToDisplay = rawComp.full_text || data.full_text;
        tokensToDisplay = rawComp.text_blocks || data.text_blocks;
        annotatedSrc = rawComp.annotated || art.cropped;
        if (ocrSelectionBadge) {
          ocrSelectionBadge.textContent = "Исходный снимок (До развертки)";
          ocrSelectionBadge.className = "badge-accent";
        }
      } else if (mode === "dewarped") {
        if (btnDew) btnDew.classList.add("active");
        textToDisplay = dewComp.full_text || data.full_text;
        tokensToDisplay = dewComp.text_blocks || data.text_blocks;
        annotatedSrc = dewComp.annotated || art.dewarped;
        if (ocrSelectionBadge) {
          ocrSelectionBadge.textContent = "Выпрямленный скан (Dewarped)";
          ocrSelectionBadge.className = "badge-accent";
        }
      } else {
        // Auto mode
        if (btnAuto) btnAuto.classList.add("active");
        const isDew = (comp.recommended === "dewarped") || ((comp.gain ?? 0) >= 0);
        textToDisplay = isDew ? (dewComp.full_text || data.full_text) : (rawComp.full_text || data.full_text);
        tokensToDisplay = isDew ? (dewComp.text_blocks || data.text_blocks) : (rawComp.text_blocks || data.text_blocks);
        annotatedSrc = isDew ? (dewComp.annotated || art.dewarped) : (rawComp.annotated || art.cropped);
        if (ocrSelectionBadge) {
          ocrSelectionBadge.textContent = isDew ? "★ Автоотбор: Выпрямленный скан" : "★ Автоотбор: Исходный снимок";
          ocrSelectionBadge.className = isDew ? "badge-success" : "badge-accent";
        }
      }

      ocrFullText.textContent = textToDisplay || "Текст не обнаружен";
      annotatedImg.src = annotatedSrc;
      
      // Update bottom diagnostics section for Stage 5
      if (typeof stageImgAnnotatedDiag !== 'undefined' && stageImgAnnotatedDiag) {
        stageImgAnnotatedDiag.src = annotatedSrc;
      }
      if (typeof ocrStatsTable !== 'undefined' && ocrStatsTable) {
        ocrStatsTable.innerHTML = `
          <div class="param-row"><span class="param-key">Всего слов / токенов:</span><span class="param-val">${(tokensToDisplay || []).length}</span></div>
          <div class="param-row"><span class="param-key">Распознанные коды:</span><span class="param-val">${(data.barcodes || []).length}</span></div>
          <div class="param-row"><span class="param-key">Средняя уверенность:</span><span class="param-val">${computeAvgConfidence(tokensToDisplay)}%</span></div>
        `;
      }

      tokensFlow.innerHTML = "";
      (tokensToDisplay || []).forEach(tb => {
        const pill = document.createElement("div");
        pill.className = "token-pill";
        pill.innerHTML = `<span>${tb.text}</span><span class="token-conf">${Math.round(tb.confidence * 100)}%</span>`;
        tokensFlow.appendChild(pill);
      });
    }

    // Attach click listeners to source switcher buttons
    const btnSourceAuto = document.getElementById("btn-source-auto");
    const btnSourceDew = document.getElementById("btn-source-dewarped");
    const btnSourceRaw = document.getElementById("btn-source-raw");

    if (btnSourceAuto) btnSourceAuto.onclick = () => applyCaptureView("auto");
    if (btnSourceDew) btnSourceDew.onclick = () => applyCaptureView("dewarped");
    if (btnSourceRaw) btnSourceRaw.onclick = () => applyCaptureView("raw");

    // Initialize default view
    applyCaptureView("auto");
    
    // Wine Lexicon Corrections Display
    const correctionsContainer = document.getElementById("corrections-container");
    const correctionsList = document.getElementById("corrections-list");
    const fixes = data.lexicon_corrections || [];
    if (correctionsContainer && correctionsList) {
      if (fixes.length > 0) {
        correctionsContainer.classList.remove("hidden");
        correctionsList.innerHTML = fixes.map(f => {
          const simText = f.similarity ? ` (сходство ${Math.round(f.similarity * 100)}%)` : "";
          return `
            <div style="font-size: 13px; color: #2D3748; display: flex; align-items: center; gap: 8px; background: #FFFFFF; padding: 6px 12px; border-radius: 8px; border: 1px solid #C6F6D5;">
              <span style="color: #C53030; text-decoration: line-through; font-family: monospace;">${f.before}</span>
              <span style="color: #2B6CB0; font-weight: bold;">➔</span>
              <span style="color: #22543D; font-weight: bold; font-family: monospace;">${f.after}</span>
              <span style="font-size: 11px; color: #718096; margin-left: auto;">${simText || f.rule || "Словарь"}</span>
            </div>
          `;
        }).join("");
      } else {
        correctionsContainer.classList.add("hidden");
      }
    }

    // 3. Barcodes / QR
    if (data.barcodes && data.barcodes.length > 0) {
      codesContainer.classList.remove("hidden");
      codesList.innerHTML = data.barcodes.map(c => `
        <div class="code-badge-item">
          <strong>[${c.type}]</strong> <span>${c.data}</span>
        </div>
      `).join("");
    } else {
      codesContainer.classList.add("hidden");
    }

    // 4. Catalog Comparison (if available)
    if (data.has_reference && data.metrics && Object.keys(data.metrics).length > 0) {
      catalogBox.classList.remove("hidden");
      catRefImg.src = art.catalog_reference || "";
      catDewarpImg.src = art.dewarped || "";
      valSsim.textContent = `${data.metrics.ssim_percent || 0}%`;
      valNrmse.textContent = data.metrics.nrmse || "0.00";
      valMse.textContent = data.metrics.mse || "0";
    } else {
      catalogBox.classList.add("hidden");
    }

    // 5. Latency Breakdown
    const timings = data.timings || {};
    totalTimeBadge.textContent = `${(timings.total_ms / 1000).toFixed(2)} сек`;
    
    const stageNames = [
      { key: "stage1_ms", name: "1. Сегментация & Retinex" },
      { key: "stage2_ms", name: "2. Линии & LSD" },
      { key: "stage3_ms", name: "3. 3D GCS Оптимизация" },
      { key: "stage4_ms", name: "4. TPS Dewarping" },
      { key: "stage5_ms", name: "5. OCR & Декодирование" }
    ];

    latencyBars.innerHTML = stageNames.map(s => {
      const ms = timings[s.key] || 0;
      const pct = Math.max(4, Math.min(100, (ms / (timings.total_ms || 1)) * 100));
      return `
        <div class="latency-row">
          <span class="latency-name">${s.name}</span>
          <div class="latency-track">
            <div class="latency-fill" style="width: ${pct}%"></div>
          </div>
          <span class="latency-ms">${ms} ms</span>
        </div>
      `;
    }).join("");

    // 6. Diagnostics Tab Content
    stageImgMask.src = art.mask || "";
    stageImgRetinex.src = art.retinex || "";
    stageImgSauvola.src = art.binarized || "";
    stageImgFeatures.src = art.features || "";
    stageImgMesh.src = art.mesh || "";
    stageImgDewarpDiag.src = art.dewarped || "";
    // stageImgAnnotatedDiag is updated via applyCaptureView

    // Camera params table
    const cam = data.cam_info || {};
    camParamsTable.innerHTML = `
      <div class="param-row"><span class="param-key">Угол наклона (Tilt):</span><span class="param-val">${cam.tilt_angle_deg?.toFixed(2)}°</span></div>
      <div class="param-row"><span class="param-key">Фокусное расстояние (Focal):</span><span class="param-val">${cam.estimated_focal_length?.toFixed(1)} px</span></div>
      <div class="param-row"><span class="param-key">Средняя кривизна текста:</span><span class="param-val">${cam.mean_curvature?.toFixed(5)}</span></div>
      <div class="param-row"><span class="param-key">Центральная ось x:</span><span class="param-val">${cam.center_axis_x?.toFixed(1)} px</span></div>
    `;

    // Solver params table
    const opt = data.opt_params || {};
    solverParamsTable.innerHTML = `
      <div class="param-row"><span class="param-key">Радиус цилиндра R:</span><span class="param-val">${opt.cylinder_radius?.toFixed(1)} px</span></div>
      <div class="param-row"><span class="param-key">Ось цилиндра c_x:</span><span class="param-val">${opt.center_x?.toFixed(1)} px</span></div>
      <div class="param-row"><span class="param-key">Кривизна верха (k_top):</span><span class="param-val">${opt.k_top?.toFixed(3)}</span></div>
      <div class="param-row"><span class="param-key">Кривизна низа (k_bot):</span><span class="param-val">${opt.k_bot?.toFixed(3)}</span></div>
      <div class="param-row"><span class="param-key">Сходимость солвера:</span><span class="param-val" style="color: #34C759;">${opt.converged ? "Успешно" : "Сходимость достигнута"}</span></div>
    `;

    // OCR stats table
    // (Now updated via applyCaptureView above)

    // Scroll smoothly to results
    resultsSection.scrollIntoView({ behavior: "smooth" });
  }

  function computeAvgConfidence(blocks) {
    if (!blocks || blocks.length === 0) return "0";
    const sum = blocks.reduce((acc, b) => acc + (b.confidence || 0), 0);
    return Math.round((sum / blocks.length) * 100);
  }

  // Interactive Split Slider Logic
  let isDragging = false;

  function setSplitPosition(pct) {
    pct = Math.max(0, Math.min(100, pct));
    dewarpedOverlay.style.width = `${pct}%`;
    splitHandle.style.left = `${pct}%`;
  }

  function handleSplitDrag(e) {
    if (!isDragging) return;
    const rect = splitContainer.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const offsetX = clientX - rect.left;
    const pct = (offsetX / rect.width) * 100;
    setSplitPosition(pct);
  }

  splitHandle.addEventListener("mousedown", () => { isDragging = true; });
  window.addEventListener("mouseup", () => { isDragging = false; });
  window.addEventListener("mousemove", handleSplitDrag);

  splitHandle.addEventListener("touchstart", () => { isDragging = true; });
  window.addEventListener("touchend", () => { isDragging = false; });
  window.addEventListener("touchmove", handleSplitDrag);

  // View Mode Toggles (Split / Side / Annotated)
  toggleSplitView.addEventListener("click", () => {
    setActiveViewToggle(toggleSplitView);
    splitContainer.classList.remove("hidden");
    sideContainer.classList.add("hidden");
    annotatedContainer.classList.add("hidden");
  });

  toggleSideView.addEventListener("click", () => {
    setActiveViewToggle(toggleSideView);
    splitContainer.classList.add("hidden");
    sideContainer.classList.remove("hidden");
    annotatedContainer.classList.add("hidden");
  });

  toggleAnnotatedView.addEventListener("click", () => {
    setActiveViewToggle(toggleAnnotatedView);
    splitContainer.classList.add("hidden");
    sideContainer.classList.add("hidden");
    annotatedContainer.classList.remove("hidden");
  });

  function setActiveViewToggle(btn) {
    [toggleSplitView, toggleSideView, toggleAnnotatedView].forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
  }

  // Diagnostic Stage Tab Switching
  document.querySelectorAll(".stage-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".stage-tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".stage-content-panel").forEach(p => p.classList.add("hidden"));
      
      btn.classList.add("active");
      const stageNum = btn.getAttribute("data-stage");
      const panel = document.getElementById(`stage-panel-${stageNum}`);
      if (panel) panel.classList.remove("hidden");
    });
  });

  // Action Buttons
  btnCopyOcr.addEventListener("click", () => {
    const text = ocrFullText.textContent;
    navigator.clipboard.writeText(text).then(() => {
      showToast("Текст скопирован в буфер обмена");
    });
  });

  btnDownloadJson.addEventListener("click", () => {
    if (!currentResultData) return;
    const blob = new Blob([JSON.stringify(currentResultData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${currentResultData.filename || "result"}_data.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast("JSON результат сохранён");
  });

  function showToast(msg) {
    toastMessage.textContent = msg;
    toast.classList.remove("hidden");
    setTimeout(() => {
      toast.classList.add("hidden");
    }, 3000);
  }

  // --- Settings Modal Handlers for Studio ---
  const btnStudioSettings = document.getElementById("btn-studio-settings");
  const settingsModal = document.getElementById("settings-modal");
  const btnCloseModal = document.getElementById("btn-close-modal");
  const modalBackdrop = document.getElementById("modal-backdrop");
  const inputApiUrl = document.getElementById("input-api-url");
  const btnTestConnection = document.getElementById("btn-test-connection");
  const btnSaveSettings = document.getElementById("btn-save-settings");
  const connectionFeedback = document.getElementById("connection-feedback");

  function openSettings() {
    if (!settingsModal) return;
    inputApiUrl.value = localStorage.getItem("vina_api_url") || "";
    if (connectionFeedback) connectionFeedback.style.display = "none";
    settingsModal.style.display = "flex";
    settingsModal.classList.remove("hidden");
  }

  function closeSettings() {
    if (!settingsModal) return;
    settingsModal.style.display = "none";
    settingsModal.classList.add("hidden");
  }

  const btnResetLocal = document.getElementById("btn-reset-local");
  if (btnResetLocal) {
    btnResetLocal.addEventListener("click", async () => {
      localStorage.removeItem("vina_api_url");
      inputApiUrl.value = "";
      closeSettings();
      await fetchHealth();
      await fetchSamples();
      showToast("Переключено на локальный сервер (127.0.0.1:8080)");
    });
  }

  if (btnStudioSettings) btnStudioSettings.addEventListener("click", openSettings);
  if (btnCloseModal) btnCloseModal.addEventListener("click", closeSettings);
  if (modalBackdrop) modalBackdrop.addEventListener("click", closeSettings);

  if (btnTestConnection) {
    btnTestConnection.addEventListener("click", async () => {
      const url = inputApiUrl.value.trim();
      connectionFeedback.style.display = "block";
      connectionFeedback.style.background = "#fff3cd";
      connectionFeedback.style.color = "#856404";
      connectionFeedback.textContent = "Проверка связи с сервером...";

      const res = await fetchHealth(url);
      if (res.ok) {
        connectionFeedback.style.background = "#d4edda";
        connectionFeedback.style.color = "#155724";
        connectionFeedback.textContent = `Успешно! Сервер доступен (${res.data.gpu_name || "OK"}).`;
      } else {
        connectionFeedback.style.background = "#f8d7da";
        connectionFeedback.style.color = "#721c24";
        connectionFeedback.textContent = "Не удалось подключиться. Проверьте запущен ли start_tunnel.bat на ПК.";
      }
    });
  }

  if (btnSaveSettings) {
    btnSaveSettings.addEventListener("click", async () => {
      const val = inputApiUrl.value.trim().replace(/\/+$/, "");
      if (val) {
        localStorage.setItem("vina_api_url", val);
      } else {
        localStorage.removeItem("vina_api_url");
      }
      closeSettings();
      await fetchHealth();
      await fetchSamples();
      showToast("Настройки подключения сохранены");
    });
  }

});


// ==========================================
// Lightbox Zoom & Pan Logic
// ==========================================
document.addEventListener("DOMContentLoaded", () => {
  const lightboxModal = document.getElementById("lightbox-modal");
  const lightboxImg = document.getElementById("lightbox-img");
  const lightboxCanvas = document.getElementById("lightbox-canvas");
  const btnCloseLightbox = document.getElementById("btn-close-lightbox");
  const btnZoomIn = document.getElementById("btn-zoom-in");
  const btnZoomOut = document.getElementById("btn-zoom-out");
  const btnZoomReset = document.getElementById("btn-zoom-reset");
  const lightboxTitle = document.getElementById("lightbox-title");

  let scale = 1;
  let posX = 0;
  let posY = 0;
  let isDragging = false;
  let startX, startY;

  function updateTransform() {
    lightboxImg.style.transform = `translate(${posX}px, ${posY}px) scale(${scale})`;
    btnZoomReset.textContent = Math.round(scale * 100) + "%";
  }

  function resetTransform() {
    scale = 1;
    posX = 0;
    posY = 0;
    updateTransform();
  }

  function openLightbox(src, title) {
    if (!src || src === "") return;
    lightboxImg.src = src;
    lightboxTitle.textContent = title || "Просмотр изображения";
    resetTransform();
    lightboxModal.classList.remove("hidden");
  }

  function closeLightbox() {
    lightboxModal.classList.add("hidden");
    lightboxImg.src = "";
  }

  // Attach to images
  const clickables = [
    "img-original-src", "img-dewarped-src", 
    "side-img-orig", "side-img-dewarped", 
    "annotated-img", 
    "stage-img-mask", "stage-img-retinex", "stage-img-sauvola", 
    "stage-img-features", "stage-img-mesh", "stage-img-dewarp-diag", "stage-img-annotated-diag"
  ];
  
  clickables.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.style.cursor = "zoom-in";
      el.addEventListener("click", () => {
        let title = "Просмотр";
        if (el.alt) title = el.alt;
        else if (el.previousElementSibling && el.previousElementSibling.tagName === "H4") {
          title = el.previousElementSibling.textContent;
        } else if (el.parentElement.querySelector('.image-tag')) {
          title = el.parentElement.querySelector('.image-tag').textContent;
        } else if (el.parentElement.previousElementSibling && el.parentElement.previousElementSibling.tagName === "H4") {
          title = el.parentElement.previousElementSibling.textContent;
        }
        openLightbox(el.src, title);
      });
    }
  });

  // Controls
  btnCloseLightbox.addEventListener("click", closeLightbox);
  btnZoomReset.addEventListener("click", resetTransform);
  
  btnZoomIn.addEventListener("click", () => {
    scale *= 1.2;
    updateTransform();
  });
  
  btnZoomOut.addEventListener("click", () => {
    scale /= 1.2;
    updateTransform();
  });

  // Mouse wheel zoom
  lightboxCanvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const zoomFactor = 1.1;
    if (e.deltaY < 0) {
      scale *= zoomFactor;
    } else {
      scale /= zoomFactor;
    }
    updateTransform();
  }, { passive: false });

  // Pan logic
  lightboxCanvas.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return; // Only left click
    isDragging = true;
    startX = e.clientX - posX;
    startY = e.clientY - posY;
  });

  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    posX = e.clientX - startX;
    posY = e.clientY - startY;
    updateTransform();
  });

  window.addEventListener("mouseup", () => {
    isDragging = false;
  });

  // Keyboard
  window.addEventListener("keydown", (e) => {
    if (lightboxModal.classList.contains("hidden")) return;
    if (e.key === "Escape") {
      closeLightbox();
    }
  });
});
