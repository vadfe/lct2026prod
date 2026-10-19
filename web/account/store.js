// Данные личного кабинета в браузере и все расчёты (очки, стадия лозы, веса вкуса, регионы, статусы). Без DOM.
import {
    COLORS, DISLIKE_RATING, HISTORY_LIMIT, KEYS, LIKE_RATING, PALETTE, POINTS, REGION_SYMBOLS, REVIEW_MIN_CHARS,
    STATUSES, STORAGE_VERSION, SUGARS, VINE_FULL_POINTS, VINE_STAGES, WEIGHTS,
} from './config.js';

let storage = null;   // обёртка сканера над localStorage (переживает приватный режим)

export function setStorage(wrapper) { storage = wrapper; }

function readJson(key, fallback) {
    const raw = storage ? storage.get(key) : null;
    if (!raw) return fallback();
    try {
        const value = JSON.parse(raw);
        return value && value.version === STORAGE_VERSION ? value : fallback();
    } catch {
        return fallback();
    }
}
const writeJson = (key, value) => storage && storage.set(key, JSON.stringify({ ...value, version: STORAGE_VERSION }));

// ---------- аккаунт ----------

export const getAccount = () => readJson(KEYS.account, () => null);
export const isLoggedIn = () => Boolean(getAccount() && getAccount().logged_in);

export function login(provider, defaultName) {
    const existing = getAccount();
    const account = existing
        ? { ...existing, provider, logged_in: true }
        : { provider, name: defaultName, created_at: Date.now(), quiz: null, logged_in: true };
    writeJson(KEYS.account, account);
    return account;
}

export function logout() {
    const account = getAccount();
    if (account) writeJson(KEYS.account, { ...account, logged_in: false });
}

export function wipe() {
    [KEYS.account, KEYS.history, KEYS.cellar, KEYS.reviews].forEach(key => storage && storage.remove(key));
}

export function setName(name) {
    const account = getAccount();
    if (account) writeJson(KEYS.account, { ...account, name: name.trim().slice(0, 40) || account.name });
}

export function setQuiz(colors, sugars) {
    const account = getAccount();
    if (account) writeJson(KEYS.account, { ...account, quiz: { colors: colors.filter(c => COLORS.includes(c)), sugars: sugars.filter(s => SUGARS.includes(s)) } });
}

// ---------- история, погреб, рецензии ----------

// Карточка вина, которую храним в истории и погребе (только поля для списков и расчётов)
export function wineMeta(w) {
    return {
        slug: String(w.slug || ''), product_id: w.product_id || null, title: String(w.title || ''), winery: String(w.winery || ''),
        category: w.category || null, region: w.region || null, sweetness: w.sweetness || null, image_url: w.image_url || null,
    };
}

export const getHistory = () => readJson(KEYS.history, () => ({ items: [] })).items;
export const getCellar = () => readJson(KEYS.cellar, () => ({ items: {} })).items;
export const getReviews = () => readJson(KEYS.reviews, () => ({ items: {} })).items;

export function recordScan(wine, status) {
    if (!isLoggedIn() || !wine.slug) return;
    const items = [{ ...wineMeta(wine), status, ts: Date.now() }, ...getHistory()].slice(0, HISTORY_LIMIT);
    writeJson(KEYS.history, { items });
}

export const inCellar = slug => Boolean(getCellar()[slug]);

export function toggleCellar(wine) {
    const items = { ...getCellar() };
    if (items[wine.slug]) delete items[wine.slug];
    else items[wine.slug] = { ...wineMeta(wine), added_ts: Date.now() };
    writeJson(KEYS.cellar, { items });
    return Boolean(items[wine.slug]);
}

export const getReview = slug => getReviews()[slug] || null;

export function setReview(wine, text) {
    const items = { ...getReviews() };
    const clean = String(text || '').trim().slice(0, 4000);
    if (clean) items[wine.slug] = { ...wineMeta(wine), text: clean, updated_ts: Date.now() };
    else delete items[wine.slug];
    writeJson(KEYS.reviews, { items });
}

export function getRating(slug) {
    const value = parseInt((storage && storage.get(`${KEYS.ratingPrefix}${slug}`)) || '0', 10);
    return value >= 1 && value <= 5 ? value : 0;
}

// Все вина, о которых кабинет что-то знает: история, погреб, рецензии (последняя известная карточка)
export function knownWines() {
    const map = new Map();
    [...getHistory()].reverse().forEach(w => map.set(w.slug, { ...map.get(w.slug), ...w }));
    Object.values(getReviews()).forEach(w => map.set(w.slug, { ...w, ...map.get(w.slug) }));
    Object.values(getCellar()).forEach(w => map.set(w.slug, { ...w, ...map.get(w.slug) }));
    return map;
}

// ---------- расчёты ----------

