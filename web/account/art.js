// Картинки личного кабинета: inline SVG в стиле vino-svoe (плоские заливки, полупрозрачные блики, без градиентов).
// Каждая картинка — данные [тег, атрибуты, дети|текст]; artSvg() собирает DOM, artMarkup() — текст SVG для предпросмотра.
// locked — серая версия ещё не полученной картинки: цвета пересчитываются здесь, без CSS-фильтров.

const NS = 'http://www.w3.org/2000/svg';

const C = {
    ink: '#2c2a28', muted: '#857e79', line: '#ebe5df', wine: '#8f3d42', wineSoft: '#f9f1f1', wineLine: '#edd4d6',
    stem: '#9a8c74', leaf: '#b9c98c', leafLine: '#8fa36a', sage: '#8fb48a', honey: '#e2b97f', rose: '#cf8f88',
    gold: '#e2c77f', goldDeep: '#b8973f', shade: '#5a3b2e', cream: '#f6f1e4', ground: '#efe9e3', water: '#8fb0b4',
};

const r2 = n => Math.round(n * 100) / 100;

function hexToRgb(hex) {
    const h = hex.replace('#', '');
    const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
    return [0, 2, 4].map(i => parseInt(full.slice(i, i + 2), 16));
}
const rgbToHex = rgb => '#' + rgb.map(v => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, '0')).join('');
function mix(a, b, t) {
    const x = hexToRgb(a), y = hexToRgb(b);
    return rgbToHex(x.map((v, i) => v + (y[i] - v) * t));
}
function lockColor(hex) {
    const [r, g, b] = hexToRgb(hex);
    const grey = 0.299 * r + 0.587 * g + 0.114 * b;
    return mix(rgbToHex([grey, grey, grey]), '#efebe7', 0.45);
}

// ---------- примитивы ----------

const g = (attrs, kids) => ['g', attrs, kids];

// Ягода: тёмный край снизу-справа, основной цвет, белый блик — как .gb-berry
function berry(cx, cy, r, color) {
    return g({}, [
        ['circle', { cx: r2(cx), cy: r2(cy), r: r2(r), fill: mix(color, C.shade, 0.35) }],
        ['circle', { cx: r2(cx - r * 0.12), cy: r2(cy - r * 0.14), r: r2(r * 0.84), fill: color }],
        ['ellipse', { cx: r2(cx - r * 0.36), cy: r2(cy - r * 0.38), rx: r2(r * 0.28), ry: r2(r * 0.19), fill: mix(color, '#ffffff', 0.7),
            ...(r >= 3 ? { transform: `rotate(-30 ${r2(cx - r * 0.36)} ${r2(cy - r * 0.38)})` } : {}) }],
    ]);
}

function ovalBerry(cx, cy, rx, ry, color, rot = 0) {
    return g({ transform: `rotate(${rot} ${cx} ${cy})` }, [
        ['ellipse', { cx, cy, rx, ry, fill: mix(color, C.shade, 0.35) }],
        ['ellipse', { cx: r2(cx - rx * 0.12), cy: r2(cy - ry * 0.1), rx: r2(rx * 0.84), ry: r2(ry * 0.88), fill: color }],
        ['ellipse', { cx: r2(cx - rx * 0.38), cy: r2(cy - ry * 0.42), rx: r2(rx * 0.26), ry: r2(ry * 0.16), fill: mix(color, '#ffffff', 0.7) }],
    ]);
}

function leaf(x, y, len, angle, fill = C.leaf, line = C.leafLine) {
    const L = len;
    return g({ transform: `translate(${x} ${y}) rotate(${angle})` }, [
        ['path', { d: `M0 0 C${r2(L * 0.35)} ${r2(-L * 0.4)} ${r2(L * 0.8)} ${r2(-L * 0.32)} ${L} 0 C${r2(L * 0.8)} ${r2(L * 0.32)} ${r2(L * 0.35)} ${r2(L * 0.4)} 0 0Z`,
            fill, stroke: line, 'stroke-width': 1 }],
        ['path', { d: `M1 0L${r2(L * 0.86)} 0`, fill: 'none', stroke: line, 'stroke-width': 0.9, 'stroke-linecap': 'round' }],
    ]);
}

