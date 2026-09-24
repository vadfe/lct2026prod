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

        // Always prefer direct local connection if running locally
        const isLocalHost = window.location.hostname === 'localhost' || 
                            window.location.hostname === '127.0.0.1' || 
                            window.location.hostname === '0.0.0.0' ||
                            window.location.port === '8080' ||
                            !window.location.hostname;
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
        if (btnSnap) btnSnap.classList.add('hidden');
    }

    function showView(view) {
        [scannerView, loadingView, resultView, originalView].forEach(v => {
            if (v) v.classList.remove('active');
        });
        if (view) view.classList.add('active');

        // Manage camera lifecycle
        if (view === scannerView) {
            startCamera();
        } else {
            stopCamera();
        }
    }

    // --- Health Check & Status Monitor ---
    async function checkServerHealth(customUrl = null) {
        const targetUrl = customUrl !== null ? (customUrl ? `${customUrl.replace(/\/+$/, '')}/api/ready` : '/api/ready') : apiUrl('/api/ready');
        
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
                statusText.textContent = data.models ? 'RTX 3090' : 'Онлайн';
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

    function showFeedback(text, type) {
        feedbackBox.textContent = text;
        feedbackBox.className = `feedback-box ${type}`;
    }

    btnSettings.addEventListener('click', openSettings);
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
        
        if (currentUploadedImageURL) {
            URL.revokeObjectURL(currentUploadedImageURL);
        }
        currentUploadedImageURL = URL.createObjectURL(file);
        
        scanningLine.classList.remove('hidden');
        
        setTimeout(async () => {
            showView(loadingView);
            
            try {
                const formData = new FormData();
                formData.append('image', file, 'snapshot.jpg');
                
                const predictEndpoint = apiUrl('/v1/eval/predict');
                const res = await fetch(predictEndpoint, {
                    method: 'POST',
                    body: formData
                });
                
                if (!res.ok) throw new Error(`Ошибка сервера: ${res.status}`);
                const data = await res.json();
                
                if (data.slug) {
                    const conf = data.confidence !== undefined ? data.confidence : data.score;
                    if (typeof window.setConfidence === 'function' && conf !== undefined && conf !== null) {
                        window.setConfidence(conf);
                    }
                    await loadWineCard(data.slug);
                    showView(resultView);
                } else {
                    alert('Вино не найдено в каталоге. Попробуйте другой ракурс.');
                    showView(scannerView);
                }
            } catch (error) {
                console.error(error);
                alert('Ошибка при связи с сервером. Проверьте настройки туннеля (⚙️).');
                showView(scannerView);
            } finally {
                scanningLine.classList.add('hidden');
                if (fileInput) fileInput.value = '';
            }
        }, 1200);
    }

    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length) processImageFile(e.target.files[0]);
        });
    }

    if (btnSnap && cameraFeed) {
        const handleSnap = (e) => {
            if (e.type === 'touchend') e.preventDefault(); // prevent double firing from click
            if (!cameraStream) {
                console.warn("No camera stream active");
                return;
            }
            // Visual feedback
            btnSnap.style.transform = "scale(0.9)";
            setTimeout(() => btnSnap.style.transform = "scale(1)", 150);

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
        const res = await fetch(apiUrl(`/api/wine/${slug}`));
        if (!res.ok) throw new Error('Карточка не найдена');
        const wine = await res.json();
        
        // Image URL through API bridge
        imgWine.src = apiUrl(`/api/image/${slug}`);
        imgWine.onerror = () => { imgWine.src = 'https://via.placeholder.com/300x500?text=Wine'; };
        
        elWinery.textContent = wine.winery || '';
        elTitle.textContent = wine.name || slug;
        elColor.textContent = wine.color || '';
        elCategory.textContent = wine.category || '';
        elRegion.textContent = wine.region || '';
        elGrape.textContent = wine.grape || '';
        elDesc.textContent = wine.description || '';
        if(typeof initRating === 'function') initRating(slug);
    }

    btnBack.addEventListener('click', () => {
        showView(scannerView);
    });

    if (btnShowOriginal) {
        btnShowOriginal.addEventListener('click', () => {
            if (currentUploadedImageURL) {
                originalImg.src = currentUploadedImageURL;
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
        lightboxTitle.textContent = title || "Просмотр скана";
        resetTransform();
        lightboxModal.classList.remove("hidden");
    }

    function closeLightbox() {
        lightboxModal.classList.add("hidden");
        lightboxImg.src = "";
    }

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

        // Pan logic for desktop (mouse)
        lightboxCanvas.addEventListener("mousedown", (e) => {
            if (e.button !== 0) return; 
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

        // Mobile touch logic (Pan + Pinch-to-Zoom)
        let initialDistance = null;
        let initialScale = 1;

        lightboxCanvas.addEventListener("touchstart", (e) => {
            if (e.touches.length === 1) {
                isDragging = true;
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
    const glassSlots = document.querySelectorAll('.glass-slot');
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

    // Sommelier interactions (stubs)
    const btnMap = document.getElementById('btn-map');
    if (btnMap) {
        btnMap.addEventListener('click', () => {
            showToast('📍 Раздел «Карта» находится в разработке');
        });
    }

    const btnChat = document.getElementById('btn-chat');
    if (btnChat) {
        btnChat.addEventListener('click', () => {
            showToast('💬 Чат с сомелье скоро станет доступен');
        });
    }

    const btnAnalogs = document.getElementById('btn-sommelier-analogs');
    if (btnAnalogs) {
        btnAnalogs.addEventListener('click', () => {
            showToast('🍷 Подбор аналогов появится в следующем обновлении');
        });
    }

    document.querySelectorAll('.btn-pairing').forEach(btn => {
        btn.addEventListener('click', () => {
            btn.classList.toggle('selected');
        });
    });

});