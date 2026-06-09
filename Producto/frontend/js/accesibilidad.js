/**
 * SpeakingHands — feedback visual y accesible (coordinador / estudiante)
 */
(function (global) {
  'use strict';

  const STORAGE_KEY = 'sh_accesibilidad_v1';
  const FONT_SCALES = { normal: 1, grande: 1.15, muygrande: 1.32 };

  let config = {
    rol: 'estudiante',
    chatBoxSelector: '.chat-box',
    bannerEstudiantesId: null,
    bannerSesionId: null,
    sonidoHabilitado: false,
  };

  let settings = cargarSettings();

  function cargarSettings() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return { ...defaults(), ...JSON.parse(raw) };
    } catch (_) {}
    return defaults();
  }

  function defaults() {
    return {
      fontSize: 'normal',
      altoContraste: false,
      sonidoMensaje: false,
    };
  }

  function guardarSettings() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch (_) {}
  }

  function aplicarSettings() {
    const scale = FONT_SCALES[settings.fontSize] || 1;
    document.documentElement.style.setProperty('--font-scale', String(scale));
    document.body.classList.toggle('modo-accesible', !!settings.altoContraste);
    document.body.dataset.fontSize = settings.fontSize;

    document.querySelectorAll('.acces-font-btns button').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.size === settings.fontSize);
    });
    const chkContraste = document.getElementById('acces-alto-contraste');
    const chkSonido = document.getElementById('acces-sonido-mensaje');
    if (chkContraste) chkContraste.checked = !!settings.altoContraste;
    if (chkSonido) chkSonido.checked = !!settings.sonidoMensaje;
  }

  function asegurarToastRegion() {
    let region = document.getElementById('sh-toast-region');
    if (!region) {
      region = document.createElement('div');
      region.id = 'sh-toast-region';
      region.className = 'sh-toast-region';
      region.setAttribute('aria-live', 'polite');
      region.setAttribute('aria-atomic', 'true');
      region.setAttribute('role', 'status');
      document.body.appendChild(region);
    }
    return region;
  }

  function toast(mensaje, esError) {
    const region = asegurarToastRegion();
    const el = document.createElement('div');
    el.className = 'sh-toast' + (esError ? ' error' : '');
    el.textContent = mensaje;
    region.appendChild(el);
    setTimeout(() => el.remove(), 2600);
  }

  function confirmarEnvio(texto) {
    toast(texto || 'Mensaje enviado');
  }

  function playNotificacion() {
    if (!settings.sonidoMensaje || config.rol !== 'coordinador') return;
    try {
      const Ctx = global.AudioContext || global.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = 740;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.2);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.22);
      osc.onended = () => ctx.close();
    } catch (_) {}
  }

  function pulsoMensajeNuevo(opciones) {
    opciones = opciones || {};
    const entrante = opciones.entrante !== false;
    const box = document.querySelector(config.chatBoxSelector);
    if (box) {
      box.classList.remove('msg-nuevo-pulso');
      void box.offsetWidth;
      box.classList.add('msg-nuevo-pulso');
      setTimeout(() => box.classList.remove('msg-nuevo-pulso'), 1400);
    }
    if (entrante) playNotificacion();
  }

  function marcarMsgNuevo(el) {
    if (!el) return;
    el.classList.add('msg-nuevo');
    setTimeout(() => el.classList.remove('msg-nuevo'), 500);
  }

  function setBannerClasses(banner, estado) {
    if (!banner) return;
    banner.classList.remove('conexion-esperando', 'conexion-conectado', 'conexion-desconectado');
    banner.classList.add('conexion-' + estado);
  }

  function pulsoBanner(banner) {
    if (!banner) return;
    banner.classList.remove('pulso-estado');
    void banner.offsetWidth;
    banner.classList.add('pulso-estado');
    setTimeout(() => banner.classList.remove('pulso-estado'), 1200);
  }

  function actualizarEstudiantes(opts) {
    const banner = config.bannerEstudiantesId
      ? document.getElementById(config.bannerEstudiantesId)
      : null;
    if (!banner) return;

    const conectados = typeof opts.conectados === 'number' ? opts.conectados : 0;
    const nombres = Array.isArray(opts.nombres) ? opts.nombres.filter(Boolean) : [];
    const tituloEl = banner.querySelector('.conexion-banner-titulo');
    const detalleEl = banner.querySelector('.conexion-banner-detalle');
    const badgeEl = banner.querySelector('.conexion-banner-badge');
    const iconEl = banner.querySelector('.conexion-banner-icon');

    banner.hidden = false;
    badgeEl.textContent = String(conectados);

    if (conectados > 0) {
      setBannerClasses(banner, 'conectado');
      if (iconEl) iconEl.textContent = '\u2705';
      tituloEl.textContent = conectados === 1
        ? '1 estudiante conectado'
        : conectados + ' estudiantes conectados';
      if (nombres.length) {
        detalleEl.textContent = nombres.slice(0, 4).join(', ') +
          (nombres.length > 4 ? '…' : '');
      } else {
        detalleEl.textContent = 'En línea en este momento';
      }
    } else if (nombres.length > 0) {
      setBannerClasses(banner, 'desconectado');
      if (iconEl) iconEl.textContent = '\u26A0\uFE0F';
      tituloEl.textContent = 'Estudiantes sin conexión';
      detalleEl.textContent = nombres.join(', ') + ' — registrados, no en línea';
    } else {
      setBannerClasses(banner, 'esperando');
      if (iconEl) iconEl.textContent = '\u23F3';
      tituloEl.textContent = 'Esperando estudiante';
      detalleEl.textContent = 'Comparte el código de sala para que se unan';
    }

    const countLegacy = document.getElementById('est-count');
    if (countLegacy) countLegacy.textContent = String(conectados);
  }

  function actualizarSesionEstudiante(opts) {
    const banner = config.bannerSesionId
      ? document.getElementById(config.bannerSesionId)
      : null;
    if (!banner) return;

    const conectado = !!opts.conectado;
    const coordinador = opts.coordinador || 'Coordinador';
    const tituloEl = banner.querySelector('.conexion-banner-titulo');
    const detalleEl = banner.querySelector('.conexion-banner-detalle');
    const iconEl = banner.querySelector('.conexion-banner-icon');
    const badgeEl = banner.querySelector('.conexion-banner-badge');

    banner.hidden = false;

    if (conectado) {
      setBannerClasses(banner, 'conectado');
      if (iconEl) iconEl.textContent = '\u2705';
      tituloEl.textContent = 'Conectado a la sala';
      detalleEl.textContent = 'Sesión con ' + coordinador;
      if (badgeEl) badgeEl.textContent = '\u2713';
    } else {
      setBannerClasses(banner, 'desconectado');
      if (iconEl) iconEl.textContent = '\u274C';
      tituloEl.textContent = 'Desconectado';
      detalleEl.textContent = 'Intenta unirte de nuevo con el código';
      if (badgeEl) badgeEl.textContent = '!';
    }

    pulsoBanner(banner);
    actualizarPillEstudiante(conectado);
  }

  function actualizarPillEstudiante(conectado) {
    const pill = document.getElementById('status-pill');
    if (!pill) return;
    const dot = pill.querySelector('.dot');
    const text = document.getElementById('statusText');
    pill.style.display = 'flex';
    if (conectado) {
      if (dot) dot.style.background = 'var(--success)';
      if (text) {
        text.textContent = 'Conectado';
        text.style.color = 'var(--success)';
      }
      pill.style.borderColor = 'rgba(16,185,129,0.45)';
      pill.style.background = 'rgba(16,185,129,0.2)';
    } else {
      if (dot) dot.style.background = 'var(--danger)';
      if (text) {
        text.textContent = 'Desconectado';
        text.style.color = 'var(--danger)';
      }
      pill.style.borderColor = 'rgba(239,68,68,0.45)';
      pill.style.background = 'rgba(239,68,68,0.15)';
    }
  }

  function crearToolbar(topbar) {
    if (!topbar || document.getElementById('acces-toolbar')) return;

    const wrap = document.createElement('div');
    wrap.className = 'topbar-acces-wrap';
    wrap.innerHTML = `
      <div class="acces-toolbar" id="acces-toolbar">
        <button type="button" class="acces-toggle" id="acces-toggle"
          aria-expanded="false" aria-controls="acces-panel"
          title="Opciones de accesibilidad">Aa</button>
        <div class="acces-panel" id="acces-panel" hidden>
          <div class="acces-panel-title">Accesibilidad</div>
          <div class="acces-field">
            <label>Tamaño de texto</label>
            <div class="acces-font-btns" role="group" aria-label="Tamaño de texto">
              <button type="button" data-size="normal" title="Normal">A</button>
              <button type="button" data-size="grande" title="Grande">A+</button>
              <button type="button" data-size="muygrande" title="Muy grande">A++</button>
            </div>
          </div>
          <label class="acces-check">
            <input type="checkbox" id="acces-alto-contraste">
            <span>Modo alto contraste</span>
          </label>
          ${config.rol === 'coordinador' ? `
          <label class="acces-check" style="margin-top:10px">
            <input type="checkbox" id="acces-sonido-mensaje">
            <span>Sonido al recibir mensaje (opcional)</span>
          </label>` : ''}
        </div>
      </div>`;

    const sessionPill = topbar.querySelector('.session-pill, .status-pill');
    const btnAbandonar = document.getElementById('btn-abandonar');
    const btnCerrarSesion = document.getElementById('btn-cerrar-sesion');
    if (sessionPill) {
      topbar.insertBefore(wrap, sessionPill);
      if (btnCerrarSesion) wrap.insertBefore(btnCerrarSesion, wrap.firstChild);
      wrap.appendChild(sessionPill);
      if (btnAbandonar) wrap.appendChild(btnAbandonar);
    } else {
      if (btnCerrarSesion) wrap.insertBefore(btnCerrarSesion, wrap.firstChild);
      topbar.appendChild(wrap);
    }

    const toggle = document.getElementById('acces-toggle');
    const panel = document.getElementById('acces-panel');

    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = panel.hidden;
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });

    document.addEventListener('click', () => {
      panel.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
    });
    panel.addEventListener('click', (e) => e.stopPropagation());

    document.querySelectorAll('.acces-font-btns button').forEach(btn => {
      btn.addEventListener('click', () => {
        settings.fontSize = btn.dataset.size || 'normal';
        guardarSettings();
        aplicarSettings();
      });
    });

    const chkContraste = document.getElementById('acces-alto-contraste');
    if (chkContraste) {
      chkContraste.addEventListener('change', () => {
        settings.altoContraste = chkContraste.checked;
        guardarSettings();
        aplicarSettings();
      });
    }

    const chkSonido = document.getElementById('acces-sonido-mensaje');
    if (chkSonido) {
      chkSonido.addEventListener('change', () => {
        settings.sonidoMensaje = chkSonido.checked;
        guardarSettings();
      });
    }
  }

  function setPantallaInicial(esInicial) {
    const btn = document.getElementById('btn-cerrar-sesion');
    if (btn) btn.style.display = esInicial ? 'inline-flex' : 'none';
  }

  function init(opciones) {
    config = { ...config, ...(opciones || {}) };
    if (config.rol === 'coordinador') config.sonidoHabilitado = true;

    const topbar = document.querySelector('.topbar');
    crearToolbar(topbar);
    aplicarSettings();
    asegurarToastRegion();
    setPantallaInicial(true);
  }

  global.Accesibilidad = {
    init,
    setPantallaInicial,
    toast,
    confirmarEnvio,
    pulsoMensajeNuevo,
    marcarMsgNuevo,
    actualizarEstudiantes,
    actualizarSesionEstudiante,
    actualizarPillEstudiante,
  };
})(window);
