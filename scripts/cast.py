#!/usr/bin/env python3
"""Замер и правка цветового сдвига (жёлтый «фильтр», сепия, розовый/зелёный, синий) у картинок.

  python3 cast.py measure a.png b.jpg ...                b* и a* светлых мест (фон, бумага) и всего кадра
  python3 cast.py fix in.png out.png [--target 0] [--a]  сдвинуть b* светлых мест к target
                                                         (0 — нейтрально, 5–7 — лёгкая сепия);
                                                         --a — заодно убрать розовый/зелёный (a* к 0)
  python3 cast.py sheet out.jpg a.png b.png ...          контактный лист для серии (без ImageMagick)
Шкала b*: |b*| ≤ 3 нейтрально; +4…+8 тёплый сдвиг; > +8 явная желтизна; < −3 холодный (синий) сдвиг.
|a*| > 4 — розовый (+) или зелёный (−) сдвиг. Нужно: pip install pillow numpy.
"""
import argparse
import io
import sys
import numpy as np
from PIL import Image, ImageCms

SRGB = ImageCms.createProfile('sRGB')
RGB2LAB = ImageCms.buildTransformFromOpenProfiles(SRGB, ImageCms.createProfile('LAB'), 'RGB', 'LAB')
LAB2RGB = ImageCms.buildTransformFromOpenProfiles(ImageCms.createProfile('LAB'), SRGB, 'LAB', 'RGB')
MIN_LIGHT = 0.03  # меньше 3% светлых пикселей — замер по «светлому» ненадёжен


def load(path):
    """RGB в sRGB (с учётом встроенного профиля, напр. Display P3 со скриншотов) + альфа, если есть."""
    im = Image.open(path)
    alpha = im.getchannel('A') if 'A' in im.getbands() else (im.convert('RGBA').getchannel('A') if im.mode == 'P' and 'transparency' in im.info else None)
    rgb = im.convert('RGB')
    icc = im.info.get('icc_profile')
    if icc:
        try:
            rgb = ImageCms.profileToProfile(rgb, ImageCms.ImageCmsProfile(io.BytesIO(icc)), SRGB, outputMode='RGB')
        except Exception:
            pass
    return rgb, alpha


def lab(im):
    return [np.asarray(c, dtype=float) for c in ImageCms.applyTransform(im, RGB2LAB).split()]


def verdict(b, a):
    if np.isnan(b):
        return 'светлых мест нет — замер не применим'
    v = ('нейтрально' if abs(b) <= 3 else 'тёплый сдвиг' if b <= 8 else 'явная желтизна') if b >= -3 else 'холодный (синий) сдвиг'
    if abs(a) > 4:
        v += ', розовый сдвиг' if a > 0 else ', зелёный сдвиг'
    return v


def stats(im, alpha=None):
    L, a, b = lab(im)
    light = L * 100 / 255 > 85
    if alpha is not None:
        light &= np.asarray(alpha) > 0  # прозрачное не считаем
    bl = (b - 128)[light].mean() if light.any() else float('nan')
    al = (a - 128)[light].mean() if light.any() else float('nan')
    return L, a, b, light, bl, al


def measure(path):
    im, alpha = load(path)
    small = im.copy(); small.thumbnail((800, 800))
    sa = alpha.resize(small.size) if alpha is not None else None
    _, _, b, light, bl, al = stats(small, sa)
    note = '' if light.mean() >= MIN_LIGHT or np.isnan(bl) else '  ⚠ мало светлых мест (тёмная сцена или UI): смотри «b* кадра», «лечить» не нужно'
    print(f'{path}: b* светлого {bl:5.1f}  a* светлого {al:5.1f}  b* кадра {(b - 128).mean():5.1f}  '
          f'светлого {light.mean():4.0%}  → {verdict(bl, al)}{note}')


def fix(src, out, target, fix_a):
    im, alpha = load(src)
    L, a, b, light, bl, al = stats(im, alpha)
    if light.mean() < MIN_LIGHT:
        sys.exit(f'{src}: светлых мест {light.mean():.0%} — это тёмная сцена или UI, автоправка оттенка её испортит. Не правлю.')
    w = L / 255  # тёмное почти не трогаем, светлое — сильнее
    b = np.clip(b - (bl - target) * w, 0, 255)
    if fix_a:
        a = np.clip(a - al * w, 0, 255)
    res = Image.merge('LAB', [Image.fromarray(np.round(x).astype('uint8')) for x in (L, a, b)])
    res = ImageCms.applyTransform(res, LAB2RGB)
    if alpha is not None:
        res.putalpha(alpha)
    kw = {'quality': 95, 'subsampling': 0} if out.lower().endswith(('.jpg', '.jpeg')) else {}
    if alpha is not None and out.lower().endswith(('.jpg', '.jpeg')):
        res = res.convert('RGB')
        print('⚠ JPEG не хранит прозрачность — сохраняй в PNG/WebP, если она нужна')
    res.save(out, **kw)
    print(f'{src} → {out}: сдвиг b* на {target - bl:+.1f}' + (f', a* на {-al:+.1f}' if fix_a else ''))
    measure(out)


def sheet(out, files, cols=2, width=1000):
    ims = []
    for p in files:
        im, _ = load(p)
        ims.append(im.resize((width, round(im.height * width / im.width))))
    rows = -(-len(ims) // cols)
    h = max(i.height for i in ims)
    canvas = Image.new('RGB', (cols * width, rows * h), (128, 128, 128))  # нейтрально-серый, не влияет на оценку цвета
    for k, im in enumerate(ims):
        canvas.paste(im, ((k % cols) * width, (k // cols) * h))
    canvas.save(out, quality=90)
    print(f'{out}: {len(ims)} шт., {cols} в ряд')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    m = sub.add_parser('measure'); m.add_argument('files', nargs='+')
    f = sub.add_parser('fix'); f.add_argument('src'); f.add_argument('out')
    f.add_argument('--target', type=float, default=0); f.add_argument('--a', action='store_true')
    s = sub.add_parser('sheet'); s.add_argument('out'); s.add_argument('files', nargs='+'); s.add_argument('--cols', type=int, default=2)
    args = ap.parse_args()
    if args.cmd == 'measure':
        for p in args.files:
            measure(p)
    elif args.cmd == 'fix':
        fix(args.src, args.out, args.target, args.a)
    else:
        sheet(args.out, args.files, args.cols)
