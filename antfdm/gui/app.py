"""Janela principal do editor.

A GUI edita o mesmo AntennaSpec que o CLI consome, e salva o mesmo YAML.  Nada
do que se faz aqui fica preso na interface: tudo continua scriptavel, e um spec
editado na mao abre aqui sem conversao.

A barra de ferramentas segue a ordem do fluxo real -- criar, montar, gerar --
porque a ordem das acoes E a documentacao para quem abre pela primeira vez.

Geracao de STL leva alguns segundos por causa dos booleanos do OCCT, entao roda
num worker: travar a janela nesse tempo passaria a impressao de que pendurou.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import spec as spec_mod
from ..core.spec import AntennaSpec
from ..core.wireset import WireSet
from .canvas import AntennaCanvas
from .dialogs import FeedDialog, NewAntennaDialog, NewParamDialog, NewWireDialog
from .inspector import (
    BlockPalette,
    ItemProperties,
    ParamTable,
    WireTree,
    default_block,
    set_param,
)

AJUDA = (
    "<b>Para montar uma antena do zero:</b> &nbsp; "
    "<b>1.</b> Nova &nbsp;&rarr;&nbsp; "
    "<b>2.</b> ajuste F0 e os comprimentos na tabela de Parametros &nbsp;&rarr;&nbsp; "
    "<b>3.</b> selecione um fio e use a paleta de Bloquinhos (direita) para "
    "dobrar, serpentear ou curvar &nbsp;&rarr;&nbsp; "
    "<b>4.</b> + Fio para refletores e diretores &nbsp;&rarr;&nbsp; "
    "<b>5.</b> Gerar CST, calibrar la, Sync, Gerar STL."
)


class _Job(QtCore.QRunnable):
    """Tarefa pesada fora da thread da interface."""

    class Sinais(QtCore.QObject):
        done = QtCore.Signal(str)
        failed = QtCore.Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn
        self.sinais = self.Sinais()

    @QtCore.Slot()
    def run(self) -> None:
        try:
            self.sinais.done.emit(self._fn())
        except Exception as exc:
            self.sinais.failed.emit(f"{exc}\n\n{traceback.format_exc(limit=3)}")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, path: str | None = None):
        super().__init__()
        self.setWindowTitle("antfdm")
        self.resize(1500, 900)
        self._path: Path | None = None
        self._spec: AntennaSpec | None = None
        self._ws: WireSet | None = None
        self._pool = QtCore.QThreadPool.globalInstance()
        self._busy = 0

        self.canvas = AntennaCanvas()
        self.params = ParamTable()
        self.wires = WireTree()
        self.props = ItemProperties()
        self.palette_blocos = BlockPalette()

        esquerda = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        esquerda.addWidget(
            _painel(
                "Parametros",
                self.params,
                [("+", self._novo_param, "Cria um parametro novo"),
                 ("−", self._remove_param, "Remove o parametro selecionado")],
            )
        )
        esquerda.addWidget(_painel("Fios, blocos e vertices", self.wires))
        esquerda.addWidget(_painel("Propriedades do item selecionado", self.props))
        esquerda.setSizes([340, 300, 220])

        self.ajuda = QtWidgets.QLabel(AJUDA)
        self.ajuda.setWordWrap(True)
        self.ajuda.setStyleSheet(
            "background:#2a2d33; color:#c8ccd4; padding:7px 10px;"
            "border-left:3px solid #d98a4f;"
        )
        fechar = QtWidgets.QToolButton()
        fechar.setText("✕")
        fechar.setAutoRaise(True)
        fechar.setToolTip("Esconder esta ajuda")
        banner = QtWidgets.QWidget()
        bl = QtWidgets.QHBoxLayout(banner)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.ajuda, 1)
        bl.addWidget(fechar, 0, QtCore.Qt.AlignTop)
        fechar.clicked.connect(banner.hide)

        centro = QtWidgets.QWidget()
        cl = QtWidgets.QVBoxLayout(centro)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        cl.addWidget(banner)
        cl.addWidget(self.canvas, 1)

        split = QtWidgets.QSplitter()
        split.addWidget(esquerda)
        split.addWidget(centro)
        split.addWidget(_painel("Bloquinhos", self.palette_blocos))
        split.setSizes([460, 780, 230])
        self.setCentralWidget(split)

        self._build_toolbar()
        self.status = self.statusBar()
        self._aviso = QtWidgets.QLabel("")
        self._aviso.setStyleSheet("color:#e05252;")
        self.status.addPermanentWidget(self._aviso)

        self.params.changed.connect(self._refresh)
        self.wires.changed.connect(self._on_wires_changed)
        self.wires.picked.connect(self._on_picked)
        self.props.changed.connect(self._on_wires_changed)
        self.palette_blocos.add_requested.connect(self._add_block)
        self.canvas.vertexPicked.connect(self.wires.select_vertex)

        if path:
            self.open(path)
        else:
            self.nova(spec_mod.AntennaSpec.blank())

    # ------------------------------------------------------------------
    def _build_toolbar(self) -> None:
        tb = self.addToolBar("principal")
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        tb.setMovable(False)

        def act(texto, slot, atalho=None, dica=""):
            a = QtGui.QAction(texto, self)
            a.triggered.connect(slot)
            if atalho:
                a.setShortcut(atalho)
                dica = f"{dica}  ({atalho})" if dica else atalho
            if dica:
                a.setToolTip(dica)
            tb.addAction(a)
            return a

        act("Nova", self._nova_antena, "Ctrl+N", "Cria uma antena do zero")
        act("Abrir", self._abrir, "Ctrl+O")
        act("Salvar", self._salvar, "Ctrl+S")
        tb.addSeparator()
        act("+ Fio", self._novo_fio, "Ctrl+W",
            "Adiciona um fio -- use para refletor, diretor ou segundo braco")
        act("Alimentacao", self._editar_feed, None, "Onde fica a porta discreta")
        tb.addSeparator()
        act("Ajustar", self.canvas.fit, "Ctrl+0", "Enquadra a antena inteira")

        self._chk_radome = QtWidgets.QCheckBox("Radome")
        self._chk_radome.setChecked(True)
        self._chk_radome.toggled.connect(self.canvas.set_show_radome)
        tb.addWidget(self._chk_radome)

        self._chk_vert = QtWidgets.QCheckBox("Vertices")
        self._chk_vert.setChecked(True)
        self._chk_vert.toggled.connect(self.canvas.set_show_vertices)
        tb.addWidget(self._chk_vert)

        tb.addSeparator()
        act("Gerar CST", self._gerar_cst, None, "Macro VBA parametrica para o CST")
        act("Gerar STL", self._gerar_stl, None, "As duas metades do radome + print card")
        act("Sync do CST", self._sync, None,
            "Traz para ca os parametros que voce calibrou no CST")

    # ------------------------------------------------------------------
    def nova(self, spec: AntennaSpec, path: Path | None = None) -> None:
        self._spec = spec
        self._path = path
        self.setWindowTitle(f"antfdm - {path.name if path else spec.name + ' (nao salva)'}")
        self.wires.load(self._spec)
        self.props.show_item(self._spec, None)
        self._refresh(fit=True)

    def open(self, path: str | Path) -> None:
        try:
            spec = spec_mod.load(path)
        except Exception as exc:
            self._erro("Nao consegui abrir", str(exc))
            return
        self.nova(spec, Path(path))

    def _nova_antena(self) -> None:
        dlg = NewAntennaDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        r = dlg.resultado()
        try:
            if r.receita is None:
                spec = spec_mod.AntennaSpec.blank(r.nome, r.f0_mhz)
            else:
                spec = spec_mod.from_recipe(r.receita, r.nome)
        except Exception as exc:
            self._erro("Nao consegui criar", str(exc))
            return
        self.nova(spec)
        self.status.showMessage(
            "Antena criada. Ajuste os parametros e use a paleta de bloquinhos.", 8000
        )

    # ------------------------------------------------------------------
    def _novo_fio(self) -> None:
        if self._spec is None:
            return
        existentes = [w.name for w in self._spec.wires]
        dlg = NewWireDialog(existentes, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        r = dlg.resultado()
        if r.nome in existentes:
            self._erro("Nome repetido", f"Ja existe um fio chamado {r.nome!r}.")
            return

        dados = {"name": r.nome, "role": r.papel}
        if r.espelho_de:
            dados |= {"mirror_of": r.espelho_de, "mirror_axis": r.espelho_eixo}
        else:
            dados |= {
                "start": {"x": r.x, "y": r.y, "dir": r.direcao},
                "blocks": [default_block(r.primeiro_bloco or "straight")],
            }
        try:
            novo = spec_mod.WireSpec.model_validate(dados)
        except Exception as exc:
            self._erro("Fio invalido", str(exc))
            return
        self._spec.wires.append(novo)
        self.wires.load(self._spec, keep=("wire", len(self._spec.wires) - 1, -1))
        self._refresh()

    def _editar_feed(self) -> None:
        if self._spec is None:
            return
        dlg = FeedDialog(self._spec.feed, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        p1, p2, z = dlg.resultado()
        try:
            self._spec.feed = spec_mod.FeedSpec.model_validate(
                {"p1": p1, "p2": p2, "impedance": z}
            )
        except Exception as exc:
            self._erro("Alimentacao invalida", str(exc))
            return
        self._refresh()

    def _novo_param(self) -> None:
        if self._spec is None:
            return
        dlg = NewParamDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        nome, expr, desc = dlg.resultado()
        if not nome:
            return
        if any(n.lower() == nome.lower() for n in self._spec.params):
            self._erro(
                "Nome ja usado",
                f"Ja existe um parametro {nome!r}. O CST nao distingue maiusculas, "
                "entao dois nomes que so mudam de caixa seriam o mesmo parametro.",
            )
            return
        set_param(self._spec, nome, expr, desc)
        self._refresh()

    def _remove_param(self) -> None:
        if self._spec is None:
            return
        linha = self.params.currentRow()
        if linha < 0:
            self._erro("Nenhum parametro selecionado",
                       "Clique na linha do parametro que quer remover.")
            return
        nome = self.params.item(linha, 0).text()
        antes = dict(self._spec.params)  # para devolver na posicao original
        del self._spec.params[nome]

        # Precisa avaliar a GEOMETRIA, e nao so os parametros: um nome usado
        # apenas dentro de um bloco nao aparece na tabela de dependencias, e a
        # remocao passaria batida para so quebrar na hora de gerar.
        problema = ""
        try:
            ws = self._spec.to_wireset()
            problemas = ws.validate()
            if problemas:
                problema = problemas[0]
        except Exception as exc:
            problema = str(exc)

        if problema:
            self._spec.params.clear()
            self._spec.params.update(antes)
            self._erro("Parametro em uso", f"{nome!r} nao pode sair: {problema}")
        self._refresh()

    # ------------------------------------------------------------------
    def _on_picked(self, kind: str, wi: int, ii: int) -> None:
        self.props.show_item(self._spec, (kind, wi, ii))

    def _on_wires_changed(self) -> None:
        """Editar bloco muda a arvore inteira, entao recarrega mantendo o foco."""
        tag = self.wires.current_tag()
        self.wires.load(self._spec, keep=tag)
        self._refresh()

    def _add_block(self, tipo: str) -> None:
        if self._spec is None:
            return
        tag = self.wires.current_tag()
        if tag is None and len(self._spec.wires) == 1:
            tag = ("wire", 0, -1)  # com um fio so, nao ha o que escolher
        if tag is None:
            self._erro(
                "Nenhum fio selecionado",
                "Clique num fio (ou num bloco dele) na arvore do meio, a esquerda, "
                "e depois adicione o bloco.",
            )
            return
        _, wi, ii = tag
        alvo = self._spec.wires[wi]
        if alvo.mirror_of:
            self._erro(
                "Fio espelhado",
                f"{alvo.name!r} e espelho de {alvo.mirror_of!r} e acompanha o "
                "original automaticamente. Edite o original.",
            )
            return
        if alvo.vertices:
            self._erro(
                "Fio por vertices",
                f"{alvo.name!r} foi definido por vertices explicitos. "
                "Um fio usa vertices OU blocos, nao os dois.",
            )
            return
        onde = ii + 1 if tag[0] == "block" else len(alvo.blocks)
        alvo.blocks.insert(onde, default_block(tipo))
        self.wires.load(self._spec, keep=("block", wi, onde))
        self.props.show_item(self._spec, ("block", wi, onde))
        self._refresh()

    # ------------------------------------------------------------------
    def _refresh(self, fit: bool = False) -> None:
        """Reavalia o spec e redesenha. Chamado a cada edicao."""
        if self._spec is None:
            return
        aviso = ""
        try:
            self._ws = self._spec.to_wireset()
            valores = self._ws.params.values()
        except Exception as exc:
            self._ws = None
            valores = {}
            aviso = str(exc)

        self.params.load(self._spec, valores)
        erro = self.canvas.set_wireset(self._ws, keep_view=not fit)
        if fit:
            self.canvas.fit()

        self._aviso.setText((aviso or erro or "")[:140])
        if self._ws is not None and not aviso:
            self.status.showMessage(self._resumo(self._ws))

    def _resumo(self, ws: WireSet) -> str:
        try:
            total = ws.total_wire_length()
            pedacos = "  ".join(f"{n}={L:.2f}" for n, L in ws.lengths().items())
            mat = ws.radome.material
            return (
                f"fio: {total:.2f} mm  ({pedacos})     "
                f"eps_eff={mat.eps_eff:.3f}  vf={mat.velocity_factor:.3f}  "
                f"infill={mat.infill:.0%}"
            )
        except Exception as exc:
            return f"geometria invalida: {exc}"

    # ------------------------------------------------------------------
    def _abrir(self) -> None:
        inicio = str(self._path.parent if self._path else spec_mod.recipes_dir())
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Abrir spec", inicio, "Spec de antena (*.yaml *.yml)"
        )
        if f:
            self.open(f)

    def _salvar(self) -> None:
        if self._spec is None:
            return
        if self._path is None:
            f, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Salvar spec",
                str(Path.cwd() / f"{self._spec.name}.yaml"),
                "Spec de antena (*.yaml)",
            )
            if not f:
                return
            self._path = Path(f)
        try:
            spec_mod.dump(self._spec, self._path)
        except Exception as exc:
            self._erro("Nao consegui salvar", str(exc))
            return
        self.setWindowTitle(f"antfdm - {self._path.name}")
        self.status.showMessage(f"gravado: {self._path}", 4000)

    def _outdir(self) -> Path:
        base = self._path.parent if self._path else Path.cwd()
        d = base / "saida"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _pronto(self) -> WireSet | None:
        if self._ws is None:
            self._erro("Antena invalida", self._aviso.text() or "corrija os parametros")
            return None
        problemas = self._ws.validate()
        if problemas:
            self._erro("Antena invalida", "\n".join(problemas))
            return None
        return self._ws

    def gerar_cst(self) -> tuple[Path, int]:
        """Grava a macro e devolve (caminho, numero de blocos).

        Separado da acao de menu de proposito: quem chama decide se mostra
        dialogo.  Assim o trabalho e testavel sem uma caixa modal no caminho.
        """
        ws = self._ws
        if ws is None:
            raise ValueError(self._aviso.text() or "antena invalida")
        from ..cst import vba

        sim = None
        if self._spec and self._spec.sim:
            s = self._spec.sim
            sim = vba.SimSetup(
                fmin_mhz=s.fmin_mhz,
                fmax_mhz=s.fmax_mhz,
                f0_mhz=s.f0_mhz or self._spec.f0_mhz,
                boundary=s.boundary,
                farfield_monitor=s.farfield_monitor,
            )
        blocos = vba.emit(ws, sim)
        out = self._outdir() / f"{ws.name}.bas"
        out.write_text(vba.render_macro(blocos, ws.name), encoding="utf-8")
        return out, len(blocos)

    def _gerar_cst(self) -> None:
        if self._pronto() is None:
            return
        try:
            out, n = self.gerar_cst()
        except Exception as exc:
            self._erro("Falha ao gerar o VBA", str(exc))
            return
        self._info(
            "Macro gerada",
            f"{out}\n\n{n} blocos de historico.\n\n"
            "No CST: Home > Macros > Run Macro. Os parametros usam "
            "MakeSureParameterExists, entao rodar de novo PRESERVA o que voce "
            "ja calibrou.",
        )

    def _gerar_stl(self) -> None:
        ws = self._pronto()
        if ws is None:
            return
        spec = self._spec
        outdir = self._outdir()

        def trabalho() -> str:
            from .. import report
            from ..cad import clamshell as cs
            from ..cad import export as ex

            clam = cs.build(ws)
            checks = ex.check(
                clam, spec.printer.bed_x, spec.printer.bed_y, spec.printer.bed_z
            )
            escritos = ex.export(clam, outdir, ws.name)
            report.build(ws, clam).write(outdir / f"{ws.name}_print_card.txt")
            return "\n".join([str(c) for c in checks] + [""] + [str(p) for p in escritos])

        self._rodar(trabalho, "Gerando o radome...", "Radome gerado")

    def _sync(self) -> None:
        if self._spec is None:
            return
        inicio = str(self._path.parent if self._path else Path.cwd())
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Projeto do CST", inicio, "Projeto CST (*.cst);;Parameters (*.json)"
        )
        if not f:
            return
        from ..io import cst_params_in as sync

        try:
            mudancas, ignorados = sync.apply_to_spec(self._spec, sync.read(f))
        except Exception as exc:
            self._erro("Nao consegui ler o projeto", str(exc))
            return

        if not mudancas:
            self._info("Sync", "Nada mudou: o spec ja esta igual ao projeto do CST.")
            return
        self.wires.load(self._spec)
        self._refresh()
        texto = "\n".join(str(c) for c in mudancas)
        if ignorados:
            texto += "\n\nignorados (so existem no CST): " + ", ".join(sorted(ignorados))
        texto += "\n\nSalve o spec (Ctrl+S) para manter."
        self._info(f"{len(mudancas)} parametro(s) vieram do CST", texto)

    # ------------------------------------------------------------------
    def _rodar(self, fn, mensagem: str, titulo: str) -> None:
        self._busy += 1
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.status.showMessage(mensagem)
        job = _Job(fn)
        job.sinais.done.connect(lambda t: self._fim(lambda: self._info(titulo, t)))
        job.sinais.failed.connect(lambda t: self._fim(lambda: self._erro("Falhou", t)))
        self._pool.start(job)

    def _fim(self, acao) -> None:
        self._busy = max(0, self._busy - 1)
        if self._busy == 0:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.status.clearMessage()
        acao()

    def _info(self, titulo: str, texto: str) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(titulo)
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setText(titulo)
        if len(texto) > 400:
            box.setDetailedText(texto)
        else:
            box.setInformativeText(texto)
        box.exec()

    def _erro(self, titulo: str, texto: str) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(titulo)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setText(titulo)
        box.setInformativeText(texto[:600])
        box.exec()


def _painel(texto: str, widget: QtWidgets.QWidget, botoes=()) -> QtWidgets.QWidget:
    caixa = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(caixa)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)

    cabecalho = QtWidgets.QHBoxLayout()
    cabecalho.setContentsMargins(6, 4, 4, 0)
    label = QtWidgets.QLabel(texto)
    label.setStyleSheet("font-weight:600; color:#c8ccd4;")
    cabecalho.addWidget(label, 1)
    for rotulo, slot, dica in botoes:
        b = QtWidgets.QToolButton()
        b.setText(rotulo)
        b.setToolTip(dica)
        b.setAutoRaise(True)
        b.clicked.connect(slot)
        cabecalho.addWidget(b)
    lay.addLayout(cabecalho)
    lay.addWidget(widget)
    return caixa


def run(path: str | None = None) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setStyle("Fusion")
    app.setPalette(_dark())
    win = MainWindow(path)
    win.show()
    return app.exec()


def _dark() -> QtGui.QPalette:
    p = QtGui.QPalette()
    c = QtGui.QColor
    p.setColor(QtGui.QPalette.Window, c("#232529"))
    p.setColor(QtGui.QPalette.WindowText, c("#c8ccd4"))
    p.setColor(QtGui.QPalette.Base, c("#1b1d21"))
    p.setColor(QtGui.QPalette.AlternateBase, c("#212429"))
    p.setColor(QtGui.QPalette.Text, c("#c8ccd4"))
    p.setColor(QtGui.QPalette.Button, c("#2a2d33"))
    p.setColor(QtGui.QPalette.ButtonText, c("#c8ccd4"))
    p.setColor(QtGui.QPalette.Highlight, c("#d98a4f"))
    p.setColor(QtGui.QPalette.HighlightedText, c("#1b1d21"))
    p.setColor(QtGui.QPalette.ToolTipBase, c("#2a2d33"))
    p.setColor(QtGui.QPalette.ToolTipText, c("#c8ccd4"))
    return p
