#!/usr/bin/env python3
"""Аудит сайта или веб-приложения на «нейрослоп»: рендер на нескольких ширинах + поиск по исходникам.

  python3 webslop.py audit URL_или_файл.html [--out папка] [--widths 390,768,1440] [--dark]
      скриншоты целой страницы на каждой ширине, горизонтальный скролл, мелкие зоны нажатия (на самой
      узкой ширине), визуальные паттерны по вычисленным стилям, штампы в видимом тексте; итог — полоса
      CLEAN / MILD / SLOPPY / TERMINAL по числу визуальных паттернов
  python3 webslop.py scan папка_или_файл [...]
      поиск по исходникам (html, css, scss, js, jsx, ts, tsx, vue, svelte, astro): дефолты Tailwind/shadcn,
      стекло, анимации на всём, заглушки, типовые кнопки, штампы в текстах
Нужно: pip install playwright && playwright install chromium (если браузера ещё нет).
Паттерны — сигналы, а не приговор: смотри скриншоты глазами, отделяй осознанные решения от дефолтов.
"""
import argparse
import json
import pathlib
import re
import sys

CLICHES_EN = [r'unlock', r'seamless(ly)?', r'elevate', r'empower', r'revolutioni[sz]e', r'supercharge', r'effortless(ly)?',
              r'cutting[- ]edge', r'game[- ]chang', r'next level', r'harness', r'leverage', r'streamline', r'robust',
              r"in today'?s fast[- ]paced", r'whether you\'?re', r'all[- ]in[- ]one', r'built for the modern', r'say goodbye to',
              r'look no further', r'take .{1,20} to the next level', r'transform (the way|your)', r'like never before']
CLICHES_RU = [r'раскро\w* (ваш |свой )?потенциал', r'откро\w* новые возможности', r'на новый уровень', r'бесшовн\w*',
              r'революционн\w*', r'инновационн\w*', r'уникальн\w*', r'передов\w*', r'в современном мире', r'ни для кого не секрет',
              r'важно отметить', r'всё в одном|все в одном', r'мощн\w* инструмент', r'интуитивно понятн\w*',
              r'не просто \w+, а', r'попрощайтесь с', r'забудьте о', r'как никогда раньше', r'идеальн\w* решени\w*']
GENERIC_CTA = r'\b(get started|learn more|read more|try (it )?(now|free)|sign up( now)?|start (now|free)|book a demo)\b|начать|подробнее|узнать больше|попробовать (бесплатно|сейчас)|начните (прямо )?сейчас'

