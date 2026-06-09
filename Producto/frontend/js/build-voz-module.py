"""Genera voz-sesion.js desde coordinador.html."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = (ROOT / "templates" / "coordinador.html").read_text(encoding="utf-8")
start = src.index("    let micStream = null;")
end = src.index("    function enviarTexto() {")
chunk = src[start:end]

chunk = chunk.replace(
    """    function enviarVoz(texto) {
      const final = texto.trim();
      if (!final || final === 'Transcribiendo...') return;
      quitarBorradorChat();
      agregarMsg(final, 'coord', 'Tú (voz → texto)');
      if (socketListo()) {
        socket.send(JSON.stringify({ tipo: 'voz', contenido: final }));
      }
      cerrarSesionVoz(true);
    }""",
    """    function enviarVoz(texto) {
      const final = texto.trim();
      if (!final || final === 'Transcribiendo...') return;
      quitarBorradorChat();
      cfg.onEnviar(final);
      cerrarSesionVoz(true);
    }""",
)

chunk = chunk.replace(
    "function actualizarBorradorChat(texto) {",
    "function actualizarBorradorChat(texto) {\n      if (cfg.sinBorradorChat) return;",
)

chunk = chunk.replace("authHeaders()", "cfg.authHeaders()")

# Quitar implementación local; usa cfg.redirigirSesionExpirada del init()
chunk = chunk.replace(
    """    function redirigirSiSesionExpirada(res) {
      if (res.status !== 401) return false;
      escuchandoActivo = false;
      sessionStorage.clear();
      alert('Tu sesión expiró. Inicia sesión de nuevo.');
      window.location.href = '/login';
      return true;
    }

""",
    "",
)
chunk = re.sub(
    r'\bredirigirSiSesionExpirada\(',
    'cfg.redirigirSiSesionExpirada(',
    chunk,
)

chunk = chunk.replace(
    "alert('Abre http://localhost:8000/coordinador (no el archivo HTML directo).');",
    "alert(cfg.mensajeContextoInseguro || 'Abre la app desde http://localhost:8000 (no el archivo HTML directo).');",
)

# Quitar auto-init al cargar script
chunk = chunk.replace(
    """    // Residuo de versión anterior: ya no persistir fallo de Google entre pestañas/días
    localStorage.removeItem(CLAVE_GOOGLE_CAIDO);
    localStorage.removeItem('voz_google_fallo_hasta');

    cargarEstadoVoz();

""",
    "",
)

# Storage key por rol
chunk = chunk.replace(
    "sessionStorage.setItem(CLAVE_GOOGLE_CAIDO, '1');",
    "sessionStorage.setItem(claveGoogle(), '1');",
)
chunk = chunk.replace(
    "return sessionStorage.getItem(CLAVE_GOOGLE_CAIDO) === '1';",
    "return sessionStorage.getItem(claveGoogle()) === '1';",
)
chunk = chunk.replace(
    "sessionStorage.removeItem(CLAVE_GOOGLE_CAIDO);",
    "sessionStorage.removeItem(claveGoogle());",
)
chunk = chunk.replace(
    "localStorage.removeItem(CLAVE_GOOGLE_CAIDO);",
    "localStorage.removeItem(claveGoogle());",
)

header = """/* SpeakingHands — módulo de voz compartido */
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

"""

footer = """
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
"""

out = header + chunk + footer
(ROOT / "js" / "voz-sesion.js").write_text(out, encoding="utf-8")
print("OK", len(out), "lines", out.count(chr(10)))
