import concurrent.futures
import io
import os
import tempfile
from pathlib import Path

from app.voz.simulacion import info_simulacion, mensaje_google_servidor_simulado, simular_google_servidor_caido

_recognizer = None
_whisper_model = None
_whisper_cache_ok = None

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CACHE = _BACKEND_ROOT / "models" / "whisper"


def _idioma_whisper(idioma: str) -> str:
    if not idioma:
        return "es"
    return idioma.split("-")[0].lower()


def _whisper_instalado() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _whisper_model_name() -> str:
    return os.getenv("WHISPER_MODEL", "base").strip() or "base"


def _whisper_model_path() -> str:
    custom = os.getenv("WHISPER_MODEL_PATH", "").strip()
    if custom:
        return custom
    return _whisper_model_name()


def _whisper_cache_dir() -> str:
    custom = os.getenv("WHISPER_CACHE_DIR", "").strip()
    if custom:
        return custom
    path = _DEFAULT_CACHE
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _whisper_opciones() -> dict:
    return {
        "device": os.getenv("WHISPER_DEVICE", "cpu"),
        "compute_type": os.getenv("WHISPER_COMPUTE", "int8"),
        "download_root": _whisper_cache_dir(),
    }


def _get_recognizer():
    global _recognizer
    if _recognizer is None:
        import speech_recognition as sr
        _recognizer = sr.Recognizer()
    return _recognizer


def _crear_whisper_model(local_files_only: bool):
    from faster_whisper import WhisperModel

    opts = _whisper_opciones()
    return WhisperModel(
        _whisper_model_path(),
        device=opts["device"],
        compute_type=opts["compute_type"],
        download_root=opts["download_root"],
        local_files_only=local_files_only,
    )


def _whisper_modelo_en_cache() -> bool:
    global _whisper_cache_ok
    if _whisper_cache_ok is not None:
        return _whisper_cache_ok
    if not _whisper_instalado():
        _whisper_cache_ok = False
        return False

    custom = os.getenv("WHISPER_MODEL_PATH", "").strip()
    if custom and Path(custom).is_dir():
        _whisper_cache_ok = True
        return True

    try:
        model = _crear_whisper_model(local_files_only=True)
        del model
        _whisper_cache_ok = True
    except Exception:
        _whisper_cache_ok = False
    return _whisper_cache_ok


def _get_whisper_model():
    global _whisper_model, _whisper_cache_ok
    if _whisper_model is not None:
        return _whisper_model

    if _whisper_modelo_en_cache():
        _whisper_model = _crear_whisper_model(local_files_only=True)
    else:
        _whisper_model = _crear_whisper_model(local_files_only=False)
        _whisper_cache_ok = True
    return _whisper_model


def precargar_whisper() -> dict:
    """Descarga y carga el modelo Whisper (requiere internet la primera vez)."""
    if not _whisper_instalado():
        return {"ok": False, "error": "faster-whisper no instalado"}

    global _whisper_model, _whisper_cache_ok
    try:
        _whisper_model = None
        _whisper_cache_ok = None
        model = _get_whisper_model()
        _whisper_model = model
        return {
            "ok": True,
            "modelo": _whisper_model_name(),
            "cache": _whisper_cache_dir(),
            "en_cache": True,
        }
    except Exception as exc:
        _whisper_cache_ok = False
        return {"ok": False, "error": str(exc)}


def estado_voz() -> dict:
    preferir = os.getenv("VOZ_PREFERIR", "auto").strip().lower()
    whisper_lib = _whisper_instalado()
    whisper_listo = _whisper_modelo_en_cache() if whisper_lib else False
    google_lib = True
    try:
        import speech_recognition  # noqa: F401
    except ImportError:
        google_lib = False

    motores = []
    if whisper_lib:
        motores.append({
            "motor": "whisper",
            "modo": "offline",
            "disponible": whisper_listo,
            "requiere_descarga": not whisper_listo,
        })
    if google_lib:
        google_sim_caido = simular_google_servidor_caido()
        motores.append({
            "motor": "google",
            "modo": "online",
            "disponible": not google_sim_caido,
            "requiere_red": True,
            "simulado_caido": google_sim_caido,
        })

    if google_lib and preferir != "whisper" and not simular_google_servidor_caido():
        modo_servidor = "online"
    elif whisper_listo:
        modo_servidor = "offline"
    else:
        modo_servidor = "sin_servicio" if not google_lib else "online"

    sim = info_simulacion()

    return {
        "servidor": {
            "disponible": whisper_listo or (google_lib and not simular_google_servidor_caido()),
            "modo": modo_servidor,
            "motores": motores,
            "preferencia": preferir if preferir in ("auto", "whisper", "google") else "auto",
            "whisper_listo": whisper_listo,
            "whisper_cache": _whisper_cache_dir(),
            "whisper_modelo": _whisper_model_name(),
        },
        "navegador": {
            "disponible": not sim["google_navegador_caido"],
            "modo": "online",
            "requiere_red": True,
            "simulado_caido": sim["google_navegador_caido"],
        },
        "simulacion": sim,
    }


