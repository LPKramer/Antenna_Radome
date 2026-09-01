"""Testes de ponta a ponta do pipeline: spec -> VBA e spec -> solido.

O teste que sustenta o projeto e ``test_comprimento_bate_entre_python_e_build123d``:
o filete e resolvido por dois kernels independentes (core.geometry aqui, OCCT no
build123d, BlendCurve no CST), e so faz sentido confiar no STL se os tres
concordam.

O segundo mais importante e ``test_vba_usa_expressoes_e_nao_numeros``, que protege
a decisao central do projeto: se o emissor comecar a assar numeros no historico,
a Parameter List do CST para de funcionar e a calibracao final fica impossivel.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from antfdm.cad import sweep as sw
from antfdm.core import spec as spec_mod
from antfdm.cst import vba

RECIPE = Path(__file__).resolve().parents[1] / "antfdm" / "recipes" / "dipolo_y.yaml"


@pytest.fixture(scope="module")
def ws():
    return spec_mod.load(RECIPE).to_wireset()


def test_receita_carrega_sem_problemas(ws):
    assert ws.validate() == []
    assert len(ws.wires) == 2
    assert ws.feed is not None


def test_comprimento_bate_entre_python_e_build123d(ws):
    """A verificacao central: geometria analitica == geometria do kernel B-rep."""
    for wire in ws.wires:
        analitico = wire.centerline.length(ws.params)
        path = sw.path_of(wire.centerline, ws.params)
        kernel = sum(e.length for e in path.edges())
        assert kernel == pytest.approx(analitico, rel=1e-9), wire.name


def test_espelho_preserva_a_expressao(ws):
    """Espelhar negando a expressao, e nao o valor, mantem o braco parametrico."""
    esq = ws.wire("braco_esq").centerline
    assert esq.vertices[0].x == "-(Gap/2)"
    assert esq.vertices[2].x == "-cordenadaNosoldaX"
    assert esq.length(ws.params) == pytest.approx(
        ws.wire("braco_dir").centerline.length(ws.params)
    )


def test_vba_usa_expressoes_e_nao_numeros(ws):
    """Nenhuma coordenada pode sair avaliada, ou o modelo deixa de ser parametrico."""
    codigo = "\n".join(b.code for b in vba.emit(ws))
    assert '.X1 "Gap/2"' in codigo
    assert '.X2 "cordenadaNosoldaX + Cotg"' in codigo
    assert '.Radius "Radius"' in codigo
    # 5.7996... e o valor de Gap/2; se aparecer, alguem assou o numero.
    assert "5.7996" not in codigo
    assert "28.4918" not in codigo


def test_parametros_preservam_calibracao_por_padrao(ws):
    """MakeSureParameterExists deixa inalterado o que ja existe no projeto."""
    bloco = vba.emit_parameters(ws, overwrite=False).code
    assert "MakeSureParameterExists" in bloco
    assert "StoreParameterWithDescription" not in bloco

    forcado = vba.emit_parameters(ws, overwrite=True).code
    assert "StoreParameterWithDescription" in forcado


def test_vba_modela_pla_como_dieletrico_e_nao_como_metal(ws):
    """O modelo antigo usava raio 'Pla+Bitola/2' em cobre; aqui sao dois solidos."""
    blocos = {b.caption: b.code for b in vba.emit(ws)}
    cobre = blocos["antfdm: cobre braco_dir"]
    casca = blocos["antfdm: casca PLA braco_dir"]
    assert '.Radius "(Bitola)/2"' in cobre
    assert '.Material "Copper (annealed)"' in cobre
    assert '.Radius "(Bitola)/2 + (Parede)"' in casca
    assert "PLA (impresso)" in casca
    assert "Solid.Insert" in blocos["antfdm: cobre dentro do PLA (braco_dir)"]


def test_material_do_radome_usa_eps_efetivo_e_nao_o_macico(ws):
    codigo = "\n".join(b.code for b in vba.emit(ws))
    assert ws.radome.material.eps_eff == pytest.approx(2.75**0.30)
    assert '.Epsilon "1.35' in codigo
    assert '.Epsilon "2.75"' not in codigo


def test_curva_3d_e_recusada_com_mensagem_clara(ws):
    from antfdm.core.centerline import Centerline, Vertex
    from antfdm.core.wireset import Wire

    w = Wire(
        name="fora_do_plano",
        centerline=Centerline(
            name="fora_do_plano",
            vertices=[Vertex(x="0", y="0", z="0"), Vertex(x="10", y="0", z="5")],
        ),
    )
    with pytest.raises(vba.VbaError, match="planares"):
        vba.emit_curve(w)


def test_macro_renderizada_usa_addtohistory(ws):
    macro = vba.render_macro(vba.emit(ws), "teste")
    assert macro.startswith("' Gerado por antfdm")
    assert "Sub Main" in macro and "End Sub" in macro
    # AddToHistory e o que faz o modelo virar historico reconstruivel, em vez de
    # geometria desenhada uma vez so.
    assert macro.count("AddToHistory ") == len(vba.emit(ws))


def test_macro_quebra_linha_com_vbnewline_e_nao_com_barra_n(ws):
    r"""VBA nao tem escape de barra invertida.

    Um "\n" no literal viraria a barra e a letra n, e o historico chegaria ao
    CST como uma linha so -- macro invalida, e o erro so apareceria la dentro.
    """
    macro = vba.render_macro(vba.emit(ws), "teste")
    assert "vbNewLine" in macro
    assert "\\n" not in macro


def test_macro_escapa_aspas_dobrando(ws):
    """Em VBA a aspa dentro de string se escapa dobrando, nao com barra."""
    macro = vba.render_macro(vba.emit(ws), "teste")
    assert 's = s + "     .X1 ""Gap/2"""' in macro
    assert '\\"' not in macro