JS_AUDIT = r"""
() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0'; };
  const rgb = c => { const m = (c || '').match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return {r:p[0], g:p[1], b:p[2], a: p.length > 3 ? p[3] : 1}; };
  const hue = ({r,g,b}) => { r/=255; g/=255; b/=255; const mx=Math.max(r,g,b), mn=Math.min(r,g,b), d=mx-mn; if (!d) return -1;
    let h = mx===r ? ((g-b)/d)%6 : mx===g ? (b-r)/d+2 : (r-g)/d+4; h*=60; return h<0?h+360:h; };
  const sat = ({r,g,b}) => { const mx=Math.max(r,g,b), mn=Math.min(r,g,b); return mx ? (mx-mn)/mx : 0; };
  const all = [...document.querySelectorAll('body *')].filter(vis);
  const bodyBg = (() => { for (const e of [document.body, document.documentElement]) { const c = rgb(getComputedStyle(e).backgroundColor); if (c && c.a > 0) return c; } return {r:255,g:255,b:255,a:1}; })();
  const dark = Math.max(bodyBg.r, bodyBg.g, bodyBg.b) <= 45;
  const P = {}; const add = (k, n, ex) => { P[k] = {n, ex: (ex || []).slice(0, 3)}; };
  const txt = e => (e.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60);

  // 1 gradient text
  const gt = all.filter(e => /^H[1-6]$/.test(e.tagName) || /stat|metric/i.test(e.className)).filter(e => { const s = getComputedStyle(e);
    return (s.backgroundClip === 'text' || s.webkitBackgroundClip === 'text') && /gradient/.test(s.backgroundImage); });
  if (gt.length) add('градиентный текст в заголовках', gt.length, gt.map(txt));
  // 2 glass
  const glass = all.filter(e => { const s = getComputedStyle(e); const f = s.backdropFilter || s.webkitBackdropFilter; return f && f !== 'none'; });
  if (glass.length >= 3) add('стекло (backdrop-filter) на многих блоках', glass.length);
  // 3 purple/blue gradients
  const pg = all.filter(e => { const bi = getComputedStyle(e).backgroundImage; if (!/gradient/.test(bi)) return false;
    const cs = [...bi.matchAll(/rgba?\([^)]+\)/g)].map(m => rgb(m[0])).filter(Boolean);
    return cs.some(c => { const h = hue(c); return h >= 220 && h <= 290 && sat(c) > 0.35; }); });
  if (pg.length) add('фиолетово-синие градиенты', pg.length, pg.map(e => e.tagName.toLowerCase() + '.' + String(e.className).split(' ')[0]));
  // 4 dark + glow / neon
  if (dark) {
    const glow = all.filter(e => { const sh = getComputedStyle(e).boxShadow; if (!sh || sh === 'none') return false;
      return [...sh.matchAll(/rgba?\([^)]+\)/g)].map(m => rgb(m[0])).some(c => c && Math.max(c.r,c.g,c.b) > 100 && Math.max(c.r,c.g,c.b) - Math.min(c.r,c.g,c.b) > 60); });
    if (glow.length > 2) add('тёмная тема со свечением', glow.length);
    const neon = all.filter(e => /^(A|BUTTON|SPAN|H1|H2|H3)$/.test(e.tagName)).filter(e => { const c = rgb(getComputedStyle(e).color); return c && Math.max(c.r,c.g,c.b) > 200 && sat(c) > 0.6; });
    if (neon.length > 3) add('неоновые акценты на тёмном', neon.length, neon.map(txt));
  }
  // 5 hero metrics
  const met = all.filter(e => e.children.length === 0 && parseFloat(getComputedStyle(e).fontSize) >= 24 && /^[\d\s%$€₽+\-.,:/×xKkMmBbкмлнрд]+$/.test(e.textContent.trim()) && e.textContent.trim().length < 15 && /\d/.test(e.textContent));
  if (met.length >= 2) add('крупные «метрики» (10K+, 99,9%) — проверь, настоящие ли', met.length, met.map(txt));
  // 6 identical card grids
  let grids = 0; const gex = [];
  for (const e of all) { const s = getComputedStyle(e); if (!/grid|flex/.test(s.display)) continue;
    const ch = [...e.children].filter(vis).map(c => c.getBoundingClientRect()).filter(r => r.width >= 100 && r.height >= 80);
    if (ch.length >= 3 && ch.every(r => Math.abs(r.width - ch[0].width) < 4 && Math.abs(r.height - ch[0].height) < 4)) { grids++; gex.push(ch.length + ' шт.'); } }
  if (grids) add('одинаковые сетки карточек', grids, gex);
  // 7 fonts
  const ff = e => (getComputedStyle(e).fontFamily || '').split(',')[0].replace(/["']/g, '').trim();
  const h1 = document.querySelector('h1'); const bodyF = ff(document.body); const h1F = h1 ? ff(h1) : bodyF;
  const generic = /^(inter|roboto|arial|open sans|helvetica|helvetica neue|system-ui|segoe ui|-apple-system|blinkmacsystemfont|geist|ui-sans-serif|sans-serif)$/i;
  if (generic.test(bodyF) && generic.test(h1F)) add('шрифт по умолчанию и для текста, и для заголовков', 1, [bodyF + ' / ' + h1F]);
  // 8 cards
  const isCard = e => { const s = getComputedStyle(e); return parseFloat(s.borderTopLeftRadius) > 4 && (s.boxShadow !== 'none' || parseFloat(s.borderTopWidth) > 0) && parseFloat(s.paddingTop) > 8; };
  const cards = all.filter(e => /^(DIV|SECTION|ARTICLE|LI|A)$/.test(e.tagName) && isCard(e));
  const nested = cards.filter(c => { let p = c.parentElement; while (p && p !== document.body) { if (isCard(p)) return true; p = p.parentElement; } return false; });
  if (nested.length >= 2) add('карточки в карточках', nested.length);
  const main = document.querySelector('main') || document.body;
  const inMain = cards.filter(c => main.contains(c));
  if (inMain.length > 6) add('всё обёрнуто в карточки', inMain.length);
  const radShadow = all.filter(e => /^(DIV|SECTION|ARTICLE)$/.test(e.tagName)).filter(e => { const s = getComputedStyle(e); const r = parseFloat(s.borderTopLeftRadius); return r >= 8 && r <= 24 && s.boxShadow !== 'none'; });
  if (radShadow.length > 4) add('скругление + мягкая тень на всём', radShadow.length);
  // 9 one-sided accent border
  const side = all.filter(e => { const s = getComputedStyle(e); const w = ['Top','Right','Bottom','Left'].map(k => parseFloat(s['border'+k+'Width'])); return w.filter(x => x >= 3).length === 1 && w.filter(x => x < 2).length >= 3; });
  if (side.length > 2) add('цветная полоса с одной стороны блока', side.length);
  // 10 centered
  const tx = all.filter(e => /^(H1|H2|H3|P)$/.test(e.tagName));
  const cen = tx.filter(e => getComputedStyle(e).textAlign === 'center');
  if (tx.length > 4 && cen.length / tx.length >= 0.7) add('почти всё по центру', Math.round(100 * cen.length / tx.length), ['% заголовков и абзацев']);
  // 11 icon above heading
  const iah = all.filter(e => /^H[2-4]$/.test(e.tagName)).filter(h => { const p = h.previousElementSibling; if (!p) return false;
    if (/^(SVG|IMG|I)$/i.test(p.tagName)) return true; const r = p.getBoundingClientRect(); return r.width < 80 && p.querySelector('svg,img,i'); });
  if (iah.length >= 3) add('иконка над каждым заголовком', iah.length);
  // 12 all buttons look primary
  const btns = all.filter(e => e.tagName === 'BUTTON' || (e.tagName === 'A' && /btn|button/i.test(e.className)) || e.getAttribute('role') === 'button');
  if (btns.length >= 3) { const sig = btns.map(b => { const s = getComputedStyle(b); return s.backgroundColor + s.backgroundImage + s.fontWeight; });
    const u = 1 - new Set(sig).size / sig.length; if (u > 0.6) add('все кнопки одинаково главные', btns.length); }
  // 13 eyebrow / pill badge above headings
  const eb = all.filter(e => /^H[12]$/.test(e.tagName)).filter(h => { const p = h.previousElementSibling; if (!p || (p.innerText || '').length > 40) return false;
    const s = getComputedStyle(p); const r = p.getBoundingClientRect(); return s.textTransform === 'uppercase' || parseFloat(s.letterSpacing) > 1 || parseFloat(s.borderTopLeftRadius) >= r.height / 2; });
  if (eb.length >= 2) add('надписи-«пилюли» / капс-подзаголовки над заголовками', eb.length, eb.map(e => txt(e.previousElementSibling)));
  // 14 emoji as UI
  const emo = all.filter(e => /^(H1|H2|H3|H4|BUTTON|LI|NAV|A)$/.test(e.tagName) && e.children.length <= 2).filter(e => /\p{Extended_Pictographic}/u.test((e.innerText || '').slice(0, 4)));
  if (emo.length >= 3) add('эмодзи вместо иконок и маркеров', emo.length, emo.map(txt));
  // 15 numbered markers / arrows
  const num = all.filter(e => e.children.length === 0 && /^0[1-9]\.?$/.test(e.textContent.trim()));
  if (num.length >= 3) add('нумерация 01 / 02 / 03 на непоследовательном', num.length);
  const arr = all.filter(e => e.tagName === 'A' && /[→↗➜›»]\s*$/.test((e.innerText || '').trim()));
  if (arr.length >= 3) add('стрелка → на каждой ссылке', arr.length);
  // 16 cream background (вторая волна)
  const {r, g, b} = bodyBg;
  if (r > 225 && r >= g && g >= b && r - b >= 8 && r - b <= 35) add('кремовый фон «тёплой редакционной» волны', 1, [`rgb(${r},${g},${b})`]);
  // 17 bounce
  let bounce = 0; try { for (const sh of document.styleSheets) { let rules; try { rules = sh.cssRules; } catch (e) { continue; }
    for (const ru of rules) { const t = ru.cssText || ''; const m = [...t.matchAll(/cubic-bezier\(([^)]+)\)/g)];
      if (m.some(x => parseFloat(x[1].split(',')[3]) >= 1.3) || /bounce|elastic/i.test(t)) bounce++; } } } catch (e) {}
  if (bounce) add('пружинящие анимации', bounce);
  return {patterns: P, bodyBg, dark, fonts: [bodyF, h1F], text: document.body.innerText};
}
"""

