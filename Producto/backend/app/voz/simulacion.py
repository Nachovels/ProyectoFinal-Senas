"""Simulación de fallos de Google Speech para pruebas locales.

Variables de entorno (Producto/backend/.env):

  VOZ_SIMULAR_GOOGLE_CAIDO=1
      Simula caída de Google en navegador y servidor.

  VOZ_SIMULAR_GOOGLE_NAVEGADOR=1
      El frontend omite Web Speech API (Google del navegador).

  VOZ_SIMULAR_GOOGLE_SERVIDOR=1
      transcribir_google() falla sin llamar a la API real.

Ejemplos:
  # Solo servidor caído → navegador OK, servidor → Whisper
  VOZ_SIMULAR_GOOGLE_SERVIDOR=1

  # Todo Google caído → directo a Whisper tras intentos
  VOZ_SIMULAR_GOOGLE_CAIDO=1
"""

from __future__ import annotations

import os

_TRUTHY = frozenset({"1", "true", "yes", "on", "si", "sí"})


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUTHY


def simular_google_caido_total() -> bool:
    return _env_bool("VOZ_SIMULAR_GOOGLE_CAIDO")


def simular_google_navegador_caido() -> bool:
    return simular_google_caido_total() or _env_bool("VOZ_SIMULAR_GOOGLE_NAVEGADOR")


def simular_google_servidor_caido() -> bool:
    return simular_google_caido_total() or _env_bool("VOZ_SIMULAR_GOOGLE_SERVIDOR")


def mensaje_google_servidor_simulado() -> str:
    return (
        "Simulación activa: Google Speech en servidor no disponible "
        "(VOZ_SIMULAR_GOOGLE_CAIDO o VOZ_SIMULAR_GOOGLE_SERVIDOR=1)."
    )


def info_simulacion() -> dict:
    nav = simular_google_navegador_caido()
    srv = simular_google_servidor_caido()
    return {
        "activa": nav or srv,
        "google_navegador_caido": nav,
        "google_servidor_caido": srv,
        "google_caido_total": simular_google_caido_total(),
    }