def transcribir_whisper(wav_bytes: bytes, idioma: str = "es-CL") -> str:
    if len(wav_bytes) < 1000:
        return ""

    if not _whisper_modelo_en_cache():
        raise RuntimeError(
            "El modelo Whisper no está descargado. Conecta WiFi, reinicia el servidor "
            "o ejecuta: python -m app.voz.transcripcion"
        )

    model = _get_whisper_model()
    lang = _idioma_whisper(idioma)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes)
        path = tmp.name

    try:
        segments, _info = model.transcribe(path, language=lang, beam_size=5, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def transcribir_google(wav_bytes: bytes, idioma: str = "es-CL") -> str:
    import speech_recognition as sr

    if simular_google_servidor_caido():
        raise RuntimeError(mensaje_google_servidor_simulado())

    if len(wav_bytes) < 1000:
        return ""

    recognizer = _get_recognizer()
    with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
        audio = recognizer.record(source)

    api_key = os.getenv("GOOGLE_SPEECH_API_KEY", "").strip()
    timeout = float(os.getenv("GOOGLE_SPEECH_TIMEOUT", "4"))

    def _llamar_google():
        if api_key:
            return recognizer.recognize_google(audio, language=idioma, key=api_key)
        return recognizer.recognize_google(audio, language=idioma)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_llamar_google)
            return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        raise RuntimeError("Google Speech: tiempo de espera agotado") from exc
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as exc:
        raise RuntimeError(f"No se pudo contactar el servicio de Google Speech: {exc}") from exc


def transcribir_wav(wav_bytes: bytes, idioma: str = "es-CL", preferir: str | None = None) -> dict:
    preferir = (preferir or os.getenv("VOZ_PREFERIR", "auto")).strip().lower()
    errores = []

    if preferir == "google":
        orden = ["google", "whisper"]
    elif preferir == "whisper":
        orden = ["whisper", "google"]
    else:
        # auto: Google primero (WiFi), Whisper como respaldo
        orden = ["google", "whisper"]

    for motor in orden:
        if motor == "whisper":
            if not _whisper_instalado():
                continue
            try:
                texto = transcribir_whisper(wav_bytes, idioma)
                return {"texto": texto, "motor": "whisper", "modo": "offline"}
            except Exception as exc:
                msg = str(exc)
                if "getaddrinfo failed" in msg or "internet connection" in msg.lower():
                    msg = (
                        "Modelo Whisper sin descargar. Con WiFi, reinicia el servidor "
                        "o ejecuta: python -m app.voz.transcripcion"
                    )
                errores.append(f"Whisper: {msg}")
        elif motor == "google":
            try:
                texto = transcribir_google(wav_bytes, idioma)
                return {"texto": texto, "motor": "google", "modo": "online"}
            except ModuleNotFoundError:
                errores.append("Google: falta SpeechRecognition")
            except RuntimeError as exc:
                errores.append(str(exc))
            except Exception as exc:
                errores.append(f"Google: {exc}")

    detalle = "; ".join(errores) if errores else "Ningún motor de voz disponible"
    raise RuntimeError(detalle)


if __name__ == "__main__":
    print("Descargando modelo Whisper (solo necesario una vez con internet)...")
    resultado = precargar_whisper()
    if resultado.get("ok"):
        print(f"Listo: {resultado['modelo']} en {resultado['cache']}")
    else:
        print(f"Error: {resultado.get('error')}")
        raise SystemExit(1)
