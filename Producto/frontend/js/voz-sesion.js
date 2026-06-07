/* SpeakingHands — módulo de voz compartido */
window.VozSesion = (function() {
  let cfg = {
    storageKey: 'voz_google_caido',
    onEnviar: function() {},
    sinBorradorChat: false,
    authHeaders: function() { return {}; },
    redirigirSiSesionExpirada: function() { return false; },
  };

  function claveGoogle() {
    return cfg.storageKey || CLAVE_GOOGLE_CAIDO;
  }

  let reconocedor = null;
  let escuchandoActivo = false;
  let sesionVozAbierta = false;
  let micPausado = false;

    let micStream = null;
    let textoSesion = '';
    let interimActual = '';
    let borradorChatEl = null;
    let modoServidor = false;
    let vozModoActual = 'online';
    let estadoVozServidor = null;
    let motorServidorActivo = null;
    let audioContext = null;
    let scriptProcessor = null;
    let muestrasUtterance = [];
    let transcribiendo = false;
    let sampleRateActual = 16000;
    let huboVoz = false;
    let msSilencio = 0;
    const UMBRAL_RMS = 0.012;
    const SILENCIO_MS = 2500;
    const MAX_FRASE_SEG = 30;
    const MIN_FRASE_SEG = 0.6;
    const TIMEOUT_GOOGLE_NAV_MS = 8000;
    const TIMEOUT_GOOGLE_SRV_MS = 4500;
    let timerFalloGoogleNav = null;
    let googleNavInicioOk = false;
    let googleFalloEnSesionActual = false;
    const CLAVE_GOOGLE_CAIDO = 'voz_google_caido';
    let verificandoGoogle = false;
    let promesaVerificacionGoogle = null;

    function escHtml(s) {
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function marcarGoogleFallido() {
      googleFalloEnSesionActual = true;
      sessionStorage.setItem(claveGoogle(), '1');
    }

    function limpiarMarcaGoogleFallido() {
      googleFalloEnSesionActual = false;
      sessionStorage.removeItem(claveGoogle());
      sessionStorage.removeItem('voz_google_fallo_hasta');
      localStorage.removeItem(claveGoogle());
      localStorage.removeItem('voz_google_fallo_hasta');
    }

    function googleMarcadoComoCaido() {
      return sessionStorage.getItem(claveGoogle()) === '1';
    }

    function debeUsarWhisperDirecto() {
      if (!navigator.onLine) return true;
      return googleMarcadoComoCaido();
    }

    function googleProbablementeDisponible() {
      return navigator.onLine && !googleMarcadoComoCaido() && !simulacionGoogleNavCaida();
    }

    function simulacionGoogleNavCaida() {
      return !!estadoVozServidor?.simulacion?.google_navegador_caido;
    }

    function simulacionGoogleSrvCaida() {
      return !!estadoVozServidor?.simulacion?.google_servidor_caido;
    }

    function actualizarBannerSimulacion() {
      const banner = document.getElementById('voz-sim-banner');
      if (!banner) return;
      const sim = estadoVozServidor?.simulacion;
      if (!sim?.activa) {
        banner.style.display = 'none';
        return;
      }
      const partes = [];
      if (sim.google_navegador_caido) partes.push('navegador');
      if (sim.google_servidor_caido) partes.push('servidor');
      banner.innerHTML = `<strong>Modo simulación</strong>Google caído (${partes.join(' + ')}). Desactiva <code>VOZ_SIMULAR_*</code> en <code>.env</code> y reinicia el servidor.`;
      banner.style.display = 'block';
    }

    function iniciarConSimulacionGoogle() {
      if (simulacionGoogleSrvCaida()) {
        document.getElementById('mic-status').textContent = 'Simulación: Google caído. Iniciando Whisper…';
        asegurarMicStream()
          .then(() => fallbackRapidoWhisper('Simulación: Google no disponible. Usando Whisper…'))
          .catch(() => {
            escuchandoActivo = false;
            sesionVozAbierta = false;
            alert('No se pudo acceder al micrófono.');
            actualizarBotonesVoz();
          });
        return true;
      }
      probarGoogleServidorAntesWhisper('Simulación: Google del navegador no disponible.');
      return true;
    }

    function verificarRecuperacionGoogle() {
      if (verificandoGoogle || !googleMarcadoComoCaido() || !navigator.onLine) return;
      verificarRecuperacionGoogleAsync().then((ok) => {
        if (ok && !escuchandoActivo && !sesionVozAbierta) indicadorVozInicial();
      });
    }

    function verificarRecuperacionGoogleAsync() {
      if (!googleMarcadoComoCaido() || !navigator.onLine) {
        return Promise.resolve(!googleMarcadoComoCaido());
      }
      if (promesaVerificacionGoogle) return promesaVerificacionGoogle;

      promesaVerificacionGoogle = new Promise((resolve) => {
        const SR = window.webkitSpeechRecognition || window.SpeechRecognition;
        if (!SR) {
          promesaVerificacionGoogle = null;
          resolve(false);
          return;
        }

        verificandoGoogle = true;
        const rec = new SR();
        rec.lang = 'es-CL';
        let listo = false;

        const terminar = (ok) => {
          if (listo) return;
          listo = true;
          verificandoGoogle = false;
          promesaVerificacionGoogle = null;
          try { rec.abort(); } catch (_) {}
          rec.onstart = null;
          rec.onerror = null;
          if (ok) limpiarMarcaGoogleFallido();
          resolve(ok);
        };

        const timer = setTimeout(() => terminar(false), 4000);
        rec.onstart = () => {
          clearTimeout(timer);
          terminar(true);
        };
        rec.onerror = (e) => {
          if (e.error === 'not-allowed' || e.error === 'network') {
            clearTimeout(timer);
            terminar(false);
          }
        };
        try {
          rec.start();
        } catch (_) {
          clearTimeout(timer);
          verificandoGoogle = false;
          promesaVerificacionGoogle = null;
          resolve(false);
        }
      });

      return promesaVerificacionGoogle;
    }

    function cancelarTimeoutGoogleNav() {
      if (timerFalloGoogleNav) {
        clearTimeout(timerFalloGoogleNav);
        timerFalloGoogleNav = null;
      }
    }

    function iniciarTimeoutGoogleNav() {
      cancelarTimeoutGoogleNav();
      googleNavInicioOk = false;
      timerFalloGoogleNav = setTimeout(() => {
        if (googleNavInicioOk || modoServidor || micPausado || !escuchandoActivo) return;
        if (reconocedor) {
          try { reconocedor.abort(); } catch (_) {}
          reconocedor = null;
        }
        if (!navigator.onLine) {
          fallbackRapidoWhisper('Sin conexión. Usando Whisper…');
        } else if (googleMarcadoComoCaido()) {
          fallbackRapidoWhisper('Google no respondió. Usando Whisper…');
        } else {
          probarGoogleServidorAntesWhisper('Google del navegador no respondió a tiempo.');
        }
      }, TIMEOUT_GOOGLE_NAV_MS);
    }

    function asegurarMicStream() {
      if (micStream) return Promise.resolve(micStream);
      return navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
        if (!escuchandoActivo) {
          stream.getTracks().forEach(t => t.stop());
          return Promise.reject(new Error('cancelado'));
        }
        if (micStream) {
          stream.getTracks().forEach(t => t.stop());
          return micStream;
        }
        micStream = stream;
        return stream;
      });
    }

    function probarGoogleServidorAntesWhisper(motivo) {
      if (googleMarcadoComoCaido()) {
        fallbackRapidoWhisper(motivo || 'Google no disponible. Usando Whisper…');
        return;
      }
      if (simulacionGoogleSrvCaida()) {
        fallbackRapidoWhisper(motivo || 'Simulación: Google en servidor no disponible. Usando Whisper…');
        return;
      }
      cancelarTimeoutGoogleNav();
      const hintRed = document.getElementById('mic-hint-red');
      if (hintRed && motivo) {
        hintRed.style.display = 'block';
        hintRed.textContent = `${motivo} Probando Google en servidor…`;
      }
      const micStatus = document.getElementById('mic-status');
      if (micStatus) micStatus.textContent = 'Probando Google en servidor…';
      asegurarMicStream()
        .then(() => cambiarAGoogleServidor(''))
        .catch(() => {
          if (escuchandoActivo) {
            alert('No se pudo acceder al micrófono.');
            cerrarSesionVoz(true);
          }
        });
    }

    function fallbackRapidoWhisper(motivo) {
      cancelarTimeoutGoogleNav();
      marcarGoogleFallido();
      const irWhisper = () => {
        if (!whisperOfflineListo()) {
          cargarEstadoVoz().then(() => {
            if (whisperOfflineListo()) cambiarAWhisper(motivo);
            else aplicarSoloTexto(mensajeModeloWhisperPendiente());
          });
          return;
        }
        cambiarAWhisper(motivo);
      };
      asegurarMicStream().then(irWhisper).catch(() => {
        if (escuchandoActivo) {
          alert('No se pudo acceder al micrófono.');
          cerrarSesionVoz(true);
        }
      });
    }

    async function fetchTranscribir(form, timeoutMs) {
      const ctrl = new AbortController();
      const id = setTimeout(() => ctrl.abort(), timeoutMs);
      try {
        return await fetch('/api/transcribir', {
          method: 'POST',
          body: form,
          headers: cfg.authHeaders(),
          signal: ctrl.signal,
        });
      } finally {
        clearTimeout(id);
      }
    }

    function apiErrorMsg(data) {
      if (!data) return '';
      if (typeof data.error === 'string') return data.error;
      if (typeof data.detail === 'string') return data.detail;
      return '';
    }

    function actualizarIndicadorVoz(modo, detalle) {
      vozModoActual = modo;
      const badge = document.getElementById('voz-status');
      const texto = document.getElementById('voz-status-text');
      if (!badge || !texto) return;

      badge.classList.remove('voz-online', 'voz-offline', 'voz-sin-servicio');
      if (modo === 'whisper' || modo === 'offline' || modo === 'local') {
        badge.classList.add('voz-offline');
        texto.textContent = detalle || 'Whisper';
        badge.title = 'Respaldo local — Google no disponible';
      } else if (modo === 'sin_servicio') {
        badge.classList.add('voz-sin-servicio');
        texto.textContent = 'Sin servicio';
        badge.title = 'Voz no disponible — usa texto o frases rápidas';
      } else {
        badge.classList.add('voz-online');
        texto.textContent = detalle || 'Google';
        badge.title = detalle === 'Google (navegador)'
          ? 'Reconocimiento en tiempo real por el navegador'
          : 'Google Speech — requiere conexión a internet';
      }
    }

    function ocultarHintsVoz() {
      ['mic-hint-red', 'mic-hint-servidor', 'mic-hint-offline', 'mic-hint-google-nav'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
      });
    }

    function mostrarHintGoogleNavegador() {
      ocultarHintsVoz();
      const hint = document.getElementById('mic-hint-google-nav');
      if (hint) hint.style.display = 'block';
    }

    function aplicarSoloTexto(motivo) {
      actualizarIndicadorVoz('sin_servicio');
      const banner = document.getElementById('voz-solo-texto-banner');
      const micArea = document.getElementById('mic-area');
      if (banner) {
        banner.style.display = 'block';
        if (motivo) {
          banner.innerHTML = `<strong>Voz no disponible — solo texto</strong>${motivo}`;
        }
      }
      if (micArea) micArea.classList.add('mic-deshabilitado');
      if (escuchandoActivo || sesionVozAbierta) cerrarSesionVoz(false);
      document.getElementById('mic-hint-red').style.display = 'none';
      ocultarHintsVoz();
    }

    function ocultarSoloTexto() {
      const banner = document.getElementById('voz-solo-texto-banner');
      const micArea = document.getElementById('mic-area');
      if (banner) banner.style.display = 'none';
      if (micArea) micArea.classList.remove('mic-deshabilitado');
    }

    function actualizarHintsServidor(motor) {
      ocultarHintsVoz();
      if (motor === 'whisper') {
        document.getElementById('mic-hint-offline').style.display = 'block';
        actualizarIndicadorVoz('whisper', 'Whisper');
      } else {
        document.getElementById('mic-hint-servidor').style.display = 'block';
        actualizarIndicadorVoz('google', 'Google (servidor)');
      }
    }

    function indicadorVozInicial() {
      ocultarHintsVoz();
      if (debeUsarWhisperDirecto() && whisperOfflineListo()) {
        actualizarIndicadorVoz('whisper', 'Whisper');
      } else if (navigator.onLine && !googleMarcadoComoCaido()) {
        actualizarIndicadorVoz('google', 'Google');
      } else if (whisperOfflineListo()) {
        actualizarIndicadorVoz('whisper', 'Whisper');
      } else {
        actualizarIndicadorVoz('google', 'Google');
      }
    }

    async function cargarEstadoVoz() {
      try {
        const res = await fetch('/api/voz/estado', { headers: cfg.authHeaders() });
        if (cfg.redirigirSiSesionExpirada(res)) return null;
        if (!res.ok) return null;
        estadoVozServidor = await res.json();
        const srv = estadoVozServidor?.servidor;
        const SR = window.webkitSpeechRecognition || window.SpeechRecognition;

        if (navigator.onLine) {
          sessionStorage.removeItem('voz_modo_servidor');
        }

        if (modoServidor && escuchandoActivo) {
          actualizarHintsServidor(motorServidorActivo === 'whisper' ? 'whisper' : 'google');
        } else {
          indicadorVozInicial();
        }
        if (navigator.onLine && googleMarcadoComoCaido()) {
          verificarRecuperacionGoogle();
        }
        actualizarBannerSimulacion();
        return estadoVozServidor;
      } catch (_) {
        return null;
      }
    }

    window.addEventListener('online', () => {
      sessionStorage.removeItem('voz_modo_servidor');
      motorServidorActivo = null;
      if (!modoServidor && !escuchandoActivo) {
        indicadorVozInicial();
        ocultarSoloTexto();
      }
      verificarRecuperacionGoogle();
    });

    window.addEventListener('offline', () => {
      marcarGoogleFallido();
      cancelarTimeoutGoogleNav();
      if (!escuchandoActivo && !sesionVozAbierta) {
        indicadorVozInicial();
        return;
      }
      if (reconocedor) {
        try { reconocedor.abort(); } catch (_) {}
        reconocedor = null;
      }
      fallbackRapidoWhisper('Sin conexión. Cambiando a Whisper…');
    });

    function whisperOfflineListo() {
      return !!(estadoVozServidor?.servidor?.whisper_listo);
    }

    function mensajeModeloWhisperPendiente() {
      return ' El modelo Whisper aún no está en este equipo. Con WiFi, reinicia el servidor (se descarga solo) o ejecuta: python -m app.voz.transcripcion';
    }

    function actualizarBotonesVoz() {
      const btnHablar = document.getElementById('btn-hablar');
      const btnPausar = document.getElementById('btn-pausar');
      const btnBorrar = document.getElementById('btn-borrar');
      const enSesion = sesionVozAbierta && (escuchandoActivo || micPausado || !!micStream);

      if (btnHablar) {
        btnHablar.disabled = enSesion;
        btnHablar.classList.toggle('recording', escuchandoActivo && !micPausado);
      }
      if (btnPausar) {
        btnPausar.style.display = enSesion ? '' : 'none';
        btnPausar.textContent = micPausado ? '▶ Reanudar' : '⏸ Pausar';
        btnPausar.classList.toggle('btn-reanudar', micPausado);
      }
      if (btnBorrar) {
        const hayContenido = !!(textoSesion || interimActual || borradorChatEl);
        btnBorrar.disabled = !hayContenido && !enSesion;
      }
      actualizarBtnEnviar();
    }

    function actualizarEstadoGrabacion() {
      const row = document.getElementById('mic-row');
      const preview = document.getElementById('mic-preview');
      const grabando = escuchandoActivo && !micPausado;

      if (row) {
        row.classList.toggle('recording', grabando);
        row.classList.toggle('paused', micPausado && sesionVozAbierta);
        row.classList.toggle('active', grabando || micPausado);
      }
      if (preview) {
        preview.classList.toggle('live', grabando || (micPausado && !!(textoSesion || interimActual)));
      }
      actualizarBotonesVoz();
    }

    function setMicUI(activo) {
      if (vozModoActual === 'sin_servicio') return;
      const status = document.getElementById('mic-status');
      let etiqueta = 'Listo para escuchar';

      if (micPausado && sesionVozAbierta) {
        etiqueta = '⏸ Pausado — pulsa Reanudar para seguir la frase';
      } else if (activo) {
        if (transcribiendo) {
          etiqueta = '⟳ Convirtiendo audio a texto…';
        } else if (modoServidor && huboVoz) {
          etiqueta = '● Grabando — detectando voz…';
        } else if (interimActual) {
          etiqueta = '● Grabando — transcribiendo en tiempo real';
        } else {
          etiqueta = '● Grabando — habla ahora, el texto aparece abajo';
        }
      }

      status.textContent = etiqueta;
      status.classList.toggle('active', activo || micPausado);
      document.getElementById('mic-circle').classList.toggle('active', activo || micPausado);
      document.getElementById('mic-waves').style.display = activo && !micPausado ? 'flex' : 'none';
      if (activo || micPausado) status.style.color = micPausado ? '#B45309' : '';
      actualizarEstadoGrabacion();
    }

    function liberarMic() {
      if (scriptProcessor) {
        scriptProcessor.disconnect();
        scriptProcessor.onaudioprocess = null;
        scriptProcessor = null;
      }
      if (audioContext) {
        audioContext.close().catch(() => {});
        audioContext = null;
      }
      muestrasUtterance = [];
      huboVoz = false;
      msSilencio = 0;
      if (micStream) {
        micStream.getTracks().forEach(t => t.stop());
        micStream = null;
      }
    }

    function quitarBorradorChat() {
      if (borradorChatEl) {
        borradorChatEl.remove();
        borradorChatEl = null;
      }
    }

    function actualizarBorradorChat(texto) {
      if (cfg.sinBorradorChat) return;
      const t = (texto || '').trim();
      const c = document.getElementById('chat-messages');
      const empty = c.querySelector('.chat-empty');
      if (empty) empty.remove();

      if (!t) {
        quitarBorradorChat();
        return;
      }

      if (!borradorChatEl) {
        borradorChatEl = document.createElement('div');
        borradorChatEl.className = 'msg coord borrador-voz';
        borradorChatEl.innerHTML = '<div class="msg-label">Tú (voz → texto)</div><div class="msg-text"></div>';
        c.appendChild(borradorChatEl);
      }
      borradorChatEl.querySelector('.msg-text').textContent = t;
      c.scrollTop = c.scrollHeight;
    }

    function actualizarBtnEnviar() {
      const btn = document.getElementById('btn-enviar-voz');
      if (!btn) return;
      const hayBorrador = !!(textoSesion || interimActual || borradorChatEl);
      btn.disabled = !hayBorrador;
    }

    function resetPreview() {
      textoSesion = '';
      interimActual = '';
      quitarBorradorChat();
      const preview = document.getElementById('mic-preview');
      preview.textContent = 'Aquí aparecerá lo que dices...';
      preview.classList.add('empty');
      preview.classList.remove('live');
      preview.innerHTML = 'Aquí aparecerá lo que dices...';
      actualizarBotonesVoz();
    }

    function renderPreviewTexto(finalText, interimText) {
      const preview = document.getElementById('mic-preview');
      const final = (finalText || '').trim();
      const interim = (interimText || '').trim();

      if (!final && !interim) {
        preview.textContent = escuchandoActivo && !micPausado
          ? 'Escuchando… el texto aparecerá mientras hablas'
          : 'Aquí aparecerá lo que dices...';
        preview.classList.add('empty');
        preview.classList.remove('live');
        quitarBorradorChat();
        actualizarBotonesVoz();
        return;
      }

      preview.classList.remove('empty');
      let html = '';
      if (final) html += escHtml(final);
      if (interim) {
        html += (final ? ' ' : '') + `<span class="interim">${escHtml(interim)}</span>`;
      }
      preview.innerHTML = html;
      actualizarBorradorChat([final, interim].filter(Boolean).join(' ').trim());
      actualizarBotonesVoz();
      setMicUI(escuchandoActivo);
    }

    function mostrarPreviewSesion(extra) {
      const interim = extra === 'Transcribiendo...' ? '' : (extra || interimActual);
      if (extra === 'Transcribiendo...') {
        const preview = document.getElementById('mic-preview');
        preview.classList.remove('empty');
        preview.classList.add('live');
        preview.innerHTML = `${escHtml(textoSesion)} <span class="interim">Transcribiendo…</span>`.trim();
        actualizarBorradorChat('Transcribiendo...');
        setMicUI(true);
        return;
      }
      renderPreviewTexto(textoSesion, interim);
    }

    function agregarTextoSesion(texto) {
      const t = texto.trim();
      if (!t) return;
      textoSesion = textoSesion ? `${textoSesion} ${t}` : t;
      interimActual = '';
      mostrarPreviewSesion();
    }

    function enviarVoz(texto) {
      const final = texto.trim();
      if (!final || final === 'Transcribiendo...') return;
      quitarBorradorChat();
      cfg.onEnviar(final);
      cerrarSesionVoz(true);
    }

    function confirmarEnvioAlChat() {
      const pendiente = [textoSesion, interimActual]
        .filter(t => t && t !== 'Transcribiendo...')
        .join(' ')
        .trim();
      if (pendiente) enviarVoz(pendiente);
      else renderPreviewTexto('', '');
    }

    function rmsAudio(muestras) {
      let sum = 0;
      for (let i = 0; i < muestras.length; i++) sum += muestras[i] * muestras[i];
      return Math.sqrt(sum / muestras.length);
    }

    function encodeWAV(muestras, sampleRate) {
      const buffer = new ArrayBuffer(44 + muestras.length * 2);
      const view = new DataView(buffer);
      const escribir = (offset, str) => { for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i)); };
      escribir(0, 'RIFF');
      view.setUint32(4, 36 + muestras.length * 2, true);
      escribir(8, 'WAVE');
      escribir(12, 'fmt ');
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * 2, true);
      view.setUint16(32, 2, true);
      view.setUint16(34, 16, true);
      escribir(36, 'data');
      view.setUint32(40, muestras.length * 2, true);
      let offset = 44;
      for (let i = 0; i < muestras.length; i++, offset += 2) {
        const s = Math.max(-1, Math.min(1, muestras[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
      }
      return new Blob([buffer], { type: 'audio/wav' });
    }

    async function transcribirEnServidor(wavBlob, preferirForzado) {
      if (!wavBlob || wavBlob.size < 1000) return { texto: '', modo: null };

      let preferir = preferirForzado || motorServidorActivo;
      if (!preferir) {
        preferir = debeUsarWhisperDirecto() ? 'whisper' : 'google';
      }
      if (debeUsarWhisperDirecto()) preferir = 'whisper';

      try {
        const form = new FormData();
        form.append('audio', wavBlob, 'audio.wav');
        form.append('preferir', preferir);

        const timeoutMs = preferir === 'google' ? TIMEOUT_GOOGLE_SRV_MS : 60000;
        let res;
        try {
          res = await fetchTranscribir(form, timeoutMs);
        } catch (err) {
          if (preferir === 'google' && whisperOfflineListo()) {
            marcarGoogleFallido();
            motorServidorActivo = 'whisper';
            actualizarHintsServidor('whisper');
            return transcribirEnServidor(wavBlob, 'whisper');
          }
          throw err;
        }

        if (cfg.redirigirSiSesionExpirada(res)) return { texto: '', modo: null };

        let data = {};
        try { data = await res.json(); } catch (_) {}

        const errMsg = apiErrorMsg(data);
        const hintRed = document.getElementById('mic-hint-red');

        if (!res.ok) {
          if (preferir === 'google' && whisperOfflineListo()) {
            marcarGoogleFallido();
            if (hintRed) {
              hintRed.style.display = 'block';
              hintRed.textContent = 'Google no respondió. Cambiando a Whisper…';
            }
            motorServidorActivo = 'whisper';
            actualizarHintsServidor('whisper');
            return transcribirEnServidor(wavBlob, 'whisper');
          }
          const modeloPendiente = /whisper.*descarg|modelo whisper/i.test(errMsg);
          if (hintRed && errMsg) {
            hintRed.style.display = 'block';
            hintRed.textContent = errMsg;
          }
          if (modeloPendiente || (res.status === 503 && data.modo === 'sin_servicio')) {
            aplicarSoloTexto(` ${modeloPendiente ? mensajeModeloWhisperPendiente().trim() : errMsg}`);
          }
          return { texto: '', modo: data.modo || null };
        }

        ocultarSoloTexto();
        if (hintRed) hintRed.style.display = 'none';
        motorServidorActivo = data.motor || preferir;
        if (data.motor === 'google') limpiarMarcaGoogleFallido();
        if (data.motor === 'whisper') {
          actualizarHintsServidor('whisper');
        } else if (modoServidor) {
          actualizarHintsServidor('google');
        }

        const texto = (data.texto || '').trim();
        if (!texto && hintRed) {
          hintRed.style.display = 'block';
          hintRed.textContent = 'No se entendió el audio — habla más claro e intenta de nuevo.';
        }
        return { texto, modo: data.modo || null, motor: data.motor || null };
      } catch (_) {
        if (preferir === 'google' && whisperOfflineListo()) {
          motorServidorActivo = 'whisper';
          actualizarHintsServidor('whisper');
          return transcribirEnServidor(wavBlob, 'whisper');
        }
        const hintRed = document.getElementById('mic-hint-red');
        if (hintRed) {
          hintRed.style.display = 'block';
          hintRed.textContent = 'Error de conexión con el servidor. Verifica que uvicorn siga activo.';
        }
        return { texto: '', modo: null };
      }
    }

    async function transcribirUtteranceServidor(muestras, permitirAlDetener) {
      if (transcribiendo || !muestras.length) return;
      if (!escuchandoActivo && !permitirAlDetener) return;
      if (muestras.length < sampleRateActual * MIN_FRASE_SEG) return;

      transcribiendo = true;
      mostrarPreviewSesion('Transcribiendo...');
      actualizarBorradorChat('Transcribiendo...');
      try {
        const wav = encodeWAV(muestras, sampleRateActual);
        const resultado = await transcribirEnServidor(wav);
        if (resultado.texto) agregarTextoSesion(resultado.texto);
        else mostrarPreviewSesion();
      } finally {
        transcribiendo = false;
      }
    }

    async function flushUtteranceServidor(forzar, permitirAlDetener) {
      if (!muestrasUtterance.length) return;
      if (!forzar && muestrasUtterance.length < sampleRateActual * MIN_FRASE_SEG) return;
      const muestras = muestrasUtterance.splice(0);
      huboVoz = false;
      msSilencio = 0;
      await transcribirUtteranceServidor(muestras, permitirAlDetener);
    }

    function cambiarAWhisper(motivo) {
      if (!whisperOfflineListo()) {
        aplicarSoloTexto(mensajeModeloWhisperPendiente());
        return false;
      }
      const hintRed = document.getElementById('mic-hint-red');
      if (hintRed && motivo) {
        hintRed.style.display = 'block';
        hintRed.textContent = motivo;
      }
      motorServidorActivo = 'whisper';
      iniciarModoServidor('whisper');
      return true;
    }

    function cambiarAGoogleServidor(motivo) {
      const hintRed = document.getElementById('mic-hint-red');
      if (hintRed && motivo) {
        hintRed.style.display = 'block';
        hintRed.textContent = motivo;
      }
      motorServidorActivo = 'google';
      iniciarModoServidor('google');
    }

    function iniciarModoServidor(motor) {
      if (vozModoActual === 'sin_servicio') return;

      motor = motor || (debeUsarWhisperDirecto() ? 'whisper' : 'google');
      motorServidorActivo = motor;

      if (motor === 'whisper') {
        if (!whisperOfflineListo()) {
          document.getElementById('mic-hint-red').style.display = 'block';
          document.getElementById('mic-hint-red').textContent = mensajeModeloWhisperPendiente().trim();
          aplicarSoloTexto(mensajeModeloWhisperPendiente());
          return;
        }
      }

      modoServidor = true;
      if (!navigator.onLine) {
        sessionStorage.setItem('voz_modo_servidor', '1');
      } else {
        sessionStorage.removeItem('voz_modo_servidor');
      }
      ocultarSoloTexto();
      actualizarHintsServidor(motor);

      if (reconocedor) {
        try { reconocedor.abort(); } catch (_) {}
        reconocedor.onstart = null;
        reconocedor.onend = null;
        reconocedor.onerror = null;
        reconocedor.onresult = null;
        reconocedor = null;
      }

      if (scriptProcessor && audioContext && micStream) {
        escuchandoActivo = true;
        setMicUI(true);
        return;
      }

      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      if (audioContext.state === 'suspended') audioContext.resume();
      sampleRateActual = audioContext.sampleRate;
      const maxMuestras = Math.floor(sampleRateActual * MAX_FRASE_SEG);
      const source = audioContext.createMediaStreamSource(micStream);
      scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);
      muestrasUtterance = [];
      huboVoz = false;
      msSilencio = 0;

      scriptProcessor.onaudioprocess = (e) => {
        if (!escuchandoActivo) return;
        const data = e.inputBuffer.getChannelData(0);
        const bloque = Array.from(data);
        const msBloque = (bloque.length / sampleRateActual) * 1000;

        muestrasUtterance.push(...bloque);

        if (muestrasUtterance.length >= maxMuestras) {
          flushUtteranceServidor(true, false);
          return;
        }

        if (transcribiendo) return;

        const esVoz = rmsAudio(bloque) > UMBRAL_RMS;
        if (esVoz) {
          huboVoz = true;
          msSilencio = 0;
          setMicUI(true);
        } else if (huboVoz) {
          msSilencio += msBloque;
          if (msSilencio >= SILENCIO_MS) flushUtteranceServidor(false, false);
        }
      };

      source.connect(scriptProcessor);
      scriptProcessor.connect(audioContext.destination);
      setMicUI(true);
    }

    function comenzarReconocimiento() {
      const SR = window.webkitSpeechRecognition || window.SpeechRecognition;

      if (simulacionGoogleNavCaida() && navigator.onLine) {
        iniciarConSimulacionGoogle();
        return;
      }

      if (!navigator.onLine || !googleProbablementeDisponible()) {
        const motivo = !navigator.onLine
          ? 'Sin conexión a internet. Usando Whisper…'
          : 'Google no respondió en esta frase. Usando Whisper…';
        fallbackRapidoWhisper(motivo);
        return;
      }

      if (!SR) {
        if (whisperOfflineListo()) {
          fallbackRapidoWhisper('Navegador sin reconocimiento de voz. Usando Whisper…');
        } else {
          cambiarAGoogleServidor('Navegador sin reconocimiento de voz. Probando Google en servidor…');
        }
        return;
      }

      if (reconocedor) {
        try { reconocedor.abort(); } catch (_) {}
        reconocedor = null;
      }

      reconocedor = new SR();
      reconocedor.lang = 'es-CL';
      reconocedor.continuous = true;
      reconocedor.interimResults = true;

      reconocedor.onstart = () => {
        googleNavInicioOk = true;
        cancelarTimeoutGoogleNav();
        ocultarHintsVoz();
        modoServidor = false;
        motorServidorActivo = null;
        sessionStorage.removeItem('voz_modo_servidor');
        ocultarSoloTexto();
        mostrarHintGoogleNavegador();
        actualizarIndicadorVoz('google', 'Google (navegador)');
        setMicUI(true);
      };

      reconocedor.onend = () => {
        if (escuchandoActivo && reconocedor && !modoServidor && !micPausado) {
          try { reconocedor.start(); } catch (_) {}
        } else if (!escuchandoActivo && !micPausado) {
          setMicUI(false);
        }
      };

      reconocedor.onerror = (event) => {
        const err = event.error;
        if (err === 'not-allowed') {
          alert('Permite el micrófono en el candado de la barra de direcciones.');
          cerrarSesionVoz(true);
          return;
        }
        if (err === 'network') {
          cancelarTimeoutGoogleNav();
          if (reconocedor) {
            try { reconocedor.abort(); } catch (_) {}
            reconocedor = null;
          }
          if (!navigator.onLine) {
            fallbackRapidoWhisper('Sin conexión. Usando Whisper…');
          } else if (googleMarcadoComoCaido()) {
            fallbackRapidoWhisper('Google no disponible. Usando Whisper…');
          } else {
            probarGoogleServidorAntesWhisper('Sin acceso a Google en el navegador.');
          }
          return;
        }
        if (err === 'no-speech') {
          document.getElementById('mic-status').textContent = 'No se oyó voz — habla más cerca del micrófono';
        }
      };

      reconocedor.onresult = (event) => {
        let interim = '';
        let final = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const t = event.results[i][0].transcript;
          if (event.results[i].isFinal) final += t;
          else interim += t;
        }
        if (final.trim()) agregarTextoSesion(final);
        interimActual = interim.trim();
        mostrarPreviewSesion();
      };

      try {
        reconocedor.start();
        iniciarTimeoutGoogleNav();
      } catch (_) {
        if (!navigator.onLine) {
          fallbackRapidoWhisper('No se pudo iniciar Google. Usando Whisper…');
        } else if (googleMarcadoComoCaido()) {
          fallbackRapidoWhisper('Google no disponible. Usando Whisper…');
        } else {
          probarGoogleServidorAntesWhisper('No se pudo iniciar Google en el navegador.');
        }
      }
    }

    async function iniciar() {
      if (escuchandoActivo) return;
      if (vozModoActual === 'sin_servicio') {
        ocultarSoloTexto();
        indicadorVozInicial();
      }

      if (!window.isSecureContext) {
        alert(cfg.mensajeContextoInseguro || 'Abre la app desde http://localhost:8000 (no el archivo HTML directo).');
        return;
      }

      const sesionOk = await fetch('/api/me', { headers: cfg.authHeaders() });
      if (cfg.redirigirSiSesionExpirada(sesionOk) || !sesionOk.ok) return;

      escuchandoActivo = true;
      sesionVozAbierta = true;
      micPausado = false;
      modoServidor = false;
      motorServidorActivo = null;
      if (navigator.onLine) sessionStorage.removeItem('voz_modo_servidor');
      resetPreview();
      actualizarBotonesVoz();

      if (navigator.onLine && googleMarcadoComoCaido()) {
        document.getElementById('mic-status').textContent = 'Comprobando Google…';
        setMicUI(false);
        await verificarRecuperacionGoogleAsync();
      }

      if (debeUsarWhisperDirecto()) {
        document.getElementById('mic-status').textContent = 'Iniciando Whisper…';
        setMicUI(false);
        const arrancarWhisper = () => {
          if (!whisperOfflineListo()) {
            cargarEstadoVoz().then(() => {
              if (whisperOfflineListo()) {
                asegurarMicStream().then(() => cambiarAWhisper(''));
              } else {
                escuchandoActivo = false;
                sesionVozAbierta = false;
                aplicarSoloTexto(mensajeModeloWhisperPendiente());
              }
            });
            return;
          }
          asegurarMicStream().then(() => cambiarAWhisper('')).catch(() => {
            escuchandoActivo = false;
            sesionVozAbierta = false;
            alert('No se pudo acceder al micrófono.');
            actualizarBotonesVoz();
          });
        };
        arrancarWhisper();
        return;
      }

      if (navigator.onLine && simulacionGoogleNavCaida()) {
        setMicUI(false);
        iniciarConSimulacionGoogle();
        return;
      }

      const SR = window.webkitSpeechRecognition || window.SpeechRecognition;
      const intentarGoogleNav = googleProbablementeDisponible() && SR;

      if (intentarGoogleNav) {
        document.getElementById('mic-status').textContent = 'Conectando con Google…';
        setMicUI(false);
        comenzarReconocimiento();
        return;
      }

      document.getElementById('mic-status').textContent = 'Solicitando micrófono…';
      setMicUI(false);

      navigator.mediaDevices.getUserMedia({ audio: true })
        .then(stream => {
          if (!escuchandoActivo) {
            stream.getTracks().forEach(t => t.stop());
            return;
          }
          liberarMic();
          micStream = stream;
          if (!navigator.onLine) {
            fallbackRapidoWhisper('Sin conexión a internet. Usando Whisper…');
          } else if (!SR) {
            cambiarAGoogleServidor('Probando Google en servidor…');
          } else {
            comenzarReconocimiento();
          }
        })
        .catch(() => {
          escuchandoActivo = false;
          sesionVozAbierta = false;
          alert('No se pudo acceder al micrófono. Revisa los permisos del navegador.');
          document.getElementById('mic-status').textContent = 'Micrófono no disponible';
          document.getElementById('mic-status').style.color = 'var(--danger)';
          actualizarBotonesVoz();
        });
    }

    function pausarReconocimiento() {
      if (!sesionVozAbierta || micPausado) return;
      micPausado = true;
      escuchandoActivo = false;

      if (reconocedor) {
        try { reconocedor.stop(); } catch (_) {}
      }

      setMicUI(false);
      actualizarEstadoGrabacion();
    }

    async function reanudarReconocimiento() {
      if (!sesionVozAbierta || !micPausado) return;
      micPausado = false;
      escuchandoActivo = true;

      if (!micStream) {
        document.getElementById('mic-status').textContent = 'Reconectando micrófono…';
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          micStream = stream;
        } catch (_) {
          escuchandoActivo = false;
          sesionVozAbierta = false;
          micPausado = false;
          alert('No se pudo acceder al micrófono.');
          actualizarBotonesVoz();
          return;
        }
      }

      if (debeUsarWhisperDirecto() || motorServidorActivo === 'whisper') {
        motorServidorActivo = 'whisper';
        modoServidor = true;
        if (!scriptProcessor) iniciarModoServidor('whisper');
        else {
          actualizarHintsServidor('whisper');
          setMicUI(true);
        }
      } else if (modoServidor) {
        if (!scriptProcessor) iniciarModoServidor(motorServidorActivo || 'google');
        else setMicUI(true);
      } else {
        comenzarReconocimiento();
      }
    }

    function togglePausaReanudar() {
      if (micPausado) reanudarReconocimiento();
      else pausarReconocimiento();
    }

    function borrarTodoVoz() {
      cerrarSesionVoz(true);
    }

    function cerrarSesionVoz(limpiarTexto) {
      cancelarTimeoutGoogleNav();
      googleNavInicioOk = false;
      escuchandoActivo = false;
      micPausado = false;
      sesionVozAbierta = false;
      motorServidorActivo = null;
      if (reconocedor) {
        try { reconocedor.stop(); } catch (_) {}
        reconocedor = null;
      }
      liberarMic();
      modoServidor = false;
      muestrasUtterance = [];
      huboVoz = false;
      msSilencio = 0;
      transcribiendo = false;
      if (limpiarTexto) resetPreview();
      else mostrarPreviewSesion();
      document.getElementById('mic-status').textContent = 'Listo para escuchar';
      document.getElementById('mic-status').style.color = '';
      document.getElementById('mic-row')?.classList.remove('recording', 'paused', 'active');
      const hintRed = document.getElementById('mic-hint-red');
      if (hintRed) hintRed.style.display = 'none';
      ocultarHintsVoz();
      if (vozModoActual !== 'sin_servicio') indicadorVozInicial();
      actualizarBotonesVoz();
    }

    async function detener() {
      cerrarSesionVoz(true);
    }

    async function enviarVozAlChat() {
      if (escuchandoActivo && modoServidor && muestrasUtterance.length) {
        await flushUtteranceServidor(true, true);
      }
      confirmarEnvioAlChat();
      actualizarBtnEnviar();
    }


  return {
    init(options) {
      cfg = Object.assign({}, cfg, options || {});
      if (cfg.storageKey) {
        localStorage.removeItem(cfg.storageKey);
      }
      cargarEstadoVoz();
      const btnH = document.getElementById('btn-hablar');
      if (btnH && !btnH.dataset.vozBound) {
        btnH.dataset.vozBound = '1';
        btnH.addEventListener('click', (e) => { e.preventDefault(); iniciar(); });
      }
      actualizarBotonesVoz();
    },
    cerrar: () => cerrarSesionVoz(true),
    enviarAlChat: () => enviarVozAlChat(),
    borrar: () => borrarTodoVoz(),
    togglePausa: () => togglePausaReanudar(),
  };
})();
