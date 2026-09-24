import { loadDetector, detect, crop, draw } from './detector.js';

const config = window.LCT_CONFIG || { apiBase: '', searchVersion: 'v1' };

// DOM Elements
const video = document.getElementById('camera-feed');
const overlay = document.getElementById('overlay');
const btnSnap = document.getElementById('btn-snap');
const fileInput = document.getElementById('file-input');
const btnBack = document.getElementById('btn-back');
const btnShowOriginal = document.getElementById('btn-show-original');

// Views
const views = {
    scanner: document.getElementById('scanner-view'),
    loading: document.getElementById('loading-view'),
    result: document.getElementById('result-view'),
    original: document.getElementById('original-view')
};

function showView(viewName) {
    Object.values(views).forEach(v => {
        if (v) v.classList.remove('active');
    });
    if (views[viewName]) {
        views[viewName].classList.add('active');
    }
}

// Result fields
const imgWine = document.getElementById('wine-image');
const elTitle = document.getElementById('wine-title');
const elWinery = document.getElementById('wine-winery');
const elDescription = document.getElementById('wine-description');
const elColor = document.getElementById('wine-color');
const elCategory = document.getElementById('wine-category');
const elRegion = document.getElementById('wine-region');
const elGrape = document.getElementById('wine-grape');

let currentBox = null;
let busy = false;
let stream = null;
let currentSlug = null;
let currentBlobUrl = null;

// Rating logic
let globalRatings = JSON.parse(localStorage.getItem('vina_global_ratings')) || {};

function initRating(slug) {
    currentSlug = slug;
    const ratingSection = document.getElementById('rating-section');
    if (!ratingSection) return;

    let rating = parseInt(localStorage.getItem(`vina_rating_${slug}`) || '0', 10);
    
    // Ensure stats exist
    if (!globalRatings[slug]) {
        globalRatings[slug] = { total: 0, sum: 0 };
    }

    const glasses = document.querySelectorAll('.glass-slot');
    glasses.forEach(slot => {
        const val = parseInt(slot.dataset.index, 10);
        
        slot.onmouseenter = () => updateRatingUI(val, rating, slug);
        slot.onmouseleave = () => updateRatingUI(0, rating, slug);
        
        slot.onclick = (e) => {
            e.preventDefault();
            const prev = rating;
            rating = val;
            localStorage.setItem(`vina_rating_${slug}`, rating);
            
            if (prev === 0) {
                globalRatings[slug].total += 1;
            } else {
                globalRatings[slug].sum -= prev;
            }
            globalRatings[slug].sum += rating;
            localStorage.setItem('vina_global_ratings', JSON.stringify(globalRatings));
            
            updateRatingUI(0, rating, slug);
            
            // Pulse animation
            const img = slot.querySelector('.glass-img');
            img.style.transform = 'rotate(15deg) scale(1.1)';
            setTimeout(() => { img.style.transform = ''; }, 200);
        };
    });

    updateRatingUI(0, rating, slug);
}

function updateRatingUI(hoverVal, rating, slug) {
    const glasses = document.querySelectorAll('.glass-slot');
    const badgeScore = document.getElementById('badge-score');
    const userRatingText = document.getElementById('user-rating-text');
    const totalVotesEl = document.getElementById('total-votes');
    const avgScoreEl = document.getElementById('avg-score');

    glasses.forEach(slot => {
        const val = parseInt(slot.dataset.index, 10);
        const img = slot.querySelector('.glass-img');
        if (hoverVal > 0) {
            if (val <= hoverVal) {
                slot.classList.add('active-bg');
                img.src = 'img/glass_filled_straight.png';
            } else {
                slot.classList.remove('active-bg');
                img.src = 'img/glass_empty_straight.png';
            }
        } else {
            if (val <= rating) {
                slot.classList.add('active-bg');
                img.src = 'img/glass_filled_straight.png';
            } else {
                slot.classList.remove('active-bg');
                img.src = 'img/glass_empty_straight.png';
            }
        }
    });

    const stats = globalRatings[slug] || { total: 0, sum: 0 };
    let avg = stats.total > 0 ? (stats.sum / stats.total).toFixed(1) : '0.0';
    
    if (badgeScore) badgeScore.textContent = avg;
    if (avgScoreEl) avgScoreEl.textContent = avg;
    if (totalVotesEl) totalVotesEl.textContent = stats.total;
    
    if (userRatingText) {
        if (rating > 0) {
            userRatingText.textContent = `Ваша оценка: ${rating} из 5`;
        } else {
            userRatingText.textContent = 'Ваша оценка: - из 5';
        }
    }
}