const clamp = v => Math.min(WEIGHTS.max, Math.max(WEIGHTS.min, v));
const argmax = (weights, order) => order.reduce((best, key) => (weights[key] > weights[best] ? key : best), order[0]);

export function plural(n, one, few, many) {
    const m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
}

export function fruitFor(color, sugar) {
    const row = PALETTE[color];
    const idx = SUGARS.indexOf(sugar);
    if (!row || idx < 0) return null;
    const [key, title] = row[idx];
    return { key, title, color, sugar };
}

function tasteWeights(quiz, wines, cellar) {
    const colors = Object.fromEntries(COLORS.map(c => [c, quiz && quiz.colors.includes(c) ? WEIGHTS.quiz : 0]));
    const sugars = Object.fromEntries(SUGARS.map(s => [s, quiz && quiz.sugars.includes(s) ? WEIGHTS.quiz : 0]));
    const base = { colors: { ...colors }, sugars: { ...sugars } };
    const likes = { colors: {}, sugars: {} };
    for (const w of wines.values()) {
        const rating = getRating(w.slug);
        const liked = Boolean(cellar[w.slug]) || rating >= LIKE_RATING;
        const disliked = !liked && rating >= 1 && rating <= DISLIKE_RATING;
        if (!liked && !disliked) continue;
        const delta = liked ? WEIGHTS.like : WEIGHTS.dislike;
        if (w.category in colors) {
            colors[w.category] = clamp(colors[w.category] + delta);
            if (liked) likes.colors[w.category] = (likes.colors[w.category] || 0) + 1;
        }
        if (w.sweetness in sugars) {
            sugars[w.sweetness] = clamp(sugars[w.sweetness] + delta);
            if (liked) likes.sugars[w.sweetness] = (likes.sugars[w.sweetness] || 0) + 1;
        }
    }
    return { colors, sugars, base, likes };
}

function shiftNote(fromKey, toKey, count) {
    if (fromKey === toKey) return null;
    return `${fromKey.toLowerCase()} → ${toKey.toLowerCase()} (${count} ${plural(count, 'лайк', 'лайка', 'лайков')})`;
}

export function metrics() {
    const account = getAccount();
    const history = getHistory();
    const cellar = getCellar();
    const reviews = getReviews();
    const wines = knownWines();

    // «Путь лозы»
    const longReviews = Object.values(reviews).filter(r => (r.text || '').length >= REVIEW_MIN_CHARS).length;
    const parts = { scan: history.length * POINTS.scan, cellar: Object.keys(cellar).length * POINTS.cellar, review: longReviews * POINTS.review };
    const points = parts.scan + parts.cellar + parts.review;
    const progress = Math.min(1, points / VINE_FULL_POINTS);
    const stageIndex = VINE_STAGES.reduce((idx, stage, i) => (progress >= stage.from ? i : idx), 0);
    const next = VINE_STAGES[stageIndex + 1] || null;

    // Вкус
    const quiz = account && account.quiz;
    const w = tasteWeights(quiz, wines, cellar);
    const color = argmax(w.colors, COLORS);
    const sugar = argmax(w.sugars, SUGARS);
    const baseColor = argmax(w.base.colors, COLORS);
    const baseSugar = argmax(w.base.sugars, SUGARS);
    const shifts = [
        shiftNote(baseColor, color, w.likes.colors[color] || 0),
        shiftNote(baseSugar, sugar, w.likes.sugars[sugar] || 0),
    ].filter(Boolean);
    const hasTaste = Boolean(quiz) || Object.values(w.colors).some(v => v > 0);

    // Регионы и статусы
    const seen = [...new Map([...history, ...Object.values(cellar)].map(x => [x.slug, x])).values()];
    const regionNames = new Set(seen.map(x => x.region).filter(Boolean));
    const known = new Set(REGION_SYMBOLS.flatMap(s => s.regions));
    const regions = REGION_SYMBOLS.map(symbol => {
        const count = seen.filter(x => x.region && (symbol.other ? !known.has(x.region) : symbol.regions.includes(x.region))).length;
        return { ...symbol, count, earned: count > 0 };
    });
    const values = { cellar: Object.keys(cellar).length, regions: regionNames.size, reviews: longReviews };
    const statuses = STATUSES.map(s => ({ ...s, value: values[s.metric], earned: values[s.metric] >= s.need }));

    return {
        points, parts, progress, stage: VINE_STAGES[stageIndex], next,
        toNext: next ? Math.max(0, Math.ceil(next.from * VINE_FULL_POINTS - points)) : 0,
        weights: { colors: w.colors, sugars: w.sugars }, hasTaste,
        fruit: fruitFor(color, sugar), baseFruit: quiz ? fruitFor(baseColor, baseSugar) : null, shifts,
        regions, statuses,
        counts: { history: history.length, cellar: values.cellar, reviews: Object.keys(reviews).length },
    };
}