JS_MOBILE = r"""
(W) => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const overflow = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - W;
  const culprits = overflow > 1 ? [...document.querySelectorAll('body *')].filter(vis).filter(e => e.getBoundingClientRect().right > W + 1)
      .map(e => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.split(' ')[0] : '')).slice(0, 5) : [];
  const inline = e => e.tagName === 'A' && e.closest('p, li') && (e.closest('p, li').innerText || '').length > (e.innerText || '').length + 10;
  const tg = [...document.querySelectorAll('a, button, input:not([type=hidden]), select, textarea, [role=button], [onclick]')].filter(vis).filter(e => !inline(e));
  const small = tg.map(e => { const r = e.getBoundingClientRect(); return {e, w: Math.round(r.width), h: Math.round(r.height)}; }).filter(x => x.w < 44 || x.h < 44);
  const label = x => ((x.e.innerText || x.e.getAttribute('aria-label') || x.e.tagName).trim().replace(/\s+/g, ' ').slice(0, 30)) + ` ${x.w}×${x.h}`;
  return {overflow, culprits, total: tg.length, under44: small.length, under24: small.filter(x => x.w < 24 || x.h < 24).map(label).slice(0, 8),
          sample44: small.map(label).slice(0, 8)};
}
"""


def band(n):
    return 'CLEAN' if n <= 1 else 'MILD' if n <= 3 else 'SLOPPY' if n <= 6 else 'TERMINAL'