async function submit(blob, cropped) {
    if (!blob || busy) return;
    busy = true;
    showView('loading');
    
    if (currentBlobUrl) URL.revokeObjectURL(currentBlobUrl);
    currentBlobUrl = URL.createObjectURL(blob);
    
    try {
        const body = new FormData();
        body.append('image', blob, 'image.jpg');
        body.append('k', '5');
        
        const endpoint = `${config.apiBase}/api/${config.searchVersion}/${cropped ? 'search-from-crop' : 'search'}`;
        const response = await fetch(endpoint, { method: 'POST', body });
        const data = await response.json();
        
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        
        if (data.results && data.results.length > 0) {
            const item = data.results[0]; // Take best match
            
            // Populate fields
            elTitle.textContent = item.title || 'Неизвестное вино';
            elWinery.textContent = item.manufacturer || '';
            
            // Show bottle image if available, otherwise fall back to label crop
            if (item.bottle_image_url) {
                imgWine.src = config.apiBase + item.bottle_image_url;
            } else {
                imgWine.src = config.apiBase + item.image_url;
            }
            imgWine.onerror = () => { imgWine.src = 'https://via.placeholder.com/300x500?text=Wine'; };
            
            // Fill wine detail fields from API response
            if (elColor) elColor.textContent = item.color || '';
            if (elCategory) elCategory.textContent = item.category || '';
            if (elRegion) elRegion.textContent = item.region || '';
            if (elGrape) elGrape.textContent = item.grape || '';
            if (elDescription) elDescription.textContent = item.description || '';
            
            // Hide empty tags
            if (elColor && !item.color) elColor.style.display = 'none'; else if (elColor) elColor.style.display = '';
            if (elCategory && !item.category) elCategory.style.display = 'none'; else if (elCategory) elCategory.style.display = '';
            if (elRegion && !item.region) elRegion.style.display = 'none'; else if (elRegion) elRegion.style.display = '';
            
            // Confidence score
            const elConfidence = document.getElementById('confidence-score');
            if (elConfidence) {
                let conf = 85;
                if (typeof item.confidence === 'number' && item.confidence > 0) {
                    conf = item.confidence > 1 ? Math.round(item.confidence) : Math.round(item.confidence * 100);
                } else if (typeof item.dino_similarity === 'number' && item.dino_similarity > 0) {
                    conf = Math.min(100, Math.max(0, Math.round(item.dino_similarity * 100)));
                } else if (typeof item.sift_score === 'number' && item.sift_score > 0) {
                    conf = Math.min(100, Math.max(0, Math.round(item.sift_score * 100)));
                }
                conf = Math.min(100, Math.max(0, conf));
                elConfidence.textContent = `${conf}%`;
            }

            // Init rating using item id or title as slug
            const slug = item.slug || item.title;
            initRating(slug);
            
            showView('result');
        } else {
            alert('Совпадений не найдено');
            showView('scanner');
        }
    } catch (error) {
        alert(`Ошибка: ${error.message}`);
        showView('scanner');
    } finally {
        busy = false;
    }
}

async function start() {
    if (!window.isSecureContext && location.hostname !== 'localhost') {
        alert('Для камеры требуется HTTPS');
        return;
    }
    
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } }
        });
        video.srcObject = stream;
        video.style.display = 'block';
        
        // Ensure buttons show up once stream is ready
        if (btnSnap) btnSnap.classList.remove('hidden');
        
        if (await loadDetector()) {
            loop();
        }
    } catch (error) {
        console.warn('Камера недоступна', error);
        // We still allow file uploads
    }
}

