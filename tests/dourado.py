"""Comparação com arquivo dourado (a saída congelada de antes).

Teste de caracterização, como no portal (coverage-hub/backend/tests):
não diz se a resposta está CERTA, diz se ela MUDOU. É o que permite
reorganizar tools.py (docs/MAPEAMENTO.md, fase F2) com prova de que as
ferramentas devolvem exatamente o mesmo.

Quando a mudança é intencional:

    python -m pytest --atualizar-dourados

e o diff dos arquivos em `tests/dourados/` entra no PR.
"""

import datetime as dt
import json
from pathlib import Path

PASTA = Path(__file__).resolve().parent / "dourados"


def _serializar(valor):
    if isinstance(valor, (dt.date, dt.datetime)):
        return valor.isoformat()
    if isinstance(valor, (set, frozenset)):
        return sorted(valor)
    return repr(valor)


def em_json(dado):
    texto = json.dumps(dado, ensure_ascii=False, indent=1, sort_keys=True, default=_serializar)
    return texto + "\n"


def conferir(nome, dado, atualizar):
    """Compara `dado` com `dourados/<nome>.json`, ou regrava se `atualizar`."""
    arquivo = PASTA / f"{nome}.json"
    texto = em_json(dado)
    if atualizar or not arquivo.exists():
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(texto, encoding="utf-8")
        if not atualizar:
            raise AssertionError(
                f"{arquivo.name} não existia e foi criado. Revise o conteúdo e rode de novo."
            )
        return
    esperado = arquivo.read_text(encoding="utf-8")
    assert texto == esperado, (
        f"A saída mudou em relação a {arquivo.name}. Se a mudança é intencional, "
        "rode `python -m pytest --atualizar-dourados` e revise o diff."
    )
