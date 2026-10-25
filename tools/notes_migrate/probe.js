// 注入页面：按笔记层同样的规则建正文文字索引，量每个字、每个公式符号、每张图在正文卡片坐标（未缩放 px）下的矩形。
(() => {
  const main = document.querySelector('main'), article = main.querySelector('article');
  const layer = document.getElementById('annot-layer') || main;
  const lr = layer.getBoundingClientRect(), s = (main.getBoundingClientRect().width / main.offsetWidth) || 1;
  const loc = r => [ (r.left - lr.left) / s, (r.top - lr.top) / s, r.width / s, r.height / s ];
  const skip = n => { const p = n.parentElement; return !p || !!p.closest('mjx-container, script, style, svg, .annot-ui'); };
  const BLK = 'p, li, figcaption, blockquote, pre, summary, dt, dd, td, th, h1, h2, h3, h4, h5, h6, .lead, div';
  const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
  const chars = [], rects = [], blk = [], blocks = new Map();
  let lastSpace = true; const rg = document.createRange();
  const nodes = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (skip(n)) continue;
    const b = (n.parentElement.closest(BLK)) || article, bid = blocks.has(b) ? blocks.get(b) : (blocks.set(b, blocks.size), blocks.size - 1);
    const t = n.data;
    for (let i = 0; i < t.length; i++) {
      const sp = /\s/.test(t[i]);
      if (sp && lastSpace) continue;
      chars.push(sp ? ' ' : t[i]); lastSpace = sp; blk.push(bid);
      let r = null;
      if (!sp) { rg.setStart(n, i); rg.setEnd(n, i + 1); for (const q of rg.getClientRects()) if (q.width || q.height) { r = loc(q); break; } }
      rects.push(r);
      nodes.push(n);
    }
  }
  const text = chars.join('');
  // 元素起点在文字索引里的位置
  const posOf = el => { for (let i = 0; i < nodes.length; i++) if (el.compareDocumentPosition(nodes[i]) & Node.DOCUMENT_POSITION_FOLLOWING) return i; return text.length; };
  const maths = [];
  for (const m of MathJax.startup.document.math) {
    const el = m.typesetRoot; if (!el || !article.contains(el)) continue;
    const els = [...el.querySelectorAll('[data-c]')];
    const ch = els.map(e => { const c = parseInt(e.getAttribute('data-c'), 16); return Number.isFinite(c) ? String.fromCodePoint(c).normalize('NFKC') : '?'; });
    const q = els.map(e => { const r = e.getBoundingClientRect(); return r.width || r.height ? loc(r) : null; });
    const br = el.getBoundingClientRect();
    maths.push({ tex: (m.math || '').replace(/\s+/g, ' ').trim(), display: !!m.display, ch, q, box: br.width || br.height ? loc(br) : null, el });
  }
  maths.sort((a, b) => (a.el.compareDocumentPosition(b.el) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
  maths.forEach(m => { m.pos = posOf(m.el); delete m.el; });
  const srcKey = el => (el.getAttribute('src') || el.currentSrc || '').split('#')[0].split('?')[0].split('/').pop();
  const media = [...article.querySelectorAll('img, video')].map(e => ({ src: srcKey(e), file: decodeURIComponent(new URL(e.currentSrc || e.src, location.href).pathname), box: loc(e.getBoundingClientRect()), pos: posOf(e) }));
  const heads = [...article.querySelectorAll('h1, h2, h3, h4')].map(h => ({ pos: posOf(h), text: h.textContent.replace(/\s+/g, ' ').trim() }));
  const strokes = {};
  const N = window.__nipcNotes;
  for (const st of N.strokes()) { const p = N.placed(st.id); strokes[st.id] = p ? { state: p.state, abs: p.abs } : null; }
  return { text, rects, blk, maths, media, heads, strokes };
})()
