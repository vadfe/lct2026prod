// Личный кабинет «Своё Вино» (мобильная раскладка): сводка под шапкой, карусель «Лоза / Вкус / Регионы / Статусы / Советы»,
// погреб / рецензии / история, настройки профиля; квиз — фруктовая палитра; кнопки «В погреб» / «Заметка» в карточке вина.
// Всё хранится только в браузере (store.js); сервер вызывается лишь за справкой о вине и похожими винами.
import { artSvg } from './art.js';
import {
    COLORS, DISLIKE_RATING, GUIDE, LIKE_RATING, POINTS, PROVIDERS, RECS_LIMIT, RECS_SEEDS, REVIEW_MIN_CHARS, SUGARS, TEXTS,
    VINE_FULL_POINTS, VINE_STAGES, WEIGHTS,
} from './config.js';
import * as store from './store.js';

let ctx = null;            // { showView, api, getJson }
let prevView = 'scanner';  // куда возвращает «Назад» из кабинета
let currentWine = null;    // вино на экране результата сканера
let listTab = 'cellar';
let quizEditing = false;
let slideIndex = 0;        // открытая карточка карусели (переживает перерисовку)

const SLIDES = ['Лоза', 'Вкус', 'Регионы', 'Статусы', 'Советы'];
const $ = id => document.getElementById(id);
const later = f => ((typeof window !== 'undefined' && window.requestAnimationFrame) ? window.requestAnimationFrame(f) : setTimeout(f, 0));

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
}

function button(className, text, onClick, icon) {
    const btn = el('button', className);
    btn.type = 'button';
    if (icon) btn.append(icon);
    if (text) btn.append(el('span', '', text));
    btn.addEventListener('click', onClick);
    return btn;
}

function card(kicker, title) {
    const box = el('section', 'acc-card');
    if (kicker) box.append(el('div', 'acc-kicker', kicker));
    if (title) box.append(el('h3', 'acc-title', title));
    return box;
}

const dateText = ts => new Date(ts).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });

function thumb(url) {
    if (!url) return el('div', 'acc-thumb empty');
    const img = el('img', 'acc-thumb');
    img.src = ctx.api(url);
    img.alt = '';
    img.loading = 'lazy';
    return img;
}

function sweetnessOf(profile) {
    const scale = profile && (profile.scales || []).find(s => s.key === 'sweetness');
    return scale && scale.word ? scale.word : null;
}

function bar(fraction) {
    const track = el('div', 'acc-bar');
    const fill = el('span');
    fill.style.width = `${Math.round(Math.min(1, Math.max(0, fraction)) * 100)}%`;
    track.append(fill);
    return track;
}

// ---------- точка входа ----------

export function initAccount(options) {
    ctx = options;
    store.setStorage(options.storage);
    $('btn-account').addEventListener('click', openAccount);
    document.addEventListener('keydown', event => { if (event.key === 'Escape') closeModal(); });
    renderHeaderButton();
}

function openAccount() {
    const active = document.querySelector('.view.active');
    if (active && active.id !== 'account-view') prevView = active.id.replace(/-view$/, '');
    quizEditing = false;
    ctx.showView('account');
    renderAccount();
}

function closeAccount() { ctx.showView(prevView || 'scanner'); }

function renderHeaderButton() {
    const btn = $('btn-account');
    const account = store.getAccount();
    const logged = store.isLoggedIn();
    btn.classList.toggle('logged', logged);
    btn.title = logged ? `Личный кабинет: ${account.name}` : 'Войти в личный кабинет';
    btn.replaceChildren(artSvg('ui', 'account', { size: logged ? 30 : 22 }));
    if (!logged) btn.append(el('span', 'acc-header-label', 'Войти'));
}

function refreshAll() {
    renderHeaderButton();
    renderWineActions();
    if ($('account-view').classList.contains('active')) renderAccount();
}

// ---------- экран кабинета ----------

