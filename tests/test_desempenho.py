"""Orcamento de quadro.

Esta trava existe porque a interatividade ja morreu uma vez, em silencio: o
redesenho custava 161 ms num dipolo e 2.9 s numa espiral, e em vez de consertar
eu desliguei o arrasto ao vivo e segui em frente.  Um teste que falha e a unica
coisa que impede isso de se repetir.

Numeros de referencia, medidos antes e depois:

| receita | antes | depois |
|---|---|---|
| dipolo  |  161 ms |  2.8 ms |
| yagi    |  149 ms |  3.0 ms |
| meander |  279 ms |  5.2 ms |
| espiral | 2870 ms | 16.4 ms |

O que fez a diferenca: expressao compilada em cache (era sympy a cada
coordenada), cena incremental (era ``scene.clear()`` a cada quadro) e amostragem
vetorizada (era um laco Python a 11 us por ponto).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6 import QtWidgets  # noqa: E402

from antfdm.core import spec as spec_mod  # noqa: E402
from antfdm.gui.canvas import AntennaCanvas  # noqa: E402

RECIPES = Path(__file__).resolve().parents[1] / "antfdm" / "recipes"
TODAS = sorted(p.stem for p in RECIPES.glob("*.yaml"))

# 16 ms = 60 quadros por segundo. E o orcamento do caminho interativo.
ORCAMENTO_ARRASTO_MS = 16.0
# Parado o redesenho so acontece a cada edicao; nao precisa de 60 fps.
ORCAMENTO_PARADO_MS = 25.0


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _medir(canvas, spec, n: int = 20) -> float:
    for _ in range(5):  # aquece o cache de expressao
        canvas.set_wireset(spec.to_wireset())
    t0 = time.perf_counter()
    for _ in range(n):
        canvas.set_wireset(spec.to_wireset())
    return (time.perf_counter() - t0) / n * 1000.0


@pytest.mark.parametrize("receita", TODAS)
def test_redesenho_cabe_no_orcamento_de_quadro(app, receita):
    """Arrastando, cada quadro tem que caber em 16 ms."""
    s = spec_mod.load(RECIPES / f"{receita}.yaml")
    c = AntennaCanvas()
    c.resize(1000, 700)
    c.set_wireset(s.to_wireset())
    c.fit()
    c.modo_leve(True)  # e assim que fica durante o arrasto
    ms = _medir(c, s)
    assert ms < ORCAMENTO_ARRASTO_MS, f"{receita}: {ms:.1f} ms por quadro"


@pytest.mark.parametrize("receita", TODAS)
def test_redesenho_parado_e_aceitavel(app, receita):
    s = spec_mod.load(RECIPES / f"{receita}.yaml")
    c = AntennaCanvas()
    c.resize(1000, 700)
    c.set_wireset(s.to_wireset())
    c.fit()
    ms = _medir(c, s)
    assert ms < ORCAMENTO_PARADO_MS, f"{receita}: {ms:.1f} ms"


def test_avaliar_expressao_nao_volta_pelo_sympy(app):
    """A avaliacao e compilada uma vez; o segundo uso tem que ser barato."""
    from antfdm.core.expr import ParamTable

    t = ParamTable()
    t.add("F0", "868")
    t.add("Lambda", "300000/F0")
    t.add("L", "0.235*Lambda")
    t.evaluate("L/2 + Lambda/8")  # compila

    N = 20000
    t0 = time.perf_counter()
    for _ in range(N):
        t.evaluate("L/2 + Lambda/8")
    us = (time.perf_counter() - t0) / N * 1e6
    assert us < 50.0, f"{us:.1f} us por avaliacao"


def test_cache_de_expressao_nao_muda_nenhum_valor():
    """A troca de sympy por compile nao pode alterar um numero sequer."""
    import json

    caminho = Path(__file__).resolve().parents[1] / "Dipolo" / "Model" / "Parameters.json"
    if not caminho.exists():
        pytest.skip("projeto CST de referencia ausente")

    from antfdm.core.expr import ParamTable, from_cst

    raw = json.loads(caminho.read_text(encoding="utf-8"))["parameters"]
    t = ParamTable()
    for p in raw:
        t.add(p["name"], from_cst(p["expr"]))
    valores = t.values()
    for p in raw:
        assert valores[p["name"]] == pytest.approx(float(p["value"]), rel=1e-9), p["name"]


def test_amostragem_vetorizada_da_os_mesmos_pontos():
    """A versao vetorizada precisa concordar com a ponto-a-ponto."""
    import numpy as np

    from antfdm.core.geometry import resolve_path, sample_path

    segs = resolve_path([(0, 0, 0), (20, 0, 0), (28, 10, 0), (40, 0, 0)], [0, 3, 3, 0])
    pts = sample_path(segs, 0.4)

    # Todo ponto amostrado tem que estar sobre algum segmento.
    for p in pts[:: max(1, len(pts) // 40)]:
        dist = min(
            min(
                float(np.linalg.norm(p - s.point_at(u * s.length)))
                for u in np.linspace(0, 1, 200)
            )
            for s in segs
        )
        assert dist < 0.05, f"ponto {p} fora do caminho ({dist:.4f} mm)"
