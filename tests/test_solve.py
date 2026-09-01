"""Inversao de posicao arrastada para edicao de parametro.

O teste que sustenta a ideia e ``test_forma_da_expressao_e_preservada``: se
arrastar transformasse ``0.235*Lambda`` em ``95``, a antena pararia de reescalar
com F0 no primeiro arrasto -- e o vinculo com a frequencia, que e a razao de
existir dos parametros, se perderia sem aviso.
"""

from __future__ import annotations

import pytest

from antfdm.core.expr import ParamTable
from antfdm.core.solve import (
    Edit,
    adjust_expression,
    apply_edit,
    format_number,
    promote_to_param,
    solve_field,
)


@pytest.fixture
def params() -> ParamTable:
    t = ParamTable()
    t.add("F0", "868")
    t.add("Lambda", "300000/F0")
    t.add("L_braco", "0.235*Lambda")
    t.add("Gap", "4")
    t.add("Offset", "Gap/2 + 10")
    t.add("Radius", "2")
    return t


def _revalida(base: ParamTable, nome: str, nova: str) -> float:
    """Reconstroi a tabela com a expressao nova e devolve o valor resultante."""
    t = ParamTable()
    for n in base.order():
        t.add(n, nova if n == nome else base.params[n].expr)
    return t.values()[nome]


# --------------------------------------------------------------------------
# preservacao da forma
# --------------------------------------------------------------------------


def test_forma_da_expressao_e_preservada(params):
    """Coeficiente muda, estrutura fica: a antena segue reescalando com F0."""
    atual = params.values()["L_braco"]
    nova = adjust_expression("0.235*Lambda", atual, 95.0)
    assert "Lambda" in nova
    assert "0.235" not in nova
    assert _revalida(params, "L_braco", nova) == pytest.approx(95.0, rel=1e-9)


def test_parcela_constante_e_ajustada_em_vez_do_todo(params):
    """Em Gap/2 + 10 quem se mexe e o 10 -- o Gap nao esta sendo arrastado."""
    atual = params.values()["Offset"]
    nova = adjust_expression("Gap/2 + 10", atual, 14.5)
    assert "Gap/2" in nova
    assert _revalida(params, "Offset", nova) == pytest.approx(14.5, rel=1e-9)


def test_literal_vira_o_numero_novo():
    assert adjust_expression("42.5", 42.5, 50.0) == "50"
    assert adjust_expression("4", 4.0, 6.0) == "6"


def test_expressao_sem_numero_e_escalada(params):
    """Sem coeficiente nem constante onde mexer, escala o conjunto.

    Avalia a expressao resultante, e nao redefine Lambda com ela -- isso criaria
    a auto-referencia ``Lambda = 1.15*Lambda``, que e um ciclo.
    """
    nova = adjust_expression("Lambda", params.values()["Lambda"], 400.0)
    assert "Lambda" in nova
    assert params.evaluate(nova) == pytest.approx(400.0, rel=1e-9)


def test_valor_atual_zero_nao_divide_por_zero(params):
    nova = adjust_expression("Gap - Gap", 0.0, 5.0)
    t = ParamTable()
    t.add("Gap", "4")
    assert t.evaluate(nova) == pytest.approx(5.0, rel=1e-9)


def test_numeros_saem_curtos_mas_exatos():
    """A forma mais curta que ainda reproduz o valor.

    O contrato e o round-trip, nao um numero fixo de casas: cortar cedo demais
    faz a antena nao cair onde foi arrastada, e o erro aparece calado.
    """
    assert format_number(50.0) == "50"
    assert format_number(0.235) == "0.235"  # nao vira 0.23500000000000001
    assert "0000000" not in format_number(0.1 + 0.2)
    for v in (1 / 3, 100 / 345.6221198, 0.2748666666666667, 1e-7, 12345.6789):
        assert float(format_number(v)) == pytest.approx(v, rel=1e-12)


# --------------------------------------------------------------------------
# solve_field
# --------------------------------------------------------------------------


def test_campo_com_nome_puro_ajusta_aquele_parametro(params):
    e = solve_field("L_braco", 95.0, params)
    assert e.kind == "param" and e.param == "L_braco"
    assert _revalida(params, "L_braco", e.new_expr) == pytest.approx(95.0, rel=1e-9)


def test_campo_composto_com_um_parametro_e_invertido(params):
    """L_braco/2 tem so um parametro livre: da para resolver sozinho."""
    e = solve_field("L_braco/2", 50.0, params)
    assert e.kind == "param" and e.param == "L_braco"
    assert _revalida(params, "L_braco", e.new_expr) == pytest.approx(100.0, rel=1e-9)


def test_campo_com_varios_parametros_pergunta_qual(params):
    e = solve_field("L_braco/2 - Gap/2", 40.0, params)
    assert e.kind == "ambiguous"
    assert e.candidates == ["Gap", "L_braco"]
    assert not e.ok


def test_ambiguidade_resolvida_pela_escolha_do_usuario(params):
    e = solve_field("L_braco/2 - Gap/2", 40.0, params, prefer="L_braco")
    assert e.kind == "param" and e.param == "L_braco"
    # L_braco/2 - 2 = 40  =>  L_braco = 84
    assert _revalida(params, "L_braco", e.new_expr) == pytest.approx(84.0, rel=1e-9)