async function loop() {
    if (video.videoWidth && !busy) {
        try {
            currentBox = await detect(video);
            draw(overlay, currentBox);
            
            // Make snap button pop if detected
            if (currentBox) {
                btnSnap.style.transform = 'scale(1.1)';
                btnSnap.style.borderColor = '#20d45a';
            } else {
                btnSnap.style.transform = 'scale(1)';
                btnSnap.style.borderColor = 'var(--primary)';
            }
            
        } catch (error) {
            console.warn(error);
        }
    }
    requestAnimationFrame(loop);
}

// Event Listeners
if (btnSnap) {
    btnSnap.addEventListener('click', async () => {
        if (currentBox) {
            const blob = await crop(video, currentBox);
            await submit(blob, true);
        } else {
            // Fallback: capture full frame
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext('2d').drawImage(video, 0, 0);
            canvas.toBlob(blob => submit(blob, false), 'image/jpeg', 0.92);
        }
    });
}

if (fileInput) {
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            submit(fileInput.files[0], false);
        }
    });
}

if (btnBack) {
    btnBack.addEventListener('click', () => {
        showView('scanner');
    });
}

// Badge scroll to rating
const badge = document.getElementById('people-rating-badge');
if (badge) {
    badge.addEventListener('click', () => {
        const section = document.getElementById('rating-section');
        if (section) {
            section.scrollIntoView({ behavior: 'smooth' });
        }
    });
}

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

// Lightbox logic
const lightboxModal = document.getElementById('lightbox-modal');
const lightboxImg = document.getElementById('lightbox-img');
const btnCloseLightbox = document.getElementById('btn-close-lightbox');
const btnZoomIn = document.getElementById('btn-zoom-in');
const btnZoomOut = document.getElementById('btn-zoom-out');
const btnZoomReset = document.getElementById('btn-zoom-reset');
const lightboxCanvas = document.getElementById('lightbox-canvas');

let zoomLevel = 1;
let isDragging = false;
let startX = 0, startY = 0;
let translateX = 0, translateY = 0;

function updateLightboxTransform() {
    if (lightboxImg) {
        lightboxImg.style.transform = `translate(${translateX}px, ${translateY}px) scale(${zoomLevel})`;
    }
}

function openLightbox(src) {
    if (!lightboxModal || !lightboxImg) return;
    lightboxImg.src = src;
    zoomLevel = 1;
    translateX = 0;
    translateY = 0;
    updateLightboxTransform();
    lightboxModal.classList.remove('hidden');
}

function closeLightbox() {
    if (!lightboxModal) return;
    lightboxModal.classList.add('hidden');
    lightboxImg.src = '';
}

if (imgWine) {
    imgWine.addEventListener('click', () => {
        if (imgWine.src) openLightbox(imgWine.src);
    });
}

if (btnShowOriginal) {
    btnShowOriginal.addEventListener('click', () => {
        if (currentBlobUrl) {
            openLightbox(currentBlobUrl);
        }
    });
}

if (btnCloseLightbox) btnCloseLightbox.addEventListener('click', closeLightbox);
if (lightboxModal) lightboxModal.addEventListener('click', (e) => {
    if (e.target === lightboxModal || e.target === lightboxCanvas) closeLightbox();
});

if (btnZoomIn) btnZoomIn.addEventListener('click', () => { zoomLevel += 0.25; updateLightboxTransform(); });
if (btnZoomOut) btnZoomOut.addEventListener('click', () => { zoomLevel = Math.max(0.25, zoomLevel - 0.25); updateLightboxTransform(); });
if (btnZoomReset) btnZoomReset.addEventListener('click', () => { zoomLevel = 1; translateX = 0; translateY = 0; updateLightboxTransform(); });

if (lightboxCanvas) {
    lightboxCanvas.addEventListener('mousedown', (e) => {
        isDragging = true;
        startX = e.clientX - translateX;
        startY = e.clientY - translateY;
        lightboxCanvas.style.cursor = 'grabbing';
    });
    lightboxCanvas.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        translateX = e.clientX - startX;
        translateY = e.clientY - startY;
        updateLightboxTransform();
    });
    lightboxCanvas.addEventListener('mouseup', () => {
        isDragging = false;
        lightboxCanvas.style.cursor = 'grab';
    });
    lightboxCanvas.addEventListener('mouseleave', () => {
        isDragging = false;
        lightboxCanvas.style.cursor = 'grab';
    });
    // touch support
    lightboxCanvas.addEventListener('touchstart', (e) => {
        if (e.touches.length === 1) {
            isDragging = true;
            startX = e.touches[0].clientX - translateX;
            startY = e.touches[0].clientY - translateY;
        }
    }, {passive: true});
    lightboxCanvas.addEventListener('touchmove', (e) => {
        if (!isDragging || e.touches.length !== 1) return;
        translateX = e.touches[0].clientX - startX;
        translateY = e.touches[0].clientY - startY;
        updateLightboxTransform();
    }, {passive: true});
    lightboxCanvas.addEventListener('touchend', () => { isDragging = false; });
}