function renderAccount() {
    const root = $('account-view');
    const top = el('div', 'acc-topbar');
    top.append(button('btn-back', 'Назад', closeAccount));
    const body = el('div', 'acc');
    if (!store.isLoggedIn()) body.append(loginCard());
    else if (!store.getAccount().quiz || quizEditing) body.append(quizCard());
    else body.append(...dashboard());
    root.replaceChildren(top, body);
    const track = root.querySelector('.acc-track');
    if (track) later(() => { track.scrollLeft = slideIndex * track.clientWidth; });
}

function guideBlock(open = false) {
    const box = el('details', 'acc-card acc-guide');
    if (open) box.open = true;
    box.append(el('summary', '', 'Как пользоваться кабинетом'));
    const list = el('ol', 'acc-guide-list');
    GUIDE.forEach(line => list.append(el('li', '', line)));
    box.append(list);
    return box;
}

function loginCard() {
    const box = card('Личный кабинет', 'Войдите в один клик');
    box.classList.add('acc-login');
    box.prepend(artSvg('vine', 'golden', { size: 96 }));
    box.append(el('p', 'acc-lead', TEXTS.loginLead));
    Object.entries(PROVIDERS).forEach(([key, provider]) => {
        box.append(button(`acc-provider ${key}`, `Войти через ${provider.title}`, () => {
            store.login(key, provider.defaultName);
            refreshAll();
        }, artSvg('ui', key, { size: 28 })));
    });
    box.append(el('p', 'acc-note', TEXTS.stubNote));
    const stack = el('div', 'acc-stack');
    stack.append(box, guideBlock());
    return stack;
}

// Квиз — та же фруктовая палитра, что в кабинете: каждый фрукт = цвет × сладость
function quizCard() {
    const account = store.getAccount();
    const selected = new Set(store.quizCells(account.quiz));
    const box = card('Первичная настройка', 'Какое вино вам по вкусу?');
    box.append(el('p', 'acc-lead', TEXTS.quizLead));
    const grid = el('div', 'acc-palette acc-quiz-grid');
    grid.append(el('div', ''));
    SUGARS.forEach(s => grid.append(el('div', 'acc-palette-head', s)));
    const save = button('acc-btn primary', 'Сохранить', () => {
        store.setQuiz([...grid.querySelectorAll('.acc-palette-cell.on')].map(c => c.dataset.cell));
        quizEditing = false;
        renderAccount();
    });
    const update = () => { save.disabled = !grid.querySelector('.acc-palette-cell.on'); };
    COLORS.forEach(color => {
        grid.append(el('div', 'acc-palette-row', color));
        SUGARS.forEach(sugar => {
            const f = store.fruitFor(color, sugar);
            const key = `${color}|${sugar}`;
            const cell = button('acc-palette-cell pick', f.title, () => {
                cell.classList.toggle('on');
                cell.setAttribute('aria-pressed', cell.classList.contains('on') ? 'true' : 'false');
                update();
            }, artSvg('fruits', f.key, { size: 40 }));
            cell.dataset.cell = key;
            cell.title = `${color.toLowerCase()}, ${sugar}`;
            if (selected.has(key)) cell.classList.add('on');
            cell.setAttribute('aria-pressed', selected.has(key) ? 'true' : 'false');
            grid.append(cell);
        });
    });
    box.append(grid);
    const actions = el('div', 'acc-actions-row');
    actions.append(save);
    if (account.quiz) actions.append(button('acc-btn', 'Отмена', () => { quizEditing = false; renderAccount(); }));
    box.append(actions);
    update();
    return box;
}

function dashboard() {
    const m = store.metrics();
    const carousel = carouselBlock(m);
    return [summaryCard(m, carousel.go), carousel.node, listsCard(), guideBlock(), settingsCard()];
}

