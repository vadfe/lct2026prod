document.addEventListener('DOMContentLoaded', () => {
    // --- API Configuration & Bridge Support ---
    function getApiBase() {
        const urlParams = new URLSearchParams(window.location.search);
        const apiParam = urlParams.get('api');
        if (apiParam) {
            const clean = apiParam.trim().replace(/\/+$/, '');
            localStorage.setItem('vina_api_url', clean);
            return clean;
        }

        if (window.location.protocol === 'file:') {
            return 'http://127.0.0.1:8030';
        }

        // Always prefer direct local connection if running locally
        const isLocalHost = window.location.hostname === 'localhost' || 
                            window.location.hostname === '127.0.0.1' || 
                            window.location.hostname === '0.0.0.0' ||
                            window.location.port === '8030' ||
                            window.location.port === '8080';
        
        if (isLocalHost) {
            return '';
        }

        const saved = localStorage.getItem('vina_api_url');
        if (saved) {
            return saved.trim().replace(/\/+$/, '');
        }
        return '';
    }

    function apiUrl(path) {
        const base = getApiBase();
        if (!path.startsWith('/')) path = '/' + path;
        return base ? `${base}${path}` : path;
    }

    // --- DOM Elements ---
    const fileInput = document.getElementById('file-input');
    const scannerView = document.getElementById('scanner-view');
    const loadingView = document.getElementById('loading-view');
    const resultView = document.getElementById('result-view');
    const btnBack = document.getElementById('btn-back');
    const scanningLine = document.querySelector('.scanning-line');
    const cameraFeed = document.getElementById('camera-feed');
    const btnSnap = document.getElementById('btn-snap');
    const labelUpload = document.getElementById('label-upload');
    
    // Status & Settings Elements
    const statusDot = document.querySelector('.status-dot');
    const statusText = document.getElementById('status-text');
    const btnSettings = document.getElementById('btn-settings');
    const settingsModal = document.getElementById('settings-modal');
    const btnCloseModal = document.getElementById('btn-close-modal');
    const modalBackdrop = document.querySelector('.modal-backdrop');
    const inputApiUrl = document.getElementById('input-api-url');
    const btnTestConnection = document.getElementById('btn-test-connection');
    const btnSaveSettings = document.getElementById('btn-save-settings');
    const feedbackBox = document.getElementById('connection-feedback');

    // Result View Elements
    const imgWine = document.getElementById('wine-image');
    const elWinery = document.getElementById('wine-winery');
    const elTitle = document.getElementById('wine-title');
    const elColor = document.getElementById('wine-color');
    const elCategory = document.getElementById('wine-category');
    const elRegion = document.getElementById('wine-region');
    const elGrape = document.getElementById('wine-grape');
    const elDesc = document.getElementById('wine-description');
    const btnShowOriginal = document.getElementById('btn-show-original');

    // Original View Elements
    const originalView = document.getElementById('original-view');
    const originalImg = document.getElementById('original-img');
    const originalCanvas = document.getElementById('original-canvas');
    const btnBackToResult = document.getElementById('btn-back-to-result');
    const btnAddToDb = document.getElementById('btn-add-to-db');

    let currentUploadedImageURL = null;
    let currentSlug = null;

    // --- Views Switcher ---
    let cameraStream = null;

    async function startCamera() {
        if (!cameraFeed) return;
        try {
            if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                cameraStream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: "environment" }
                });
                cameraFeed.srcObject = cameraStream;
                cameraFeed.style.display = 'block';
                if (btnSnap) btnSnap.classList.remove('hidden');
            }
        } catch (e) {
            console.warn("Camera access denied or unavailable", e);
        }
    }

    function stopCamera() {
        if (cameraStream) {
            cameraStream.getTracks().forEach(t => t.stop());
            cameraStream = null;
        }
        if (cameraFeed) cameraFeed.style.display = 'none';
    }

    window.startScannerCamera = startCamera;
    window.stopScannerCamera = stopCamera;
    window.showScannerMainView = () => showView(scannerView);
    window.showScannerResultView = (slug) => { showView(resultView); if (slug) loadWineCard(slug); };

    function showView(view) {
        [scannerView, loadingView, resultView, originalView].forEach(v => {
            if (v) v.classList.remove('active');
        });
        if (view) view.classList.add('active');

        const scannerPanel = document.getElementById('hub-panel-scanner');
        const isScannerActive = scannerPanel && scannerPanel.classList.contains('active');

        // Manage camera lifecycle
        if (view === scannerView && isScannerActive) {
            startCamera();
        } else {
            stopCamera();
        }
    }

    // --- Health Check & Status Monitor ---
    async function checkServerHealth(customUrl = null) {
        const targetUrl = customUrl !== null ? (customUrl ? `${customUrl.replace(/\/+$/, '')}/api/health` : '/api/health') : apiUrl('/api/health');
        
        statusDot.className = 'status-dot';
        statusText.textContent = 'Проверка...';

        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 5000);
            const res = await fetch(targetUrl, { signal: controller.signal });
            clearTimeout(timeoutId);

            if (res.ok) {
                const data = await res.json();
                statusDot.className = 'status-dot online';
                statusText.textContent = 'Онлайн';
                return { ok: true, data };
            } else {
                throw new Error(`HTTP ${res.status}`);
            }
        } catch (e) {
            statusDot.className = 'status-dot offline';
            statusText.textContent = 'Офлайн';
            return { ok: false, error: e.message };
        }
    }

    // Run health check initially
    checkServerHealth();

    // --- Settings Modal Handlers ---
    function openSettings() {
        inputApiUrl.value = localStorage.getItem('vina_api_url') || '';
        feedbackBox.className = 'feedback-box hidden';
        settingsModal.classList.remove('hidden');
    }

    function closeSettings() {
        settingsModal.classList.add('hidden');
    }

    window.openBridgeSettings = openSettings;
    window.closeBridgeSettings = closeSettings;

    function showFeedback(text, type) {
        feedbackBox.textContent = text;
        feedbackBox.className = `feedback-box ${type}`;
    }

    if (btnSettings) btnSettings.addEventListener('click', openSettings);
    const serverStatusEl = document.getElementById('server-status');
    if (serverStatusEl) serverStatusEl.addEventListener('click', openSettings);
    btnCloseModal.addEventListener('click', closeSettings);
    modalBackdrop.addEventListener('click', closeSettings);

    const btnResetLocal = document.getElementById('btn-reset-local');
    if (btnResetLocal) {
        btnResetLocal.addEventListener('click', async () => {
            localStorage.removeItem('vina_api_url');
            inputApiUrl.value = '';
            closeSettings();
            await checkServerHealth();
        });
    }

    btnTestConnection.addEventListener('click', async () => {
        const testUrl = inputApiUrl.value.trim();
        showFeedback('Проверка соединения...', '');
        const res = await checkServerHealth(testUrl);
        if (res.ok) {
            showFeedback(`Успешно! Сервер доступен (${res.data.gpu_name || 'OK'}).`, 'success');
        } else {
            showFeedback('Не удалось связаться с сервером. Проверьте запущен ли cloudflared туннель.', 'error');
        }
    });

    btnSaveSettings.addEventListener('click', async () => {
        const val = inputApiUrl.value.trim().replace(/\/+$/, '');
        if (val) {
            localStorage.setItem('vina_api_url', val);
        } else {
            localStorage.removeItem('vina_api_url');
        }
        await checkServerHealth();
        closeSettings();
    });

    // --- File Upload & Scan Logic ---
    async function processImageFile(file) {
        if (!file) return;

        if (typeof window.switchHubTab === 'function') {
            window.switchHubTab('scanner');
        }
        showView(scannerView);
        
        if (currentUploadedImageURL) {
            URL.revokeObjectURL(currentUploadedImageURL);
        }
        currentUploadedImageURL = URL.createObjectURL(file);
        
        if (scanningLine) scanningLine.classList.remove('hidden');
        
        setTimeout(async () => {
            showView(loadingView);
            
            try {
                const formData = new FormData();
                formData.append('image', file, 'snapshot.jpg');
                formData.append('k', '5');
                
                // 1. Попытка через основной пайплайн поиска lct2026prod (/api/v1/search)
                let res = null;
                try {
                    res = await fetch(apiUrl('/api/v1/search'), {
                        method: 'POST',
                        body: formData
                    });
                } catch (err) {
                    console.warn('[VINA Scanner] /api/v1/search network error, trying fallback', err);
                }

                // 2. Если этикетка не обнаружена детектором (422) или ошибка, fallback на /api/v1/eval/predict
                if (!res || !res.ok) {
                    const fallbackData = new FormData();
                    fallbackData.append('image', file, 'snapshot.jpg');
                    res = await fetch(apiUrl('/api/v1/eval/predict'), {
                        method: 'POST',
                        body: fallbackData
                    });
                }
                
                if (!res.ok) throw new Error(`Ошибка сервера: ${res.status}`);
                const data = await res.json();
                
                let slug = null;
                let conf = null;

                if (data.winner && data.winner.slug) {
                    slug = data.winner.slug;
                    conf = data.winner.confidence !== undefined ? data.winner.confidence : 0.90;
                } else if (data.slug) {
                    slug = data.slug;
                    conf = data.confidence !== undefined ? data.confidence : (data.score !== undefined ? data.score : 0.90);
                }

                if (data.query_crop) {
                    window.lastDetectedCropURL = data.query_crop;
                }

                if (slug && (!conf || conf >= 0.35)) {
                    if (typeof window.setConfidence === 'function' && conf !== undefined && conf !== null) {
                        window.setConfidence(conf);
                    }
                    window.lastScannedSlug = slug;
                    if (typeof window.openWineDetail === 'function') {
                        window.openWineDetail(slug, 'scanner');
                    } else {
                        await loadWineCard(slug);
                        showView(resultView);
                    }
                } else if (data.status === 'not_in_catalog' || (conf !== null && conf < 0.35)) {
                    showView(scannerView);
                    const msg = (data && (data.message || data.user_message)) || 'Данного вина пока нет в каталоге, скоро появится, спасибо за проявленный интерес.';
                    showMissingWineModal(msg);
                } else {
                    showView(scannerView);
                    showMissingWineModal('Данного вина пока нет в каталоге, скоро появится, спасибо за проявленный интерес.');
                }
            } catch (error) {
                console.error(error);
                showToast('Ошибка при связи с сервером инференса.');
                showView(scannerView);
            } finally {
                if (scanningLine) scanningLine.classList.add('hidden');
                if (fileInput) fileInput.value = '';
            }
        }, 1200);
    }

    window.processScannerImageFile = processImageFile;

    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length) processImageFile(e.target.files[0]);
        });
    }

    if (btnSnap && cameraFeed) {
        const handleSnap = (e) => {
            if (e.type === 'touchend') e.preventDefault(); // prevent double firing from click
            btnSnap.style.transform = "translateX(-50%) scale(0.9)";
            setTimeout(() => btnSnap.style.transform = "translateX(-50%) scale(1)", 150);

            if (!cameraStream) {
                console.warn("No camera stream active, attempting startCamera or file picker");
                if (fileInput) fileInput.click();
                return;
            }

            // Draw current video frame to canvas
            const canvas = document.createElement('canvas');
            canvas.width = cameraFeed.videoWidth || 1080;
            canvas.height = cameraFeed.videoHeight || 1920;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(cameraFeed, 0, 0, canvas.width, canvas.height);
            
            // Convert to Blob
            canvas.toBlob((blob) => {
                if (blob) {
                    const file = new File([blob], "snapshot.jpg", { type: "image/jpeg" });
                    processImageFile(file);
                } else {
                    alert("Ошибка создания снимка с камеры");
                }
            }, 'image/jpeg', 0.9);
        };
        
        btnSnap.addEventListener('click', handleSnap);
        btnSnap.addEventListener('touchend', handleSnap);
    }

    // --- Load Wine Metadata & Image ---
    async function loadWineCard(slug) {
        currentSlug = slug;
        window.currentScannedSlug = slug;

        let wine = null;
        let fullSommData = null;

        try {
            const fRes = await fetch(apiUrl(`/api/v2/wine/${slug}/full-sommelier`));
            if (fRes.ok) {
                fullSommData = await fRes.json();
                wine = fullSommData.wine;
            }
        } catch (e) {
            console.warn("Full sommelier fetch fallback", e);
        }

        if (!wine) {
            const res = await fetch(apiUrl(`/api/wine/${slug}`));
            if (!res.ok) throw new Error('Карточка не найдена');
            wine = await res.json();
        }
        
        // Image URL through API bridge
        imgWine.src = apiUrl(`/api/image/${slug}`);
        imgWine.onerror = () => { imgWine.src = 'https://via.placeholder.com/300x500?text=Wine'; };
        
        elWinery.textContent = wine.winery || '';
        elTitle.textContent = wine.name || slug;
        elColor.textContent = wine.color || '';
        elCategory.textContent = wine.category || '';
        
        const elSweetness = document.getElementById('wine-sweetness');
        if (elSweetness) {
            elSweetness.textContent = wine.sweetness || wine.sugar || '';
            elSweetness.style.display = (wine.sweetness || wine.sugar) ? '' : 'none';
        }
        
        elRegion.textContent = wine.region || '';
        elGrape.textContent = wine.grape || '';
        elDesc.textContent = wine.description || '';

        // Крепость вина
        const alcBadge = document.getElementById('scan-alcohol-badge');
        if (alcBadge) {
            alcBadge.textContent = wine.alcohol ? `${wine.alcohol} об.` : '13.5% об.';
        }

        // Кнопка истории в результате сканера
        const histBtn = document.getElementById('btn-result-history');
        if (histBtn) {
            if (fullSommData && fullSommData.history) {
                histBtn.style.display = 'inline-flex';
                histBtn.onclick = () => openWineHistoryModal(slug);
            } else {
                histBtn.style.display = 'none';
            }
        }

        // Шкалы характеристик вина (кислотность, танины, тело, сладость, дуб)
        const organoBox = document.getElementById('result-sensory-bars');
        if (organoBox) {
            const organo = (fullSommData && fullSommData.organoleptic) ? fullSommData.organoleptic : {
                acidity: 3.8, tannins: 3.5, body: 4.2, sweetness: 1.5, oak_intensity: 3.2
            };
            organoBox.innerHTML = renderSensoryBarsHtml(organo);
        }

        // Логика употребления от сомелье и блюда с фото и рецептами
        const logicBox = document.getElementById('scanner-sommelier-logic');
        if (logicBox) {
            renderScannerSommelierLogic(logicBox, fullSommData, wine);
        }

        // Подключаем экспресс-подбор блюд и аналоги сомелье VINA
        initScannerSommelierRetention(slug, wine);
        
        // Populate Original View Card
        const ow = document.getElementById('orig-wine-winery'); if(ow) ow.textContent = wine.winery || '';
        const ot = document.getElementById('orig-wine-title'); if(ot) ot.textContent = wine.name || slug;
        const oc = document.getElementById('orig-wine-category'); if(oc) oc.textContent = wine.category || '';
        const os = document.getElementById('orig-wine-sweetness');
        if (os) {
            os.textContent = wine.sweetness || wine.sugar || '';
            os.style.display = (wine.sweetness || wine.sugar) ? '' : 'none';
        }
        const ocol = document.getElementById('orig-wine-color'); if(ocol) ocol.textContent = wine.color || '';
        const or = document.getElementById('orig-wine-region'); if(or) or.textContent = wine.region || '';
        const og = document.getElementById('orig-wine-grape'); if(og) og.textContent = wine.grape || '';
        const od = document.getElementById('orig-wine-desc'); if(od) od.textContent = wine.description || '';

        if(typeof initRating === 'function') initRating(slug);
    }

    btnBack.addEventListener('click', () => {
        showView(scannerView);
    });

    if (btnShowOriginal) {
        btnShowOriginal.addEventListener('click', () => {
            const displayImg = window.lastDetectedCropURL || currentUploadedImageURL;
            if (displayImg) {
                originalImg.src = displayImg;
                showView(originalView);
            } else {
                alert("Исходное фото не найдено");
            }
        });
    }

    if (btnBackToResult) {
        btnBackToResult.addEventListener('click', () => {
            showView(resultView);
        });
    }

    if (btnAddToDb) {
        btnAddToDb.addEventListener('click', () => {
            alert("Функция 'Добавить в базу' в разработке");
        });
    }

    // Attach to original image to open Lightbox
    if (originalImg) {
        const handleOpenOrig = (e) => {
            if (e.type === 'touchend') e.preventDefault();
            openLightbox(originalImg.src, "Исходное фото");
        };
        originalImg.addEventListener("click", handleOpenOrig);
        originalImg.addEventListener("touchend", handleOpenOrig);
    }

    // Pairing buttons
    document.querySelectorAll('.btn-pairing').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.btn-pairing').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
        });
    });

    // ==========================================
    // Lightbox Zoom & Pan Logic
    // ==========================================
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
        scale = Math.min(Math.max(scale, 0.4), 8);
        lightboxImg.style.transform = `translate(${posX}px, ${posY}px) scale(${scale})`;
        if (btnZoomReset) btnZoomReset.textContent = Math.round(scale * 100) + "%";
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
        lightboxTitle.textContent = title || "Бутылка и этикетка вина";
        resetTransform();
        lightboxModal.classList.remove("hidden");
        document.body.style.overflow = "hidden";
    }

    function closeLightbox() {
        lightboxModal.classList.add("hidden");
        lightboxImg.src = "";
        document.body.style.overflow = "";
    }

    window.openLightbox = openLightbox;
    window.closeLightbox = closeLightbox;

    // Attach to the result wine image
    if (imgWine) {
        imgWine.style.cursor = "zoom-in";
        // Both click and touchend to ensure it triggers on mobile
        const handleOpen = (e) => {
            if (e.type === 'touchend') e.preventDefault(); // prevent double firing
            openLightbox(imgWine.src, elTitle.textContent || "Этикетка вина");
        };
        imgWine.addEventListener("click", handleOpen);
        imgWine.addEventListener("touchend", handleOpen);
    }

    // Controls
    if(btnCloseLightbox) btnCloseLightbox.addEventListener("click", closeLightbox);
    if(btnZoomReset) btnZoomReset.addEventListener("click", resetTransform);
    
    if(btnZoomIn) {
        btnZoomIn.addEventListener("click", () => {
            scale *= 1.3;
            updateTransform();
        });
    }
    
    if(btnZoomOut) {
        btnZoomOut.addEventListener("click", () => {
            scale /= 1.3;
            updateTransform();
        });
    }

    // Mouse wheel zoom
    if (lightboxCanvas) {
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

        let lastTapTime = 0;
        let dragDistance = 0;

        // Double-click zoom to 2.5x or reset
        lightboxCanvas.addEventListener("dblclick", (e) => {
            e.preventDefault();
            if (scale > 1.25) {
                resetTransform();
            } else {
                scale = 2.5;
                const rect = lightboxCanvas.getBoundingClientRect();
                const offsetX = e.clientX - rect.left - rect.width / 2;
                const offsetY = e.clientY - rect.top - rect.height / 2;
                posX = -offsetX * 1.5;
                posY = -offsetY * 1.5;
                updateTransform();
            }
        });

        // Pan logic for desktop (mouse)
        lightboxCanvas.addEventListener("mousedown", (e) => {
            if (e.button !== 0) return; 
            isDragging = true;
            dragDistance = 0;
            startX = e.clientX - posX;
            startY = e.clientY - posY;
        });

        window.addEventListener("mousemove", (e) => {
            if (!isDragging) return;
            dragDistance += Math.abs(e.movementX || 0) + Math.abs(e.movementY || 0);
            posX = e.clientX - startX;
            posY = e.clientY - startY;
            updateTransform();
        });

        window.addEventListener("mouseup", (e) => {
            if (isDragging && dragDistance < 4 && scale <= 1.05 && e.target === lightboxCanvas) {
                closeLightbox();
            }
            isDragging = false;
        });

        // Mobile touch logic (Pan + Pinch-to-Zoom + Double-tap)
        let initialDistance = null;
        let initialScale = 1;

        lightboxCanvas.addEventListener("touchstart", (e) => {
            if (e.touches.length === 1) {
                isDragging = true;
                dragDistance = 0;
                startX = e.touches[0].clientX - posX;
                startY = e.touches[0].clientY - posY;
            } else if (e.touches.length === 2) {
                isDragging = false;
                const touch1 = e.touches[0];
                const touch2 = e.touches[1];
                initialDistance = Math.hypot(touch2.clientX - touch1.clientX, touch2.clientY - touch1.clientY);
                initialScale = scale;
            }
        });

        window.addEventListener("touchmove", (e) => {
            if (e.touches.length === 1 && isDragging) {
                dragDistance += 1;
                posX = e.touches[0].clientX - startX;
                posY = e.touches[0].clientY - startY;
                updateTransform();
            } else if (e.touches.length === 2 && initialDistance) {
                const touch1 = e.touches[0];
                const touch2 = e.touches[1];
                const currentDistance = Math.hypot(touch2.clientX - touch1.clientX, touch2.clientY - touch1.clientY);
                const zoomDelta = currentDistance / initialDistance;
                scale = initialScale * zoomDelta;
                updateTransform();
            }
        });

        window.addEventListener("touchend", (e) => {
            const now = Date.now();
            if (now - lastTapTime < 300 && e.changedTouches && e.changedTouches.length === 1 && dragDistance < 10) {
                e.preventDefault();
                if (scale > 1.25) {
                    resetTransform();
                } else {
                    scale = 2.5;
                    const touch = e.changedTouches[0];
                    const rect = lightboxCanvas.getBoundingClientRect();
                    const offsetX = touch.clientX - rect.left - rect.width / 2;
                    const offsetY = touch.clientY - rect.top - rect.height / 2;
                    posX = -offsetX * 1.5;
                    posY = -offsetY * 1.5;
                    updateTransform();
                }
            } else if (scale <= 1.05 && dragDistance < 5 && e.target === lightboxCanvas && e.changedTouches && e.changedTouches.length === 1) {
                closeLightbox();
            }
            lastTapTime = now;
            if (e.touches.length < 2) {
                initialDistance = null;
            }
            if (e.touches.length === 0) {
                isDragging = false;
            }
        });
    }

    // Keyboard
    window.addEventListener("keydown", (e) => {
        if (!lightboxModal.classList.contains("hidden")) {
            if (e.key === "Escape") {
                closeLightbox();
            }
        }
    });


    // ==========================================
    // Rating Logic
    // ==========================================
    const ratingBadge = document.getElementById('people-rating-badge');
    const badgeScore = document.getElementById('badge-score');
    const ratingSection = document.getElementById('rating-section');
    const glassSlots = document.querySelectorAll('#glasses-container .glass-slot');
    const userRatingText = document.getElementById('user-rating-text');
    const totalVotesEl = document.getElementById('total-votes');
    const avgScoreEl = document.getElementById('avg-score');

    let currentRating = 0;
    
    // Fallback global ratings (mock)
    let globalStats = JSON.parse(localStorage.getItem('vina_global_ratings')) || {};

    window.setConfidence = function(score) {
        const el = document.getElementById('confidence-score');
        if (el) {
            let val = score;
            if (typeof score === 'number') {
                val = score <= 1.0 && score >= 0 ? Math.round(score * 100) : Math.round(score);
                val = Math.min(100, Math.max(0, val));
            }
            el.textContent = `${val}%`;
        }
    };

    window.initRating = function(slug) {
        if (!globalStats[slug]) {
            globalStats[slug] = { total: 15, sum: 67 }; // Mock initial data: avg 4.46 -> 4.5
        }
        
        const userSaved = localStorage.getItem('vina_rating_' + slug);
        currentRating = userSaved ? parseInt(userSaved) : 0;
        
        updateRatingUI(currentRating, slug);
    };

    function updateRatingUI(rating, slug) {
        const stats = globalStats[slug] || { total: 1, sum: rating || 5 };
        const avg = (stats.sum / stats.total).toFixed(1);
        
        badgeScore.textContent = avg;
        avgScoreEl.textContent = avg;
        totalVotesEl.textContent = stats.total;
        
        if (rating > 0) {
            userRatingText.textContent = `Ваша оценка: ${rating} из 5`;
        } else {
            userRatingText.textContent = 'Ваша оценка: - из 5';
        }

        glassSlots.forEach((slot, index) => {
            const val = index + 1;
            const img = slot.querySelector('.glass-img');
            if (val <= rating) {
                slot.classList.add('active-bg');
                img.src = 'img/glass_filled_straight.png';
            } else {
                slot.classList.remove('active-bg');
                img.src = 'img/glass_empty_straight.png';
            }
        });
    }

    if (ratingBadge && ratingSection) {
        ratingBadge.addEventListener('click', () => {
            ratingSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
    }

    glassSlots.forEach((slot, index) => {
        const val = index + 1;
        
        // Hover
        slot.addEventListener('mouseenter', () => {
            glassSlots.forEach((s, i) => {
                if (i <= index) {
                    s.classList.add('active-bg');
                } else {
                    if (i + 1 > currentRating) {
                        s.classList.remove('active-bg');
                    }
                }
            });
        });

        // Leave
        slot.addEventListener('mouseleave', () => {
            updateRatingUI(currentRating, currentSlug);
        });

        // Click
        const handleRatingClick = (e) => {
            if (e.type === 'touchend') e.preventDefault();
            if (!currentSlug) return;
            
            // If replacing previous rating, remove old from sum
            if (currentRating > 0) {
                globalStats[currentSlug].sum -= currentRating;
            } else {
                globalStats[currentSlug].total += 1;
            }
            
            currentRating = val;
            globalStats[currentSlug].sum += currentRating;
            
            localStorage.setItem('vina_rating_' + currentSlug, currentRating);
            localStorage.setItem('vina_global_ratings', JSON.stringify(globalStats));
            
            updateRatingUI(currentRating, currentSlug);
        };

        slot.addEventListener('click', handleRatingClick);
        slot.addEventListener('touchend', handleRatingClick);
    });

    // Toast notification helper
    let toastTimeout = null;
    function showToast(message) {
        const toast = document.getElementById('toast');
        if (!toast) return;
        toast.textContent = message;
        toast.classList.add('show');
        clearTimeout(toastTimeout);
        toastTimeout = setTimeout(() => {
            toast.classList.remove('show');
        }, 2500);
    }

    // =========================================================================
    // ЦИФРОВОЙ СОМЕЛЬЕ В РЕЗУЛЬТАТЕ СКАНИРОВАНИЯ (SCANNER RETENTION SOMMELIER)
    // =========================================================================
    async function initScannerSommelierRetention(slug, wine) {
        const verdictBox = document.getElementById('scanner-pairing-verdict-box');
        if (verdictBox) { verdictBox.style.display = 'none'; }
        const altContainer = document.getElementById('scanner-alternatives-container');
        if (altContainer) { altContainer.style.display = 'none'; altContainer.innerHTML = ''; }
        document.querySelectorAll('#scanner-quick-pairing-options .btn-pairing').forEach(b => b.classList.remove('selected'));

        const chipsWrap = document.getElementById('scanner-dynamic-dishes-chips');
        if (chipsWrap) chipsWrap.innerHTML = '';

        try {
            const res = await fetch(apiUrl(`/api/sommelier/wine/${slug}`));
            if (!res.ok) return;
            const data = await res.json();

            // 1. Динамические шкалы профиля (если вернулись из движка сомелье)
            if (data.profile && data.profile.scales) {
                const organoBox = document.getElementById('result-sensory-bars');
                if (organoBox) {
                    const mapped = { acidity: 3.8, tannins: 3.5, body: 4.0, sweetness: 1.5, oak_intensity: 3.0 };
                    data.profile.scales.forEach(sc => {
                        if (sc.key === 'sweetness' && sc.value !== null) mapped.sweetness = sc.value * 5;
                        if (sc.key === 'body' && sc.value !== null) mapped.body = sc.value * 5;
                        if (sc.key === 'tannin' && sc.value !== null) mapped.tannins = sc.value * 5;
                        if (sc.key === 'acidity' && sc.value !== null) mapped.acidity = sc.value * 5;
                    });
                    organoBox.innerHTML = renderSensoryBarsHtml(mapped);
                }
            }

            // 2. Чипсы рекомендованных блюд (best_dishes)
            if (chipsWrap && data.best_dishes && data.best_dishes.length > 0) {
                chipsWrap.innerHTML = data.best_dishes.map(d => `
                    <button type="button" class="btn-pairing" onclick="handleScannerPairingClick('${escapeSommHtml(d.query)}', '${escapeSommHtml(d.label)}')">
                        🍽 ${escapeSommHtml(d.label)} <span style="font-size: 10px; color: #2e7d32; font-weight: 700; margin-left: 2px;">${Math.round(d.score)}%</span>
                    </button>
                `).join('');
            }
        } catch (e) {
            console.warn('Sommelier scanner section init fallback', e);
        }
    }
    window.initScannerSommelierRetention = initScannerSommelierRetention;

    window.handleScannerPairingClick = async function(query, label) {
        const slug = currentSlug || window.currentScannedSlug || window.currentDetailWineSlug;
        if (!slug) return;
        document.querySelectorAll('.scanner-pairing-block .btn-pairing').forEach(b => {
            if (b.textContent.includes(label)) b.classList.add('selected');
            else b.classList.remove('selected');
        });

        const vBox = document.getElementById('scanner-pairing-verdict-box');
        if (!vBox) return;
        vBox.style.display = 'block';
        vBox.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
                <strong style="color: #722F37; font-size: 13.5px;">🍽 ${escapeSommHtml(label)}</strong>
                <span class="somm-spinner" style="width: 14px; height: 14px;"></span>
            </div>
            <div style="font-size: 12.5px; color: #6c757d;">Запрашиваем оценку цифрового сомелье...</div>
        `;

        try {
            const res = await fetch(apiUrl(`/api/sommelier/wine/${slug}?dish=${encodeURIComponent(query)}`));
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();

            if (data.pairing) {
                const p = data.pairing;
                const verdictTitle = p.verdict ? p.verdict.title : 'Оценка пары';
                const score = Math.round(p.score || 0);

                let factorsHtml = '';
                if (p.factors && p.factors.length > 0) {
                    factorsHtml = `<ul style="margin: 6px 0 0 0; padding-left: 18px; font-size: 12.5px; line-height: 1.45; color: #495057;">
                        ${p.factors.map(f => `<li style="margin-bottom: 3px;">${escapeSommHtml(f.text)}</li>`).join('')}
                    </ul>`;
                }

                vBox.innerHTML = `
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                        <strong style="color: #722F37; font-size: 13.5px;">🍽 ${escapeSommHtml(label)}: <span style="color: #1a1a1a;">${escapeSommHtml(verdictTitle)}</span></strong>
                        <span style="background: #722F37; color: #fff; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 8px;">${score}%</span>
                    </div>
                    ${factorsHtml}
                    <div style="margin-top: 10px; display: flex; gap: 8px;">
                        <button type="button" onclick="openSommelierEntryPoint('${slug}', null, 'pairing'); runSommPairingFast('${escapeSommHtml(label)}');" style="background: #722F37; color: #ffffff; border: none; border-radius: 8px; padding: 6px 12px; font-size: 11.5px; font-weight: 600; cursor: pointer;">
                            Другие вина к ${escapeSommHtml(label)} &rarr;
                        </button>
                    </div>
                `;
            } else if (data.text) {
                vBox.innerHTML = `
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                        <strong style="color: #722F37; font-size: 13.5px;">🍽 ${escapeSommHtml(label)}</strong>
                    </div>
                    <div style="font-size: 12.5px; color: #495057;">${formatSommMarkdown(data.text)}</div>
                `;
            }
        } catch (err) {
            console.error(err);
            vBox.innerHTML = '<span style="color: #c92a2a; font-size: 12.5px;">Не удалось получить вердикт сомелье.</span>';
        }
    };

    window.loadScannerAlternatives = async function(slug) {
        if (!slug) slug = currentSlug;
        if (!slug) return;

        const container = document.getElementById('scanner-alternatives-container');
        if (!container) return;
        container.style.display = 'flex';
        container.innerHTML = `
            <div style="text-align: center; padding: 16px; color: #6c757d; font-size: 13px;">
                <span class="somm-spinner" style="width: 16px; height: 16px; margin-right: 6px;"></span>
                Подбираем 3 лучших российских аналога в каталоге...
            </div>
        `;

        try {
            const res = await fetch(apiUrl(`/api/sommelier/wine/${slug}/alternatives?limit=3`));
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();

            if (data.items && data.items.length > 0) {
                container.innerHTML = data.items.map(it => `
                    <div style="display: flex; gap: 12px; align-items: center; background: #ffffff; border: 1px solid #eef0f3; border-radius: 12px; padding: 10px 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.03);">
                        <img src="${it.image_url || 'img/glass_filled_straight.png'}" style="width: 36px; height: 56px; object-fit: contain; border-radius: 4px;" onerror="this.src='img/glass_filled_straight.png'">
                        <div style="flex: 1; min-width: 0;">
                            <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px;">
                                <strong style="font-size: 13.5px; color: #1a1a1a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeSommHtml(it.name)}</strong>
                                <span style="background: #e8f5e9; color: #2e7d32; font-weight: 700; font-size: 11px; padding: 2px 7px; border-radius: 8px;">${Math.round((it.score || 0.85) * 100)}%</span>
                            </div>
                            <div style="font-size: 11.5px; color: #6c757d; margin: 2px 0 4px 0;">${escapeSommHtml(it.winery)} &bull; ${escapeSommHtml(it.facts || '')}</div>
                            <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px;">
                                ${(it.reasons || []).slice(0, 2).map(r => `<span style="font-size: 10px; background: #f8f9fa; border: 1px solid #dee2e6; padding: 1px 6px; border-radius: 6px; color: #495057;">${escapeSommHtml(r)}</span>`).join('')}
                            </div>
                            <button type="button" onclick="openWineDetail('${it.id}')" style="background: #722F37; color: #ffffff; border: none; border-radius: 6px; padding: 4px 10px; font-size: 11.5px; font-weight: 600; cursor: pointer;">
                                Перейти к вину &rarr;
                            </button>
                        </div>
                    </div>
                `).join('');
            } else {
                container.innerHTML = '<div style="text-align: center; padding: 12px; color: #6c757d; font-size: 12.5px;">Аналогичные вина в текущей выборке не найдены.</div>';
            }
        } catch (err) {
            console.error(err);
            container.innerHTML = '<div style="text-align: center; padding: 12px; color: #c92a2a; font-size: 12.5px;">Не удалось загрузить аналоги.</div>';
        }
    };

    // Слушатели кнопок чата и карты сомелье
    const btnMap = document.getElementById('btn-map');
    if (btnMap) {
        btnMap.addEventListener('click', () => {
            if (typeof switchHubTab === 'function') switchHubTab('map');
            else showToast('📍 Переход в раздел «Карта»');
        });
    }

    const btnChat = document.getElementById('btn-chat');
    if (btnChat) {
        btnChat.addEventListener('click', () => {
            window.openSommelierEntryPoint(currentSlug, null, 'chat');
        });
    }

    // =========================================================================
    // 1. ИНТЕРАКТИВНЫЙ ИНСПЕКТОР ЭТИКЕТКИ (ПИНЧ-ЗУМ + ДРАГ НА МОБИЛЬНОМ И В ПК)
    // =========================================================================
    function makeInteractiveInspector(canvasId, imgId, resetBtnId, inBtnId, outBtnId) {
        const canvas = document.getElementById(canvasId);
        const img = document.getElementById(imgId);
        if (!canvas || !img) return null;

        let scale = 1.0;
        let posX = 0;
        let posY = 0;
        let isDragging = false;
        let startX = 0;
        let startY = 0;

        let initialPinchDistance = null;
        let initialScale = 1.0;
        let touchStartX = 0;
        let touchStartY = 0;

        function updateTransform() {
            scale = Math.min(Math.max(scale, 1.0), 4.5);
            if (scale === 1.0) {
                posX = 0;
                posY = 0;
            } else {
                const maxPanX = (canvas.clientWidth * (scale - 1)) / 1.5;
                const maxPanY = (canvas.clientHeight * (scale - 1)) / 1.5;
                posX = Math.min(Math.max(posX, -maxPanX), maxPanX);
                posY = Math.min(Math.max(posY, -maxPanY), maxPanY);
            }
            img.style.transform = `translate3d(${posX}px, ${posY}px, 0px) scale(${scale})`;
            img.style.transition = isDragging ? 'none' : 'transform 0.15s ease-out';
        }

        function reset() {
            scale = 1.0;
            posX = 0;
            posY = 0;
            updateTransform();
        }

        const inBtn = document.getElementById(inBtnId);
        const outBtn = document.getElementById(outBtnId);
        const resetBtn = document.getElementById(resetBtnId);

        if (inBtn) inBtn.onclick = (e) => { e.preventDefault(); scale = Math.min(scale + 0.35, 4.5); updateTransform(); };
        if (outBtn) outBtn.onclick = (e) => { e.preventDefault(); scale = Math.max(scale - 0.35, 1.0); updateTransform(); };
        if (resetBtn) resetBtn.onclick = (e) => { e.preventDefault(); reset(); };

        // Десктоп: скролл колесиком мыши (с привязкой к точке курсора)
        canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY < 0 ? 0.2 : -0.2;
            const newScale = Math.min(Math.max(scale + delta, 1.0), 4.5);
            
            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left - rect.width / 2;
            const mouseY = e.clientY - rect.top - rect.height / 2;
            
            if (newScale !== scale) {
                posX -= mouseX * (newScale - scale) * 0.4;
                posY -= mouseY * (newScale - scale) * 0.4;
                scale = newScale;
                updateTransform();
            }
        }, { passive: false });

        // Десктоп: перетаскивание зажатой мышью (pan)
        canvas.addEventListener('mousedown', (e) => {
            if (scale <= 1.0 && e.button !== 0) return;
            isDragging = true;
            startX = e.clientX - posX;
            startY = e.clientY - posY;
            canvas.style.cursor = 'grabbing';
        });

        window.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            posX = e.clientX - startX;
            posY = e.clientY - startY;
            updateTransform();
        });

        window.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                canvas.style.cursor = scale > 1.0 ? 'grab' : 'default';
                updateTransform();
            }
        });

        // Мобильный: сенсорный пинч двумя пальцами и перемещение одним
        canvas.addEventListener('touchstart', (e) => {
            if (e.touches.length === 1) {
                isDragging = true;
                touchStartX = e.touches[0].clientX - posX;
                touchStartY = e.touches[0].clientY - posY;
            } else if (e.touches.length === 2) {
                isDragging = false;
                const dx = e.touches[0].clientX - e.touches[1].clientX;
                const dy = e.touches[0].clientY - e.touches[1].clientY;
                initialPinchDistance = Math.hypot(dx, dy);
                initialScale = scale;
            }
        }, { passive: false });

        canvas.addEventListener('touchmove', (e) => {
            if (e.touches.length === 1 && isDragging && scale > 1.0) {
                e.preventDefault();
                posX = e.touches[0].clientX - touchStartX;
                posY = e.touches[0].clientY - touchStartY;
                updateTransform();
            } else if (e.touches.length === 2 && initialPinchDistance) {
                e.preventDefault();
                const dx = e.touches[0].clientX - e.touches[1].clientX;
                const dy = e.touches[0].clientY - e.touches[1].clientY;
                const currentDist = Math.hypot(dx, dy);
                const pinchRatio = currentDist / initialPinchDistance;
                scale = Math.min(Math.max(initialScale * pinchRatio, 1.0), 4.5);
                updateTransform();
            }
        }, { passive: false });

        canvas.addEventListener('touchend', (e) => {
            if (e.touches.length < 2) {
                initialPinchDistance = null;
            }
            if (e.touches.length === 0) {
                isDragging = false;
                updateTransform();
            }
        });

        canvas.addEventListener('dblclick', () => {
            if (scale > 1.0) reset();
            else { scale = 2.2; updateTransform(); }
        });

        return { reset, updateTransform };
    }

    // Инициализация инспекторов для сканера и каталога
    window.resultInspector = makeInteractiveInspector('result-inspector-canvas', 'wine-image', 'result-zoom-reset', 'result-zoom-in', 'result-zoom-out');
    window.detailInspector = makeInteractiveInspector('detail-inspector-canvas', 'detail-wine-img', 'detail-zoom-reset', 'detail-zoom-in', 'detail-zoom-out');

    // =========================================================================
    // 2. РЕНДЕРИНГ ШКАЛ ХАРАКТЕРИСТИК (СТИЛЬНЫЕ ПРОГРЕСС-БАРЫ)
    // =========================================================================
    function renderSensoryBarsHtml(vec) {
        if (!vec) return '';
        const acidity = Number(vec.acidity || 3.8);
        const tannins = Number(vec.tannins || 3.5);
        const body = Number(vec.body || 4.0);
        const sweetness = Number(vec.sweetness || 1.5);
        const oak = Number(vec.oak_intensity || 3.0);

        const items = [
            { label: 'Кислотность', val: acidity, desc: acidity >= 3.8 ? 'Яркая, освежающая' : 'Мягкая, сглаженная' },
            { label: 'Танинность', val: tannins, desc: tannins >= 3.5 ? 'Бархатные, структурные' : 'Шелковистые' },
            { label: 'Тело / Плотность', val: body, desc: body >= 3.8 ? 'Полнотелое, глубокое' : 'Средняя плотность' },
            { label: 'Сладость', val: sweetness, desc: sweetness >= 3.0 ? 'Десертное / Ликерное' : 'Сухое вино' },
            { label: 'Выдержка в дубе', val: oak, desc: oak >= 3.5 ? 'Благородный кавказский/французский дуб' : 'Легкая бочка' },
        ];

        return `
            <div class="sensory-bars-card">
                ${items.map(it => {
                    const pct = Math.min(Math.max((it.val / 5.0) * 100, 5), 100);
                    return `
                        <div class="sensory-meter-row">
                            <div class="sensory-meter-label">
                                <span class="sensory-meter-name">${it.label}</span>
                                <span class="sensory-meter-val">${it.val.toFixed(1)} / 5</span>
                            </div>
                            <div class="sensory-meter-track">
                                <div class="sensory-meter-fill" style="width: ${pct}%;"></div>
                            </div>
                            <div style="font-size: 10px; color: #868e96; text-align: right; margin-top: 1px;">${it.desc}</div>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    }

    // =========================================================================
    // 3. РЕНДЕРИНГ ЛОГИКИ СОМЕЛЬЕ И БЛЮД С ФОТО И РЕЦЕПТАМИ В СКАНЕРЕ
    // =========================================================================
    function renderScannerSommelierLogic(container, fullData, wine) {
        if (!container) return;
        const organo = (fullData && fullData.organoleptic) ? fullData.organoleptic : { acidity: 3.8, tannins: 3.5, body: 4.0 };
        const acidity = Number(organo.acidity || 3.8);
        const tannins = Number(organo.tannins || 3.5);
        const body = Number(organo.body || 4.0);

        let summaryLogic = "";
        if (tannins >= 2.8) {
            summaryLogic = `Вино обладает выраженной танинностью (${tannins.toFixed(1)}/5) и насыщенным телом (${body.toFixed(1)}/5). Танины мгновенно связываются с белком сочного мяса на гриле, устраняя вяжущее ощущение и раскрывая глубокие ягодные грани вкуса. Кислотность (${acidity.toFixed(1)}/5) освежает вкусовые рецепторы после каждого кусочка.`;
        } else {
            summaryLogic = `Вино отличается бодрящей кислотностью (${acidity.toFixed(1)}/5) и деликатным телом (${body.toFixed(1)}/5). Кислотность работает как свежий лимонный сок: деликатно балансирует жирность рыбы и морепродуктов, подчеркивая природную сладость блюда без тяжести.`;
        }

        const simpleDishes = (fullData && fullData.simple_dishes) ? fullData.simple_dishes : [];
        const unusualDishes = (fullData && fullData.unusual_dishes) ? fullData.unusual_dishes : [];
        const allDishes = [...simpleDishes, ...unusualDishes].slice(0, 3);

        container.innerHTML = `
            <div class="dish-wine-logic-box">
                <div style="font-weight: 700; color: #1a1a1a; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;">
                    <img src="img/glass_filled_straight.png" class="badge-icon-glass-mini" alt="">
                    Логика употребления от сомелье VINA
                </div>
                <p style="margin: 0; font-size: 13px; line-height: 1.55; color: #495057;">
                    ${summaryLogic}
                </p>
            </div>

            <div style="margin-top: 14px;">
                <div style="font-size: 14px; font-weight: 700; color: #1a1a1a; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between;">
                    <span>Рекомендованные блюда с фото и рецептом</span>
                    <span style="font-size: 11px; font-weight: 600; color: var(--primary);">Простые и необычные</span>
                </div>
                <div class="dishes-list-wrap" style="display: flex; flex-direction: column; gap: 12px;">
                    ${allDishes.map(d => `
                        <div class="dish-card-horizontal">
                            <div class="dish-card-img-wrap">
                                <img src="${d.image_url || 'img/dishes/steak_wine.jpg'}" alt="${d.title}" class="dish-card-img" onerror="this.src='badge_glass.png'">
                                <span class="dish-type-badge">${d.dish_type === 'simple' ? 'Простое' : 'Необычное'}</span>
                            </div>
                            <div class="dish-card-content">
                                <div class="dish-card-header">
                                    <h4 class="dish-card-title">${d.title}</h4>
                                    <span class="dish-prep-time">⏱ ${d.prep_time_min} мин</span>
                                </div>
                                <p class="dish-card-why"><b>Вкусовой баланс:</b> ${d.short_why}</p>
                                ${d.recipe_brief ? `
                                    <div class="dish-recipe-box">
                                        <strong>Краткий рецепт приготовления:</strong>
                                        <div style="margin-top: 3px;">${d.recipe_brief}</div>
                                    </div>
                                ` : ''}
                                ${d.wine_logic ? `
                                    <div style="font-size: 11px; color: #6c757d; margin-top: 5px;">
                                        <b>Логика сомелье:</b> ${d.wine_logic}
                                    </div>
                                ` : ''}
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // =========================================================================
    // 4. РЕЖИМ ПРОСМОТРА ВИНА ИЗ КАТАЛОГА (WINE DETAIL VIEW)
    // =========================================================================
    function renderGlassesStripHtml(score) {
        const s = Math.max(0, Math.min(5, parseFloat(score) || 0));
        let html = '';
        for (let i = 1; i <= 5; i++) {
            let fillPct = 0;
            if (s >= i) {
                fillPct = 100;
            } else if (s > i - 1) {
                fillPct = Math.round((s - (i - 1)) * 100);
            } else {
                fillPct = 0;
            }
            html += '<span class="fractional-glass-box" title="' + s + ' / 5">' +
                    '<img src="img/glass_empty_straight.png" class="glass-bg" alt="">' +
                    (fillPct > 0 ? '<span class="glass-fill-wrap" style="width: ' + fillPct + '%;"><img src="img/glass_filled_straight.png" class="glass-fg" alt=""></span>' : '') +
                    '</span>';
        }
        return html;
    }

    // =====================================================================
    // ИНТЕРАКТИВНЫЙ ЦИФРОВОЙ ИИ-СОМЕЛЬЕ (VINA AI SOMMELIER PROD)
    // =====================================================================
    window.sommChatSessionId = null;
    window.currentSommelierSlug = null;
    window.currentSommelierWineData = null;

    function escapeSommHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function formatSommMarkdown(rawText) {
        if (!rawText) return '';
        let escaped = escapeSommHtml(rawText);
        escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        const lines = escaped.split('\n');
        let inList = false;
        let outHtml = '';
        for (let line of lines) {
            const trim = line.trim();
            if (trim.startsWith('•') || trim.startsWith('-') || trim.startsWith('*')) {
                if (!inList) {
                    outHtml += '<ul style="margin: 6px 0; padding-left: 18px;">';
                    inList = true;
                }
                const content = trim.replace(/^[•\-\*]\s*/, '');
                outHtml += `<li style="margin-bottom: 3px;">${content}</li>`;
            } else {
                if (inList) {
                    outHtml += '</ul>';
                    inList = false;
                }
                if (trim.length > 0) {
                    outHtml += `<p style="margin: 0 0 6px 0;">${trim}</p>`;
                }
            }
        }
        if (inList) outHtml += '</ul>';
        return outHtml || escaped;
    }

    window.openSommelierEntryPoint = function(slug, wineData, initialTab = 'chat') {
        console.log('[SOMMELIER ENTRY POINT] Точка входа модуля Сомелье активирована:', slug, wineData, initialTab);
        window.currentSommelierSlug = slug;
        window.currentSommelierWineData = wineData;

        const isHomeOrAll = !slug || slug === 'main-home' || slug === 'all';
        const title = (wineData && (wineData.name || wineData.title))
            ? (wineData.name || wineData.title)
            : (document.getElementById('detail-wine-title')?.textContent || (isHomeOrAll ? 'Все вина каталога (2108 вин)' : slug));

        const nameEl = document.getElementById('somm-stub-wine-name');
        if (nameEl) {
            nameEl.textContent = title;
        }

        const welcomeEl = document.getElementById('somm-welcome-text');
        if (welcomeEl) {
            if (isHomeOrAll) {
                welcomeEl.textContent = 'Задайте любой вопрос по вину: с чем подать, какой у него вкусовой профиль, или попросите подобрать российские вина к вашему ужину.';
            } else {
                welcomeEl.innerHTML = `Вы открыли сомелье для вина <strong>${escapeSommHtml(title)}</strong>. Спросите о вкусе, кислотности, идеальной температуре подачи и гастрономических сочетаниях, или попросите подобрать похожие вина из каталога.`;
            }
        }

        // Переключаем на нужную вкладку
        window.switchSommModalTab(initialTab || 'chat');

        const modal = document.getElementById('sommelier-stub-modal');
        if (modal) {
            modal.style.display = 'flex';
        }
    };

    window.closeSommelierStubModal = function() {
        const modal = document.getElementById('sommelier-stub-modal');
        if (modal) {
            modal.style.display = 'none';
        }
    };

    window.openSommelierFromHome = function() {
        window.openSommelierEntryPoint('main-home', { name: 'Персональный ИИ-Сомелье' });
    };

    window.switchSommModalTab = function(tabName) {
        const tabs = ['chat', 'pairing', 'toast'];
        tabs.forEach(t => {
            const pill = document.getElementById(`somm-pill-${t}`);
            const view = document.getElementById(`somm-modal-view-${t}`);
            const isActive = (t === tabName);
            if (pill) {
                if (isActive) {
                    pill.classList.add('active');
                    pill.style.background = '#ffffff';
                    pill.style.color = '#722F37';
                    pill.style.boxShadow = '0 1px 4px rgba(0,0,0,0.06)';
                } else {
                    pill.classList.remove('active');
                    pill.style.background = 'transparent';
                    pill.style.color = '#6c757d';
                    pill.style.boxShadow = 'none';
                }
            }
            if (view) {
                view.style.display = isActive ? (t === 'chat' ? 'flex' : 'block') : 'none';
            }
        });
    };

    window.sendSommQuickQuery = function(text) {
        window.sendSommChatMessage(text);
    };

    window.resetSommChatSession = async function() {
        if (window.sommChatSessionId) {
            try {
                await fetch('/api/sommelier/reset', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: window.sommChatSessionId })
                });
            } catch (e) {
                console.warn('Sommelier reset error:', e);
            }
            window.sommChatSessionId = null;
        }

        const messagesBox = document.getElementById('somm-chat-messages');
        if (messagesBox) {
            const isHomeOrAll = !window.currentSommelierSlug || window.currentSommelierSlug === 'main-home';
            const title = document.getElementById('somm-stub-wine-name')?.textContent || 'каталога';
            messagesBox.innerHTML = `
                <div class="somm-msg somm-msg-assistant" style="display: flex; gap: 10px; align-items: flex-start;">
                    <div style="width: 32px; height: 32px; border-radius: 50%; background: #fdf2f4; border: 1px solid #f8d7da; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                        <img src="img/glass_filled_straight.png" style="width: 16px; height: 22px; object-fit: contain;" alt="">
                    </div>
                    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 4px 16px 16px 16px; padding: 12px 16px; font-size: 13.5px; line-height: 1.55; color: #212529; max-width: 90%;">
                        <p style="margin: 0 0 8px 0; font-weight: 600; color: #722F37;">Диалог очищен. Чем могу помочь?</p>
                        <p style="margin: 0;">${isHomeOrAll ? 'Задайте любой вопрос по вину: с чем подать, какой у него вкусовой профиль, или попросите подобрать российские аналоги к вашему ужину.' : `Я готов рассказать всё о вине <strong>${escapeSommHtml(title)}</strong>.`}</p>
                        <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px;">
                            <button type="button" class="somm-chip-btn" onclick="sendSommQuickQuery('С чем подать это вино?')">🍽 С чем подать?</button>
                            <button type="button" class="somm-chip-btn" onclick="sendSommQuickQuery('Опиши вкус, кислотность и танины')">🍷 Профиль вкуса</button>
                            <button type="button" class="somm-chip-btn" onclick="sendSommQuickQuery('Подбери 3 похожих российских вина')">🔄 Найти аналоги</button>
                            <button type="button" class="somm-chip-btn" onclick="sendSommQuickQuery('Стейк рибай, не люблю дуб')">🥩 Стейк без дуба</button>
                        </div>
                    </div>
                </div>
            `;
        }
    };

    window.sendSommChatMessage = async function(queryOverride) {
        const inputEl = document.getElementById('somm-chat-input');
        const query = (queryOverride || (inputEl ? inputEl.value : '')).trim();
        if (!query) return;

        if (inputEl) inputEl.value = '';

        const messagesBox = document.getElementById('somm-chat-messages');
        if (!messagesBox) return;

        // 1. Добавляем реплику пользователя
        const userMsg = document.createElement('div');
        userMsg.className = 'somm-msg somm-msg-user';
        userMsg.style.cssText = 'display: flex; justify-content: flex-end;';
        userMsg.innerHTML = `
            <div style="background: #722F37; color: #ffffff; border-radius: 16px 4px 16px 16px; padding: 10px 15px; font-size: 13.5px; max-width: 85%; line-height: 1.45; word-break: break-word; box-shadow: 0 2px 6px rgba(114,47,55,0.15);">
                ${escapeSommHtml(query)}
            </div>
        `;
        messagesBox.appendChild(userMsg);

        // 2. Индикатор набора / поиска
        const typingEl = document.createElement('div');
        typingEl.id = 'somm-typing-indicator';
        typingEl.className = 'somm-msg somm-msg-assistant';
        typingEl.style.cssText = 'display: flex; gap: 10px; align-items: center;';
        typingEl.innerHTML = `
            <div style="width: 32px; height: 32px; border-radius: 50%; background: #fdf2f4; border: 1px solid #f8d7da; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                <img src="img/glass_filled_straight.png" style="width: 16px; height: 22px; object-fit: contain;">
            </div>
            <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 4px 16px 16px 16px; padding: 8px 14px; font-size: 12.5px; color: #6c757d; display: flex; align-items: center; gap: 8px;">
                <span class="somm-spinner"></span> Сомелье анализирует реестр 2108 вин...
            </div>
        `;
        messagesBox.appendChild(typingEl);
        messagesBox.scrollTop = messagesBox.scrollHeight;

        try {
            const payload = {
                message: query,
                session_id: window.sommChatSessionId || undefined,
                wine_slug: (window.currentSommelierSlug && window.currentSommelierSlug !== 'main-home' ? window.currentSommelierSlug : null)
            };

            const res = await fetch('/api/sommelier/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (document.getElementById('somm-typing-indicator')) {
                document.getElementById('somm-typing-indicator').remove();
            }

            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }

            const data = await res.json();
            if (data.session_id) {
                window.sommChatSessionId = data.session_id;
            }

            // Формируем блок ответа
            const asstMsg = document.createElement('div');
            asstMsg.className = 'somm-msg somm-msg-assistant';
            asstMsg.style.cssText = 'display: flex; gap: 10px; align-items: flex-start;';

            let picksHtml = '';
            if (data.picks && data.picks.length > 0) {
                picksHtml = '<div style="display: flex; flex-direction: column; gap: 8px; margin-top: 10px;">';
                data.picks.forEach(p => {
                    const imgUrl = p.image_url || 'img/glass_filled_straight.png';
                    const scoreVal = typeof p.score === 'number' ? Math.round(p.score) : p.score;
                    picksHtml += `
                        <div class="somm-wine-card-item" style="border: 1px solid #e9ecef; border-radius: 12px; padding: 10px 12px; display: flex; gap: 12px; align-items: center; background: #ffffff;">
                            <img src="${imgUrl}" style="width: 38px; height: 56px; object-fit: contain; border-radius: 4px;" onerror="this.src='img/glass_filled_straight.png'">
                            <div style="flex: 1; min-width: 0;">
                                <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px;">
                                    <div style="font-weight: 700; font-size: 13.5px; color: #1a1a1a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeSommHtml(p.name)}</div>
                                    <span style="background: #e8f5e9; color: #2e7d32; font-weight: 700; font-size: 10.5px; padding: 2px 7px; border-radius: 8px; white-space: nowrap;">${scoreVal}%</span>
                                </div>
                                <div style="font-size: 11.5px; color: #6c757d; margin: 2px 0 4px 0;">
                                    ${escapeSommHtml(p.winery || '')} &bull; ${escapeSommHtml(p.region || '')} &bull; ${escapeSommHtml(p.grape || '')}
                                </div>
                                ${p.quote ? `<div style="font-size: 11px; color: #495057; font-style: italic; line-height: 1.35; margin-bottom: 6px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;">«${escapeSommHtml(p.quote)}»</div>` : ''}
                                <button type="button" onclick="openWineDetail('${p.id}'); closeSommelierStubModal();" style="background: #722F37; color: #ffffff; border: none; border-radius: 6px; padding: 4px 10px; font-size: 11.5px; font-weight: 600; cursor: pointer;">
                                    Открыть в каталоге &rarr;
                                </button>
                            </div>
                        </div>
                    `;
                });
                picksHtml += '</div>';
            }

            let noteHtml = '';
            if (data.note) {
                noteHtml = `<div style="margin-top: 8px; font-size: 11px; color: #8c98a4; font-style: italic; border-top: 1px dashed #dee2e6; padding-top: 6px;">${escapeSommHtml(data.note)}</div>`;
            }

            asstMsg.innerHTML = `
                <div style="width: 32px; height: 32px; border-radius: 50%; background: #fdf2f4; border: 1px solid #f8d7da; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                    <img src="img/glass_filled_straight.png" style="width: 16px; height: 22px; object-fit: contain;">
                </div>
                <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 4px 16px 16px 16px; padding: 12px 16px; font-size: 13.5px; line-height: 1.55; color: #212529; max-width: 90%;">
                    ${formatSommMarkdown(data.text || '')}
                    ${picksHtml}
                    ${noteHtml}
                </div>
            `;
            messagesBox.appendChild(asstMsg);

        } catch (err) {
            console.error('Sommelier error:', err);
            if (document.getElementById('somm-typing-indicator')) {
                document.getElementById('somm-typing-indicator').remove();
            }
            const errEl = document.createElement('div');
            errEl.className = 'somm-msg somm-msg-assistant';
            errEl.style.cssText = 'display: flex; gap: 10px; align-items: flex-start;';
            errEl.innerHTML = `
                <div style="width: 32px; height: 32px; border-radius: 50%; background: #fdf2f4; border: 1px solid #f8d7da; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                    <img src="img/glass_filled_straight.png" style="width: 16px; height: 22px; object-fit: contain;">
                </div>
                <div style="background: #fff5f5; border: 1px solid #fed7d7; border-radius: 4px 16px 16px 16px; padding: 12px 16px; font-size: 13px; color: #c53030;">
                    Не удалось получить ответ от сомелье. Проверьте соединение и попробуйте еще раз.
                </div>
            `;
            messagesBox.appendChild(errEl);
        }

        messagesBox.scrollTop = messagesBox.scrollHeight;
    };

    // Подбор к блюду
    window.runSommPairingFast = function(dishName) {
        const input = document.getElementById('somm-pairing-custom-dish');
        if (input) input.value = dishName;
        window.runSommPairingCustom();
    };

    window.runSommPairingCustom = async function() {
        const input = document.getElementById('somm-pairing-custom-dish');
        const dish = (input ? input.value : '').trim();
        if (!dish) return;

        const resultsBox = document.getElementById('somm-pairing-results-box');
        if (!resultsBox) return;

        resultsBox.innerHTML = `
            <div style="text-align: center; padding: 24px; color: #6c757d;">
                <span class="somm-spinner" style="width: 22px; height: 22px; border-width: 3px; margin-bottom: 8px;"></span>
                <div style="font-size: 13.5px; font-weight: 500;">Анализ гастрономической совместимости...</div>
                <div style="font-size: 12px; color: #adb5bd; margin-top: 4px;">Сопоставление жирности, кислотности и танинов блюда с 2108 винами</div>
            </div>
        `;

        try {
            const isAnalog = dish.toLowerCase().includes('аналог') || dish.toLowerCase().includes('замена');
            const res = await fetch('/api/sommelier/pairing/dish', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: dish,
                    scenario: isAnalog ? 'analog' : 'dish'
                })
            });

            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            let profileHtml = '';
            if (data.dish_profile && data.dish_profile.dish) {
                const dp = data.dish_profile;
                profileHtml = `
                    <div style="background: #fdf2f4; border: 1px solid #f8d7da; border-radius: 12px; padding: 10px 14px; margin-bottom: 12px;">
                        <div style="font-size: 13px; font-weight: 700; color: #722F37;">🍽 Блюдо: ${escapeSommHtml(dp.dish || dish)}</div>
                        <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px;">
                            ${dp.weight ? `<span style="background: #ffffff; border: 1px solid #f8d7da; padding: 2px 7px; border-radius: 8px; font-size: 11px; color: #495057;">Вес: ${escapeSommHtml(dp.weight)}</span>` : ''}
                            ${dp.fat ? `<span style="background: #ffffff; border: 1px solid #f8d7da; padding: 2px 7px; border-radius: 8px; font-size: 11px; color: #495057;">Жирность: ${escapeSommHtml(dp.fat)}</span>` : ''}
                            ${dp.acid ? `<span style="background: #ffffff; border: 1px solid #f8d7da; padding: 2px 7px; border-radius: 8px; font-size: 11px; color: #495057;">Кислотность: ${escapeSommHtml(dp.acid)}</span>` : ''}
                        </div>
                    </div>
                `;
            }

            let explHtml = '';
            if (data.explanation) {
                explHtml = `
                    <div style="font-size: 13px; color: #495057; line-height: 1.5; margin-bottom: 14px; background: #f8f9fa; border-radius: 10px; padding: 10px 12px; border-left: 3px solid #722F37;">
                        ${formatSommMarkdown(data.explanation)}
                    </div>
                `;
            }

            let winesHtml = '';
            if (data.wines && data.wines.length > 0) {
                winesHtml = '<div style="display: flex; flex-direction: column; gap: 10px;">';
                data.wines.forEach(w => {
                    const img = w.image_url || 'img/glass_filled_straight.png';
                    const score = Math.round(w.score || 0);
                    const role = w.role_label || 'Рекомендация';
                    const note = w.story || w.explanation || '';
                    winesHtml += `
                        <div class="somm-wine-card-item">
                            <img src="${img}" style="width: 44px; height: 68px; object-fit: contain;" onerror="this.src='img/glass_filled_straight.png'">
                            <div style="flex: 1; min-width: 0;">
                                <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px;">
                                    <div style="font-weight: 700; font-size: 14px; color: #1a1a1a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeSommHtml(w.name)}</div>
                                    <span style="background: #e8f5e9; color: #2e7d32; font-weight: 700; font-size: 11px; padding: 2px 8px; border-radius: 10px;">${score}%</span>
                                </div>
                                <div style="font-size: 11.5px; color: #6c757d; margin: 2px 0 4px 0;">
                                    ${escapeSommHtml(w.producer || '')} &bull; ${escapeSommHtml(w.region || '')} &bull; ${escapeSommHtml(w.grape || '')}
                                </div>
                                <div style="display: inline-block; background: #fdf2f4; color: #722F37; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 8px; margin-bottom: 4px;">
                                    ${escapeSommHtml(role)}
                                </div>
                                ${note ? `<div style="font-size: 11.5px; color: #495057; line-height: 1.35; margin-bottom: 6px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;">${escapeSommHtml(note)}</div>` : ''}
                                <button type="button" onclick="openWineDetail('${w.slug}'); closeSommelierStubModal();" style="background: #722F37; color: #ffffff; border: none; border-radius: 8px; padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer;">
                                    Перейти к вину &rarr;
                                </button>
                            </div>
                        </div>
                    `;
                });
                winesHtml += '</div>';
            } else {
                winesHtml = '<div style="color: #6c757d; font-size: 13px; text-align: center; padding: 16px;">Вин под этот запрос не найдено. Попробуйте изменить название блюда.</div>';
            }

            resultsBox.innerHTML = profileHtml + explHtml + winesHtml;

        } catch (err) {
            console.error('Pairing error:', err);
            resultsBox.innerHTML = `
                <div style="background: #fff5f5; border: 1px solid #fed7d7; border-radius: 10px; padding: 12px; color: #c53030; font-size: 13px;">
                    Ошибка при подборе вина к блюду. Проверьте запрос и попробуйте снова.
                </div>
            `;
        }
    };

    // Тосты и авторские советы
    window.runSommModalToast = async function() {
        const occEl = document.getElementById('somm-modal-toast-occasion');
        const occasion = occEl ? occEl.value : 'friends';
        const slug = (window.currentSommelierSlug && window.currentSommelierSlug !== 'main-home')
            ? window.currentSommelierSlug
            : 'loco-cimbali-blanc-de-neige-shardone-beloe-suhoe-131';

        const resultsBox = document.getElementById('somm-modal-toast-results-box');
        if (!resultsBox) return;

        resultsBox.innerHTML = `
            <div style="text-align: center; padding: 24px; color: #6c757d;">
                <span class="somm-spinner" style="width: 22px; height: 22px; border-width: 3px; margin-bottom: 8px;"></span>
                <div style="font-size: 13.5px; font-weight: 500;">Составление тоста и рекомендаций...</div>
            </div>
        `;

        try {
            const res = await fetch('/api/v2/sommelier/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ occasion: occasion, wine_slug: slug })
            });

            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            let toastHtml = '';
            if (data.toast) {
                const t = data.toast;
                const safeToastText = escapeSommHtml(t.toast_text || '').replace(/'/g, "\\'");
                toastHtml = `
                    <div class="somm-quote-card">
                        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                            <div style="font-weight: 700; color: #856404; font-size: 14px;">${escapeSommHtml(t.toast_title || '🥂 Авторский тост')}</div>
                            <button type="button" id="btn-copy-toast" onclick="navigator.clipboard.writeText('${safeToastText}'); this.textContent='✓ Скопировано!'; setTimeout(()=>this.textContent='Скопировать', 2000);" style="background: #ffffff; border: 1px solid #eedcba; border-radius: 6px; padding: 3px 8px; font-size: 11px; cursor: pointer; color: #856404; font-weight: 600;">
                                Скопировать
                            </button>
                        </div>
                        <div style="font-size: 13.5px; line-height: 1.55; color: #382d13; font-style: italic;">
                            «${escapeSommHtml(t.toast_text || '')}»
                        </div>
                    </div>
                `;

                if (t.sommelier_advice) {
                    toastHtml += `
                        <div class="somm-advice-card">
                            <div style="font-weight: 700; color: #1e3a8a; font-size: 13px; margin-bottom: 4px;">💡 Совет сомелье по подаче</div>
                            <div>${formatSommMarkdown(t.sommelier_advice)}</div>
                        </div>
                    `;
                }
            }

            let similarHtml = '';
            if (data.recommended_catalog_wines && data.recommended_catalog_wines.length > 0) {
                similarHtml = `
                    <div style="margin-top: 14px;">
                        <h5 style="margin: 0 0 8px 0; font-size: 13px; color: #495057; font-weight: 700;">🍷 Близнецы по вкусовому профилю в каталоге:</h5>
                        <div style="display: flex; flex-direction: column; gap: 8px;">
                `;
                data.recommended_catalog_wines.forEach(w => {
                    similarHtml += `
                        <div class="somm-wine-card-item">
                            <div style="flex: 1; min-width: 0;">
                                <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px;">
                                    <div style="font-weight: 700; font-size: 13px; color: #1a1a1a;">${escapeSommHtml(w.wine_name)}</div>
                                    <span style="background: #e8f5e9; color: #2e7d32; font-weight: 700; font-size: 10.5px; padding: 2px 7px; border-radius: 8px;">${w.similarity_percent}% сходство</span>
                                </div>
                                <div style="font-size: 11.5px; color: #6c757d; margin: 2px 0;">${escapeSommHtml(w.comparison_note || '')}</div>
                                <button type="button" onclick="openWineDetail('${w.wine_slug}'); closeSommelierStubModal();" style="background: #722F37; color: #ffffff; border: none; border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 600; cursor: pointer; margin-top: 4px;">
                                    Открыть в каталоге &rarr;
                                </button>
                            </div>
                        </div>
                    `;
                });
                similarHtml += '</div></div>';
            }

            resultsBox.innerHTML = toastHtml + similarHtml;

        } catch (err) {
            console.error('Toast error:', err);
            resultsBox.innerHTML = `
                <div style="background: #fff5f5; border: 1px solid #fed7d7; border-radius: 10px; padding: 12px; color: #c53030; font-size: 13px;">
                    Ошибка при генерации тоста. Попробуйте еще раз.
                </div>
            `;
        }
    };

    window.openWineDetail = async function(slug, source = 'catalog') {
        window.wineDetailSource = source;
        if (typeof switchHubTab === 'function') {
            switchHubTab('catalog');
        }
        const mainView = document.getElementById('catalog-main-view');
        const detailView = document.getElementById('catalog-detail-view');
        if (!detailView) return;

        window.currentDetailWineSlug = slug;

        // Переключаем шапку: скрываем бренд, показываем Артикул + Поделиться
        const brandEl = document.getElementById('header-center-brand');
        const detailHdrEl = document.getElementById('header-center-detail');
        const stickyBar = document.getElementById('detail-sticky-action-bar');
        if (brandEl) brandEl.style.display = 'none';
        if (detailHdrEl) detailHdrEl.style.display = 'flex';
        if (stickyBar) stickyBar.classList.add('visible');

        // Артикул
        const artNum = Math.abs(slug.split('').reduce((acc, c) => (acc << 5) - acc + c.charCodeAt(0), 0)) % 900000 + 100000;
        const artEl = document.getElementById('detail-header-article');
        if (artEl) artEl.textContent = 'Арт. ' + artNum;

        // Настройка заголовков возврата
        const backTxt = document.getElementById('detail-back-text');
        const origPhotoBtn = document.getElementById('btn-detail-original-photo');
        if (backTxt) {
            if (source === 'scanner') backTxt.textContent = 'Назад к сканеру';
            else if (source === 'home') backTxt.textContent = 'Назад на главную';
            else backTxt.textContent = 'Назад в каталог';
        }
        if (origPhotoBtn) {
            const origImg = document.getElementById('original-img');
            const hasPhoto = (origImg && origImg.src && origImg.src.length > 5 && !origImg.src.endsWith('/'));
            origPhotoBtn.style.display = (source === 'scanner' && hasPhoto) ? 'inline-flex' : 'none';
        }

        if (mainView) mainView.style.display = 'none';
        detailView.style.display = 'block';
        window.scrollTo({ top: 0, behavior: 'smooth' });

        if (window.detailInspector) window.detailInspector.reset();

        document.getElementById('detail-wine-title').textContent = 'Загрузка карточки вина...';
        document.getElementById('detail-wine-winery').textContent = '';
        document.getElementById('detail-wine-description').textContent = '';
        document.getElementById('detail-wine-img').src = apiUrl(`/api/image/${slug}`);
        document.getElementById('detail-wine-history-block').style.display = 'none';
        const histTopPill = document.getElementById('detail-history-pill-top');
        if (histTopPill) histTopPill.innerHTML = '';

        if (typeof updateDetailFavState === 'function') {
            updateDetailFavState(slug);
        }

        try {
            let wineData = null;
            let fullData = null;
            try {
                const res = await fetch(apiUrl(`/api/v2/wine/${slug}/full-sommelier`));
                if (res.ok) {
                    fullData = await res.json();
                    wineData = fullData.wine;
                }
            } catch(e) { console.warn(e); }

            if (!wineData) {
                try {
                    const res = await fetch(apiUrl(`/api/wine/${slug}`));
                    if (res.ok) wineData = await res.json();
                } catch(e) {}
            }

            // Фоллбэк из локальных вин при открытии без запущенного бэкенда
            if (!wineData) {
                const localList = (window.HOME_POPULAR_ROW_1 || []).concat(window.HOME_POPULAR_ROW_2 || []);
                const found = localList.find(w => w.slug === slug);
                if (found) {
                    wineData = {
                        name: found.title,
                        winery: found.title.includes(' ') ? found.title.split(' ')[0] : 'Винодельня России',
                        alcohol: '13.1% об.',
                        color: found.meta.includes('белое') ? 'Белое' : (found.meta.includes('розовое') ? 'Розовое' : 'Красное'),
                        sweetness: found.meta.includes('сухое') ? 'Сухое' : (found.meta.includes('брют') ? 'Брют' : 'Полусухое'),
                        region: found.meta.includes('Крым') ? 'Крым' : (found.meta.includes('Кубань') ? 'Кубань' : 'Россия'),
                        grape: 'Шардоне',
                        description: 'Изящное российское вино с гармоничным органолептическим профилем, минеральной свежестью и долгим выразительным послевкусием.',
                        rating: found.rating || '4.5',
                        price: found.price || 2090
                    };
                } else {
                    wineData = {
                        name: 'Loco Cimbali Blanc de Neige',
                        winery: 'Loco Cimbali',
                        alcohol: '13.1% об.',
                        color: 'Белое',
                        sweetness: 'Сухое',
                        region: 'Крым',
                        grape: 'Шардоне',
                        description: 'Изящное российское вино с богатым органолептическим букетом и гармоничным послевкусием.',
                        rating: '4.5',
                        price: 2090
                    };
                }
            }

            window.currentDetailWinePrice = wineData.price || 2090;

            const detailImg = document.getElementById('detail-wine-img');
            if (detailImg) {
                if (wineData.image_url && wineData.image_url.startsWith('http')) {
                    detailImg.src = wineData.image_url;
                } else if (wineData.remote_image_url && wineData.remote_image_url.startsWith('http')) {
                    detailImg.onerror = function() {
                        this.onerror = null;
                        this.src = wineData.remote_image_url;
                    };
                }
            }

            const wineTitle = wineData.name || wineData.title || slug;
            const wineryName = wineData.winery || (typeof wineTitle === 'string' && wineTitle.includes(' ') ? wineTitle.split(' ')[0] : 'Винодельня России');
            const titleEl = document.getElementById('detail-wine-title');
            if (titleEl) titleEl.textContent = wineTitle;

            const wineryEl = document.getElementById('detail-wine-winery');
            if (wineryEl) wineryEl.textContent = wineryName;

            const alcEl = document.getElementById('detail-wine-alcohol');
            if (alcEl) alcEl.textContent = wineData.alcohol ? (String(wineData.alcohol).includes('об') ? wineData.alcohol : `${wineData.alcohol} об.`) : '13.1% об.';

            const colEl = document.getElementById('detail-wine-color');
            if (colEl) colEl.textContent = wineData.color || 'Белое';

            const sugEl = document.getElementById('detail-wine-sugar');
            if (sugEl) sugEl.textContent = wineData.sugar || wineData.sweetness || 'Сухое';

            const regEl = document.getElementById('detail-wine-region');
            if (regEl) regEl.textContent = wineData.region || 'Крым';

            const grpEl = document.getElementById('detail-wine-grape');
            if (grpEl) grpEl.textContent = wineData.grape ? (wineData.grape.startsWith('Сорт:') ? wineData.grape : `Сорт: ${wineData.grape}`) : 'Сорт: Шардоне';

            const descEl = document.getElementById('detail-wine-description');
            if (descEl) descEl.textContent = wineData.description || 'Аутентичное российское вино с богатым органолептическим букетом и терруарным характером.';

            const score = wineData.rating ? parseFloat(wineData.rating).toFixed(1) : '4.5';
            const totalVotes = Math.max(12, Math.round((parseFloat(score) * 28) + (slug.length * 3)));
            
            const badgeScoreEl = document.getElementById('detail-badge-score');
            if (badgeScoreEl) badgeScoreEl.textContent = score.replace('.', ',');
            const badgeVotesEl = document.getElementById('detail-badge-votes');
            if (badgeVotesEl) badgeVotesEl.textContent = totalVotes;

            const stripEl = document.getElementById('detail-glasses-strip');
            if (stripEl) stripEl.innerHTML = renderGlassesStripHtml(score);

            initDetailRating(slug);

            const hist = fullData ? fullData.history : null;
            const histBlock = document.getElementById('detail-wine-history-block');
            if (hist) {
                histBlock.style.display = 'block';
                document.getElementById('detail-wine-history-year').textContent = `Год создания: ${hist.creation_year}`;
                document.getElementById('detail-wine-history-headline').textContent = hist.headline;
                document.getElementById('detail-wine-history-text').textContent = hist.legend_summary;
                
                const evBox = document.getElementById('detail-wine-history-events');
                if (evBox && hist.historical_events) {
                    evBox.innerHTML = hist.historical_events.map(ev => `
                        <div style="margin-top: 6px; padding: 8px 10px; background: rgba(255,255,255,0.7); border-radius: 8px; font-size: 12px; color: #333;">
                            <strong style="color: var(--primary);">${ev.era_year}: ${ev.title}</strong>
                            <div style="margin-top: 2px;">${ev.story}</div>
                        </div>
                    `).join('');
                }
                if (histTopPill) {
                    histTopPill.innerHTML = `
                        <span class="cat-chip gold-badge" onclick="openWineHistoryModal('${slug}')" style="cursor: pointer; padding: 6px 12px; font-size: 12px;">
                            <img src="img/glass_filled_straight.png" class="badge-icon-glass-mini" alt=""> История вина
                        </span>
                    `;
                }
            } else {
                histBlock.style.display = 'none';
                if (histTopPill) histTopPill.innerHTML = '';
            }

            const organo = (fullData && fullData.organoleptic) ? fullData.organoleptic : {
                acidity: 3.8, tannins: 3.5, body: 4.2, sweetness: 1.5, oak_intensity: 3.2
            };
            const sensoryBox = document.getElementById('detail-sensory-bars');
            if (sensoryBox) sensoryBox.innerHTML = renderSensoryBarsHtml(organo);

            // Привязываем кнопки постоянной панели
            const btnStickySomm = document.getElementById('btn-detail-sticky-somm');
            if (btnStickySomm) {
                btnStickySomm.onclick = () => window.openSommelierEntryPoint(slug, wineData);
            }
            const btnStickyMap = document.getElementById('btn-detail-sticky-map');
            if (btnStickyMap) {
                btnStickyMap.onclick = () => {
                    if (typeof window.findStoresForCurrentWine === 'function') {
                        window.findStoresForCurrentWine();
                    } else if (typeof window.switchHubTab === 'function') {
                        window.switchHubTab('map');
                    }
                };
            }

        } catch(err) {
            console.error(err);
            document.getElementById('detail-wine-title').textContent = 'Ошибка загрузки карточки вина';
        }
    };

    window.closeWineDetail = function() {
        const mainView = document.getElementById('catalog-main-view');
        const detailView = document.getElementById('catalog-detail-view');
        if (detailView) detailView.style.display = 'none';
        if (mainView) mainView.style.display = 'block';

        const brandEl = document.getElementById('header-center-brand');
        const detailHdrEl = document.getElementById('header-center-detail');
        const stickyBar = document.getElementById('detail-sticky-action-bar');
        if (brandEl) brandEl.style.display = 'flex';
        if (detailHdrEl) detailHdrEl.style.display = 'none';
        if (stickyBar) stickyBar.classList.remove('visible');
    };

        function initDetailRating(slug) {
        const container = document.getElementById('detail-glasses-container');
        if (!container) return;

        const userRatingText = document.getElementById('detail-user-rating-text');
        const totalVotesEl = document.getElementById('detail-total-votes');
        const avgScoreEl = document.getElementById('detail-avg-score');
        const badgeScoreEl = document.getElementById('detail-badge-score');
        const badgeVotesEl = document.getElementById('detail-badge-votes');
        const detailBadge = document.getElementById('detail-rating-badge');
        const detailSection = document.getElementById('detail-rating-section');

        if (detailBadge && detailSection) {
            detailBadge.onclick = () => {
                detailSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
            };
        }

        let globalStats = JSON.parse(localStorage.getItem('vina_global_ratings')) || {};
        if (!globalStats[slug]) {
            globalStats[slug] = { total: 15, sum: 67 };
        }

        let currentRating = parseInt(localStorage.getItem('vina_rating_' + slug) || '0', 10);
        const slots = container.querySelectorAll('.glass-slot');

        function updateGlasses(rating) {
            const stats = globalStats[slug] || { total: 15, sum: 67 };
            const avg = (stats.sum / stats.total).toFixed(1);

            if (avgScoreEl) avgScoreEl.textContent = avg;
            if (totalVotesEl) totalVotesEl.textContent = stats.total;
            if (badgeScoreEl) badgeScoreEl.textContent = avg.replace('.', ',');
            if (badgeVotesEl) badgeVotesEl.textContent = stats.total;
            const stripEl = document.getElementById('detail-glasses-strip');
            if (stripEl) stripEl.innerHTML = renderGlassesStripHtml(avg);

            if (userRatingText) {
                userRatingText.textContent = rating > 0 ? `Ваша оценка: ${rating} из 5` : 'Ваша оценка: - из 5';
            }

            slots.forEach((slot, index) => {
                const idx = index + 1;
                const img = slot.querySelector('.glass-img');
                if (idx <= rating) {
                    slot.classList.add('active-bg');
                    if (img) img.src = 'img/glass_filled_straight.png';
                } else {
                    slot.classList.remove('active-bg');
                    if (img) img.src = 'img/glass_empty_straight.png';
                }
            });
        }

        updateGlasses(currentRating);

        slots.forEach((slot, index) => {
            const idx = index + 1;

            slot.onmouseenter = () => {
                slots.forEach((s, i) => {
                    if (i <= index) {
                        s.classList.add('active-bg');
                    } else if (i + 1 > currentRating) {
                        s.classList.remove('active-bg');
                    }
                });
            };

            slot.onmouseleave = () => {
                updateGlasses(currentRating);
            };

            const handleRate = (e) => {
                if (e.type === 'touchend') e.preventDefault();
                e.stopPropagation();

                if (currentRating > 0) {
                    globalStats[slug].sum -= currentRating;
                } else {
                    globalStats[slug].total += 1;
                }

                currentRating = idx;
                globalStats[slug].sum += currentRating;

                localStorage.setItem('vina_rating_' + slug, currentRating);
                localStorage.setItem('vina_global_ratings', JSON.stringify(globalStats));

                updateGlasses(currentRating);
                showToast(`Спасибо! Ваша оценка: ${idx} из 5`);
            };

            slot.onclick = handleRate;
            slot.ontouchend = handleRate;
        });
    }

    // =========================================================================
    // 5. МОДАЛЬНОЕ ОКНО НЕДОСТАЮЩЕГО ВИНА
    // =========================================================================
    function showMissingWineModal(msg) {
        const modal = document.getElementById('missing-wine-modal');
        const msgEl = document.getElementById('missing-wine-message');
        if (msgEl && msg) msgEl.textContent = msg;
        if (modal) modal.style.display = 'flex';
    }

    window.closeMissingWineModal = function() {
        const modal = document.getElementById('missing-wine-modal');
        if (modal) modal.style.display = 'none';
    };

    window.logMissingWineQuery = async function(q) {
        try {
            await fetch(apiUrl('/api/missing-wines/report'), {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ source: 'catalog_search', query_text: q })
            });
            showToast('Запрос передан администрации сервиса');
        } catch(e) {
            console.warn(e);
            showToast('Запрос сохранен');
        }
    };

    // =========================================================================
    // 6. ДАШБОРД СЕРВИСА (ОБРАБОТКА ЗАПРОСОВ И ПОПОЛНЕНИЕ БАЗЫ)
    // =========================================================================
    window.openAdminDashboard = function() {
        const modal = document.getElementById('admin-dashboard-modal');
        if (modal) {
            modal.style.display = 'flex';
            loadAdminDashboardData();
        }
    };

    window.closeAdminDashboard = function() {
        const modal = document.getElementById('admin-dashboard-modal');
        if (modal) modal.style.display = 'none';
    };

    window.loadAdminDashboardData = async function() {
        const list = document.getElementById('dashboard-feed-list');
        list.innerHTML = '<div style="text-align: center; padding: 25px; color: #6c757d;"><div class="spinner"></div><p style="margin-top:8px;">Загрузка данных...</p></div>';

        try {
            const res = await fetch(apiUrl('/api/admin/dashboard/missing-wines'));
            if (!res.ok) throw new Error('Ошибка связи с сервером');
            const data = await res.json();

            document.getElementById('metric-total').textContent = data.total_count || 0;
            document.getElementById('metric-pending').textContent = data.pending_count || 0;
            document.getElementById('metric-in-progress').textContent = data.in_progress_count || 0;
            document.getElementById('metric-resolved').textContent = data.resolved_count || 0;

            const requests = data.requests || [];
            if (requests.length === 0) {
                list.innerHTML = '<div style="text-align: center; padding: 30px; color: #6c757d;">Пока нет зарегистрированных запросов на добавление вин.</div>';
                return;
            }

            list.innerHTML = requests.map(r => {
                const hasImg = !!r.image_url;
                const imgSrc = hasImg ? apiUrl(r.image_url) : 'badge_glass.png';
                const statusLabel = r.status === 'resolved' ? 'В базе' : (r.status === 'in_progress' ? 'В обработке' : 'Ожидает');
                const statusClass = r.status === 'resolved' ? 'badge-resolved' : (r.status === 'in_progress' ? 'badge-in-progress' : 'badge-pending');

                return `
                    <div class="dashboard-feed-item">
                        <img src="${imgSrc}" class="dashboard-feed-thumb" alt="" onerror="this.src='badge_glass.png'">
                        <div class="dashboard-feed-info">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                <span class="dashboard-status-tag ${statusClass}">${statusLabel}</span>
                                <span style="font-size: 11px; color: #868e96;">${r.timestamp}</span>
                            </div>
                            <div style="font-size: 13px; font-weight: 600; color: #1a1a1a;">
                                Источник: ${r.source === 'scanner' ? 'Сканер камеры' : 'Поиск каталога'}
                            </div>
                            ${r.query_text ? `<div style="font-size: 12px; color: #495057; margin-top: 3px; word-break: break-word;">${r.query_text}</div>` : ''}
                            ${r.confidence ? `<div style="font-size: 11px; color: #868e96; margin-top: 2px;">Уверенность OCR: ${r.confidence}%</div>` : ''}
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 6px;">
                            <button onclick="updateMissingWineStatus('${r.id}', 'in_progress')" class="btn btn-secondary" style="font-size: 10px; padding: 4px 8px;">В обработку</button>
                            <button onclick="updateMissingWineStatus('${r.id}', 'resolved')" class="btn btn-primary" style="font-size: 10px; padding: 4px 8px;">Добавлено</button>
                        </div>
                    </div>
                `;
            }).join('');
        } catch(err) {
            console.error(err);
            list.innerHTML = '<div style="color: #c92a2a; text-align: center; padding: 20px;">Не удалось загрузить данные дашборда.</div>';
        }
    };

    window.updateMissingWineStatus = async function(reqId, newStatus) {
        try {
            const res = await fetch(apiUrl(`/api/admin/dashboard/missing-wines/${reqId}/status`), {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ status: newStatus })
            });
            if (res.ok) {
                showToast('Статус запроса обновлен');
                loadAdminDashboardData();
            }
        } catch(e) {
            console.warn(e);
            showToast('Ошибка обновления статуса');
        }
    };

    // Привязка кнопки дашборда в шапке
    const btnOpenDash = document.getElementById('btn-open-dashboard');
    if (btnOpenDash) {
        btnOpenDash.addEventListener('click', window.openAdminDashboard);
    }
});

    // =========================================================================
    // 6. УПРАВЛЕНИЕ КОРЗИНОЙ И ОФОРМЛЕНИЕ ЗАКАЗА
    // =========================================================================
    window.getCartItems = function() {
        let cart = [];
        try {
            cart = JSON.parse(localStorage.getItem('vina_cart') || '[]');
        } catch(e) { cart = []; }
        if (!Array.isArray(cart)) cart = [];
        return cart.map(item => ({
            slug: item.slug || 'wine',
            title: item.title || 'Свое вино',
            winery: item.winery || '',
            price: typeof item.price === 'number' ? item.price : (parseInt(item.price, 10) || 2090),
            qty: typeof item.qty === 'number' && item.qty > 0 ? item.qty : 1,
            checked: item.checked !== false, // по умолчанию галочки стоят
            img: item.img || '',
            meta: item.meta || 'Российское вино · 0.75 л'
        }));
    };

    window.saveCartItems = function(items) {
        try {
            localStorage.setItem('vina_cart', JSON.stringify(items));
        } catch(e) { console.warn(e); }
        window.updateCartBadge();
    };

    window.updateCartBadge = function() {
        let count = 0;
        try {
            const cart = window.getCartItems();
            count = cart.reduce((acc, it) => acc + (it.qty || 1), 0);
        } catch(e) {}
        const badge = document.getElementById('bnav-cart-badge');
        if (badge) {
            if (count > 0) {
                badge.textContent = count;
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        }
    };

    window.ensureSampleCartItem = function() {
        let cart = window.getCartItems();
        if (cart.length === 0) {
            cart = [
                {
                    slug: 'loco-cimbali-blanc-de-neige-shardone-beloe-suhoe-131',
                    title: 'Loco Cimbali Blanc de Neige',
                    winery: 'Loco Cimbali',
                    price: 2090,
                    qty: 1,
                    checked: true,
                    img: '../wines_images_clean/wines_images/loco-cimbali-blanc-de-neige-shardone-beloe-suhoe-131.webp',
                    meta: 'Крым · Белое, сухое · 0.75 л'
                },
                {
                    slug: 'fanagoriya-100-ottenkov-krasnogo-saperevi-krasnoe-suhoe-132',
                    title: 'Фанагория 100 Оттенков Саперави',
                    winery: 'Фанагория',
                    price: 1850,
                    qty: 2,
                    checked: true,
                    img: '../wines_images_clean/wines_images/fanagoriya-100-ottenkov-krasnogo-saperevi-krasnoe-suhoe-132.webp',
                    meta: 'Кубань · Красное, сухое · 0.75 л'
                }
            ];
            window.saveCartItems(cart);
        }
    };

    
    window.addWineToCartDirectly = function(slug, titleOrBtn, price, img, meta) {
        if (!slug) return;

        let clickedBtn = null;
        let finalTitle = '';
        let finalPrice = 0;
        let finalImg = '';
        let finalMeta = '';

        if (titleOrBtn && typeof titleOrBtn === 'object' && titleOrBtn.nodeType) {
            clickedBtn = titleOrBtn;
        } else if (typeof titleOrBtn === 'string') {
            finalTitle = titleOrBtn;
            finalPrice = typeof price === 'number' ? price : (parseInt(String(price).replace(/\D/g, ''), 10) || 0);
            finalImg = img || '';
            finalMeta = meta || '';
        }

        if (!clickedBtn) {
            clickedBtn = (window.event && window.event.currentTarget) ? window.event.currentTarget : (window.event ? window.event.target : null);
        }

        let card = clickedBtn ? clickedBtn.closest('.home-wine-card, .catalog-wine-card-2col, [data-slug]') : null;
        if (!card && slug) {
            card = document.querySelector('[data-slug="' + slug + '"]') || document.querySelector('.home-wine-card [onclick*="' + slug + '"]')?.closest('.home-wine-card, .catalog-wine-card-2col');
        }

        if (card) {
            if (!finalTitle) {
                const tEl = card.querySelector('.home-wine-title');
                if (tEl) finalTitle = tEl.textContent.trim();
            }
            if (!finalPrice) {
                const pEl = card.querySelector('.home-wine-price');
                if (pEl) finalPrice = parseInt(pEl.textContent.replace(/\D/g, ''), 10) || 2090;
            }
            if (!finalImg) {
                const iEl = card.querySelector('.home-wine-bottle-img');
                if (iEl) finalImg = iEl.src;
            }
            if (!finalMeta) {
                const mEl = card.querySelector('.home-wine-meta');
                if (mEl) finalMeta = mEl.textContent.trim();
            }
        }

        if ((!finalTitle || !finalPrice) && Array.isArray(window.CURRENT_CATALOG_ITEMS)) {
            const foundCat = window.CURRENT_CATALOG_ITEMS.find(w => w.slug === slug);
            if (foundCat) {
                finalTitle = finalTitle || foundCat.name;
                finalPrice = finalPrice || foundCat.price || 2090;
                finalMeta = finalMeta || [foundCat.region, foundCat.color, '0.75 л'].filter(Boolean).join(', ');
            }
        }

        if (!finalTitle || !finalPrice) {
            const pool = (window.HOME_POPULAR_ROW_1 || []).concat(window.HOME_POPULAR_ROW_2 || []);
            const found = pool.find(w => w.slug === slug);
            if (found) {
                finalTitle = finalTitle || found.title;
                finalPrice = finalPrice || (typeof found.price === 'number' ? found.price : parseInt(String(found.price).replace(/\D/g, ''), 10) || 2090);
                finalMeta = finalMeta || found.meta;
            }
        }

        if (!finalTitle) finalTitle = 'Российское вино';
        if (!finalPrice) finalPrice = 2090;
        if (!finalImg) {
            const localImg = `../wines_images_clean/wines_images/${slug}.webp`;
            const apiImg = `${getHubApiBase()}/api/image/${slug}`;
            finalImg = (window.location.protocol === 'file:') ? localImg : apiImg;
        }
        if (!finalMeta) finalMeta = 'Россия · 0.75 л';

        let cart = window.getCartItems();
        const existing = cart.find(it => it.slug === slug);
        if (existing) {
            existing.qty = (existing.qty || 1) + 1;
            existing.checked = true;
        } else {
            cart.push({
                slug: slug,
                title: finalTitle,
                price: finalPrice,
                qty: 1,
                checked: true,
                img: finalImg,
                meta: finalMeta
            });
        }

        window.saveCartItems(cart);
        if (typeof window.updateCartBadge === 'function') window.updateCartBadge();

        if (clickedBtn) {
            const btn = clickedBtn.closest('.btn-card-add-cart') || clickedBtn;
            if (btn && btn.classList.contains('btn-card-add-cart')) {
                const origHtml = btn.innerHTML;
                btn.classList.add('added');
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> <span>В корзине!</span>';
                setTimeout(() => {
                    btn.classList.remove('added');
                    btn.innerHTML = origHtml;
                }, 1400);
            }
        }

        if (typeof showToast === 'function') {
            showToast(`✓ «${finalTitle}» добавлено в корзину`);
        }

        const cartPanel = document.getElementById('hub-panel-cart');
        if (cartPanel && cartPanel.classList.contains('active')) {
            window.renderCartPanel();
        }
    };

    window.deleteCartItem = function(slug) {
        let cart = window.getCartItems();
        cart = cart.filter(it => it.slug !== slug);
        window.saveCartItems(cart);
        window.renderCartPanel();
        if (typeof window.updateCartBadge === 'function') window.updateCartBadge();
        if (typeof showToast === 'function') showToast('Товар удален из корзины');
    };

    window.deleteSelectedCartItems = function() {
        let cart = window.getCartItems();
        const beforeCount = cart.length;
        cart = cart.filter(it => it.checked === false);
        if (cart.length === beforeCount) {
            if (typeof showToast === 'function') showToast('Нет выделенных товаров для удаления');
            return;
        }
        window.saveCartItems(cart);
        window.renderCartPanel();
        if (typeof window.updateCartBadge === 'function') window.updateCartBadge();
        if (typeof showToast === 'function') showToast('Выделенные товары удалены');
    };

    window.toggleCartSelectAll = function() {
        let cart = window.getCartItems();
        const allChecked = cart.every(it => it.checked !== false);
        const newChecked = !allChecked;
        cart.forEach(it => it.checked = newChecked);
        window.saveCartItems(cart);
        window.renderCartPanel();
    };

    window.addCurrentDetailWineToCart = function(customSlug, customWine) {
        let cart = window.getCartItems();
        const slug = customSlug || window.currentDetailWineSlug || 'loco-cimbali-blanc-de-neige-shardone-beloe-suhoe-131';
        const existing = cart.find(item => item.slug === slug);

        if (existing) {
            existing.qty = (existing.qty || 1) + 1;
            existing.checked = true;
        } else {
            let title = 'Вино';
            let price = window.currentDetailWinePrice || 2090;
            let meta = 'Российское вино · 0.75 л';
            let img = '';

            if (customWine) {
                title = customWine.name || customWine.title || slug;
                price = customWine.price || 2090;
                meta = customWine.meta || `${customWine.region || 'Россия'} · ${customWine.color || ''}, ${customWine.sweetness || customWine.sugar || ''} · 0.75 л`;
                img = customWine.image_url || customWine.img || '';
            } else {
                const titleEl = document.getElementById('detail-wine-title');
                if (titleEl && titleEl.textContent) title = titleEl.textContent;

                const color = document.getElementById('detail-wine-color')?.textContent || '';
                const sugar = document.getElementById('detail-wine-sugar')?.textContent || '';
                const region = document.getElementById('detail-wine-region')?.textContent || '';
                meta = [region, color && sugar ? `${color}, ${sugar.toLowerCase()}` : (color || sugar), '0.75 л'].filter(Boolean).join(' · ');

                const imgEl = document.getElementById('detail-wine-img');
                if (imgEl && imgEl.src) img = imgEl.src;
            }

            if (!img) {
                const localImg = `../wines_images_clean/wines_images/${slug}.webp`;
                const apiImg = `${getHubApiBase()}/api/image/${slug}`;
                img = (window.location.protocol === 'file:') ? localImg : apiImg;
            }

            cart.push({
                slug: slug,
                title: title,
                price: price,
                qty: 1,
                checked: true,
                img: img,
                meta: meta
            });
        }

        window.saveCartItems(cart);

        const btn = document.getElementById('btn-detail-sticky-cart');
        const label = document.getElementById('detail-sticky-cart-label');
        if (btn && label) {
            btn.classList.add('added');
            label.textContent = '✓ Добавлено в корзину';
            setTimeout(() => {
                btn.classList.remove('added');
                label.textContent = 'Добавить в корзину';
            }, 1600);
        }

        if (typeof showToast === 'function') {
            showToast('✓ Товар добавлен в корзину');
        }

        const cartPanel = document.getElementById('hub-panel-cart');
        if (cartPanel && cartPanel.classList.contains('active')) {
            window.renderCartPanel();
        }
    };

    window.toggleCartItemChecked = function(slug) {
        const cart = window.getCartItems();
        const item = cart.find(it => it.slug === slug);
        if (item) {
            item.checked = !item.checked;
            window.saveCartItems(cart);
            window.renderCartPanel();
        }
    };

    window.changeCartItemQty = function(slug, delta) {
        let cart = window.getCartItems();
        const item = cart.find(it => it.slug === slug);
        if (item) {
            item.qty = (item.qty || 1) + delta;
            if (item.qty <= 0) {
                cart = cart.filter(it => it.slug !== slug);
            }
            window.saveCartItems(cart);
            window.renderCartPanel();
        }
    };

    window.removeCartItem = function(slug) {
        let cart = window.getCartItems();
        cart = cart.filter(it => it.slug !== slug);
        window.saveCartItems(cart);
        window.renderCartPanel();
    };

    window.clearEntireCart = function() {
        window.saveCartItems([]);
        window.renderCartPanel();
        if (typeof showToast === 'function') {
            showToast('Корзина очищена');
        }
    };

    window.setCartDeliveryMethod = function(method) {
        try {
            localStorage.setItem('vina_cart_delivery', method);
        } catch(e) {}
        window.renderCartPanel();
    };

    window.renderCartPanel = function() {
        const container = document.getElementById('cart-items-container');
        const deliverySec = document.getElementById('cart-delivery-section');
        const summarySec = document.getElementById('cart-summary-section');
        const clearBtn = document.getElementById('cart-clear-btn');
        if (!container) return;

        const cart = window.getCartItems();

        if (cart.length === 0) {
            if (clearBtn) clearBtn.style.display = 'none';
            if (deliverySec) deliverySec.style.display = 'none';
            if (summarySec) summarySec.style.display = 'none';

            container.innerHTML = `
                <div class="cart-empty-box">
                    <div class="cart-empty-icon-wrap">
                        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="var(--primary, #800020)" stroke-width="2">
                            <path d="M5 7h14l-1 13H6L5 7z"></path>
                            <path d="M9 7v-1a3 3 0 0 1 6 0v1"></path>
                        </svg>
                    </div>
                    <div class="cart-empty-title">В вашей корзине пока пусто</div>
                    <div class="cart-empty-desc">
                        Выберите понравившиеся российские вина в каталоге или сканере и добавьте их в корзину.
                    </div>
                    <button type="button" class="btn btn-primary" onclick="switchHubTab('catalog')" style="border-radius: 12px; padding: 12px 24px; font-weight: 700;">
                        Перейти в каталог
                    </button>
                </div>
            `;
            return;
        }

        if (clearBtn) clearBtn.style.display = 'inline-block';
        if (deliverySec) deliverySec.style.display = 'block';
        if (summarySec) summarySec.style.display = 'block';

        // 1. Тулбар выделения и удаления
        const allChecked = cart.length > 0 && cart.every(w => w.checked !== false);
        const checkedSelectedCount = cart.filter(w => w.checked !== false).length;

        const toolbarHtml = `
            <div class="cart-action-toolbar">
                <button type="button" class="cart-select-all-btn" onclick="toggleCartSelectAll()">
                    <div class="cart-custom-checkbox ${allChecked ? 'checked' : ''}" style="width: 20px; height: 20px; border-radius: 6px;">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>
                    </div>
                    <span>Выбрать все</span>
                </button>
                <button type="button" class="btn-cart-delete-selected" onclick="deleteSelectedCartItems()">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                    <span>Удалить выбранные (${checkedSelectedCount})</span>
                </button>
            </div>
        `;

        // 2. Рендеринг карточек вин с кнопкой удаления каждой позиции
        const cardsHtml = cart.map(w => {
            const isChecked = w.checked !== false;
            const price = w.price || 2090;
            const qty = w.qty || 1;
            const itemTotal = price * qty;
            const localImg = `../wines_images_clean/wines_images/${w.slug}.webp`;
            const apiImg = `${getHubApiBase()}/api/image/${w.slug}`;
            const imgSrc = w.img || ((window.location.protocol === 'file:') ? localImg : apiImg);

            return `
                <div class="cart-wine-card ${isChecked ? 'checked-card' : ''}" data-slug="${w.slug}">
                    <!-- В углу карточки вверху слева квадратик с галочкой (по умолчанию стоят) -->
                    <div class="cart-wine-card-checkbox">
                        <div class="cart-custom-checkbox ${isChecked ? 'checked' : ''}" onclick="toggleCartItemChecked('${w.slug}')" title="Выбрать для покупки">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                        </div>
                    </div>
                    <!-- В правом верхнем углу кнопка удаления одной позиции -->
                    <button type="button" class="cart-item-delete-btn" onclick="deleteCartItem('${w.slug}')" title="Удалить вино из корзины">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                    </button>
                    <div class="cart-wine-thumb-box" onclick="openWineDetail('${w.slug}')">
                        <img src="${imgSrc}" class="cart-wine-thumb-img" alt="${w.title}" onerror="this.src='badge_glass.png'">
                    </div>
                    <div class="cart-wine-info">
                        <h4 class="cart-wine-title" onclick="openWineDetail('${w.slug}')" title="${w.title}">${w.title}</h4>
                        <div class="cart-wine-meta">${w.meta || 'Российское вино · 0.75 л'}</div>
                        <div class="cart-wine-unit-price">${price.toLocaleString('ru-RU')} ₽ / шт</div>
                    </div>
                    <!-- Справа - количество шт, в стиле бордово-сером -->
                    <div class="cart-wine-right-col">
                        <div class="cart-qty-control">
                            <button type="button" class="cart-qty-btn minus" onclick="changeCartItemQty('${w.slug}', -1)" title="Уменьшить">-</button>
                            <span class="cart-qty-val">${qty} шт</span>
                            <button type="button" class="cart-qty-btn plus" onclick="changeCartItemQty('${w.slug}', 1)" title="Увеличить">+</button>
                        </div>
                        <div class="cart-item-total-price">${itemTotal.toLocaleString('ru-RU')} ₽</div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = toolbarHtml + cardsHtml;

        // 2. Способ получения (самовывоз / курьер)
        const deliveryMethod = localStorage.getItem('vina_cart_delivery') || 'pickup';
        const cardPickup = document.getElementById('delivery-opt-pickup');
        const cardCourier = document.getElementById('delivery-opt-courier');
        const chkPickup = document.getElementById('chk-delivery-pickup');
        const chkCourier = document.getElementById('chk-delivery-courier');

        if (cardPickup && cardCourier && chkPickup && chkCourier) {
            const isPickup = deliveryMethod === 'pickup';
            cardPickup.classList.toggle('active', isPickup);
            chkPickup.classList.toggle('checked', isPickup);
            cardCourier.classList.toggle('active', !isPickup);
            chkCourier.classList.toggle('checked', !isPickup);
        }

        // 3. Подсчет итоговых сумм
        const checkedItems = cart.filter(w => w.checked !== false);
        const checkedCount = checkedItems.reduce((acc, it) => acc + (it.qty || 1), 0);
        const itemsTotal = checkedItems.reduce((acc, it) => acc + ((it.price || 0) * (it.qty || 1)), 0);

        let deliveryFee = 0;
        let deliveryLabel = 'Бесплатно (Самовывоз)';

        if (deliveryMethod === 'courier') {
            if (itemsTotal >= 5000 || checkedCount === 0) {
                deliveryFee = 0;
                deliveryLabel = 'Бесплатно (от 5 000 ₽)';
            } else {
                deliveryFee = 350;
                deliveryLabel = '350 ₽ (Курьер)';
            }
        }

        const grandTotal = checkedCount > 0 ? (itemsTotal + deliveryFee) : 0;

        const countEl = document.getElementById('cart-sum-count');
        if (countEl) countEl.textContent = `${checkedCount} шт.`;

        const totalItemsEl = document.getElementById('cart-sum-items-total');
        if (totalItemsEl) totalItemsEl.textContent = `${itemsTotal.toLocaleString('ru-RU')} ₽`;

        const delivEl = document.getElementById('cart-sum-delivery');
        if (delivEl) delivEl.textContent = deliveryLabel;

        const grandEl = document.getElementById('cart-sum-grand-total');
        if (grandEl) grandEl.textContent = `${grandTotal.toLocaleString('ru-RU')} ₽`;

        // 4. Бордовая кнопка «Купить»
        const buyBtn = document.getElementById('btn-cart-buy');
        if (buyBtn) {
            if (checkedCount > 0) {
                buyBtn.disabled = false;
                buyBtn.textContent = `Купить · ${grandTotal.toLocaleString('ru-RU')} ₽`;
            } else {
                buyBtn.disabled = true;
                buyBtn.textContent = 'Выберите вина для покупки';
            }
        }
    };

    window.handleCartCheckout = function() {
        const cart = window.getCartItems();
        const checkedItems = cart.filter(w => w.checked !== false);
        if (checkedItems.length === 0) {
            if (typeof showToast === 'function') showToast('Выберите хотя бы одно вино для покупки');
            return;
        }

        const deliveryMethod = localStorage.getItem('vina_cart_delivery') || 'pickup';
        const checkedCount = checkedItems.reduce((acc, it) => acc + (it.qty || 1), 0);
        const itemsTotal = checkedItems.reduce((acc, it) => acc + ((it.price || 0) * (it.qty || 1)), 0);
        const deliveryFee = (deliveryMethod === 'courier' && itemsTotal < 5000) ? 350 : 0;
        const grandTotal = itemsTotal + deliveryFee;

        const randNum = Math.floor(10000 + Math.random() * 90000);
        const orderNum = `VN-${randNum}`;

        const modal = document.getElementById('cart-checkout-modal');
        const numEl = document.getElementById('checkout-order-num');
        const delivEl = document.getElementById('checkout-modal-delivery');
        const qtyEl = document.getElementById('checkout-modal-qty');
        const totalEl = document.getElementById('checkout-modal-total');

        if (numEl) numEl.textContent = `Заказ № ${orderNum}`;
        if (delivEl) delivEl.textContent = deliveryMethod === 'courier' ? 'Доставка курьером' : 'Самовывоз из магазина';
        if (qtyEl) qtyEl.textContent = `${checkedCount} шт.`;
        if (totalEl) totalEl.textContent = `${grandTotal.toLocaleString('ru-RU')} ₽`;

        if (modal) modal.classList.add('visible');

        const remaining = cart.filter(w => w.checked === false);
        window.saveCartItems(remaining);
    };

    window.closeCartCheckoutModal = function() {
        const modal = document.getElementById('cart-checkout-modal');
        if (modal) modal.classList.remove('visible');
        window.renderCartPanel();
        if (typeof switchHubTab === 'function') {
            switchHubTab('catalog');
        }
    };
