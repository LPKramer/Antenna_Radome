"""Expressoes: regressao contra a Parameter List real do Dipolo.cst."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from antfdm.core.expr import ExprError, ParamTable, from_cst, to_cst

PARAMS_JSON = Path(__file__).resolve().parents[1] / "Dipolo" / "Model" / "Parameters.json"


def _tabela_do_projeto() -> tuple[ParamTable, list[dict]]:
    raw = json.loads(PARAMS_JSON.read_text(encoding="utf-8"))["parameters"]
    t = ParamTable()
    for p in raw:
        t.add(p["name"], from_cst(p["expr"]))
    return t, raw


@pytest.mark.skipif(not PARAMS_JSON.exists(), reason="projeto CST de referencia ausente")
def test_todos_os_parametros_batem_com_o_cst():
    """Se um valor divergir, o modelo gerado nao e a antena que o CST simulou."""
    t, raw = _tabela_do_projeto()
    valores = t.values()
    for p in raw:
        assert valores[p["name"]] == pytest.approx(float(p["value"]), rel=1e-9), p["name"]


@pytest.mark.skipif(not PARAMS_JSON.exists(), reason="projeto CST de referencia ausente")
def test_trigonometria_do_cst_e_em_radianos():
    """As funcoes trigonometricas do CST operam em radianos, nao em graus.

    Ancora uma convencao que, se estivesse errada, produziria geometria errada
    silenciosamente -- sem erro, so com a antena no lugar errado.

    Compara as duas interpretacoes de ``Cotg = (TAN(Ang/(2*pi)))^-1`` contra o
    valor que o proprio CST gravou.  Nao ha numero fixo aqui de proposito: o
    Parameters.json e um arquivo vivo, reescrito toda vez que o projeto e salvo.
    """
    import math

    t, raw = _tabela_do_projeto()
    ang = t.values()["Ang"]
    cotg_cst = float(next(p["value"] for p in raw if p["name"] == "Cotg"))

    em_radianos = 1.0 / math.tan(ang / (2 * math.pi))
    em_graus = 1.0 / math.tan(math.radians(ang / (2 * math.pi)))

    assert cotg_cst == pytest.approx(em_radianos, rel=1e-9)
    assert cotg_cst != pytest.approx(em_graus, rel=1e-3)
    assert t.values()["Cotg"] == pytest.approx(em_radianos, rel=1e-12)


def test_identificadores_sao_case_insensitive_como_no_cst():
    """O historico do Dipolo escreve PLA e radius; os parametros sao Pla e Radius."""
    t = ParamTable()
    t.add("Pla", "1")
    t.add("Bitola", "3/2")
    t.add("Radius", "3")
    assert t.evaluate("PLA+Bitola/2") == pytest.approx(1.75)
    assert t.evaluate("radius/3") == pytest.approx(1.0)


def test_nomes_que_diferem_so_na_caixa_sao_recusados():
    t = ParamTable()
    t.add("Radius", "3")
    with pytest.raises(ExprError, match="diferem so na caixa"):
        t.add("radius", "5")


def test_expressoes_derivadas_resolvem_em_ordem():
    t = ParamTable()
    t.add("c", "a + b")
    t.add("a", "2")
    t.add("b", "3")
    assert t.order().index("a") < t.order().index("c")
    assert t.values()["c"] == pytest.approx(5.0)


def test_ciclo_e_detectado_e_nomeado():
    t = ParamTable()
    t.add("a", "b + 1")
    t.add("b", "a + 1")
    with pytest.raises(ExprError, match="ciclo"):
        t.order()


def test_parametro_ausente_diz_quem_usou():
    t = ParamTable()
    t.add("a", "naoexiste * 2")
    with pytest.raises(ExprError, match="naoexiste"):
        t.values()


def test_round_trip_de_sintaxe():
    assert to_cst("x**2") == "x^2"
    assert from_cst("x^2") == "x**2"
    assert to_cst(from_cst("(TAN(Ang/(2*pi)))^-1")) == "(tan(Ang/(2*pi)))^-1"


def test_deg_e_rad_disponiveis():
    t = ParamTable()
    t.add("a", "90")
    assert t.evaluate("sin(rad(a))") == pytest.approx(1.0)
    assert t.evaluate("deg(pi)") == pytest.approx(180.0)