// Сводка под шапкой: все текущие достижения разом; нажатие открывает нужную карточку карусели
function summaryCard(m, go) {
    const account = store.getAccount();
    const box = el('section', 'acc-card acc-summary');
    const head = el('div', 'acc-profile-head');
    head.append(artSvg('ui', 'account', { size: 44 }));
    const who = el('div', 'acc-profile-who');
    who.append(el('div', 'acc-name', account.name), el('div', 'acc-muted', `${m.points} / ${VINE_FULL_POINTS} очков · ${m.counts.cellar} в погребе`));
    head.append(who);
    const chips = el('div', 'acc-sum-chips');
    const chip = (index, art, label) => {
        const c = button('acc-sum-chip', '', () => go(index));
        c.append(art, el('span', '', label));
        return c;
    };
    const earnedRegions = m.regions.filter(r => r.earned);
    const statusArt = el('span', 'acc-sum-statuses');
    m.statuses.forEach(s => statusArt.append(artSvg('statuses', s.key, { size: 26, locked: !s.earned })));
    chips.append(
        chip(0, artSvg('vine', m.stage.key, { size: 34 }), `${Math.round(m.progress * 100)}%`),
        chip(1, artSvg('fruits', m.fruit.key, { size: 34 }), m.fruit.title),
        chip(2, artSvg('regions', (earnedRegions[0] || m.regions[0]).key, { size: 34, locked: !earnedRegions.length }), `${earnedRegions.length} / ${m.regions.length}`),
        chip(3, statusArt, `${m.statuses.filter(s => s.earned).length} / ${m.statuses.length}`),
    );
    box.append(head, chips);
    return box;
}