def test_escolha_fora_da_expressao_e_recusada(params):
    e = solve_field("L_braco", 95.0, params, prefer="Radius")
    assert e.kind == "impossible"
    assert "Radius" in e.reason


def test_campo_literal_avisa_que_perde_a_calibracao(params):
    e = solve_field("42.5", 50.0, params)
    assert e.kind == "literal" and e.new_expr == "50"
    assert "parametro" in e.reason  # sugere promover


def test_campo_vazio_nao_quebra(params):
    assert solve_field("", 10.0, params).kind == "impossible"


def test_round_trip_de_arrasto(params):
    """Resolver e reavaliar tem que cair exatamente no alvo, nao perto dele."""
    for campo, alvo in [
        ("L_braco", 77.7),
        ("L_braco/2", 33.3),
        ("Offset", 21.0),
        ("Gap", 2.5),
    ]:
        e = solve_field(campo, alvo, params)
        assert e.kind == "param", campo
        t = ParamTable()
        for n in params.order():
            t.add(n, e.new_expr if n == e.param else params.params[n].expr)
        assert t.evaluate(campo) == pytest.approx(alvo, rel=1e-9), campo


# --------------------------------------------------------------------------
# aplicacao no spec
# --------------------------------------------------------------------------


def test_aplicar_edicao_de_parametro_move_o_espelho():
    """O braco espelhado acompanha: e o acoplamento ficando visivel."""
    from antfdm.core import spec as sm

    s = sm.AntennaSpec.blank("x", 868.0)
    ws = s.to_wireset()
    antes_dir = ws.wire("braco_dir").centerline.length(ws.params)
    antes_esq = ws.wire("braco_esq").centerline.length(ws.params)
    assert antes_dir == pytest.approx(antes_esq)

    e = solve_field("L_braco", antes_dir * 1.2, ws.params)
    assert apply_edit(s, e)

    depois = s.to_wireset()
    assert depois.wire("braco_dir").centerline.length(depois.params) == pytest.approx(
        antes_dir * 1.2, rel=1e-9
    )
    assert depois.wire("braco_esq").centerline.length(depois.params) == pytest.approx(
        antes_dir * 1.2, rel=1e-9
    )


def test_arrastar_preserva_o_vinculo_com_a_frequencia():
    """Depois de arrastar, mudar F0 ainda tem que reescalar a antena."""
    from antfdm.core import spec as sm

    s = sm.AntennaSpec.blank("x", 868.0)
    ws = s.to_wireset()
    apply_edit(s, solve_field("L_braco", 95.0, ws.params))

    antes = s.to_wireset().total_wire_length()
    s.params["F0"]["expr"] = "1736"  # o dobro
    depois = s.to_wireset().total_wire_length()

    # O Gap e absoluto, entao a escala nao e exatamente 1/2; mas tem que encolher.
    assert depois < antes * 0.6


def test_edicao_literal_grava_no_campo_do_bloco():
    from antfdm.core import spec as sm

    s = sm.AntennaSpec.model_validate(
        {
            "name": "t",
            "params": {"Gap": "4"},
            "feed": {"p1": ["-2", "0", "0"], "p2": ["2", "0", "0"]},
            "wires": [
                {
                    "name": "w",
                    "start": {"x": "2", "y": "0", "dir": "0"},
                    "blocks": [{"type": "straight", "len": "30"}],
                }
            ],
        }
    )
    e = solve_field("30", 45.0, s.to_wireset().params)
    assert apply_edit(s, e, wire=0, block=0, field_name="len")
    assert s.wires[0].blocks[0]["len"] == "45"
    assert s.to_wireset().total_wire_length() == pytest.approx(45.0)


def test_edicao_ambigua_nao_e_aplicada(params):
    from antfdm.core import spec as sm

    s = sm.AntennaSpec.blank("x")
    assert not apply_edit(s, Edit(kind="ambiguous", candidates=["a", "b"]))


def test_promover_literal_a_parametro():
    from antfdm.core import spec as sm

    s = sm.AntennaSpec.blank("x")
    promote_to_param(s, "L1", "45", "trecho desenhado")
    assert s.params["L1"]["expr"] == "45"
    assert s.to_wireset().params.values()["L1"] == pytest.approx(45.0)


# --------------------------------------------------------------------------
# procedencia dos vertices
# --------------------------------------------------------------------------


def test_chain_registra_de_qual_bloco_veio_cada_vertice():
    """Sem procedencia nao ha como saber que campo editar ao arrastar."""
    from antfdm.blocks import Cursor, build_chain_traced

    c = build_chain_traced(
        [
            {"type": "straight", "len": "A"},
            {"type": "bend", "angle": "45"},
            {"type": "straight", "len": "B"},
        ],
        Cursor(),
    )
    assert len(c.origins) == len(c.vertices)
    assert c.origins == [-1, 0, 2]  # -1 = ponto de partida; bend nao gera vertice


def test_procedencia_sobrevive_a_blocos_que_limpam_a_cadeia():
    from antfdm.blocks import Cursor, build_chain_traced

    c = build_chain_traced(
        [{"type": "spiral", "turns": "1", "r0": "3", "r1": "20", "per_turn": "8"}],
        Cursor(),
    )
    assert len(c.origins) == len(c.vertices)
    assert set(c.origins) == {0}
