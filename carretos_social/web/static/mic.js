// Ditado por microfone: acrescenta um botão 🎤 a cada <textarea data-mic>.
// Grava no browser (computador ou telemóvel), envia ao servidor, que transcreve (faster-whisper),
// e o texto é acrescentado à caixa para se poder corrigir antes de enviar.
(function () {
  const MAX_MS = 3 * 60 * 1000;
  const supported = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);

  function pickType() {
    const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
    for (const t of types) { if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) return t; }
    return '';
  }

  function setup(area) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn mic';
    btn.title = 'Falar (ditado por microfone)';
    btn.textContent = '🎤';
    const status = document.createElement('span');
    status.className = 'mic-status muted';
    const wrap = document.createElement('div');
    wrap.className = 'mic-row';
    area.parentNode.insertBefore(wrap, area.nextSibling);
    wrap.appendChild(btn);
    wrap.appendChild(status);
    if (area.dataset.micInline !== undefined) {           // no Assistente: botão ao lado do enviar
      const form = area.closest('form');
      const send = form && form.querySelector('button:not(.mic)');
      if (send) { send.parentNode.insertBefore(btn, send); wrap.remove(); btn.after(status); status.classList.add('inline'); }
    }
    if (!supported) {
      btn.disabled = true;
      btn.title = 'Este browser não permite gravar áudio';
      return;
    }

    let rec = null, chunks = [], timer = null, started = 0, stream = null;

    function tick() {
      const s = Math.floor((Date.now() - started) / 1000);
      status.textContent = '⏺ a gravar ' + Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0') + ' — toca para parar';
      if (Date.now() - started >= MAX_MS) stop();
    }

    async function start() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e) {
        status.textContent = 'Sem acesso ao microfone (autoriza nas definições do browser).';
        return;
      }
      const type = pickType();
      rec = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream);
      chunks = [];
      rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onstop = send;
      rec.start();
      started = Date.now();
      btn.classList.add('rec');
      btn.textContent = '⏹';
      tick();
      timer = setInterval(tick, 500);
    }

    function stop() {
      clearInterval(timer);
      if (rec && rec.state !== 'inactive') rec.stop();
      if (stream) stream.getTracks().forEach(t => t.stop());
      btn.classList.remove('rec');
      btn.textContent = '🎤';
    }

    async function send() {
      const type = (rec && rec.mimeType) || 'audio/webm';
      const ext = type.includes('mp4') ? '.m4a' : type.includes('ogg') ? '.ogg' : '.webm';
      const blob = new Blob(chunks, { type });
      if (!blob.size) { status.textContent = ''; return; }
      status.textContent = '⏳ a transcrever…';
      btn.disabled = true;
      const fd = new FormData();
      fd.append('audio', blob, 'voz' + ext);
      try {
        const r = await fetch('/transcrever', { method: 'POST', body: fd });
        const j = await r.json();
        if (j.texto) {
          area.value = (area.value ? area.value.replace(/\s*$/, ' ') : '') + j.texto;
          area.dispatchEvent(new Event('input'));
          area.focus();
          status.textContent = '✓ texto acrescentado — revê e corrige se for preciso';
        } else {
          status.textContent = j.erro || 'Não percebi nada. Tenta outra vez, mais perto do microfone.';
        }
      } catch (e) {
        status.textContent = 'Erro de ligação ao transcrever.';
      }
      btn.disabled = false;
    }

    btn.addEventListener('click', () => (rec && rec.state === 'recording') ? stop() : start());
  }

  document.querySelectorAll('textarea[data-mic]').forEach(setup);
})();
