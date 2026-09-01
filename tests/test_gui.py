"""Editor grafico, em modo offscreen.

O que importa aqui nao e a aparencia, e o contrato: a GUI edita o MESMO
AntennaSpec que o CLI usa, e uma expressao invalida tem que virar aviso em vez
de derrubar a janela -- durante a calibracao se digita muita coisa errada.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="editor grafico precisa do PySide6")

from PySide6 import QtCore, QtWidgets  # noqa: E402

from antfdm.gui.app import MainWindow  # noqa: E402

RECIPE = Path(__file__).resolve().parents[1] / "antfdm" / "recipes" / "dipolo_y.yaml"


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def win(app):
    w = MainWindow(str(RECIPE))
    w.resize(1200, 800)
    yield w
    w.close()


def _linha(win, nome: str) -> int:
    return next(
        r for r in range(win.params.rowCount()) if win.params.item(r, 0).text() == nome
    )


def _set_param(app, win, nome: str, expr: str) -> None:
    win.params.item(_linha(win, nome), 1).setText(expr)
    app.processEvents()


def test_abre_a_receita_e_desenha(win, app):
    assert win._spec is not None
    assert win._ws is not None
    assert win._aviso.text() == ""
    assert win.params.rowCount() == 12
    assert win.wires.topLevelItemCount() == 2
    assert len(win.canvas.scene().items()) > 0


def test_editar_parametro_recalcula_a_geometria(win, app):
    antes = win._ws.total_wire_length()
    _set_param(app, win, "Ltotal", "140")
    assert win._ws.total_wire_length() > antes
    assert win.params.item(_linha(win, "Ltotal"), 2).text() == "140"


def test_expressao_invalida_vira_aviso_e_nao_derruba(win, app):
    _set_param(app, win, "Ltotal", "naoexiste + 1")
    assert win._ws is None
    assert "naoexiste" in win._aviso.text()
    # e se recupera quando o valor volta a ser valido
    _set_param(app, win, "Ltotal", "107.44701481255")
    assert win._ws is not None
    assert win._aviso.text() == ""


def test_geometria_impossivel_e_reportada_com_numeros(win, app):
    """Filete grande demais: o aviso tem que dizer o que reduzir."""
    _set_param(app, win, "Radius", "50")
    assert "reduza o raio" in win._aviso.text() or "consomem" in win._aviso.text()


def test_editar_vertice_pelo_painel_altera_o_spec(win, app):
    """A arvore so lista; quem edita e o painel de propriedades."""
    win.wires.select("vertex", 0, 4)
    app.processEvents()
    linha = next(
        r for r in range(win.props.rowCount()) if win.props.item(r, 0).text() == "x"
    )
    win.props.item(linha, 1).setText("Ltotal/2 + 10")
    app.processEvents()
    assert win._spec.wires[0].vertices[4].x == "Ltotal/2 + 10"
    assert win._ws is not None


def test_enquadramento_ignora_a_grade(win, app):
    """fit() precisa enquadrar a antena, nao a grade que e bem maior."""
    win.canvas.fit()
    r = win.canvas._content
    assert r.width() == pytest.approx(111.2, abs=1.0)  # ~Ltotal + secao
    assert r.height() < 20.0


def test_gui_e_cli_produzem_o_mesmo_spec(win, app, tmp_path):
    """A GUI nao pode ser um formato paralelo: salva o mesmo YAML que o CLI le."""
    from antfdm.core import spec as spec_mod

    _set_param(app, win, "Gap", "12.5")
    destino = tmp_path / "editado.yaml"
    win._path = destino
    win._salvar()

    recarregado = spec_mod.load(destino)
    assert recarregado.params["Gap"]["expr"] == "12.5"
    assert recarregado.to_wireset().total_wire_length() == pytest.approx(
        win._ws.total_wire_length()
    )


def test_gerar_cst_pela_gui_escreve_a_macro(win, app, tmp_path):
    win._path = tmp_path / "spec.yaml"
    macro, blocos = win.gerar_cst()
    assert macro.exists() and blocos > 0
    texto = macro.read_text(encoding="utf-8")
    assert "AddToHistory" in texto
    # A GUI nao pode ter um caminho de emissao proprio: mesmo VBA parametrico,
    # com as coordenadas ainda em expressao (aspas dobradas pelo escape do VBA).
    assert '.X1 ""Gap/2""' in texto
    assert "5.7996" not in texto


# --------------------------------------------------------------------------
# bloquinhos na interface
# --------------------------------------------------------------------------

YAGI = RECIPE.parent / "yagi.yaml"


@pytest.fixture
def win_yagi(app):
    w = MainWindow(str(YAGI))
    w.resize(1400, 800)
    yield w
    w.close()


def test_paleta_vem_do_registro_de_blocos(win_yagi):
    """Um bloco novo em blocks/library.py precisa aparecer sem codigo de GUI."""
    from antfdm import blocks

    assert win_yagi.palette_blocos.lista.count() == len(blocks.catalog())


def test_arvore_mostra_blocos_em_fio_composto(win_yagi):
    top = win_yagi.wires.topLevelItem(0)
    assert top.childCount() == 1
    assert top.child(0).data(0, QtCore.Qt.UserRole) == ("block", 0, 0)


def test_propriedades_mostram_os_campos_do_bloco(win_yagi, app):
    win_yagi.wires.select("block", 0, 0)
    app.processEvents()
    campos = {
        win_yagi.props.item(r, 0).text(): win_yagi.props.item(r, 1).text()
        for r in range(win_yagi.props.rowCount())
    }
    assert campos["type"] == "straight"
    assert campos["len"] == "L_drv/2 - Gap/2"


def test_editar_campo_de_bloco_recalcula_a_antena(win_yagi, app):
    antes = win_yagi._ws.lengths()["drv_sup"]
    win_yagi.wires.select("block", 0, 0)
    app.processEvents()
    linha = next(
        r for r in range(win_yagi.props.rowCount())
        if win_yagi.props.item(r, 0).text() == "len"
    )
    win_yagi.props.item(linha, 1).setText("20")
    app.processEvents()
    assert win_yagi._ws.lengths()["drv_sup"] == pytest.approx(20.0)
    assert win_yagi._ws.lengths()["drv_sup"] != pytest.approx(antes)


def test_adicionar_bloco_pela_paleta(win_yagi, app):
    win_yagi.wires.select("block", 0, 0)
    app.processEvents()
    antes = len(win_yagi._spec.wires[0].blocks)
    win_yagi._add_block("bend")
    app.processEvents()
    assert len(win_yagi._spec.wires[0].blocks) == antes + 1
    assert win_yagi._spec.wires[0].blocks[1]["type"] == "bend"
    assert win_yagi._ws is not None  # o padrao do bloco precisa gerar algo valido


def test_bloco_novo_nasce_com_valores_utilizaveis(app):
    """Adicionar um bloco nao pode quebrar a antena: o padrao tem que desenhar."""
    from antfdm.gui.inspector import default_block
    from antfdm import blocks

    for tipo in blocks.catalog():
        b = default_block(tipo)
        assert b["type"] == tipo
        if tipo in ("spiral", "jump"):
            continue  # precisam ser o primeiro bloco; cobertos em test_blocks
        blocks.build_chain(
            [{"type": "straight", "len": "10"}, b], blocks.Cursor()
        )


def test_nao_da_para_misturar_blocos_num_fio_de_vertices(win, app):
    """Um fio usa vertices OU blocos; a GUI precisa recusar antes de corromper."""
    win.wires.select("vertex", 0, 0)
    app.processEvents()
    antes = len(win._spec.wires[0].vertices)
    erros = []
    win._erro = lambda t, d: erros.append(t)
    win._add_block("straight")
    assert erros and "vertices" in erros[0].lower()
    assert len(win._spec.wires[0].vertices) == antes
    assert not win._spec.wires[0].blocks


# --------------------------------------------------------------------------
# construir uma antena do zero
# --------------------------------------------------------------------------


def test_gui_abre_com_antena_valida_sem_arquivo(app):
    """Sem argumento a janela nao pode abrir vazia: tela em branco nao ensina nada."""
    w = MainWindow()
    try:
        assert w._spec is not None
        assert w._ws is not None
        assert w._ws.validate() == []
        assert w._ws.total_wire_length() > 0
    finally:
        w.close()


def test_antena_em_branco_e_um_dipolo_de_meia_onda(app):
    from antfdm.core import spec as sm

    s = sm.AntennaSpec.blank("x", 900.0)
    ws = s.to_wireset()
    meia_onda = 300000.0 / 900.0 / 2.0
    # 0.235*Lambda por braco = 0.47*Lambda no total: o encurtamento classico.
    assert ws.total_wire_length() == pytest.approx(meia_onda * 0.94, rel=0.02)
    assert ws.feed is not None


def test_antena_em_branco_reescala_por_f0(app):
    from antfdm.core import spec as sm

    a = sm.AntennaSpec.blank("a", 900.0).to_wireset().total_wire_length()
    b = sm.AntennaSpec.blank("b", 1800.0).to_wireset().total_wire_length()
    assert b == pytest.approx(a / 2.0, rel=1e-9)


def test_adicionar_fio_parasita(app):
    from antfdm.core import spec as sm

    w = MainWindow()
    try:
        antes = len(w._spec.wires)
        w._spec.wires.append(
            sm.WireSpec.model_validate(
                {
                    "name": "refletor",
                    "role": "parasitic",
                    "start": {"x": "-40", "y": "-50", "dir": "90"},
                    "blocks": [{"type": "straight", "len": "100"}],
                }
            )
        )
        w.wires.load(w._spec)
        w._refresh()
        assert len(w._spec.wires) == antes + 1
        assert w._ws is not None
        assert any(x.role == "parasitic" for x in w._ws.wires)
    finally:
        w.close()


def test_adicionar_bloco_sem_selecao_usa_o_unico_fio(app):
    """Com um fio so nao ha o que escolher; exigir clique seria burocracia."""
    from antfdm.core import spec as sm

    w = MainWindow()
    try:
        w._spec = sm.AntennaSpec.model_validate(
            {
                "name": "um_fio",
                "params": {"L": "20"},
                "feed": {"p1": ["-1", "0", "0"], "p2": ["1", "0", "0"]},
                "wires": [
                    {
                        "name": "unico",
                        "start": {"x": "1", "y": "0", "dir": "0"},
                        "blocks": [{"type": "straight", "len": "L"}],
                    }
                ],
            }
        )
        w.nova(w._spec)
        w.wires.setCurrentItem(None)
        w._add_block("bend")
        assert len(w._spec.wires[0].blocks) == 2
    finally:
        w.close()


def test_parametro_em_uso_nao_pode_ser_removido(app):
    """Remover um parametro que a geometria usa quebraria a antena em silencio."""
    w = MainWindow()
    try:
        linha = next(
            r for r in range(w.params.rowCount())
            if w.params.item(r, 0).text() == "L_braco"
        )
        w.params.setCurrentCell(linha, 0)
        erros = []
        w._erro = lambda t, d: erros.append(t)
        w._remove_param()
        assert erros and "uso" in erros[0].lower()
        assert "L_braco" in w._spec.params
        assert w._ws is not None
    finally:
        w.close()


def test_cli_new_gera_spec_que_a_gui_abre(app, tmp_path):
    """CLI e GUI produzem e consomem o mesmo formato -- nao ha dialeto de GUI."""
    from antfdm.cli import main

    destino = tmp_path / "nova.yaml"
    assert main(["new", "nova", "--freq", "868", "--out", str(destino)]) == 0
    assert destino.exists()

    w = MainWindow(str(destino))
    try:
        assert w._ws is not None
        assert w._ws.params.values()["F0"] == pytest.approx(868.0)
    finally:
        w.close()
