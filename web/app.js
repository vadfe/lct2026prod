import { loadDetector, detect, crop, draw } from './detector.js';

const config = window.LCT_CONFIG || { apiBase: '', searchVersion: 'v1' };

// DOM Elements
const video = document.getElementById('camera-feed');
const overlay = document.getElementById('overlay');
const btnSnap = document.getElementById('btn-snap');
const fileInput = document.getElementById('file-input');
const btnBack = document.getElementById('btn-back');

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
            img.style.transform = 'rotate(-15deg) scale(1.1)';
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
            imgWine.src = config.apiBase + item.image_url;
            imgWine.onerror = () => { imgWine.src = 'https://via.placeholder.com/300x500?text=Wine'; };
            
            // Clear unused fields based on user request
            if (elColor) elColor.textContent = '';
            if (elCategory) elCategory.textContent = '';
            if (elRegion) elRegion.textContent = '';
            if (elGrape) elGrape.textContent = '';
            if (elDescription) elDescription.textContent = '';
            
            // Init rating using item id or title as slug
            const slug = item.id || item.title;
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

// Start sequence
document.addEventListener('DOMContentLoaded', () => {
    start();
});
