"""Bloquinhos componiveis.

O teste que sustenta a ideia e ``test_blocos_e_vertices_dao_a_mesma_antena``:
os blocos precisam ser acucar sintatico sobre a linha de centro, nao um caminho
paralelo com regras proprias.  Se as duas formas divergirem, passam a existir
duas geometrias possiveis para a mesma antena.

O segundo e ``test_cursor_nao_deixa_trigonometria_a_toa``: o cursor e simbolico
para o modelo continuar parametrico no CST, mas expressao inchada atrapalha
quem vai calibrar lendo a Parameter List.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from antfdm import blocks
from antfdm.blocks import BlockError, Cursor, build_chain
from antfdm.blocks.cursor import add, delta, scale
from antfdm.core import spec as spec_mod
from antfdm.core.expr import ParamTable, simplify

RECIPES = Path(__file__).resolve().parents[1] / "antfdm" / "recipes"


# --------------------------------------------------------------------------
# equivalencia com os vertices explicitos
# --------------------------------------------------------------------------


def test_blocos_e_vertices_dao_a_mesma_antena():
    a = spec_mod.load(RECIPES / "dipolo_y.yaml").to_wireset()
    b = spec_mod.load(RECIPES / "dipolo_y_blocos.yaml").to_wireset()

    for nome in ("braco_dir", "braco_esq"):
        pa = a.wire(nome).centerline.points(a.params)
        pb = b.wire(nome).centerline.points(b.params)
        assert pa.shape == pb.shape
        assert np.abs(pa - pb).max() < 1e-9, nome
        assert a.wire(nome).centerline.length(a.params) == pytest.approx(
            b.wire(nome).centerline.length(b.params), rel=1e-12
        )


def test_blocos_preservam_os_filetes():
    b = spec_mod.load(RECIPES / "dipolo_y_blocos.yaml").to_wireset()
    fillets = [v.fillet for v in b.wire("braco_dir").centerline.vertices]
    assert fillets == [None, "Radius", "Radius", "Radius", None]


# --------------------------------------------------------------------------
# cursor simbolico
# --------------------------------------------------------------------------


def test_cursor_anda_em_expressao_e_nao_em_numero():
    c = Cursor(x="Gap/2", y="0", heading="0").advance("Sec_inical")
    assert c.x == "Gap/2 + Sec_inical"
    assert c.y == "0"


def test_cursor_nao_deixa_trigonometria_a_toa():
    """Rumo nos eixos resolve o cosseno na hora, em vez de emitir cos(rad(0))."""
    for rumo, esperado in (("0", ("L", "0")), ("90", ("0", "L")), ("180", ("-L", "0"))):
        assert delta("L", rumo) == esperado


def test_rumo_parametrico_emite_trigonometria_de_verdade():
    """Angulo como parametro TEM que virar trig: e o que deixa girar no CST."""
    dx, dy = delta("L", "AnguloYperna")
    assert "cos(rad(AnguloYperna))" in dx
    assert "sin(rad(AnguloYperna))" in dy


def test_soma_e_escala_ficam_legiveis():
    assert add("Gap/2", "0") == "Gap/2"
    assert add("0", "Sec_inical") == "Sec_inical"
    assert add("a", "-b") == "a - b"
    assert add("2", "3") == "5"
    assert scale("Lambda", 1) == "Lambda"
    assert scale("Lambda", -1) == "-Lambda"
    assert scale("a + b", -1) == "-(a + b)"
    assert scale("qualquer", 0) == "0"


def test_simplificacao_reduz_sem_mudar_o_valor():
    t = ParamTable()
    for n, v in (("Gap", "11.6"), ("Sec", "14.5"), ("Cotg", "5.8")):
        t.add(n, v)
    bruta = "Gap/2 + Sec + Cotg - Gap/2 - Cotg"
    reduzida = simplify(bruta)
    assert len(reduzida) < len(bruta)
    assert t.evaluate(reduzida) == pytest.approx(t.evaluate(bruta), rel=1e-12)


def test_simplificacao_nunca_piora():
    """Se o sympy nao ajudar, a expressao original fica -- legibilidade importa."""
    assert simplify("Gap/2") == "Gap/2"
    assert simplify("Ltotal") == "Ltotal"
    assert simplify("nao ( eh ( expressao") == "nao ( eh ( expressao"


# --------------------------------------------------------------------------
# erros com mensagem util
# --------------------------------------------------------------------------


def test_bloco_desconhecido_lista_os_disponiveis():
    with pytest.raises(BlockError, match="straight"):
        build_chain([{"type": "nao_existe"}], Cursor())


def test_campo_desconhecido_lista_os_aceitos():
    with pytest.raises(BlockError, match="len"):
        build_chain([{"type": "straight", "comprimento": "10"}], Cursor())


def test_campo_obrigatorio_ausente_e_nomeado():
    with pytest.raises(BlockError, match="len"):
        build_chain([{"type": "straight"}], Cursor())


def test_meander_recusa_numero_de_dentes_parametrico():
    """Numero de dentes muda topologia; o Parametric Update nao cria vertices."""
    with pytest.raises(BlockError, match="topologia|inteiro"):
        build_chain(
            [{"type": "meander", "n": "N_dentes", "pitch": "5", "height": "8"}],
            Cursor(),
        )


def test_jump_no_meio_do_fio_e_recusado():
    """Andar sem desenhar no meio deixaria a linha de centro descontinua."""
    with pytest.raises(BlockError, match="descontinu|primeiro traco"):
        build_chain(
            [{"type": "straight", "len": "10"}, {"type": "jump", "len": "5"}], Cursor()
        )


def test_spiral_precisa_ser_o_primeiro_bloco():
    with pytest.raises(BlockError, match="primeiro bloco"):
        build_chain(
            [
                {"type": "straight", "len": "10"},
                {"type": "spiral", "turns": "2", "r0": "3", "r1": "30"},
            ],
            Cursor(),
        )


def test_cadeia_vazia_e_recusada():
    with pytest.raises(BlockError, match="nao produziu geometria"):
        build_chain([], Cursor())


def test_spec_recusa_duas_fontes_de_geometria():
    with pytest.raises(Exception, match="UMA forma"):
        spec_mod.AntennaSpec.model_validate(
            {
                "name": "x",
                "wires": [
                    {
                        "name": "w",
                        "vertices": [{"x": "0"}, {"x": "10"}],
                        "blocks": [{"type": "straight", "len": "10"}],
                    }
                ],
            }
        )


# --------------------------------------------------------------------------
# geometria dos blocos
# --------------------------------------------------------------------------


def test_meander_alonga_o_fio_sem_alongar_a_antena():
    """E para isso que a serpentina existe: mais fio no mesmo comprimento."""
    t = ParamTable()
    t.add("P", "6")
    t.add("H", "7")
    reta = build_chain([{"type": "straight", "len": "24"}], Cursor())
    serp = build_chain(
        [{"type": "meander", "n": "4", "pitch": "6", "height": "7"}], Cursor()
    )
    from antfdm.core.centerline import Centerline

    c_reta = Centerline(name="r", vertices=reta).length(t)
    c_serp = Centerline(name="s", vertices=serp).length(t)
    assert c_serp > c_reta
    # Mesmo avanco em X: a serpentina ocupa a mesma janela.
    assert serp[-1].x == reta[-1].x or t.evaluate(serp[-1].x) == pytest.approx(24.0)


def test_arc_aproxima_o_comprimento_do_arco_verdadeiro():
    from antfdm.core.centerline import Centerline

    t = ParamTable()
    t.add("R", "20")
    verts = build_chain(
        [{"type": "arc", "radius": "R", "angle": "90", "n": "36"}], Cursor()
    )
    comprimento = Centerline(name="a", vertices=verts).length(t)
    exato = 20 * np.pi / 2
    assert comprimento == pytest.approx(exato, rel=1e-3)


def test_spiral_comeca_no_raio_interno_e_termina_no_externo():
    t = ParamTable()
    t.add("R0", "3")
    t.add("R1", "40")
    verts = build_chain(
        [{"type": "spiral", "turns": "2", "r0": "R0", "r1": "R1", "per_turn": "24"}],
        Cursor(),
    )
    r_ini = np.hypot(t.evaluate(verts[0].x), t.evaluate(verts[0].y))
    r_fim = np.hypot(t.evaluate(verts[-1].x), t.evaluate(verts[-1].y))
    assert r_ini == pytest.approx(3.0, rel=1e-9)
    assert r_fim == pytest.approx(40.0, rel=1e-9)


# --------------------------------------------------------------------------
# as receitas do catalogo
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "receita", ["dipolo_y", "dipolo_y_blocos", "yagi", "meander", "espiral_cp"]
)
def test_receita_do_catalogo_produz_antena_valida(receita):
    ws = spec_mod.load(RECIPES / f"{receita}.yaml").to_wireset()
    assert ws.validate() == []
    assert ws.total_wire_length() > 0
    for w in ws.wires:
        w.centerline.resolve(ws.params)


@pytest.mark.parametrize(
    "receita", ["dipolo_y", "dipolo_y_blocos", "yagi", "meander", "espiral_cp"]
)
def test_receita_do_catalogo_emite_vba_parametrico(receita):
    from antfdm.cst import vba

    ws = spec_mod.load(RECIPES / f"{receita}.yaml").to_wireset()
    codigo = "\n".join(b.code for b in vba.emit(ws))
    assert "MakeSureParameterExists" in codigo
    assert "Solid.Insert" in codigo


def test_yagi_inteira_reescala_por_um_parametro():
    """Toda dimensao e fracao de Lambda, entao mudar F0 reescala a antena.

    E o que a composicao por blocos da de graca e um catalogo de templates nao
    daria: nao ha nenhum numero absoluto para reajustar a mao.
    """
    s = spec_mod.load(RECIPES / "yagi.yaml")
    base = s.to_wireset()
    antes = base.lengths()

    s.params["F0"]["expr"] = "2600"  # o dobro da frequencia
    depois = s.to_wireset().lengths()

    for nome in antes:
        if nome.startswith("drv"):
            continue  # o Gap e absoluto, entao o braco alimentado nao escala puro
        assert depois[nome] == pytest.approx(antes[nome] / 2.0, rel=1e-9), nome


def test_yagi_declara_boom_para_nao_sair_em_pedacos():
    """Elementos parasitas nao se tocam: sem boom a peca sairia solta."""
    ws = spec_mod.load(RECIPES / "yagi.yaml").to_wireset()
    assert ws.radome.boom is not None
    assert len([w for w in ws.wires if w.role == "parasitic"]) == 3


def test_catalogo_de_blocos_esta_documentado():
    """A paleta da GUI le daqui, entao todo bloco precisa de resumo e campos."""
    for tipo, resumo, campos in blocks.describe():
        assert resumo, f"bloco {tipo} sem docstring"
        assert campos, f"bloco {tipo} sem campos"
