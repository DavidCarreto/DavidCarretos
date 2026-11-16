// Ditado por microfone: acrescenta um botão 🎤 a cada <textarea data-mic>.
// - Barras que mexem com a voz (nível do microfone), para se ver que está a captar.
// - Pré-visualização do texto enquanto se fala (a cada ~3 s o servidor transcreve o que já foi dito).
// - Ao parar, o texto final é acrescentado à caixa para se corrigir antes de enviar.
// A transcrição é feita no próprio servidor (faster-whisper); nada vai para serviços externos.
(function () {
  const MAX_MS = 3 * 60 * 1000;
  const PREVIEW_EVERY_MS = 3000;
  const supported = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);

  function pickType() {
    const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
    for (const t of types) { if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) return t; }
    return '';
  }

  function extFor(type) { return type.includes('mp4') ? '.m4a' : type.includes('ogg') ? '.ogg' : '.webm'; }

  async function transcribe(blob, type) {
    const fd = new FormData();
    fd.append('audio', blob, 'voz' + extFor(type));
    const r = await fetch('/transcrever', { method: 'POST', body: fd });
    return r.json();
  }

  function setup(area) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn mic';
    btn.title = 'Falar (ditado por microfone)';
    btn.textContent = '🎤';

    const panel = document.createElement('div');            // barras + estado + pré-visualização
    panel.className = 'mic-panel';
    panel.hidden = true;
    panel.innerHTML = '<div class="mic-bars">' + '<i></i>'.repeat(9) + '</div>' +
                      '<div class="mic-info"><span class="mic-status"></span><span class="mic-preview"></span></div>';
    const bars = panel.querySelectorAll('.mic-bars i');
    const status = panel.querySelector('.mic-status');
    const preview = panel.querySelector('.mic-preview');

    const inline = area.dataset.micInline !== undefined;
    const form = area.closest('form');
    if (inline && form) {                                    // Assistente: botão ao lado do enviar, painel por cima
      const send = form.querySelector('button:not(.mic)');
      send.parentNode.insertBefore(btn, send);
      form.parentNode.insertBefore(panel, form);
      panel.classList.add('floating');
    } else {
      const row = document.createElement('div');
      row.className = 'mic-row';
      area.parentNode.insertBefore(row, area.nextSibling);
      row.appendChild(btn);
      row.appendChild(panel);
    }
    if (!supported) { btn.disabled = true; btn.title = 'Este browser não permite gravar áudio'; return; }

    let rec = null, chunks = [], type = '', stream = null, started = 0, clock = null;
    let audioCtx = null, raf = null, previewTimer = null, previewBusy = false, finished = false;

    function show(msg) { panel.hidden = false; status.textContent = msg; }

    function meter() {
      const src = audioCtx.createMediaStreamSource(stream);
      const an = audioCtx.createAnalyser();
      an.fftSize = 512;
      src.connect(an);
      const data = new Uint8Array(an.fftSize);
      const draw = () => {
        an.getByteTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; sum += v * v; }
        const level = Math.min(1, Math.sqrt(sum / data.length) * 7);      // 0..1
        bars.forEach((b, i) => {
          const shape = 1 - Math.abs(i - 4) / 5;                           // mais alto ao centro
          const h = 4 + level * 26 * (0.55 + 0.45 * shape) * (0.75 + Math.random() * 0.5);
          b.style.height = h.toFixed(1) + 'px';
        });
        raf = requestAnimationFrame(draw);
      };
      draw();
    }

    function tick() {
      const s = Math.floor((Date.now() - started) / 1000);
      status.textContent = '⏺ a ouvir ' + Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0') + ' · toca ⏹ para parar';
      if (Date.now() - started >= MAX_MS) stop();
    }

    async function livePreview() {                           // texto provisório enquanto se fala
      if (previewBusy || finished || !chunks.length) return;
      previewBusy = true;
      try {
        const j = await transcribe(new Blob(chunks, { type }), type);
        if (!finished && j.texto) preview.textContent = '“' + j.texto + '”';
      } catch (e) { /* a pré-visualização é opcional */ }
      previewBusy = false;
    }

    async function start() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      } catch (e) {
        show('Sem acesso ao microfone (autoriza nas definições do browser).');
        return;
      }
      type = pickType();
      rec = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream);
      type = rec.mimeType || type || 'audio/webm';
      chunks = []; finished = false; preview.textContent = '';
      rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onstop = finish;
      rec.start(1000);                                       // um pedaço por segundo (para a pré-visualização)
      started = Date.now();
      btn.classList.add('rec');
      btn.textContent = '⏹';
      panel.classList.add('live');
      show('⏺ a ouvir 0:00 · toca ⏹ para parar');
      clock = setInterval(tick, 500);
      previewTimer = setInterval(livePreview, PREVIEW_EVERY_MS);
      try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); meter(); } catch (e) { /* sem barras */ }
    }

    function stop() {
      clearInterval(clock); clearInterval(previewTimer);
      if (raf) cancelAnimationFrame(raf);
      bars.forEach(b => b.style.height = '4px');
      if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
      if (rec && rec.state !== 'inactive') rec.stop();
      if (stream) stream.getTracks().forEach(t => t.stop());
      btn.classList.remove('rec');
      btn.textContent = '🎤';
      panel.classList.remove('live');
    }

    async function finish() {
      finished = true;
      const blob = new Blob(chunks, { type });
      if (!blob.size) { panel.hidden = true; return; }
      btn.disabled = true;
      const t0 = Date.now();
      panel.classList.add('busy');
      show('⏳ a escrever o texto… 0s');
      const wait = setInterval(() => { status.textContent = '⏳ a escrever o texto… ' + Math.round((Date.now() - t0) / 1000) + 's'; }, 500);
      try {
        const j = await transcribe(blob, type);
        if (j.texto) {
          area.value = (area.value ? area.value.replace(/\s*$/, ' ') : '') + j.texto;
          area.dispatchEvent(new Event('input'));
          area.focus();
          status.textContent = '✓ texto acrescentado — revê e corrige se for preciso';
          preview.textContent = '';
          setTimeout(() => { if (!rec || rec.state === 'inactive') panel.hidden = true; }, 4000);
        } else {
          status.textContent = j.erro || 'Não percebi nada. Tenta outra vez, mais perto do microfone.';
        }
      } catch (e) {
        status.textContent = 'Erro de ligação ao transcrever.';
      }
      clearInterval(wait);
      panel.classList.remove('busy');
      btn.disabled = false;
    }

    btn.addEventListener('click', () => (rec && rec.state === 'recording') ? stop() : start());
  }

  document.querySelectorAll('textarea[data-mic]').forEach(setup);
})();