const stroke = (d, color, width, extra = {}) => ['path', { d, fill: 'none', stroke: color, 'stroke-width': width, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', ...extra }];

// Точки грозди: ряды сверху вниз, n — число ягод в ряду; одна и та же форма для всех стадий «Пути лозы»
function bunchPoints(cx, top, rows, step, rowStep) {
    const pts = [];
    rows.forEach((n, i) => {
        for (let j = 0; j < n; j += 1) pts.push([cx + (j - (n - 1) / 2) * step, top + i * rowStep]);
    });
    return pts;
}

function bunch(cx, top, r, colors, rows = [4, 3, 3, 2, 1]) {
    return g({}, bunchPoints(cx, top, rows, r * 1.95, r * 1.6).map(([x, y], k) => berry(x, y, r, colors[k % colors.length])));
}

// Соцветие той же формы, что и гроздь: мелкие зачатки (bud) или раскрытые цветки (flower)
function inflorescence(kind) {
    // зачатки — маленькое соцветие у самой лозы; цветки — уже в полный размер грозди
    const pts = kind === 'bud' ? bunchPoints(32, 24, [4, 3, 2, 1], 4.3, 3.8) : bunchPoints(32, 25, [6, 5, 5, 4, 3, 2, 1], 5.3, 4.6);
    return g({}, pts.map(([x, y], k) => {
        if (kind === 'bud') return berry(x, y, 2, k % 2 ? '#a9bf7a' : '#c4d29a');
        if (k % 3 === 2) return berry(x, y, 2.3, k % 2 ? '#a9bf7a' : '#c4d29a');
        return g({}, [
            ['circle', { cx: r2(x), cy: r2(y), r: 2.9, fill: C.cream, stroke: '#d9cfb8', 'stroke-width': 0.7 }],
            ['circle', { cx: r2(x), cy: r2(y), r: 1, fill: C.honey }],
        ]);
    }));
}

function sparkle(x, y, s, color = C.gold) {
    return ['path', { d: `M${x} ${y - s}L${r2(x + s * 0.28)} ${r2(y - s * 0.28)}L${x + s} ${y}L${r2(x + s * 0.28)} ${r2(y + s * 0.28)}L${x} ${y + s}L${r2(x - s * 0.28)} ${r2(y + s * 0.28)}L${x - s} ${y}L${r2(x - s * 0.28)} ${r2(y - s * 0.28)}Z`, fill: color }];
}

const glint = (cx, cy, rx, ry, rot = -30) => ['ellipse', { cx, cy, rx, ry, fill: '#ffffff', 'fill-opacity': 0.55, transform: `rotate(${rot} ${cx} ${cy})` }];
const ground = () => ['ellipse', { cx: 32, cy: 58, rx: 20, ry: 3, fill: C.ground }];

function medallion(fill, ring, ringWidth = 1.5) {
    return ['circle', { cx: 32, cy: 32, r: 29, fill, stroke: ring, 'stroke-width': ringWidth }];
}
// Грамота статуса: свиток с валиками, двойная рамка, крупная эмблема (поле x 17–47, y 17–46) и восковая печать цвета статуса
const SCROLL = { paper: '#fbf3dc', edge: '#d9c49a', roll: '#efe0b8', rollEdge: '#c9b07a', ink: '#8a6a1f' };
function diploma(seal, emblem) {
    const roll = y => g({}, [
        ['rect', { x: 8, y, width: 48, height: 7, rx: 3.5, fill: SCROLL.roll, stroke: SCROLL.rollEdge, 'stroke-width': 1 }],
        ['ellipse', { cx: 9.5, cy: y + 3.5, rx: 2, ry: 3.5, fill: mix(SCROLL.roll, C.shade, 0.25) }],
        ['ellipse', { cx: 54.5, cy: y + 3.5, rx: 2, ry: 3.5, fill: mix(SCROLL.roll, C.shade, 0.25) }],
    ]);
    return [
        ['rect', { x: 11, y: 9, width: 42, height: 46, fill: SCROLL.paper, stroke: SCROLL.edge, 'stroke-width': 1.2 }],
        ['rect', { x: 14.5, y: 14, width: 35, height: 36, fill: 'none', stroke: C.gold, 'stroke-width': 1.3 }],
        ['rect', { x: 16.5, y: 16, width: 31, height: 32, fill: 'none', stroke: C.gold, 'stroke-width': 0.6 }],
        roll(5), roll(52),
        ...emblem,
        ['path', { d: 'M41 50L39 60L43 57.5L45 61L46.5 51Z', fill: mix(seal, C.shade, 0.2) }],
        ['path', { d: 'M49 50L51 60L47 57.5L45 61L43.5 51Z', fill: seal }],
        ['circle', { cx: 45, cy: 47, r: 6.2, fill: seal }],
        ['circle', { cx: 45, cy: 47, r: 4.3, fill: 'none', stroke: mix(seal, '#ffffff', 0.45), 'stroke-width': 0.9 }],
        sparkle(45, 47, 2.2, mix(seal, '#ffffff', 0.55)),
    ];
}

// ---------- «Путь лозы» ----------

const UNRIPE = ['#b9c98c', '#a9bf7a', '#c4d29a'];
const TURNING = ['#e0b85a', '#d98a52', '#c9614f', '#e3c46e', '#d47a55'];   // недозревшие: жёлто-красные
const RIPE = ['#4a1a26', '#5e2030', '#3b1520'];                           // вызревшие: чёрно-красные

function cane() {
    return g({}, [
        stroke('M8 14C20 9 42 9 56 15', C.stem, 3.2),
        stroke('M32 11L32 21', C.stem, 2),
        leaf(14, 13, 15, 155),
        stroke('M48 12c3 -1 5 2 3 4c-2 1 -3 -1 -1 -2', C.stem, 1.2),
    ]);
}

const vine = [
    { key: 'bud', title: 'Почка на веточке', shapes: [cane(), inflorescence('bud')] },
    { key: 'flowers', title: 'Цветки', shapes: [cane(), inflorescence('flower')] },
    { key: 'green', title: 'Зелёная гроздь', shapes: [cane(), bunch(32, 25, 4.4, UNRIPE)] },
    { key: 'ripe', title: 'Налитая гроздь', shapes: [cane(), bunch(32, 25, 4.4, TURNING)] },
    { key: 'golden', title: 'Гроздь с золотым ореолом', shapes: [
        ['circle', { cx: 32, cy: 36, r: 28, fill: mix(C.gold, '#fefdfa', 0.82) }],
        ['circle', { cx: 32, cy: 36, r: 22, fill: mix(C.gold, '#fefdfa', 0.66) }],
        ['circle', { cx: 32, cy: 36, r: 27, fill: 'none', stroke: C.gold, 'stroke-width': 1.5 }],
        cane(), bunch(32, 25, 4.4, RIPE),
        sparkle(10, 32, 3.5), sparkle(54, 28, 3), sparkle(50, 52, 2.5),
    ] },
];

// ---------- фрукты палитры ----------

const fruits = [
    { key: 'cherry', title: 'Вишня', shapes: [
        stroke('M34 12C30 20 24 30 22 37', '#7a5a3a', 1.8),
        stroke('M34 12C38 22 42 32 42 41', '#7a5a3a', 1.8),
        leaf(34, 12, 16, -25),
        berry(22, 44, 9, '#b3303d'), berry(42, 48, 9, '#a12a36'),
    ] },
    { key: 'currant', title: 'Смородина', shapes: [
        stroke('M12 12C24 16 34 26 44 44', '#7a5a3a', 1.6),
        leaf(12, 12, 14, 200),
        ...[[22, 22, 5.2], [31, 28, 5.6], [24, 33, 5], [38, 36, 5.6], [31, 42, 5.2], [44, 46, 5]].map(([x, y, r], i) => berry(x, y, r, i % 2 ? '#c42a36' : '#dc3a46')),
        ...[[22, 22, 5.2], [31, 28, 5.6], [24, 33, 5], [38, 36, 5.6], [31, 42, 5.2], [44, 46, 5]].map(([x, y, r]) => ['circle', { cx: r2(x + r * 0.35), cy: r2(y + r * 0.45), r: 0.7, fill: '#5a1f24' }]),
    ] },
    { key: 'strawberry', title: 'Клубника', shapes: [
        ['path', { d: 'M32 57C18 47 12 33 18 25C24 19 40 19 46 25C52 33 46 47 32 57Z', fill: mix('#d8434c', C.shade, 0.3) }],
        ['path', { d: 'M31 54C19 45 14 33 19 26C24 21 39 21 44 26C49 33 44 45 31 54Z', fill: '#d8434c' }],
        ...[[24, 30], [32, 29], [40, 30], [22, 37], [29, 36], [36, 36], [43, 37], [26, 43], [33, 43], [39, 43], [30, 49], [35, 49]]
            .map(([x, y]) => ['ellipse', { cx: x, cy: y, rx: 0.9, ry: 1.4, fill: '#f6e3a1' }]),
        glint(23, 29, 3, 2),
        ...[-70, -35, 0, 35, 70].map(a => leaf(32, 23, 9, -90 + a, C.sage, '#6f9a6a')),
        stroke('M32 22L33 13', '#6f9a6a', 1.8),
    ] },
    { key: 'watermelon', title: 'Арбуз', shapes: [g({ transform: 'translate(0 8)' }, [
        ['path', { d: 'M6 20A26 26 0 0 0 58 20Z', fill: '#6f9a5a' }],
        ['path', { d: 'M9 20A23 23 0 0 0 55 20Z', fill: '#e8efd0' }],
        ['path', { d: 'M11 20A21 21 0 0 0 53 20Z', fill: '#e05a5f' }],
        ...[[22, 27, -30], [32, 31, 0], [42, 27, 30], [27, 35, -15], [37, 35, 15]]
            .map(([x, y, a]) => ['ellipse', { cx: x, cy: y, rx: 1.1, ry: 1.9, fill: C.ink, transform: `rotate(${a} ${x} ${y})` }]),
        ['path', { d: 'M13 21L51 21', stroke: mix('#e05a5f', '#ffffff', 0.45), 'stroke-width': 1.2, fill: 'none' }],
    ])] },
    { key: 'lemon', title: 'Лимон', shapes: [
        leaf(38, 18, 15, -35),
        g({ transform: 'rotate(-18 32 36)' }, [
            ['ellipse', { cx: 10.5, cy: 36, rx: 3, ry: 2.4, fill: mix('#f2d45c', C.shade, 0.15) }],
            ['ellipse', { cx: 53.5, cy: 36, rx: 3, ry: 2.4, fill: mix('#f2d45c', C.shade, 0.15) }],
            ['ellipse', { cx: 32, cy: 36, rx: 21, ry: 15, fill: mix('#f2d45c', C.shade, 0.25) }],
            ['ellipse', { cx: 31, cy: 34.5, rx: 19, ry: 13, fill: '#f2d45c' }],
            ['ellipse', { cx: 24, cy: 29, rx: 5, ry: 2.6, fill: mix('#f2d45c', '#ffffff', 0.6) }],
        ]),
    ] },
    { key: 'apple', title: 'Яблоко', shapes: [
        ['path', { d: 'M32 22C24 14 10 18 10 32C10 46 20 56 28 56C30 56 31 55 32 55C33 55 34 56 36 56C44 56 54 46 54 32C54 18 40 14 32 22Z', fill: mix('#dcd56a', C.shade, 0.28) }],
        ['path', { d: 'M31 23C24 16 12 20 12 32C12 44 21 53 28 53C30 53 31 52 32 52C33 52 34 53 36 53C43 53 51 44 51 32C51 20 39 16 31 23Z', fill: '#dcd56a' }],
        ['ellipse', { cx: 42, cy: 40, rx: 7, ry: 9, fill: mix('#dcd56a', '#c9cf5a', 0.7) }],
        glint(20, 30, 4, 2.6, -50),
        stroke('M32 22C32 16 33 12 36 9', '#7a5a3a', 2),
        leaf(34, 15, 14, -30),
    ] },
    { key: 'pear', title: 'Груша', shapes: [
        ['path', { d: 'M32 14C38 14 40 21 40 27C48 33 52 41 50 48C48 56 40 58 32 58C24 58 16 56 14 48C12 41 16 33 24 27C24 21 26 14 32 14Z', fill: mix('#e8c95a', C.shade, 0.28) }],
        ['path', { d: 'M31 16C36 16 38 22 38 28C45 33 49 41 47 47C45 54 38 55 31 55C24 55 18 53 16 47C15 41 18 34 25 28C25 22 27 16 31 16Z', fill: '#e8c95a' }],
        glint(23, 40, 3.5, 6, 15),
        stroke('M32 14C32 10 33 8 35 6', '#7a5a3a', 2),
        leaf(34, 10, 12, -20),
    ] },
    { key: 'pineapple', title: 'Ананас', shapes: [
        ...[[-40, 15], [-18, 19], [0, 21], [18, 19], [40, 15]].map(([a, l]) => g({ transform: `translate(32 28) rotate(${a - 90})` }, [
            ['path', { d: `M0 0C${l * 0.3} -3 ${l * 0.7} -2 ${l} 0C${l * 0.7} 2 ${l * 0.3} 3 0 0Z`, fill: C.sage, stroke: '#6f9a6a', 'stroke-width': 0.8 }],
        ])),
        ['ellipse', { cx: 32, cy: 43, rx: 14, ry: 16, fill: mix('#f0cd4e', C.shade, 0.25) }],
        ['ellipse', { cx: 31, cy: 42, rx: 12.5, ry: 14.5, fill: '#f0cd4e' }],
        ...[[26, 33], [36, 33], [21, 40], [31, 39], [41, 40], [25, 46], [35, 46], [29, 52], [39, 52], [22, 52]]
            .map(([x, y]) => ['path', { d: `M${x - 2.8} ${y}L${x} ${y - 2.8}L${x + 2.8} ${y}L${x} ${y + 2.8}Z`, fill: 'none', stroke: '#8a5a2b', 'stroke-width': 1.1 }]),
        glint(25, 36, 2.5, 4, 20),
    ] },
    { key: 'grapefruit', title: 'Грейпфрут', shapes: [
        ['circle', { cx: 32, cy: 34, r: 23, fill: '#eea0a8' }],
        ['circle', { cx: 32, cy: 34, r: 20, fill: '#fde8ea' }],
        ['circle', { cx: 32, cy: 34, r: 18, fill: '#f28ea2' }],
        ...Array.from({ length: 8 }, (_, i) => {
            const a = (i * Math.PI) / 4;
            return ['path', { d: `M32 34L${r2(32 + 18 * Math.cos(a))} ${r2(34 + 18 * Math.sin(a))}`, stroke: '#fde8ea', 'stroke-width': 1.6, fill: 'none' }];
        }),
        ['circle', { cx: 32, cy: 34, r: 2.4, fill: '#fde8ea' }],
        glint(24, 26, 4, 2.4, -40),
    ] },
    { key: 'dogwood', title: 'Кизил', shapes: [
        stroke('M32 9C29 15 23 22 19 27', '#7a5a3a', 1.4),
        stroke('M32 9C32 17 32 24 32 31', '#7a5a3a', 1.4),
        stroke('M32 9C35 15 41 22 45 27', '#7a5a3a', 1.4),
        leaf(32, 9, 15, -160, C.sage, '#6f9a6a'), leaf(32, 9, 15, -20, C.sage, '#6f9a6a'),
        ovalBerry(17, 39, 4.6, 11, '#e46a8c', 22),
        ovalBerry(47, 39, 4.6, 11, '#d95c80', -22),
        ovalBerry(32, 44, 4.8, 12, '#ee7898', 0),
    ] },
    { key: 'pomegranate', title: 'Гранат', shapes: [
        ['path', { d: 'M25 21L27 13L30 18L32 11L34 18L37 13L39 21Z', fill: '#c4607a' }],
        ['circle', { cx: 32, cy: 39, r: 19, fill: mix('#e57a92', C.shade, 0.3) }],
        ['circle', { cx: 30.5, cy: 37.5, r: 16.5, fill: '#e57a92' }],
        glint(23, 31, 4.5, 2.8, -40),
    ] },
    { key: 'raspberry', title: 'Малина', shapes: [
        ...[[3, 24], [4, 30.5], [4, 37], [3, 43.5], [2, 50]].flatMap(([n, y]) =>
            Array.from({ length: n }, (_, j) => berry(32 + (j - (n - 1) / 2) * 7.2, y, 4.3, j % 2 ? '#ea7ea0' : '#f290ae'))),
        ...[-60, -25, 25, 60].map(a => leaf(32, 21, 8, -90 + a, C.sage, '#6f9a6a')),
        stroke('M32 20L32 12', '#6f9a6a', 1.6),
    ] },
];

// ---------- региональные символы ----------

const regions = [
    { key: 'kuban', title: 'Кубанский колос', shapes: [
        medallion(C.wineSoft, C.wineLine),
        leaf(32, 52, 14, -150, C.leaf), leaf(32, 52, 14, -30, C.leaf),
        stroke('M32 56L32 14', '#b48a4a', 2),
        ...[0, 1, 2, 3, 4].flatMap(i => {
            const y = 44 - i * 6.2;
            return [
                stroke(`M28 ${y - 3}L22 ${y - 11}`, '#c9a467', 0.8),
                stroke(`M36 ${y - 3}L42 ${y - 11}`, '#c9a467', 0.8),
                ['ellipse', { cx: 28.5, cy: y, rx: 3.3, ry: 5.4, fill: C.honey, stroke: '#b48a4a', 'stroke-width': 0.8, transform: `rotate(-28 28.5 ${y})` }],
                ['ellipse', { cx: 35.5, cy: y, rx: 3.3, ry: 5.4, fill: C.honey, stroke: '#b48a4a', 'stroke-width': 0.8, transform: `rotate(28 35.5 ${y})` }],
            ];
        }),
        ['ellipse', { cx: 32, cy: 13, rx: 3, ry: 5, fill: C.honey, stroke: '#b48a4a', 'stroke-width': 0.8 }],
    ] },
    { key: 'crimea', title: 'Таврическая амфора', shapes: [
        medallion(C.wineSoft, C.wineLine),
        stroke('M27 22C18 20 18 31 24 32', '#a85f43', 2.4),
        stroke('M37 22C46 20 46 31 40 32', '#a85f43', 2.4),
        ['path', { d: 'M26 16L38 16L37 22C46 26 48 36 42 46L34 56L30 56L22 46C16 36 18 26 27 22Z', fill: '#c97b5a' }],
        ['path', { d: 'M21 34C26 31 38 31 43 34', fill: 'none', stroke: C.wine, 'stroke-width': 2 }],
        ['path', { d: 'M23 39C27 37 37 37 41 39', fill: 'none', stroke: C.wine, 'stroke-width': 1, 'stroke-dasharray': '2 2' }],
        ['rect', { x: 25, y: 13, width: 14, height: 3.5, rx: 1.5, fill: '#a85f43' }],
        glint(26, 30, 2, 5, 15),
    ] },
    { key: 'dagestan', title: 'Дагестанская крепость', shapes: [
        medallion(C.wineSoft, C.wineLine),
        ['path', { d: 'M5 46L18 30L28 40L38 26L59 46Z', fill: '#d5dcc0' }],
        ['rect', { x: 13, y: 36, width: 38, height: 17, fill: '#c7b394', stroke: '#9a8468', 'stroke-width': 1 }],
        ...[13, 21, 29, 37, 45].map(x => ['rect', { x, y: 32, width: 5, height: 5, fill: '#c7b394', stroke: '#9a8468', 'stroke-width': 1 }]),
        ['rect', { x: 26, y: 22, width: 12, height: 31, fill: '#b8a27f', stroke: '#9a8468', 'stroke-width': 1 }],
        ...[26, 30.5, 35].map(x => ['rect', { x, y: 18.5, width: 3, height: 4, fill: '#b8a27f', stroke: '#9a8468', 'stroke-width': 0.8 }]),
        ['path', { d: 'M29 53L29 46C29 43 35 43 35 46L35 53Z', fill: '#5a4a3a' }],
        ['rect', { x: 30.5, y: 28, width: 3, height: 4, rx: 1.5, fill: '#5a4a3a' }],
        stroke('M32 18L32 9', C.stem, 1.2),
        ['path', { d: 'M32 9L40 11L32 13.5Z', fill: C.wine }],
    ] },
    { key: 'stavropol', title: 'Врата Предгорья', shapes: [
        medallion(C.wineSoft, C.wineLine),
        ['path', { d: 'M4 44L20 22L30 34L42 18L60 44Z', fill: mix(C.wineSoft, C.sage, 0.75) }],
        ['path', { d: 'M38 24L42 18L46 24L43 23L41 25Z', fill: mix(C.sage, '#ffffff', 0.8) }],
        ['path', { d: 'M8 46L24 32L36 42L48 34L58 46Z', fill: C.leaf }],
        ['path', { d: 'M28 58L30 40L34 40L36 58Z', fill: '#efe3cc' }],
        ['rect', { x: 17, y: 30, width: 7, height: 24, fill: '#d8c9ae', stroke: '#b5a385', 'stroke-width': 1 }],
        ['rect', { x: 40, y: 30, width: 7, height: 24, fill: '#d8c9ae', stroke: '#b5a385', 'stroke-width': 1 }],
        ['path', { d: 'M20.5 32C20.5 16 43.5 16 43.5 32', fill: 'none', stroke: '#d8c9ae', 'stroke-width': 6 }],
        ['path', { d: 'M20.5 32C20.5 16 43.5 16 43.5 32', fill: 'none', stroke: '#b5a385', 'stroke-width': 0.8, transform: 'translate(0 -3)' }],
        ['rect', { x: 29.5, y: 16, width: 5, height: 6, rx: 1, fill: C.wine }],
    ] },
    { key: 'don', title: 'Донской предел', shapes: [
        medallion(C.wineSoft, C.wineLine),
        ['path', { d: 'M5 40C20 35 44 44 59 38L57 46C53 54 42 60 32 60C22 60 11 54 7 46Z', fill: '#d9e6e3' }],
        stroke('M10 44C16 41 20 47 26 44C32 41 36 47 42 44C48 41 52 47 56 44', C.water, 2.2),
        stroke('M16 51C21 48 25 54 30 51C35 48 39 54 44 51C47 49 49 51 50 51', C.water, 1.8),
        ['path', { d: 'M27 40L27 18C27 14 37 14 37 18L37 40Z', fill: '#c7b394', stroke: '#9a8468', 'stroke-width': 1 }],
        stroke('M29 24L35 24', '#9a8468', 1),
        berry(31, 30, 2, C.wine), berry(34.5, 30, 2, C.wine), berry(32.75, 33.2, 2, C.wine),
        ...[[14, 38], [48, 36]].map(([x, y]) => stroke(`M${x} ${y}L${x - 2} ${y - 6}M${x} ${y}L${x} ${y - 7}M${x} ${y}L${x + 2} ${y - 6}`, C.leafLine, 1.2)),
    ] },
    { key: 'explorer', title: 'Винный следопыт', shapes: [
        medallion(C.wineSoft, C.wineLine),
        ['rect', { x: 21, y: 8, width: 22, height: 5, rx: 2.5, fill: C.stem }],
        stroke('M32 13L32 16', C.stem, 2.5),
        ['circle', { cx: 32, cy: 31, r: 15, fill: '#ffffff', stroke: C.stem, 'stroke-width': 2 }],
        ...Array.from({ length: 8 }, (_, i) => {
            const a = (i * Math.PI) / 4, r1 = i % 2 ? 12.5 : 11;
            return stroke(`M${r2(32 + r1 * Math.cos(a))} ${r2(31 + r1 * Math.sin(a))}L${r2(32 + 14 * Math.cos(a))} ${r2(31 + 14 * Math.sin(a))}`, C.muted, 1);
        }),
        ['path', { d: 'M32 19L35.5 31L32 33L28.5 31Z', fill: C.wine }],
        ['path', { d: 'M32 43L35.5 31L32 29L28.5 31Z', fill: '#c9c2bb' }],
        ['circle', { cx: 32, cy: 31, r: 2, fill: C.stem }],
        stroke('M32 46q4 2 0 3.5q-4 2 0 3.5q4 2 0 3.5', C.stem, 1.8),
    ] },
];

// ---------- статусы ----------

const statuses = [
    { key: 'collector', title: 'Коллекционер Третьяков', shapes: diploma(C.wine, [
        ['rect', { x: 18.5, y: 18.5, width: 27, height: 21, fill: C.gold, stroke: C.goldDeep, 'stroke-width': 1 }],
        ['rect', { x: 22, y: 22, width: 20, height: 14, fill: '#f4efe2', stroke: C.goldDeep, 'stroke-width': 0.7 }],
        ['circle', { cx: 37.5, cy: 25.5, r: 2.2, fill: C.honey }],
        ['path', { d: 'M22 36L22 32L27 27.5L31 31L35 28.5L42 33.5L42 36Z', fill: C.sage }],
        berry(26, 32.5, 1.5, C.wine), berry(28.6, 32.5, 1.5, C.wine), berry(27.3, 34.8, 1.5, C.wine),
        stroke('M26 39.5L23.5 45.5M38 39.5L40.5 45.5M32 39.5L32 44', SCROLL.ink, 1.3),
    ]) },
    { key: 'traveller', title: 'Путешественник Конюхов', shapes: diploma('#5f8f98', [
        stroke('M31 17.5L31 37', SCROLL.ink, 1.1),
        ['path', { d: 'M31 17.5L36 19L31 20.5Z', fill: C.wine }],
        ['path', { d: 'M32.5 20.5L32.5 36L43 36Z', fill: '#ffffff', stroke: SCROLL.ink, 'stroke-width': 0.8 }],
        ['path', { d: 'M29.5 23L29.5 36L21 36Z', fill: C.cream, stroke: SCROLL.ink, 'stroke-width': 0.8 }],
        ['path', { d: 'M19 37.5L44 37.5L40 43L23 43Z', fill: C.wine }],
        stroke('M19 46c2.5 -1.5 4.5 1.5 7 0c2.5 -1.5 4.5 1.5 7 0c2 -1.2 3.5 0 4.5 0', '#5f8f98', 1.3),
    ]) },
    { key: 'critic', title: 'Критик Белинский', shapes: diploma('#5b3a5e', [
        ['rect', { x: 19, y: 35, width: 13, height: 10, rx: 2.5, fill: C.ink }],
        ['rect', { x: 22, y: 32, width: 7, height: 3.5, rx: 0.8, fill: '#5d5753' }],
        ['ellipse', { cx: 22, cy: 39, rx: 1, ry: 2.5, fill: '#6b6560' }],
        ['path', { d: 'M26 37C29 29 36 22 45 17C44 26 37 33 28.5 37.5Z', fill: '#ffffff', stroke: SCROLL.ink, 'stroke-width': 0.9 }],
        stroke('M25.5 38.5C30 31 36.5 24.5 44 18', SCROLL.ink, 0.8),
        ...[[33, 28, 30.5, 25], [36.5, 25, 34.5, 21.5], [39.5, 22, 38.5, 19], [35, 30, 38, 31.5], [38.5, 26.5, 42, 27]].map(([x1, y1, x2, y2]) => stroke(`M${x1} ${y1}L${x2} ${y2}`, SCROLL.edge, 0.7)),
    ]) },
];

// ---------- элементы интерфейса ----------

const ui = [
    { key: 'account', title: 'Личный кабинет', shapes: [
        ['circle', { cx: 32, cy: 32, r: 29, fill: C.wineSoft, stroke: C.wineLine, 'stroke-width': 1.5 }],
        ['circle', { cx: 32, cy: 25, r: 9, fill: C.wine }],
        ['path', { d: 'M15 51C16 41 24 37 32 37C40 37 48 41 49 51C44 56 38 58 32 58C26 58 20 56 15 51Z', fill: C.wine }],
    ] },
    { key: 'cellar', title: 'Винный погреб', shapes: [
        ['path', { d: 'M28 6L36 6L36 19C42 23 44 28 44 34L44 54C44 56.5 42 58 40 58L24 58C22 58 20 56.5 20 54L20 34C20 28 22 23 28 19Z', fill: C.wine }],
        ['rect', { x: 27.5, y: 6, width: 9, height: 6, rx: 1, fill: mix(C.wine, C.shade, 0.4) }],
        ['rect', { x: 23, y: 33, width: 18, height: 15, rx: 2, fill: '#fefdfa' }],
        ['path', { d: 'M32 45C27 41.5 25.5 39.5 25.5 37.5C25.5 35.8 26.8 34.6 28.4 34.6C29.8 34.6 31 35.4 32 36.8C33 35.4 34.2 34.6 35.6 34.6C37.2 34.6 38.5 35.8 38.5 37.5C38.5 39.5 37 41.5 32 45Z', fill: C.rose }],
        glint(24.5, 26, 1.6, 5, 10),
    ] },
    { key: 'note', title: 'Заметка', shapes: [
        ['rect', { x: 14, y: 10, width: 30, height: 44, rx: 3, fill: '#ffffff', stroke: C.line, 'stroke-width': 1.5 }],
        ...[20, 27, 34, 41].map(y => stroke(`M20 ${y}L38 ${y}`, C.line, 1.4)),
        ...[16, 26, 36, 46].map(y => ['circle', { cx: 14, cy: y, r: 1.8, fill: '#ffffff', stroke: C.muted, 'stroke-width': 1 }]),
        // заточенный карандаш по диагонали: ластик, ободок, корпус, деревянный конус, грифель
        g({ transform: 'translate(25 55) rotate(-50)' }, [
            ['rect', { x: 0, y: -4, width: 6, height: 8, rx: 2, fill: '#e8a0a8' }],
            ['rect', { x: 5, y: -4, width: 4, height: 8, fill: '#c9c2bb' }],
            stroke('M6.3 -4L6.3 4M7.7 -4L7.7 4', '#a59d95', 0.6),
            ['rect', { x: 9, y: -4, width: 22, height: 8, fill: '#f0c64e' }],
            ['rect', { x: 9, y: 1.3, width: 22, height: 2.7, fill: '#d9a93a' }],
            ['path', { d: 'M31 -4L39 0L31 4Z', fill: '#ecd2a8' }],
            ['path', { d: 'M36.4 -1.3L39 0L36.4 1.3Z', fill: C.ink }],
        ]),
    ] },
    { key: 'yandex', title: 'Яндекс ID', shapes: [
        ['circle', { cx: 32, cy: 32, r: 28, fill: '#fc3f1d' }],
        ['text', { x: 32, y: 44, 'text-anchor': 'middle', 'font-family': 'Inter, Arial, sans-serif', 'font-size': 32, 'font-weight': 700, fill: '#ffffff' }, 'Я'],
    ] },
    { key: 'vk', title: 'VK ID', shapes: [
        ['rect', { x: 4, y: 4, width: 56, height: 56, rx: 16, fill: '#0077ff' }],
        ['text', { x: 32, y: 41, 'text-anchor': 'middle', 'font-family': 'Inter, Arial, sans-serif', 'font-size': 24, 'font-weight': 700, fill: '#ffffff' }, 'VK'],
    ] },
];

export const ART = { vine, fruits, regions, statuses, ui };
export const ART_GROUP_TITLES = { vine: 'Путь лозы', fruits: 'Фрукты палитры', regions: 'Региональные символы', statuses: 'Статусы', ui: 'Интерфейс' };

export function getArt(group, key) {
    const item = (ART[group] || []).find(a => a.key === key);
    if (!item) throw new Error(`art not found: ${group}/${key}`);
    return item;
}

const COLOR_ATTRS = new Set(['fill', 'stroke']);
const isHex = v => typeof v === 'string' && /^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(v);
const attrValue = (name, value, locked) => (locked && COLOR_ATTRS.has(name) && isHex(value) ? lockColor(value) : String(value));

function buildElement([tag, attrs, kids], locked) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, attrValue(k, v, locked)));
    if (typeof kids === 'string') node.textContent = kids;
    else (kids || []).forEach(child => node.append(buildElement(child, locked)));
    return node;
}