function carouselBlock(m) {
    const node = el('div', 'acc-carousel');
    const nav = el('div', 'acc-slide-nav');
    const track = el('div', 'acc-track');
    const dots = el('div', 'acc-dots');
    const slides = [vineSlide(m), tasteSlide(m), regionsSlide(m), statusesSlide(m), recsSlide()];
    const paint = i => {
        slideIndex = i;
        nav.querySelectorAll('.acc-slide-tab').forEach((t, k) => t.classList.toggle('on', k === i));
        dots.querySelectorAll('.acc-dot').forEach((d, k) => d.classList.toggle('on', k === i));
    };
    const go = i => {
        paint(i);
        track.scrollTo({ left: i * track.clientWidth, behavior: 'smooth' });
        node.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    SLIDES.forEach((title, i) => {
        nav.append(button('acc-slide-tab', title, () => go(i)));
        dots.append(button('acc-dot', '', () => go(i)));
    });
    slides.forEach(s => { s.classList.add('acc-slide'); track.append(s); });
    track.addEventListener('scroll', () => {
        const i = Math.round(track.scrollLeft / Math.max(1, track.clientWidth));
        if (i !== slideIndex && i >= 0 && i < slides.length) paint(i);
    });
    node.append(nav, track, dots);
    paint(Math.min(slideIndex, slides.length - 1));
    return { node, go };
}

function vineSlide(m) {
    const box = card('Путь лозы', m.stage.title);
    const row = el('div', 'acc-vine');
    row.append(artSvg('vine', m.stage.key, { size: 96 }));
    const info = el('div', 'acc-vine-info');
    info.append(el('div', 'acc-big', `${m.points} / ${VINE_FULL_POINTS}`), bar(m.progress));
    info.append(el('div', 'acc-muted', m.next
        ? `До стадии «${m.next.title}» — ${m.toNext} ${store.plural(m.toNext, 'очко', 'очка', 'очков')}`
        : 'Лоза в полной силе!'));
    row.append(info);
    const stages = el('div', 'acc-stages');
    VINE_STAGES.forEach(stage => {
        const item = el('div', `acc-stage${stage.key === m.stage.key ? ' current' : ''}`);
        item.append(artSvg('vine', stage.key, { size: 40, locked: m.progress < stage.from }), el('span', '', `${Math.round(stage.from * 100)}%`));
        item.title = stage.title;
        stages.append(item);
    });
    box.append(row, stages, el('div', 'acc-rule',
        `Как растёт: скан +${POINTS.scan} · вино в погреб +${POINTS.cellar} · рецензия от ${REVIEW_MIN_CHARS} символов +${POINTS.review}. Сейчас: сканы ${m.parts.scan}, погреб ${m.parts.cellar}, рецензии ${m.parts.review}.`));
    return box;
}

function tasteSlide(m) {
    const fruit = m.fruit;
    const box = card('Фруктовая палитра', `Ваш фрукт: ${fruit.title}`);
    box.append(el('div', 'acc-muted', `${fruit.color.toLowerCase()}, ${fruit.sugar}`));
    if (m.shifts.length) {
        const note = el('div', 'acc-shift');
        note.append(el('b', '', 'Профиль сместился: '), document.createTextNode(m.shifts.join('; ')));
        box.append(note);
    }
    const grid = el('div', 'acc-palette');
    grid.append(el('div', ''));
    SUGARS.forEach(s => grid.append(el('div', 'acc-palette-head', s)));
    const cw = m.weights.colors, sw = m.weights.sugars;
    const maxW = Math.max(...COLORS.flatMap(c => SUGARS.map(s => cw[c] * sw[s])), 0);
    COLORS.forEach(color => {
        grid.append(el('div', 'acc-palette-row', color));
        SUGARS.forEach(sugar => {
            const f = store.fruitFor(color, sugar);
            const w = maxW > 0 ? (cw[color] * sw[sugar]) / maxW : 0;
            const cell = el('div', `acc-palette-cell${f.key === fruit.key ? ' main' : ''}`);
            cell.style.setProperty('--w', w.toFixed(2));
            cell.title = `${f.title}: ${color.toLowerCase()}, ${sugar}`;
            cell.append(artSvg('fruits', f.key, { size: 34, locked: w === 0 }), el('span', '', f.title));
            grid.append(cell);
        });
    });
    box.append(grid, el('div', 'acc-rule',
        `Старт — ваш квиз (+${WEIGHTS.quiz}). Лайк — вино в погребе или оценка ${LIKE_RATING}–5 бокалов: +${WEIGHTS.like} его цвету и сладости; оценка 1–${DISLIKE_RATING}: ${WEIGHTS.dislike}.`));
    return box;
}

function regionsSlide(m) {
    const box = card('Региональные символы', `Открыто ${m.regions.filter(r => r.earned).length} из ${m.regions.length}`);
    const grid = el('div', 'acc-regions');
    m.regions.forEach(r => {
        const item = el('div', `acc-region${r.earned ? ' earned' : ''}`);
        item.append(artSvg('regions', r.key, { size: 56, locked: !r.earned }), el('div', 'acc-region-title', r.title));
        item.append(el('div', 'acc-muted', r.earned
            ? `${r.count} ${store.plural(r.count, 'вино', 'вина', 'вин')}`
            : (r.other ? r.hint : `вин региона «${r.regions[0]}» пока нет`)));
        grid.append(item);
    });
    box.append(grid, el('div', 'acc-rule', 'Символ открывается первым вином региона в истории или погребе.'));
    return box;
}

function statusesSlide(m) {
    const box = card('Высшая лига', 'Статусы');
    m.statuses.forEach(s => {
        const row = el('div', `acc-status${s.earned ? ' earned' : ''}`);
        row.append(artSvg('statuses', s.key, { size: 72, locked: !s.earned }));
        const info = el('div', 'acc-status-info');
        info.append(el('div', 'acc-status-title', s.title), el('div', 'acc-muted', `За ${s.rule(s.need)}`), bar(s.value / s.need),
            el('div', 'acc-status-count', s.earned ? `Получен · ${s.value} / ${s.need}` : `${Math.min(s.value, s.need)} / ${s.need}`));
        row.append(info);
        box.append(row);
    });
    return box;
}

function settingsCard() {
    const account = store.getAccount();
    const box = card('Профиль', '');
    box.append(el('div', 'acc-muted', `Вход через ${PROVIDERS[account.provider] ? PROVIDERS[account.provider].title : account.provider} · демо, данные только на этом устройстве`));
    const actions = el('div', 'acc-actions-row');
    actions.append(
        button('acc-btn small', 'Пройти квиз заново', () => { quizEditing = true; renderAccount(); }),
        button('acc-btn small', 'Изменить имя', () => {
            const name = window.prompt('Как к вам обращаться?', account.name);
            if (name !== null) { store.setName(name); refreshAll(); }
        }),
        button('acc-btn small', 'Выйти', () => { store.logout(); refreshAll(); }),
        button('acc-btn small danger', 'Удалить мои данные', () => {
            if (window.confirm('Удалить профиль, историю, погреб и рецензии с этого устройства?')) { store.wipe(); refreshAll(); }
        }),
    );
    box.append(actions);
    return box;
}

// ---------- рекомендации ----------

function recsSlide() {
    const box = card('Советы', 'Вам может понравиться');
    box.append(el('p', 'acc-caption', TEXTS.recsCaption));
    const list = el('div', 'acc-recs');
    list.append(el('div', 'acc-muted', 'Подбираем вина…'));
    box.append(list);
    loadRecs(list);
    return box;
}

async function loadRecs(list) {
    const cellar = store.getCellar();
    const wines = store.knownWines();
    const seeds = [
        ...Object.values(cellar).sort((a, b) => b.added_ts - a.added_ts),
        ...[...wines.values()].filter(w => store.getRating(w.slug) >= LIKE_RATING),
    ].map(w => w.slug).filter((slug, i, all) => slug && all.indexOf(slug) === i).slice(0, RECS_SEEDS);

    const exclude = new Set([...Object.keys(cellar), ...seeds]);
    const picks = new Map();
    const results = await Promise.allSettled(seeds.map(slug =>
        ctx.getJson(ctx.api(`/api/sommelier/wine/${encodeURIComponent(slug)}/alternatives?limit=4`))));
    results.flatMap(r => (r.status === 'fulfilled' ? r.value.items : []))
        .sort((a, b) => b.score - a.score)
        .forEach(item => {
            if (!exclude.has(item.id) && !picks.has(item.id)) {
                picks.set(item.id, { slug: item.id, title: item.name, winery: item.winery, image_url: item.image_url, note: item.reasons[0] || item.facts });
            }
        });

    const fruit = store.metrics().fruit;
    if (picks.size < RECS_LIMIT && fruit) {
        try {
            const data = await ctx.getJson(ctx.api('/api/sommelier/pairing/dish'), {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: 'подарок', scenario: 'gift', filters: { color: fruit.color, sweetness: [fruit.sugar] } }),
            });
            (data.wines || []).forEach(w => {
                if (w.slug && !exclude.has(w.slug) && !picks.has(w.slug)) {
                    picks.set(w.slug, { slug: w.slug, title: w.name, winery: w.region || '', image_url: w.image_url, note: [w.color, w.sweetness].filter(Boolean).join(', ').toLowerCase() });
                }
            });
        } catch { /* подбор по профилю необязателен: остаются похожие на погреб */ }
    }

    const items = [...picks.values()].slice(0, RECS_LIMIT);
    if (!list.isConnected) return;
    if (!items.length) {
        list.replaceChildren(el('div', 'acc-muted', 'Добавьте вино в погреб или поставьте оценку — и здесь появятся похожие вина.'));
        return;
    }
    list.replaceChildren(...items.map(item => {
        const tile = button('acc-rec', '', () => openWine(item));
        tile.append(thumb(item.image_url));
        const text = el('div', 'acc-rec-text');
        text.append(el('div', 'acc-rec-title', item.title), el('div', 'acc-muted', item.winery || ''));
        if (item.note) text.append(el('div', 'acc-rec-note', item.note));
        tile.append(text);
        return tile;
    }));
}

