// Visualizador de carrossel (página da publicação e miniaturas em "Aprovar").
// Desliza com o dedo (scroll-snap), setas ‹ ›, pontinhos, miniaturas e, no principal, setas do teclado.
(function () {
  function setup(root) {
    const track = root.querySelector('.cv-track');
    const slides = [...track.children];
    const n = slides.length;
    const id = root.dataset.cv;
    const count = root.querySelector('.cv-count');
    const dots = document.querySelectorAll(`[data-cv-dots="${id}"] i`);
    const thumbs = document.querySelectorAll(`[data-cv-thumbs="${id}"] button`);
    const infos = document.querySelectorAll(`[data-cv-info="${id}"] > [data-i]`);
    const prev = root.querySelector('.cv-prev'), next = root.querySelector('.cv-next');
    let cur = -1;

    function show(i) {
      i = Math.max(0, Math.min(n - 1, i));
      if (i === cur) return;
      cur = i;
      if (count) count.textContent = `${i + 1} / ${n}`;
      dots.forEach((d, k) => d.classList.toggle('on', k === i));
      thumbs.forEach((t, k) => t.classList.toggle('on', k === i));
      infos.forEach(el => { el.hidden = Number(el.dataset.i) !== i; });
      if (prev) prev.disabled = i === 0;
      if (next) next.disabled = i === n - 1;
    }
    function go(i, smooth = true) {
      i = Math.max(0, Math.min(n - 1, i));
      track.scrollTo({ left: i * track.clientWidth, behavior: smooth ? 'smooth' : 'auto' });
      show(i);
    }
    let t;
    track.addEventListener('scroll', () => {
      clearTimeout(t);
      t = setTimeout(() => show(Math.round(track.scrollLeft / track.clientWidth)), 40);
    }, { passive: true });
    prev && prev.addEventListener('click', e => { e.preventDefault(); go(cur - 1); });
    next && next.addEventListener('click', e => { e.preventDefault(); go(cur + 1); });
    dots.forEach((d, k) => d.addEventListener('click', () => go(k)));
    thumbs.forEach((b, k) => b.addEventListener('click', e => { e.preventDefault(); go(k); }));
    if (root.hasAttribute('data-cv-keys')) {
      document.addEventListener('keydown', e => {
        if (/INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || '')) return;
        if (e.key === 'ArrowLeft') { e.preventDefault(); go(cur - 1); }
        if (e.key === 'ArrowRight') { e.preventDefault(); go(cur + 1); }
      });
    }
    window.addEventListener('resize', () => go(cur, false));
    // abrir numa imagem concreta (ex.: depois de mover/retirar: #img=3)
    const m = root.hasAttribute('data-cv-keys') && location.hash.match(/img=(\d+)/);
    const start = m ? Number(m[1]) - 1 : 0;
    show(start);
    if (start) requestAnimationFrame(() => go(start, false));
  }
  document.querySelectorAll('[data-cv]').forEach(setup);
})();