// SVG-элемент для страницы: size — сторона в px, locked — серая версия, title — подпись для скринридера
export function artSvg(group, key, { size = 64, locked = false, title } = {}) {
    const item = getArt(group, key);
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 64 64');
    svg.setAttribute('width', String(size));
    svg.setAttribute('height', String(size));
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', title || item.title);
    svg.classList.add('acc-art');
    if (locked) svg.classList.add('locked');
    item.shapes.forEach(shape => svg.append(buildElement(shape, locked)));
    return svg;
}

const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
function markup([tag, attrs, kids], locked) {
    const a = Object.entries(attrs || {}).map(([k, v]) => ` ${k}="${esc(attrValue(k, v, locked))}"`).join('');
    const inner = typeof kids === 'string' ? esc(kids) : (kids || []).map(child => markup(child, locked)).join('');
    return `<${tag}${a}>${inner}</${tag}>`;
}

// Фрагмент SVG (группа) для общего листа предпросмотра вне браузера; x, y — смещение, size — сторона в px
export function artMarkup(group, key, { size = 64, locked = false, x = 0, y = 0 } = {}) {
    const item = getArt(group, key);
    const body = item.shapes.map(shape => markup(shape, locked)).join('');
    return `<g transform="translate(${r2(x)} ${r2(y)}) scale(${r2(size / 64)})">${body}</g>`;
}