def pretty(pat):
    s = re.sub(r'\([^)]*\)\?\s?', '', pat)
    s = s.replace('\\w*', '…').replace('\\w+', '…').replace('.{1,20}', '…').replace('\\', '')
    s = re.sub(r'[()?\[\]]', '', s).replace("'", '’')
    return s.replace('|', ' / ')


def copy_hits(text):
    low = text.lower()
    hits = []
    for pat in CLICHES_EN + CLICHES_RU:
        m = re.findall(pat, low)
        if m:
            hits.append((pretty(pat), len(m)))
    cta = len(re.findall(GENERIC_CTA, low))
    latin = len(re.findall(r'[a-z]', low)) > len(re.findall(r'[а-яё]', low))
    words = max(1, len(re.findall(r'\w+', text)))
    dashes = text.count('—')
    return hits, cta, (dashes, words, latin)


def audit(target, out, widths, dark):
    from playwright.sync_api import sync_playwright
    p = pathlib.Path(target)
    url = p.resolve().as_uri() if p.exists() else target
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    res = {}
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for w in widths:
            ctx = br.new_context(viewport={'width': w, 'height': 900 if w > 600 else 844}, device_scale_factor=1,
                                 color_scheme='dark' if dark else 'light', is_mobile=w < 600, has_touch=w < 600)
            pg = ctx.new_page()
            pg.goto(url, wait_until='networkidle', timeout=45000)
            pg.wait_for_timeout(600)
            shot = out / f'{w}.png'
            pg.screenshot(path=str(shot), full_page=True)
            mob = pg.evaluate(JS_MOBILE, w)
            vis = pg.evaluate(JS_AUDIT) if w == max(widths) else None
            res[w] = {'shot': str(shot), 'mobile': mob, 'visual': vis}
            ctx.close()
        br.close()

    big = res[max(widths)]['visual']
    pats = big['patterns']
    print(f'== {target}')
    print(f'шрифты: текст {big["fonts"][0]}, h1 {big["fonts"][1]};  фон body rgb({big["bodyBg"]["r"]},{big["bodyBg"]["g"]},{big["bodyBg"]["b"]}){" — тёмная тема" if big["dark"] else ""}')
    print(f'\nВизуальные паттерны ({len(pats)}) → {band(len(pats))}')
    for k, v in pats.items():
        ex = ('  напр.: ' + ' | '.join(map(str, v['ex']))) if v['ex'] else ''
        print(f'  • {k}: {v["n"]}{ex}')
    print('\nШирины:')
    for w in widths:
        m = res[w]['mobile']
        line = f'  {w}px: скриншот {res[w]["shot"]}'
        if m['overflow'] > 1:
            line += f'  ⚠ горизонтальный скролл +{m["overflow"]}px ({", ".join(m["culprits"])})'
        print(line)
    m = res[min(widths)]['mobile']
    print(f'\nЗоны нажатия на {min(widths)}px: {m["total"]} всего, меньше 44×44 — {m["under44"]}')
    if m['under24']:
        print('  ✗ меньше 24px (не проходит WCAG 2.2 AA): ' + '; '.join(m['under24']))
    elif m['sample44']:
        print('  ⚠ меньше 44 (Apple 44pt / Material 48dp): ' + '; '.join(m['sample44']))
    hits, cta, (dashes, words, latin) = copy_hits(big['text'])
    print('\nТекст:')
    if hits:
        print('  штампы: ' + ', '.join(f'{h}×{n}' for h, n in hits))
    if cta >= 3:
        print(f'  типовые кнопки («Get started», «Подробнее»…): {cta}')
    if latin and dashes * 100 / words > 1:
        print(f'  длинных тире {dashes} на {words} слов — много для английского текста')
    if not hits and cta < 3:
        print('  штампов не найдено')
    (out / 'report.json').write_text(json.dumps(res, ensure_ascii=False, indent=1))