// ---------- погреб, рецензии, история ----------

function listsCard() {
    const box = el('section', 'acc-card');
    const tabs = el('div', 'acc-tabs');
    const withRating = (w, text) => {
        const r = store.getRating(w.slug);
        return r ? `${text} · оценка ${r}/5` : text;
    };
    const lists = {
        cellar: { title: `Погреб · ${Object.keys(store.getCellar()).length}`, items: Object.values(store.getCellar()).sort((a, b) => b.added_ts - a.added_ts), meta: w => withRating(w, `добавлено ${dateText(w.added_ts)}`) },
        reviews: { title: `Рецензии · ${Object.keys(store.getReviews()).length}`, items: Object.values(store.getReviews()).sort((a, b) => b.updated_ts - a.updated_ts), meta: w => `«${w.text.slice(0, 80)}${w.text.length > 80 ? '…' : ''}»` },
        history: { title: `История · ${store.getHistory().length}`, items: store.getHistory(), meta: w => withRating(w, `${dateText(w.ts)} · ${w.status === 'found' ? 'найдено' : 'похоже'}`) },
    };
    const body = el('div', 'acc-list');
    const show = key => {
        listTab = key;
        tabs.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.tab === key));
        const { items, meta } = lists[key];
        body.replaceChildren(...(items.length ? items.map(w => {
            const row = button('acc-row', '', () => openWine(w));
            row.append(thumb(w.image_url));
            const text = el('div', 'acc-row-text');
            text.append(el('div', 'acc-row-title', w.title), el('div', 'acc-muted', w.winery), el('div', 'acc-row-meta', meta(w)));
            row.append(text);
            return row;
        }) : [el('div', 'acc-muted', {
            cellar: 'Погреб пуст. Нажмите «В погреб» в карточке распознанного вина.',
            reviews: 'Рецензий пока нет. Нажмите «Заметка» в карточке вина.',
            history: 'История пуста. Отсканируйте этикетку — она появится здесь.',
        }[key])]));
    };
    Object.entries(lists).forEach(([key, list]) => {
        const tab = button('acc-tab', list.title, () => show(key));
        tab.dataset.tab = key;
        tabs.append(tab);
    });
    box.append(tabs, body);
    show(listTab);
    return box;
}

