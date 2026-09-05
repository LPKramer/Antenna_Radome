"""Gestos: clicar na ponta, arrastar aresta, soltar bloco.

Tres travas sustentam esta etapa:

* **A invariante do projeto.** Uma antena montada com gestos tem que emitir VBA
  com EXPRESSAO em toda coordenada.  Se um gesto assar o numero, a Parameter
  List do CST vem vazia e a ferramenta perde a razao de existir.

* **Clique no vazio nao cria nada** quando ja existe antena.  Era metade do "o
  desenho nao faz o que espero": um clique fora do lugar virava um elemento
  parasita novo, sem aviso.

* **A contagem de controles e de ajustes da peca.** Sem elas eu volto a
  acrescentar -- foi o que aconteceu em tres rodadas seguidas.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from antfdm.core import spec as spec_mod  # noqa: E402
from antfdm.gui import draw, interact  # noqa: E402


@pytest.fixture
def vazia():
    return spec_mod.AntennaSpec.empty("desenhada", 868.0)


@pytest.fixture
def dipolo(vazia):
    draw.primeiro_braco(vazia, (85, 0))
    return vazia


# --------------------------------------------------------------------------
# o dipolo em um clique
# --------------------------------------------------------------------------


def test_um_clique_ja_da_um_dipolo(vazia):
    """Braco, espelho e alimentacao nascem juntos: e o caso mais comum."""
    traco = draw.primeiro_braco(vazia, (85, 0))
    assert traco is not None
    assert len(vazia.wires) == 2 and vazia.feed is not None
    ws = vazia.to_wireset()
    assert [w.role for w in ws.wires] == ["driven", "driven"]
    assert ws.wire("braco_2").centerline.length(ws.params) == pytest.approx(
        ws.wire("braco_1").centerline.length(ws.params)
    )


def test_desenho_vertical_espelha_no_eixo_certo(vazia):
    draw.primeiro_braco(vazia, (0, 85))
    assert vazia.wires[1].mirror_axis == "y"
    assert vazia.feed.p1 == ["0", "-Gap/2", "0"]


# --------------------------------------------------------------------------
# o que esta sob o cursor
# --------------------------------------------------------------------------


def test_ponta_ganha_do_trecho_no_empate(dipolo):
    """Com o cursor na ponta, o alvo tem que ser a ponta e nao a aresta."""
    ws = dipolo.to_wireset()
    alvo = interact.localizar(ws, (85, 0), 6.0, spec_wires=dipolo.wires)
    assert alvo is not None and alvo.tipo == "ponta"


def test_meio_do_fio_e_aresta(dipolo):
    ws = dipolo.to_wireset()
    alvo = interact.localizar(ws, (45, 0), 6.0, spec_wires=dipolo.wires)
    assert alvo is not None and alvo.tipo == "aresta"


def test_longe_de_tudo_nao_ha_alvo(dipolo):
    ws = dipolo.to_wireset()
    assert interact.localizar(ws, (200, 200), 6.0, spec_wires=dipolo.wires) is None


def test_fio_espelhado_e_marcado_como_nao_editavel(dipolo):
    ws = dipolo.to_wireset()
    alvo = interact.localizar(ws, (-85, 0), 6.0, spec_wires=dipolo.wires)
    assert alvo is not None and alvo.wire == "braco_2"
    assert not alvo.editavel


def test_descricao_fala_em_linguagem_de_antena(dipolo):
    ws = dipolo.to_wireset()
    texto = interact.descrever(
        interact.localizar(ws, (45, 0), 6.0, spec_wires=dipolo.wires), ws
    )
    assert "mm" in texto and "arraste" in texto


# --------------------------------------------------------------------------
# soltar bloco: o gesto principal
# --------------------------------------------------------------------------


def test_bloco_solto_perto_da_ponta_encaixa_no_fio(dipolo):
    ws = dipolo.to_wireset()
    alvo = interact.ponta_mais_proxima(ws, (87, 2), 25.0, spec_wires=dipolo.wires)
    assert alvo is not None and alvo.wire == "braco_1"

    antes = len(dipolo.wires)
    traco = draw.anexar_bloco(dipolo, alvo.wire, "meander")
    assert traco is not None
    assert len(dipolo.wires) == antes  # anexou, nao criou fio novo
    assert [b["type"] for b in dipolo.wires[0].blocks] == ["straight", "meander"]


def test_bloco_solto_longe_vira_elemento_solto(dipolo):
    ws = dipolo.to_wireset()
    assert interact.ponta_mais_proxima(ws, (-60, -90), 25.0,
                                       spec_wires=dipolo.wires) is None

    antes = len(dipolo.wires)
    traco = draw.novo_fio_com_bloco(dipolo, (-60, -90), "straight")
    assert traco is not None
    assert len(dipolo.wires) == antes + 1
    assert dipolo.wires[-1].role == "parasitic"


def test_bloco_que_nao_anda_sozinho_ganha_uma_reta(dipolo):
    """'dobra' so vira geometria depois de algo para dobrar."""
    draw.novo_fio_com_bloco(dipolo, (60, -90), "bend")
    assert [b["type"] for b in dipolo.wires[-1].blocks] == ["straight", "bend"]
    assert dipolo.to_wireset().validate() == []


def test_encaixe_ignora_fio_espelhado(dipolo):
    """A ponta do braco espelhado nao recebe bloco: quem manda e o original."""
    ws = dipolo.to_wireset()
    alvo = interact.ponta_mais_proxima(ws, (-85, 0), 25.0, spec_wires=dipolo.wires)
    assert alvo is None or alvo.wire != "braco_2"


def test_anexar_em_fio_espelhado_e_recusado(dipolo):
    assert draw.anexar_bloco(dipolo, "braco_2", "meander") is None


# --------------------------------------------------------------------------
# crescer e esticar
# --------------------------------------------------------------------------


def test_crescer_da_ponta_adiciona_dobra_e_trecho(dipolo):
    antes = len(dipolo.wires[0].blocks)
    draw.crescer(dipolo, "braco_1", (85, 40))
    tipos = [b["type"] for b in dipolo.wires[0].blocks]
    assert len(tipos) == antes + 2
    assert tipos[-2:] == ["bend", "straight"]


def test_crescer_na_mesma_direcao_nao_cria_dobra(vazia):
    draw.primeiro_braco(vazia, (50, 0))
    draw.crescer(vazia, "braco_1", (90, 0))
    assert [b["type"] for b in vazia.wires[0].blocks] == ["straight", "straight"]


def test_elemento_solto_nasce_centrado(vazia):
    draw.primeiro_braco(vazia, (85, 0))
    traco = draw.novo_elemento(vazia, (-50, 0), 110.0, 90.0)
    ws = vazia.to_wireset()
    verts = ws.wire(traco.wire).centerline.points(ws.params)
    meio = (verts[0][:2] + verts[-1][:2]) / 2.0
    assert meio[0] == pytest.approx(-50.0, abs=0.6)
    assert meio[1] == pytest.approx(0.0, abs=0.6)


# --------------------------------------------------------------------------
# a invariante
# --------------------------------------------------------------------------


def test_antena_montada_com_gestos_emite_vba_parametrico(vazia):
    from antfdm.cst import vba

    draw.primeiro_braco(vazia, (85, 0))
    draw.crescer(vazia, "braco_1", (85, 40))
    draw.anexar_bloco(vazia, "braco_1", "bend")
    draw.novo_fio_com_bloco(vazia, (-60, -90), "straight")

    ws = vazia.to_wireset()
    codigo = "\n".join(b.code for b in vba.emit(ws))
    assert "MakeSureParameterExists" in codigo
    assert '"L1"' in codigo and "Gap/2" in codigo


def test_cada_traco_cria_seu_parametro(vazia):
    draw.primeiro_braco(vazia, (85, 0))
    draw.crescer(vazia, "braco_1", (85, 40))
    assert {"L1", "L2", "A1"} <= set(vazia.params)
    for nome in ("L1", "L2", "A1"):
        assert vazia.params[nome]["description"]


def test_parametro_novo_nao_colide_com_existente(vazia):
    vazia.params["L1"] = {"expr": "10", "description": "ja existia"}
    draw.primeiro_braco(vazia, (85, 0))
    assert vazia.params["L1"]["expr"] == "10"
    assert "L2" in vazia.params


# --------------------------------------------------------------------------
# encaixe de valores
# --------------------------------------------------------------------------


def test_angulo_encaixa_em_passos_de_15_graus(vazia):
    draw.primeiro_braco(vazia, (85, 3))  # ~2 graus
    assert float(vazia.wires[0].start.dir) == pytest.approx(0.0)


def test_alt_desliga_o_encaixe(vazia):
    draw.primeiro_braco(vazia, (85, 20), livre=True)
    assert float(vazia.wires[0].start.dir) == pytest.approx(13.24, abs=0.1)


def test_comprimento_encaixa_em_meio_milimetro(vazia):
    draw.primeiro_braco(vazia, (85.13, 0))
    valor = float(vazia.params["L1"]["expr"])
    assert valor * 2 == pytest.approx(round(valor * 2))


# --------------------------------------------------------------------------
# as travas
# --------------------------------------------------------------------------


def _janela():
    from PySide6 import QtWidgets

    from antfdm.gui.app import MainWindow

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return MainWindow()


def test_tela_padrao_tem_poucos_controles():
    """Falha se a barra voltar a encher. Foram tres rodadas de 'acrescentei'."""
    w = _janela()
    try:
        controles = w.controles_visiveis()
        assert len(controles) <= 8, controles
        assert not w.avancado_aberto()
    finally:
        w.close()


def test_paleta_fica_na_tela_e_nao_no_avancado():
    """O gesto principal e arrastar bloco; a paleta nao pode estar escondida."""
    w = _janela()
    try:
        assert w.palette_blocos.isVisibleTo(w)
        assert w.palette_blocos.lista.count() > 0
    finally:
        w.close()


def test_paleta_mostra_nomes_em_portugues():
    w = _janela()
    try:
        nomes = {w.palette_blocos.lista.item(i).text()
                 for i in range(w.palette_blocos.lista.count())}
        assert {"reta", "dobra", "serpentina", "espiral"} <= nomes
        assert "straight" not in nomes and "vee" not in nomes
    finally:
        w.close()


def test_clique_no_vazio_nao_cria_com_antena_existente():
    """Metade do 'nao faz o que espero': clique fora criava parasita sem aviso."""
    w = _janela()
    try:
        w.canvas.cliqueEm.emit(85.0, 0.0, False)  # cria o dipolo
        antes = len(w._spec.wires)
        w.canvas.cliqueEm.emit(-70.0, 90.0, False)  # bem longe de tudo
        assert len(w._spec.wires) == antes
    finally:
        w.close()


def test_peca_tem_poucos_ajustes():
    """Mesma ideia: a peca so segura o fio, nao precisa de onze parametros."""
    import dataclasses

    from antfdm.cad.clamshell import ClamshellOptions

    campos = [f.name for f in dataclasses.fields(ClamshellOptions)]
    assert len(campos) <= 4, campos


def test_avancado_continua_existindo():
    """Nada foi apagado: quem quiser digitar expressao ainda pode."""
    w = _janela()
    try:
        w._alternar_avancado()
        assert w.avancado_aberto()
        assert w.params is not None and w.wires is not None and w.props is not None
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
    draw.primeiro_braco(s, (85, 0))
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


# --------------------------------------------------------------------------
# a linha de comando tambem constroi a peca
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_cli_print_gera_a_peca(tmp_path):
    """Faltava este teste, e por isso o CLI passou quebrado pela suite: eu tinha
    apagado opcoes da peca sem tirar as flags que as passavam."""
    from antfdm.cli import main

    spec_mod.dump(
        spec_mod.from_recipe("dipolo_y", "t"), tmp_path / "t.yaml"
    )
    rc = main(["print", str(tmp_path / "t.yaml"), "--out", str(tmp_path / "out"),
               "--no-step"])
    assert rc == 0
    assert (tmp_path / "out" / "t_base.stl").exists()
    assert (tmp_path / "out" / "t_topo.stl").exists()
    card = (tmp_path / "out" / "t_print_card.txt").read_text(encoding="utf-8")
    assert "parafusos" in card
    assert "pinos" not in card and "coax" not in card  # sumiram da peca


# --------------------------------------------------------------------------
# arrasto ao vivo: o coracao do pedido
# --------------------------------------------------------------------------


def test_arrasto_move_durante_o_movimento():
    """A antena tem que acompanhar o cursor, nao pular ao soltar.

    Este teste falharia na versao anterior: o arrasto so aplicava no
    mouseRelease, porque o redesenho custava 161 ms e eu desliguei o ao vivo em
    vez de consertar a lentidao.
    """
    w = _janela()
    try:
        w.canvas.cliqueEm.emit(85.0, 0.0, False)  # dipolo
        comprimentos = []
        w.canvas.arrastoIniciado.emit(85.0, 0.0, False)
        for x in (95.0, 105.0, 115.0):
            w.canvas.arrastoMovido.emit(x, 0.0, False)
            comprimentos.append(
                w._ws.wire("braco_1").centerline.length(w._ws.params)
            )
        w.canvas.arrastoSolto.emit(115.0, 0.0, False)

        assert len(set(comprimentos)) == 3, comprimentos
        assert comprimentos == sorted(comprimentos)
    finally:
        w.close()


def test_arrasto_no_vazio_desenha_um_fio_num_gesto():
    """Sem selecionar nada e sem dialogo: apertar, arrastar, soltar."""
    w = _janela()
    try:
        assert w._spec.wires == []
        w.canvas.arrastoIniciado.emit(0.0, 0.0, False)
        w.canvas.arrastoMovido.emit(50.0, 0.0, False)
        w.canvas.arrastoSolto.emit(85.0, 0.0, False)

        assert len(w._spec.wires) == 2  # braco e espelho
        assert w._spec.feed is not None
        ws = w._ws
        assert ws.wire("braco_1").centerline.length(ws.params) == pytest.approx(
            83.0, abs=1.0  # 85 menos Gap/2
        )
    finally:
        w.close()


def test_arrasto_com_antena_existente_cria_elemento_solto():
    w = _janela()
    try:
        w.canvas.cliqueEm.emit(85.0, 0.0, False)
        antes = len(w._spec.wires)
        w.canvas.arrastoIniciado.emit(-50.0, -80.0, False)
        w.canvas.arrastoMovido.emit(0.0, -80.0, False)
        w.canvas.arrastoSolto.emit(50.0, -80.0, False)
        assert len(w._spec.wires) == antes + 1
        assert w._spec.wires[-1].role == "parasitic"
    finally:
        w.close()


def test_arrasto_nao_acumula_edicoes_a_cada_quadro():
    """Cada quadro parte do estado do inicio do arrasto, nao do quadro anterior.

    Sem isso o fio cresceria a cada pixel de movimento.
    """
    w = _janela()
    try:
        w.canvas.cliqueEm.emit(85.0, 0.0, False)
        w.canvas.arrastoIniciado.emit(85.0, 0.0, False)
        for _ in range(10):
            w.canvas.arrastoMovido.emit(100.0, 0.0, False)  # sempre o MESMO ponto
        w.canvas.arrastoSolto.emit(100.0, 0.0, False)
        assert w._ws.wire("braco_1").centerline.length(
            w._ws.params
        ) == pytest.approx(98.0, abs=1.0)
    finally:
        w.close()


def test_arrastar_ponta_mantem_o_parametro():
    """Arrastar edita o PARAMETRO; a geometria nunca vira numero solto."""
    w = _janela()
    try:
        w.canvas.cliqueEm.emit(85.0, 0.0, False)
        w.canvas.arrastoIniciado.emit(85.0, 0.0, False)
        w.canvas.arrastoMovido.emit(110.0, 0.0, False)
        w.canvas.arrastoSolto.emit(110.0, 0.0, False)

        campo = w._spec.wires[0].blocks[0]["len"]
        assert campo in w._spec.params, f"campo virou literal: {campo!r}"

        from antfdm.cst import vba

        codigo = "\n".join(b.code for b in vba.emit(w._ws))
        assert "MakeSureParameterExists" in codigo
    finally:
        w.close()


def test_desfazer_volta_o_arrasto_inteiro():
    """Um arrasto e uma acao so, por mais quadros que ele tenha tido."""
    w = _janela()
    try:
        w.canvas.cliqueEm.emit(85.0, 0.0, False)
        antes = w._ws.wire("braco_1").centerline.length(w._ws.params)
        w.canvas.arrastoIniciado.emit(85.0, 0.0, False)
        for x in (95.0, 105.0, 115.0):
            w.canvas.arrastoMovido.emit(x, 0.0, False)
        w.canvas.arrastoSolto.emit(115.0, 0.0, False)

        w._desfazer()
        assert w._ws.wire("braco_1").centerline.length(
            w._ws.params
        ) == pytest.approx(antes)
    finally:
        w.close()


def test_sucesso_nao_abre_dialogo():
    """So erro interrompe. Sucesso vira uma linha no rodape."""
    import inspect

    from antfdm.gui import app as app_mod

    fonte = inspect.getsource(app_mod)
    assert "def _info(" not in fonte, "o dialogo de sucesso voltou"