// --- Settings Modal Logic ---
const btnSettings = document.getElementById('btn-settings');
const settingsModal = document.getElementById('settings-modal');
const btnCloseModal = document.getElementById('btn-close-modal');
const modalBackdrop = document.querySelector('.modal-backdrop');
const inputApiUrl = document.getElementById('input-api-url');
const btnTestConnection = document.getElementById('btn-test-connection');
const btnSaveSettings = document.getElementById('btn-save-settings');
const feedbackBox = document.getElementById('connection-feedback');
const btnResetLocal = document.getElementById('btn-reset-local');
const statusText = document.getElementById('status-text');
const statusDot = document.querySelector('.status-dot');

// Override config.apiBase with saved localStorage if present
const savedApiUrl = localStorage.getItem('vina_api_url');
if (savedApiUrl !== null) {
    config.apiBase = savedApiUrl;
}

function openSettings() {
    if (inputApiUrl) inputApiUrl.value = localStorage.getItem('vina_api_url') || '';
    if (feedbackBox) feedbackBox.className = 'feedback-box hidden';
    if (settingsModal) settingsModal.classList.remove('hidden');
}

function closeSettings() {
    if (settingsModal) settingsModal.classList.add('hidden');
}

function showFeedback(text, type) {
    if (!feedbackBox) return;
    feedbackBox.textContent = text;
    feedbackBox.className = `feedback-box ${type}`;
}

if (btnSettings) btnSettings.addEventListener('click', openSettings);
if (btnCloseModal) btnCloseModal.addEventListener('click', closeSettings);
if (modalBackdrop) modalBackdrop.addEventListener('click', closeSettings);

if (btnResetLocal) {
    btnResetLocal.addEventListener('click', () => {
        localStorage.removeItem('vina_api_url');
        config.apiBase = '';
        if (inputApiUrl) inputApiUrl.value = '';
        closeSettings();
        checkServerHealth();
    });
}

if (btnTestConnection) {
    btnTestConnection.addEventListener('click', async () => {
        const testUrl = inputApiUrl.value.trim().replace(/\/+$/, '');
        showFeedback('Проверка соединения...', '');
        try {
            const res = await fetch(`${testUrl || ''}/api/ready`);
            if (res.ok) {
                showFeedback(`Успешно! Сервер доступен.`, 'success');
            } else {
                showFeedback('Не удалось связаться с сервером.', 'error');
            }
        } catch (e) {
            showFeedback('Не удалось связаться с сервером.', 'error');
        }
    });
}

if (btnSaveSettings) {
    btnSaveSettings.addEventListener('click', () => {
        const val = inputApiUrl.value.trim().replace(/\/+$/, '');
        if (val) {
            localStorage.setItem('vina_api_url', val);
            config.apiBase = val;
        } else {
            localStorage.removeItem('vina_api_url');
            config.apiBase = '';
        }
        closeSettings();
        checkServerHealth();
    });
}

async function checkServerHealth() {
    if (!statusText || !statusDot) return;
    statusDot.className = 'status-dot';
    statusText.textContent = 'Проверка...';
    try {
        const res = await fetch(`${config.apiBase}/api/ready`);
        if (res.ok) {
            statusDot.className = 'status-dot online';
            statusText.textContent = 'Онлайн';
        } else {
            statusDot.className = 'status-dot offline';
            statusText.textContent = 'Офлайн';
        }
    } catch (e) {
        statusDot.className = 'status-dot offline';
        statusText.textContent = 'Офлайн';
    }
}
checkServerHealth();

// Start sequence
document.addEventListener('DOMContentLoaded', () => {
    start();
});
