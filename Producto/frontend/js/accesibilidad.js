// ── SpeakingHands — Accesibilidad y Notificaciones ────────────
(function () {

  // ── Persistencia ───────────────────────────────────────────
  const CLAVE_FUENTE = 'sh_fuente';
  const CLAVE_CONTRASTE = 'sh_contraste';
  const CLAVE_SONIDO = 'sh_sonido';

  const estado = {
    fuente: localStorage.getItem(CLAVE_FUENTE) || 'normal',
    contraste: localStorage.getItem(CLAVE_CONTRASTE) === '1',
    sonido: localStorage.getItem(CLAVE_SONIDO) !== '0',
  };

  // ── Tamaño de fuente (zoom) ────────────────────────────────
  const ESCALAS = { normal: '1', grande: '1.15', muygrande: '1.3' };

  function aplicarFuente(nivel) {
    estado.fuente = nivel;
    localStorage.setItem(CLAVE_FUENTE, nivel);
    // zoom escala todo el body sin importar si los estilos usan px o rem
    document.body.style.zoom = ESCALAS[nivel] || '1';
    document.querySelectorAll('.acc-btn-fuente').forEach(b => {
      b.classList.toggle('activo', b.dataset.nivel === nivel);
    });
  }

  // ── Alto contraste ─────────────────────────────────────────
  function aplicarContraste(activo) {
    estado.contraste = activo;
    localStorage.setItem(CLAVE_CONTRASTE, activo ? '1' : '0');
    document.body.classList.toggle('modo-accesible', activo);
  }

  // ── Sonido ─────────────────────────────────────────────────
  function toggleSonido(activo) {
    estado.sonido = activo;
    localStorage.setItem(CLAVE_SONIDO, activo ? '1' : '0');
  }

  function reproducirBip() {
    if (!estado.sonido) return;
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 520;
      gain.gain.setValueAtTime(0.18, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.25);
    } catch (_) {}
  }

  // ── Toolbar ────────────────────────────────────────────────
  function crearToolbar() {
    const topbar = document.querySelector('.topbar');
    if (!topbar) return;

    const wrap = document.createElement('div');
    wrap.id = 'acc-toolbar';
    wrap.innerHTML = `
      <button id="acc-toggle" title="Opciones de accesibilidad" aria-label="Accesibilidad">
        ♿
      </button>
      <div id="acc-panel" hidden>
        <div class="acc-section">
          <div class="acc-label">Tamaño de letra</div>
          <div class="acc-fila">
            <button class="acc-btn-fuente" data-nivel="normal">A</button>
            <button class="acc-btn-fuente" data-nivel="grande" style="font-size:1.1em">A</button>
            <button class="acc-btn-fuente" data-nivel="muygrande" style="font-size:1.25em">A</button>
          </div>
        </div>
        <div class="acc-section">
          <label class="acc-toggle-row">
            <input type="checkbox" id="acc-contraste" ${estado.contraste ? 'checked' : ''}>
            <span>Alto contraste</span>
          </label>
          <label class="acc-toggle-row">
            <input type="checkbox" id="acc-sonido" ${estado.sonido ? 'checked' : ''}>
            <span>Sonido al recibir mensaje</span>
          </label>
        </div>
      </div>
    `;

    // Estilos del toolbar
    const style = document.createElement('style');
    style.textContent = `
      #acc-toolbar { position: relative; }
      #acc-toggle {
        background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.2);
        color: white; border-radius: 8px; padding: 6px 10px; font-size: 16px;
        cursor: pointer; font-family: inherit; transition: background 0.2s;
      }
      #acc-toggle:hover { background: rgba(255,255,255,0.22); }
      #acc-panel {
        position: absolute; top: calc(100% + 8px); right: 0;
        background: white; border-radius: 12px; padding: 14px 16px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.18); min-width: 220px; z-index: 999;
        border: 1px solid #E2E8F0;
      }
      #acc-panel[hidden] { display: none; }
      .acc-section { margin-bottom: 14px; }
      .acc-section:last-child { margin-bottom: 0; }
      .acc-label { font-size: 11px; font-weight: 600; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }
      .acc-fila { display: flex; gap: 6px; }
      .acc-btn-fuente {
        flex: 1; background: #F8FAFC; border: 1.5px solid #E2E8F0;
        border-radius: 8px; padding: 8px; font-family: inherit; color: #0F2744;
        cursor: pointer; transition: all 0.15s; font-weight: 600;
      }
      .acc-btn-fuente:hover { border-color: #2563EB; color: #2563EB; }
      .acc-btn-fuente.activo { background: #0F2744; color: white; border-color: #0F2744; }
      .acc-toggle-row {
        display: flex; align-items: center; gap: 10px; font-size: 13px;
        color: #0F172A; cursor: pointer; padding: 6px 0;
      }
      .acc-toggle-row input { width: 16px; height: 16px; cursor: pointer; accent-color: #0D9488; }

      /* Alto contraste */
      body.modo-accesible { background: #000 !important; color: #fff !important; }
      body.modo-accesible .chat-area,
      body.modo-accesible .mic-area,
      body.modo-accesible .escribir-area,
      body.modo-accesible .chat-principal,
      body.modo-accesible .unirse-card,
      body.modo-accesible .sala-card,
      body.modo-accesible .panel-inferior { background: #111 !important; border-color: #fff !important; }
      body.modo-accesible .msg.coord { background: #00008B !important; }
      body.modo-accesible .msg.estudiante,
      body.modo-accesible .msg.yo { background: #006400 !important; color: #fff !important; border-color: #0f0 !important; }
      body.modo-accesible .topbar { background: #000 !important; border-bottom: 2px solid #fff !important; }
      body.modo-accesible input,
      body.modo-accesible textarea { background: #111 !important; color: #fff !important; border-color: #fff !important; }
    `;
    document.head.appendChild(style);
    topbar.appendChild(wrap);

    // Eventos
    document.getElementById('acc-toggle').addEventListener('click', (e) => {
      e.stopPropagation();
      const panel = document.getElementById('acc-panel');
      panel.hidden = !panel.hidden;
    });

    document.addEventListener('click', () => {
      const panel = document.getElementById('acc-panel');
      if (panel) panel.hidden = true;
    });

    document.querySelectorAll('.acc-btn-fuente').forEach(btn => {
      btn.addEventListener('click', () => aplicarFuente(btn.dataset.nivel));
    });

    document.getElementById('acc-contraste').addEventListener('change', (e) => {
      aplicarContraste(e.target.checked);
    });

    document.getElementById('acc-sonido').addEventListener('change', (e) => {
      toggleSonido(e.target.checked);
    });

    // Aplicar estado guardado al cargar
    aplicarFuente(estado.fuente);
    aplicarContraste(estado.contraste);
  }

  // ── Toasts ─────────────────────────────────────────────────
  let toastContainer = null;

  function toast(mensaje, tipo) {
    if (!toastContainer) {
      toastContainer = document.createElement('div');
      toastContainer.id = 'sh-toasts';
      toastContainer.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastContainer);
      const s = document.createElement('style');
      s.textContent = `
        #sh-toasts { position: fixed; bottom: 90px; left: 50%; transform: translateX(-50%); display: flex; flex-direction: column; gap: 8px; z-index: 9999; pointer-events: none; max-width: 320px; width: 90%; }
        .sh-toast { background: #0F2744; color: white; border-radius: 10px; padding: 10px 16px; font-size: 13px; font-weight: 500; font-family: 'DM Sans', sans-serif; box-shadow: 0 4px 16px rgba(0,0,0,0.2); animation: toastIn 0.25s ease; text-align: center; }
        .sh-toast.exito { background: #0D9488; }
        .sh-toast.error { background: #EF4444; }
        @keyframes toastIn { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
        @keyframes toastOut { from{opacity:1} to{opacity:0} }
        .sh-toast.saliendo { animation: toastOut 0.3s ease forwards; }
      `;
      document.head.appendChild(s);
    }

    const el = document.createElement('div');
    el.className = 'sh-toast' + (tipo ? ' ' + tipo : '');
    el.textContent = mensaje;
    toastContainer.appendChild(el);

    setTimeout(() => {
      el.classList.add('saliendo');
      setTimeout(() => el.remove(), 300);
    }, 2600);
  }

  // ── Pulso de mensaje nuevo ─────────────────────────────────
  function pulsoMensajeNuevo() {
    reproducirBip();
    const chat = document.querySelector('.chat-messages, #chat-messages, #chat-messages-main');
    if (!chat) return;
    chat.classList.remove('pulso-chat');
    void chat.offsetWidth;
    chat.classList.add('pulso-chat');
    setTimeout(() => chat.classList.remove('pulso-chat'), 600);

    const s = document.getElementById('sh-pulso-style');
    if (!s) {
      const style = document.createElement('style');
      style.id = 'sh-pulso-style';
      style.textContent = `@keyframes pulsochat { 0%,100%{box-shadow:none} 50%{box-shadow:0 0 0 3px rgba(13,148,136,0.35)} } .pulso-chat { animation: pulsochat 0.6s ease; }`;
      document.head.appendChild(style);
    }
  }

  // ── API pública ────────────────────────────────────────────
  window.Accesibilidad = {
    init() {
      document.addEventListener('DOMContentLoaded', crearToolbar);
      if (document.readyState !== 'loading') crearToolbar();
    },
    toast,
    pulsoMensajeNuevo,
    confirmarEnvio(msg) { toast(msg || '✅ Mensaje enviado', 'exito'); },
  };

})();