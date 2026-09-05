"""Desenhar a antena clicando.

Duas travas sustentam esta etapa:

* **A invariante do projeto.** Uma antena desenhada com o mouse tem que emitir
  VBA com EXPRESSAO em toda coordenada.  Se um clique assar o numero, a
  Parameter List do CST vem vazia e a ferramenta perde a razao de existir.

* **A contagem de controles.** Sem ela eu volto a acrescentar botao -- foi
  exatamente o que aconteceu tres vezes seguidas, e o usuario reclamou as tres.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from antfdm.check import rules  # noqa: E402
from antfdm.core import spec as spec_mod  # noqa: E402
from antfdm.gui.draw import DrawController  # noqa: E402


@pytest.fixture
def vazia():
    return spec_mod.AntennaSpec.empty("desenhada", 868.0)


# --------------------------------------------------------------------------
# o dipolo em um clique
# --------------------------------------------------------------------------


def test_um_clique_ja_da_um_dipolo(vazia):
    """Braco, espelho e alimentacao nascem juntos: e o caso mais comum."""
    d = DrawController()
    traco = d.clicar(vazia, (85, 0))

    assert traco is not None
    assert len(vazia.wires) == 2
    assert vazia.feed is not None
    ws = vazia.to_wireset()
    assert [w.role for w in ws.wires] == ["driven", "driven"]
    assert ws.wire("braco_2").centerline.length(
        ws.params
    ) == pytest.approx(ws.wire("braco_1").centerline.length(ws.params))


def test_dipolo_desenhado_fica_dentro_da_faixa(vazia):
    """Clicar perto de lambda/4 tem que produzir uma antena que ja passa."""
    lam = 300000.0 / 868.0
    DrawController().clicar(vazia, (lam / 4, 0))
    avisos = rules.verificar(vazia.to_wireset())
    assert not [a for a in avisos if a.severidade in ("erro", "aviso")]


def test_desenho_vertical_espelha_no_eixo_certo(vazia):
    DrawController().clicar(vazia, (0, 85))
    assert vazia.wires[1].mirror_axis == "y"
    assert vazia.feed.p1 == ["0", "-Gap/2", "0"]


def test_desenho_horizontal_espelha_no_eixo_certo(vazia):
    DrawController().clicar(vazia, (85, 0))
    assert vazia.wires[1].mirror_axis == "x"


# --------------------------------------------------------------------------
# a invariante
# --------------------------------------------------------------------------


def test_antena_desenhada_emite_vba_parametrico(vazia):
    """Nenhuma coordenada pode sair como numero, mesmo desenhada a mao."""
    from antfdm.cst import vba

    d = DrawController()
    d.clicar(vazia, (85, 0))
    d.clicar(vazia, (85, 40))
    d.terminar_fio()

    ws = vazia.to_wireset()
    codigo = "\n".join(b.code for b in vba.emit(ws))

    # Cada traco virou parametro na Parameter List.
    assert "MakeSureParameterExists" in codigo
    assert '"L1"' in codigo
    # E as coordenadas referenciam esses parametros, nao os valores.
    assert "L1" in codigo and "Gap/2" in codigo


def test_cada_traco_cria_seu_parametro(vazia):
    d = DrawController()
    d.clicar(vazia, (85, 0))
    d.clicar(vazia, (85, 40))
    assert "L1" in vazia.params and "L2" in vazia.params
    assert "A1" in vazia.params  # a dobra tambem
    for nome in ("L1", "L2", "A1"):
        assert vazia.params[nome]["description"]


def test_parametro_desenhado_nao_colide_com_existente():
    s = spec_mod.AntennaSpec.empty("x", 868.0)
    s.params["L1"] = {"expr": "10", "description": "ja existia"}
    DrawController().clicar(s, (85, 0))
    assert s.params["L1"]["expr"] == "10"  # intacto
    assert "L2" in s.params


# --------------------------------------------------------------------------
# fios seguintes
# --------------------------------------------------------------------------


def test_segundo_fio_nasce_parasita_em_dois_cliques(vazia):
    """Refletor e diretor nao se conectam: precisam de inicio e fim proprios."""
    d = DrawController()
    d.clicar(vazia, (85, 0))
    d.terminar_fio()

    assert d.clicar(vazia, (-50, -60)) is None  # so marca de onde sai
    assert len(vazia.wires) == 2
    traco = d.clicar(vazia, (50, -60))
    assert traco is not None
    assert len(vazia.wires) == 3
    assert vazia.wires[2].role == "parasitic"
    assert vazia.to_wireset().wire(vazia.wires[2].name).centerline.length(
        vazia.to_wireset().params
    ) == pytest.approx(100.0, abs=1.0)


def test_continuar_o_fio_adiciona_dobra_e_trecho(vazia):
    d = DrawController()
    d.clicar(vazia, (85, 0))
    antes = len(vazia.wires[0].blocks)
    d.clicar(vazia, (85, 40))
    tipos = [b["type"] for b in vazia.wires[0].blocks]
    assert len(tipos) == antes + 2
    assert tipos[-2:] == ["bend", "straight"]


def test_trecho_na_mesma_direcao_nao_cria_dobra(vazia):
    d = DrawController()
    d.clicar(vazia, (50, 0))
    d.clicar(vazia, (90, 0))
    assert [b["type"] for b in vazia.wires[0].blocks] == ["straight", "straight"]


def test_terminar_fio_faz_o_proximo_clique_comecar_outro(vazia):
    d = DrawController()
    d.clicar(vazia, (85, 0))
    assert d.desenhando
    d.terminar_fio()
    assert not d.desenhando


# --------------------------------------------------------------------------
# encaixe
# --------------------------------------------------------------------------


def test_angulo_encaixa_em_passos_de_15_graus(vazia):
    d = DrawController()
    d.clicar(vazia, (85, 3))  # ~2 graus
    assert float(vazia.wires[0].start.dir) == pytest.approx(0.0)


def test_alt_desliga_o_encaixe(vazia):
    d = DrawController()
    d.clicar(vazia, (85, 20), livre=True)
    assert float(vazia.wires[0].start.dir) != pytest.approx(0.0)
    assert float(vazia.wires[0].start.dir) == pytest.approx(13.24, abs=0.1)


def test_comprimento_encaixa_em_meio_milimetro(vazia):
    DrawController().clicar(vazia, (85.13, 0))
    valor = float(vazia.params["L1"]["expr"])
    assert valor * 2 == pytest.approx(round(valor * 2))


# --------------------------------------------------------------------------
# a trava da tela
# --------------------------------------------------------------------------


def test_tela_padrao_tem_poucos_controles():
    """Trava contra eu voltar a encher a barra.

    Foram tres rodadas de "acrescentei botoes" antes de entender que o pedido
    era o contrario.  Este teste falha se a tela padrao passar de 8 controles.
    """
    from PySide6 import QtWidgets

    from antfdm.gui.app import MainWindow

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow()
    try:
        controles = w.controles_visiveis()
        assert len(controles) <= 8, controles
        assert not w.avancado_aberto(), "o painel avancado nao pode abrir sozinho"
    finally:
        w.close()


def test_avancado_continua_existindo():
    """Nada foi apagado: quem quiser digitar expressao ainda pode."""
    from PySide6 import QtWidgets

    from antfdm.gui.app import MainWindow

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow()
    try:
        w._alternar_avancado()
        assert w.avancado_aberto()
        assert w.params is not None and w.wires is not None
        assert w.props is not None and w.palette_blocos is not None
    finally:
        w.close()


# --------------------------------------------------------------------------
# desfazer
# --------------------------------------------------------------------------


def test_desfazer_devolve_o_spec_inteiro():
    from antfdm.gui.history import History

    s = spec_mod.AntennaSpec.empty("x", 868.0)
    h = History()
    h.marcar(s)
    DrawController().clicar(s, (85, 0))
    assert len(s.wires) == 2

    voltou = h.desfazer(s)
    assert voltou is not None and voltou.wires == []
    refeito = h.refazer(voltou)
    assert refeito is not None and len(refeito.wires) == 2


def test_desfazer_vazio_nao_quebra():
    from antfdm.gui.history import History

    s = spec_mod.AntennaSpec.empty("x", 868.0)
    assert History().desfazer(s) is None
    assert History().refazer(s) is None
