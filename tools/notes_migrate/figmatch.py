"""图重画了（同名文件、内容变了）时，图上的笔跟着它圈的那块图走：
在旧图上取笔画周围的一块（不含笔迹，图本身是干净的），在新图里多尺度模板匹配（归一化互相关），
笔画按匹配到的位置和尺度搬过去；笔画正下方的那一小块内容（紧贴外框）在新图对应处再比一次，
对不上（标签删了、改了）就判为内容没了。图没变（文件字节相同）就原样不动。"""
import cv2, numpy as np, hashlib

SCALE = 2.0         # 在显示尺寸的 2 倍上算
INK = 200           # 灰度 < INK 算有内容（标签、线条）


def load_gray(path, w, h):
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im.ndim == 3 and im.shape[2] == 4:   # 透明底当白底
        a = im[:, :, 3:4].astype(np.float32) / 255
        im = (im[:, :, :3].astype(np.float32) * a + 255 * (1 - a)).astype(np.uint8)
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im
    return cv2.resize(g, (max(1, int(round(w * SCALE))), max(1, int(round(h * SCALE)))), interpolation=cv2.INTER_AREA)


def same_file(a, b):
    return hashlib.md5(open(a, 'rb').read()).digest() == hashlib.md5(open(b, 'rb').read()).digest()


def ink(p):
    return float((p < INK).mean()) if p.size else 0.0


def crop(img, x0, y0, x1, y1):
    H, W = img.shape
    x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(W, int(x1)), min(H, int(y1))
    return img[y0:y1, x0:x1], (x0, y0)


def match(old, new, box, prior):
    """box = 笔画外框（旧图显示坐标 ×SCALE）；prior = 不动时它在新图里的位置（按比例换算）。
    返回 (score, s, (dx, dy)) ：新坐标 = (旧坐标 − 块左上角) × s + 匹配左上角。"""
    x0, y0, x1, y1 = box
    best = None
    for m in (10, 20, 34, 52, 76):
        pm = m * SCALE
        P, org = crop(old, x0 - pm, y0 - pm, x1 + pm, y1 + pm)
        if ink(P) < 0.03 and m < 76:
            continue
        if P.shape[0] < 8 or P.shape[1] < 8:
            continue
        for s in np.geomspace(0.45, 2.4, 33):
            T = cv2.resize(P, (max(4, int(P.shape[1] * s)), max(4, int(P.shape[0] * s))), interpolation=cv2.INTER_AREA)
            if T.shape[0] >= new.shape[0] or T.shape[1] >= new.shape[1] or T.std() < 1:
                continue
            R = cv2.matchTemplate(new, T, cv2.TM_CCOEFF_NORMED)
            # 离「不动时的位置」越远扣分越多（同一张图里常有几个相同的标签）
            ey, ex = (prior[1] - (y0 - org[1]) * 0) , prior[0]
            H, W = R.shape
            yy, xx = np.mgrid[0:H, 0:W]
            px = org[0] * new.shape[1] / old.shape[1]; py = org[1] * new.shape[0] / old.shape[0]
            dist = np.hypot(xx - px, yy - py) / np.hypot(*new.shape)
            S = R - 0.5 * dist
            k = np.unravel_index(np.argmax(S), S.shape)
            sc = float(R[k])
            if best is None or S[k] > best[0]:
                best = (float(S[k]), sc, s, org, (int(k[1]), int(k[0])), m)
        if best and best[1] >= 0.8:
            break
    return best


def refine(old, new, box, s, org, loc):
    """笔画正下方那一小块（外框外扩 4 px，要有内容）在粗匹配位置附近再精配一次（尺度单独搜，标签常比线条放大得多）。
    返回 (ncc, s2, org2, loc2)；这块没内容（笔画画在空白处）返回 None。"""
    x0, y0, x1, y1 = box
    P, o2 = crop(old, x0 - 4 * SCALE, y0 - 4 * SCALE, x1 + 4 * SCALE, y1 + 4 * SCALE)
    if ink(P) < 0.02 or min(P.shape) < 6:
        return None
    cx = loc[0] + (o2[0] + P.shape[1] / 2 - org[0]) * s; cy = loc[1] + (o2[1] + P.shape[0] / 2 - org[1]) * s
    best = (0.0, s, o2, loc)
    for s2 in np.geomspace(0.5, 2.4, 29):
        T = cv2.resize(P, (max(4, int(P.shape[1] * s2)), max(4, int(P.shape[0] * s2))), interpolation=cv2.INTER_AREA)
        if T.std() < 1:
            continue
        r = 40 * SCALE + max(T.shape) / 2
        Q, qo = crop(new, cx - r, cy - r, cx + r, cy + r)
        if Q.shape[0] < T.shape[0] or Q.shape[1] < T.shape[1]:
            continue
        R = cv2.matchTemplate(Q, T, cv2.TM_CCOEFF_NORMED)
        k = np.unravel_index(np.argmax(R), R.shape)
        if R[k] > best[0]:
            best = (float(R[k]), float(s2), o2, (qo[0] + int(k[1]), qo[1] + int(k[0])))
    return best


def transfer(old_path, new_path, old_box, new_box, strokes_abs):
    """strokes_abs：一组笔在旧页的正文坐标点列表。返回 (状态, 每笔的新归一化点列表, 说明)。"""
    ow, oh = old_box[2], old_box[3]; nw, nh = new_box[2], new_box[3]
    norm_old = [[((p[0] - old_box[0]) / ow, (p[1] - old_box[1]) / oh, p[2]) for p in a] for a in strokes_abs]
    if same_file(old_path, new_path):
        return 'same', norm_old, ''
    old = load_gray(old_path, ow, oh); new = load_gray(new_path, nw, nh)
    pts = [(x * ow * SCALE, y * oh * SCALE) for a in norm_old for x, y, _ in a]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    pad = 4 * SCALE
    box = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    prior = (box[0] * new.shape[1] / old.shape[1], box[1] * new.shape[0] / old.shape[0])
    best = match(old, new, box, prior)
    if not best or best[1] < 0.6:
        return 'gone', None, f'no match (ncc {best[1] if best else 0:.2f})'
    _, sc, s, org, loc, m = best
    t = refine(old, new, box, s, org, loc)
    if t is not None:
        if t[0] < 0.7:
            return 'gone', None, f'content under stroke changed (ncc {t[0]:.2f}, around {sc:.2f})'
        _, s, org, loc = t
    out = []
    for a in norm_old:
        out.append([(((x * ow * SCALE - org[0]) * s + loc[0]) / (nw * SCALE),
                     ((y * oh * SCALE - org[1]) * s + loc[1]) / (nh * SCALE), pr) for x, y, pr in a])
    return 'matched', out, f'ncc {sc:.2f} tight {None if t is None else round(t[0], 2)} scale {s:.2f} margin {m}'