SRC = [
    ('Tailwind-градиенты фиолет/индиго/синий/циан', r'bg-gradient-to-\w+|from-(purple|violet|indigo|blue|fuchsia)-\d+|to-(purple|violet|indigo|blue|cyan)-\d+|via-(purple|violet|indigo|blue)-\d+'),
    ('indigo/violet как акцент', r'\b(bg|text|border|ring)-(indigo|violet)-[4-7]00\b'),
    ('rounded-2xl/3xl', r'rounded-(2xl|3xl)'),
    ('тени shadow-lg/xl/2xl', r'shadow-(lg|xl|2xl)'),
    ('стекло backdrop-blur', r'backdrop-blur|backdrop-filter:\s*blur'),
    ('градиентный текст', r'bg-clip-text|background-clip:\s*text'),
    ('Inter/Geist/Roboto', r'font-family:[^;]*(Inter|Geist|Roboto)|family=(Inter|Geist|Roboto)|next/font/google.*(Inter|Geist)|\bInter\(|\bGeist\('),
    ('анимации на всём', r'transition-all|animate-(bounce|pulse)|framer-motion'),
    ('компоненты shadcn как есть', r'@/components/ui/(card|badge|button)'),
    ('карточки-метрики', r'StatCard|MetricCard|stat-card|metric-card'),
    ('заглушки', r'lorem ipsum|coming soon|\[your [^\]]+\]|\[insert|todo: replace'),
    ('чистые #000/#fff', r'#000000\b|#ffffff\b|#000\b|#fff\b'),
    ('стоковый alt', r'alt="[^"]*(diverse team|business meeting|smiling (person|woman|man)|happy customer)'),
    ('классы длиннее 200 символов', r'class(Name)?="[^"]{200,}"'),
]
EXT = {'.html', '.htm', '.css', '.scss', '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte', '.astro', '.mdx'}


def scan(paths):
    files = []
    for p in map(pathlib.Path, paths):
        if p.is_file():
            files.append(p)
        else:
            files += [f for f in p.rglob('*') if f.suffix in EXT and not any(x in f.parts for x in ('node_modules', 'dist', 'build', '.next', '.git'))]
    total = {k: 0 for k, _ in SRC}
    where = {k: [] for k, _ in SRC}
    text = []
    for f in files:
        s = f.read_text(errors='ignore')
        for k, pat in SRC:
            n = len(re.findall(pat, s, re.I))
            if n:
                total[k] += n
                where[k].append(f'{f.name}×{n}')
        text.append(re.sub(r'<[^>]+>|\{[^}]*\}', ' ', s))
    print(f'== исходники: {len(files)} файлов')
    for k, _ in SRC:
        if total[k]:
            print(f'  • {k}: {total[k]}  ({", ".join(where[k][:4])})')
    if not any(total.values()):
        print('  типовых паттернов не найдено')
    hits, cta, _ = copy_hits(' '.join(text))
    if hits:
        print('  штампы в текстах: ' + ', '.join(f'{h}×{n}' for h, n in hits))
    if cta >= 3:
        print(f'  типовые кнопки: {cta}')
    print('Совпадение в коде ≠ слоп на экране: неиспользуемый код тоже находится. Сверяй с audit.')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('audit'); a.add_argument('target'); a.add_argument('--out', default='webslop-out')
    a.add_argument('--widths', default='390,768,1440'); a.add_argument('--dark', action='store_true')
    s = sub.add_parser('scan'); s.add_argument('paths', nargs='+')
    args = ap.parse_args()
    if args.cmd == 'audit':
        audit(args.target, args.out, sorted(int(x) for x in args.widths.split(',')), args.dark)
    else:
        scan(args.paths)