// ---------- карточка вина (окно поверх любого экрана) ----------

function closeModal() {
    const modal = $('acc-modal');
    if (modal) modal.remove();
}

// Оценка бокалами — тот же ключ, что у блока «Поставь свою оценку» в сканере
function ratingRow(slug) {
    const box = el('div', 'acc-rating');
    box.append(el('div', 'acc-quiz-label', 'Ваша оценка'));
    const glasses = el('div', 'acc-glasses');
    const label = el('span', 'acc-muted');
    const paint = () => {
        const value = store.getRating(slug);
        glasses.querySelectorAll('.acc-glass').forEach((g, i) => {
            g.classList.toggle('on', i < value);
            g.querySelector('img').src = i < value ? 'img/glass_filled_straight.png' : 'img/glass_empty_straight.png';
        });
        label.textContent = value ? `${value} из 5 · ${value >= LIKE_RATING ? 'лайк' : (value <= DISLIKE_RATING ? 'не моё' : 'нейтрально')}` : 'нажмите на бокал';
    };
    for (let i = 1; i <= 5; i += 1) {
        const img = el('img');
        img.alt = String(i);
        const glass = button('acc-glass', '', () => { store.setRating(slug, i); paint(); refreshAll(); }, img);
        glass.title = `${i} из 5`;
        glasses.append(glass);
    }
    box.append(glasses, label);
    paint();
    return box;
}

async function openWine(wine) {
    closeModal();
    const meta = store.wineMeta({ ...(store.knownWines().get(wine.slug) || {}), ...wine });
    const modal = el('div', 'acc-modal');
    modal.id = 'acc-modal';
    const backdrop = el('div', 'acc-modal-backdrop');
    backdrop.addEventListener('click', closeModal);
    const sheet = el('div', 'acc-sheet');
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-label', meta.title);
    sheet.append(button('acc-close', '×', closeModal));

    const head = el('div', 'acc-sheet-head');
    head.append(thumb(meta.image_url));
    const who = el('div');
    const tags = el('div', 'acc-tags');
    who.append(el('h3', 'acc-title', meta.title), el('div', 'acc-muted', meta.winery), tags);
    head.append(who);
    sheet.append(head);
    const paintTags = () => tags.replaceChildren(...[meta.category, meta.sweetness, meta.region].filter(Boolean).map(t => el('span', 'acc-tag', t)));
    paintTags();
    sheet.append(ratingRow(meta.slug));

    if (store.isLoggedIn()) {
        const actions = el('div', 'acc-actions-row');
        const cellarBtn = button('acc-btn', '', () => {
            store.toggleCellar(meta);
            paintCellar();
            refreshAll();
        });
        const paintCellar = () => {
            const on = store.inCellar(meta.slug);
            cellarBtn.classList.toggle('on', on);
            cellarBtn.replaceChildren(artSvg('ui', 'cellar', { size: 22 }), el('span', '', on ? 'В погребе ✓' : 'В погреб'));
        };
        paintCellar();
        actions.append(cellarBtn);
        sheet.append(actions);

        const review = store.getReview(meta.slug);
        const label = el('label', 'acc-quiz-label', 'Дегустационная заметка');
        const area = el('textarea', 'acc-textarea');
        area.maxLength = 4000;
        area.rows = 5;
        area.placeholder = 'Цвет, аромат, вкус, с чем пили, кому понравится…';
        area.value = review ? review.text : '';
        const counter = el('div', 'acc-counter');
        const paintCounter = () => {
            const n = area.value.trim().length;
            counter.textContent = n >= REVIEW_MIN_CHARS ? `${n} символов · развёрнутая рецензия ✓` : `${n} / ${REVIEW_MIN_CHARS} символов до развёрнутой рецензии`;
            counter.classList.toggle('ok', n >= REVIEW_MIN_CHARS);
        };
        area.addEventListener('input', paintCounter);
        paintCounter();
        const saved = el('span', 'acc-muted');
        const save = button('acc-btn primary', 'Сохранить заметку', () => {
            store.setReview(meta, area.value);
            saved.textContent = area.value.trim() ? 'Сохранено' : 'Заметка удалена';
            refreshAll();
        });
        const row = el('div', 'acc-actions-row');
        row.append(save, saved);
        sheet.append(label, area, counter, row);
    } else {
        sheet.append(button('acc-btn primary', 'Войти, чтобы сохранить в погреб', () => { closeModal(); openAccount(); }));
    }

    modal.append(backdrop, sheet);
    document.body.append(modal);

    if (meta.slug && (!meta.category || !meta.region || !meta.sweetness)) {
        try {
            const info = await ctx.getJson(ctx.api(`/api/sommelier/wine/${encodeURIComponent(meta.slug)}`));
            if (info.kind === 'wine_info') {
                const c = info.card || {};
                meta.category = meta.category || c.category || null;
                meta.region = meta.region || c.region || null;
                meta.sweetness = meta.sweetness || sweetnessOf(info.profile);
                meta.winery = meta.winery || c.winery || '';
                paintTags();
            }
        } catch { /* справка необязательна: остаются сохранённые поля */ }
    }
}

// ---------- врезка в карточку распознанного вина ----------

// Вызывается сканером после показа вина: record=false для просмотра результатов пакетной проверки
export function onWineShown(winner, status, info, imageUrl, record = true) {
    if (!winner || !winner.slug) { currentWine = null; renderWineActions(); return; }
    const c = (info && info.card) || {};
    currentWine = store.wineMeta({
        slug: winner.slug, product_id: winner.product_id, title: winner.title, winery: winner.manufacturer || c.winery,
        category: c.category, region: c.region, sweetness: sweetnessOf(info && info.profile), image_url: imageUrl || winner.image_url,
    });
    if (record) store.recordScan(currentWine, status);
    renderWineActions();
}

function renderWineActions() {
    const anchor = $('rating-section');
    if (!anchor) return;
    let box = $('acc-wine-actions');
    if (!box) {
        box = el('div', 'acc-wine-actions');
        box.id = 'acc-wine-actions';
        anchor.after(box);
    }
    box.classList.toggle('hidden', !currentWine);
    if (!currentWine) return;
    const wine = currentWine;
    if (!store.isLoggedIn()) {
        box.replaceChildren(button('acc-btn', 'Войти и сохранить в «Винный погреб»', openAccount, artSvg('ui', 'account', { size: 22 })));
        return;
    }
    const on = store.inCellar(wine.slug);
    const cellarBtn = button(`acc-btn${on ? ' on' : ''}`, on ? 'В погребе ✓' : 'В погреб', () => {
        store.toggleCellar(wine);
        refreshAll();
    }, artSvg('ui', 'cellar', { size: 22 }));
    const noteBtn = button('acc-btn', store.getReview(wine.slug) ? 'Моя заметка' : 'Заметка', () => openWine(wine), artSvg('ui', 'note', { size: 22 }));
    box.replaceChildren(cellarBtn, noteBtn);
}
