"""Janela principal: a tela e o desenho.

Sete controles e um painel.  Tudo que existia antes -- parametros, arvore de
blocos, propriedades, paleta -- continua existindo atras do botao Avancado; o que
mudou e nao aparecer sem ser pedido.

Esta contagem e verificada por teste (``test_tela_padrao_tem_poucos_controles``).
Sem essa trava eu volto a acrescentar, que foi o que aconteceu tres vezes.

A GUI edita o mesmo AntennaSpec que o CLI consome e salva o mesmo YAML: nada do
que se faz aqui fica preso na interface.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..check import rules
from ..core import spec as spec_mod
from ..core.spec import AntennaSpec
from ..core.wireset import WireSet
from .canvas import AntennaCanvas
from .dialogs import FeedDialog, NewAntennaDialog, NewParamDialog, NewWireDialog
from .draw import DrawController
from .history import History
from .inspector import (
    BlockPalette,
    ItemProperties,
    ParamTable,
    WireTree,
    default_block,
    set_param,
)

DICA_VAZIA = "clique na tela para desenhar o primeiro braco"
DICA_DESENHANDO = "clique para continuar o fio   ·   Esc termina"


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
        self.resize(1200, 800)
        self._path: Path | None = None
        self._spec: AntennaSpec | None = None
        self._ws: WireSet | None = None
        self._pool = QtCore.QThreadPool.globalInstance()
        self._busy = 0
        self._hist = History()
        self._draw = DrawController()

        self.canvas = AntennaCanvas()
        self.setCentralWidget(self.canvas)

        self._build_toolbar()
        self._build_footer()
        self._build_advanced()

        self.canvas.pontoClicado.connect(self._clique)
        self.canvas.pontoArrastado.connect(self._arrasto)
        self.canvas.fioTerminado.connect(self._terminar_fio)
        self.canvas.vertexPicked.connect(self.wires.select_vertex)

        if path:
            self.open(path)
        else:
            self.nova(spec_mod.AntennaSpec.empty())

    # ------------------------------------------------------------------
    # a barra: sete controles
    # ------------------------------------------------------------------
    def _build_toolbar(self) -> None:
        tb = self.addToolBar("principal")
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        tb.setMovable(False)
        self._toolbar = tb

        self.f0 = QtWidgets.QDoubleSpinBox()
        self.f0.setRange(1.0, 100000.0)
        self.f0.setDecimals(0)
        self.f0.setValue(1300)
        self.f0.setSuffix(" MHz")
        self.f0.setToolTip("Frequencia alvo. Toda dimensao acompanha.")
        self.f0.valueChanged.connect(self._mudou_f0)
        tb.addWidget(self.f0)
        tb.addSeparator()

        def act(texto, slot, atalho=None, dica=""):
            a = QtGui.QAction(texto, self)
            a.triggered.connect(slot)
            if atalho:
                a.setShortcut(atalho)
            a.setToolTip(f"{dica}  ({atalho})" if atalho and dica else (dica or atalho or ""))
            tb.addAction(a)
            return a

        act("Nova", self._nova_antena, "Ctrl+N", "Comeca uma antena do zero")
        act("Abrir", self._abrir, "Ctrl+O")
        act("Salvar", self._salvar, "Ctrl+S")
        tb.addSeparator()
        act("Gerar CST", self._gerar_cst, None, "Macro parametrica para o CST")
        act("Gerar STL", self._gerar_stl, None, "As duas metades do radome")

        espaco = QtWidgets.QWidget()
        espaco.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        tb.addWidget(espaco)
        self._acao_avancado = act("Avancado", self._alternar_avancado, "Ctrl+E",
                                  "Parametros, blocos e o resto")

        # Sem botao: atalhos que nao precisam ocupar espaco na barra.
        for atalho, slot in (
            ("Ctrl+Z", self._desfazer),
            ("Ctrl+Y", self._refazer),
            ("Ctrl+Shift+Z", self._refazer),
            ("Ctrl+0", self.canvas.fit),
            ("Delete", self._apagar_selecionado),
        ):
            a = QtGui.QAction(self)
            a.setShortcut(atalho)
            a.triggered.connect(slot)
            self.addAction(a)

    def _build_footer(self) -> None:
        self.status = self.statusBar()
        self._medida = QtWidgets.QLabel("")
        self._aviso = QtWidgets.QLabel("")
        self._corrigir = QtWidgets.QPushButton("corrigir")
        self._corrigir.setFlat(True)
        self._corrigir.setCursor(QtCore.Qt.PointingHandCursor)
        self._corrigir.clicked.connect(self._aplicar_correcao)
        self._corrigir.hide()
        self.status.addWidget(self._medida)
        self.status.addPermanentWidget(self._aviso)
        self.status.addPermanentWidget(self._corrigir)
        self._correcao_atual = None

    def _build_advanced(self) -> None:
        """Tudo o que existia antes, agora atras de um botao."""
        self.params = ParamTable()
        self.wires = WireTree()
        self.props = ItemProperties()
        self.palette_blocos = BlockPalette()

        self.params.changed.connect(self._refresh)
        self.wires.changed.connect(self._on_wires_changed)
        self.wires.picked.connect(self._on_picked)
        self.props.changed.connect(self._on_wires_changed)
        self.palette_blocos.add_requested.connect(self._add_block)

        abas = QtWidgets.QTabWidget()
        abas.addTab(_com_botoes(self.params, [
            ("+", self._novo_param, "Novo parametro"),
            ("-", self._remove_param, "Remove o selecionado"),
        ]), "Parametros")
        abas.addTab(self.wires, "Fios")
        abas.addTab(self.props, "Item")
        abas.addTab(self.palette_blocos, "Blocos")

        extras = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(extras)
        lay.setContentsMargins(4, 2, 4, 2)
        for rotulo, slot in (
            ("+ Fio", self._novo_fio),
            ("Alimentacao", self._editar_feed),
            ("Sync do CST", self._sync),
        ):
            b = QtWidgets.QPushButton(rotulo)
            b.clicked.connect(slot)
            lay.addWidget(b)
        self._chk_radome = QtWidgets.QCheckBox("Radome")
        self._chk_radome.setChecked(True)
        self._chk_radome.toggled.connect(self.canvas.set_show_radome)
        lay.addWidget(self._chk_radome)
        lay.addStretch(1)

        caixa = QtWidgets.QWidget()
        vl = QtWidgets.QVBoxLayout(caixa)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(abas, 1)
        vl.addWidget(extras)

        self.dock = QtWidgets.QDockWidget("Avancado", self)
        self.dock.setWidget(caixa)
        self.dock.setAllowedAreas(QtCore.Qt.RightDockWidgetArea)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.dock)
        self.dock.hide()  # a tela padrao e so o desenho

    def avancado_aberto(self) -> bool:
        """``isVisible`` seria False com a janela ainda nao mostrada; o que
        interessa aqui e a visibilidade em relacao a janela, nao a tela."""
        return self.dock.isVisibleTo(self)

    def _alternar_avancado(self) -> None:
        self.dock.setVisible(not self.avancado_aberto())

    def controles_visiveis(self) -> list[str]:
        """Controles que o usuario ve sem abrir nada. A trava do teste."""
        nomes = [a.text() for a in self._toolbar.actions() if a.text()]
        nomes.append("f0")
        if self.avancado_aberto():
            nomes.append("avancado(aberto)")
        return nomes

    # ------------------------------------------------------------------
    # desenho
    # ------------------------------------------------------------------
    def _clique(self, x: float, y: float, livre: bool) -> None:
        if self._spec is None:
            return
        self._hist.marcar(self._spec)
        try:
            traco = self._draw.clicar(self._spec, (x, y), livre)
        except Exception as exc:
            self._spec = self._hist.desfazer(self._spec) or self._spec
            self._erro("Nao consegui desenhar", str(exc))
            return
        if traco is None:
            self.status.showMessage("clique de novo para fechar o trecho", 3000)
        self._apos_edicao()

    def _arrasto(self, fio: str, indice: int, x: float, y: float) -> None:
        """Soltar um ponto edita o PARAMETRO que o coloca ali."""
        if self._spec is None or self._ws is None:
            return
        from ..core.solve import apply_edit, solve_field

        alvo = next((w for w in self._spec.wires if w.name == fio), None)
        if alvo is None or alvo.mirror_of:
            self.status.showMessage(
                f"{fio} acompanha outro fio; arraste o original", 4000
            )
            return

        import numpy as np

        verts = self._ws.wire(fio).centerline.points(self._ws.params)
        if indice == 0 or indice >= len(verts):
            self.status.showMessage("este ponto nao se move sozinho", 3000)
            return
        comprimento = float(np.linalg.norm(np.array([x, y]) - verts[indice - 1][:2]))

        retos = [i for i, b in enumerate(alvo.blocks) if b.get("type") == "straight"]
        if not retos:
            return
        bloco = min(len(retos), indice) - 1
        campo = str(alvo.blocks[retos[bloco]].get("len", ""))

        edit = solve_field(campo, comprimento, self._ws.params)
        if edit.kind == "ambiguous":
            self.status.showMessage(
                f"depende de {', '.join(edit.candidates)}; ajuste no Avancado", 5000
            )
            return
        if not edit.ok:
            self.status.showMessage(edit.reason, 5000)
            return

        self._hist.marcar(self._spec)
        apply_edit(self._spec, edit, wire=self._spec.wires.index(alvo),
                   block=retos[bloco], field_name="len")
        if edit.affects:
            self.status.showMessage(f"tambem mudou: {', '.join(edit.affects)}", 4000)
        self._apos_edicao()

    def _terminar_fio(self) -> None:
        self._draw.terminar_fio()
        self._atualizar_dica()

    def _apagar_selecionado(self) -> None:
        if self._spec is None or not self._spec.wires:
            return
        self._hist.marcar(self._spec)
        alvo = self._spec.wires[-1].name
        # Some tambem quem espelhava o fio removido, senao o spec fica invalido.
        self._spec.wires = [
            w for w in self._spec.wires if w.name != alvo and w.mirror_of != alvo
        ]
        self._draw.reset()
        self._apos_edicao()

    def _desfazer(self) -> None:
        if self._spec is None:
            return
        anterior = self._hist.desfazer(self._spec)
        if anterior is None:
            self.status.showMessage("nada para desfazer", 2000)
            return
        self._spec = anterior
        self._draw.reset()
        self._apos_edicao(marcar=False)

    def _refazer(self) -> None:
        if self._spec is None:
            return
        proximo = self._hist.refazer(self._spec)
        if proximo is None:
            self.status.showMessage("nada para refazer", 2000)
            return
        self._spec = proximo
        self._draw.reset()
        self._apos_edicao(marcar=False)

    def _apos_edicao(self, marcar: bool = True) -> None:
        del marcar
        self.wires.load(self._spec)
        self._refresh()

    # ------------------------------------------------------------------
    def nova(self, spec: AntennaSpec, path: Path | None = None) -> None:
        self._spec = spec
        self._path = path
        self._hist.limpar()
        self._draw.reset()
        self.setWindowTitle(
            f"antfdm - {path.name if path else spec.name + ' (nao salva)'}"
        )
        self.f0.blockSignals(True)
        self.f0.setValue(spec.f0_mhz or 1300)
        self.f0.blockSignals(False)
        self.wires.load(spec)
        self.props.show_item(spec, None)
        self._refresh(fit=True)

    def open(self, path: str | Path) -> None:
        try:
            spec = spec_mod.load(path)
        except Exception as exc:
            self._erro("Nao consegui abrir", str(exc))
            return
        self.nova(spec, Path(path))

    def _mudou_f0(self, valor: float) -> None:
        if self._spec is None:
            return
        self._hist.marcar(self._spec)
        self._spec.f0_mhz = float(valor)
        if "F0" in self._spec.params:
            set_param(self._spec, "F0", f"{valor:g}")
        if self._spec.sim:
            self._spec.sim.f0_mhz = float(valor)
        self._refresh()

    def _refresh(self, fit: bool = False) -> None:
        if self._spec is None:
            return
        aviso = ""
        try:
            self._ws = self._spec.to_wireset() if self._spec.wires else None
            valores = self._ws.params.values() if self._ws else {}
        except Exception as exc:
            self._ws = None
            valores = {}
            aviso = str(exc)

        self.params.load(self._spec, valores)
        lam = 300000.0 / self._spec.f0_mhz if self._spec.f0_mhz else None
        self.canvas.set_lambda(lam)
        erro = self.canvas.set_wireset(self._ws, keep_view=not fit)
        if fit:
            self.canvas.fit()

        self._atualizar_rodape(aviso or erro or "", lam)
        self._atualizar_dica()

    def _atualizar_rodape(self, erro: str, lam: float | None) -> None:
        self._corrigir.hide()
        self._correcao_atual = None

        if erro:
            self._medida.setText("")
            self._aviso.setText(erro[:110])
            self._aviso.setStyleSheet("color:#e05252;")
            return
        if self._ws is None:
            self._medida.setText("")
            self._aviso.setText("")
            return

        total = self._ws.total_wire_length()
        fracao = f" · {total / lam:.2f} lambda" if lam else ""
        self._medida.setText(f"fio {total:.1f} mm{fracao}")

        bed = (
            self._spec.printer.bed_x,
            self._spec.printer.bed_y,
            self._spec.printer.bed_z,
        )
        avisos = rules.verificar(self._ws, bed)
        self._aviso.setText(rules.resumo(avisos)[:110])
        graves = [a for a in avisos if a.severidade != "dica"]
        self._aviso.setStyleSheet(
            "color:#e0a052;" if graves else "color:#7ea88f;"
        )
        com_correcao = next((a for a in avisos if a.correcao), None)
        if com_correcao:
            self._correcao_atual = com_correcao.correcao
            self._corrigir.setToolTip(com_correcao.correcao.descricao)
            self._corrigir.show()

    def _atualizar_dica(self) -> None:
        if self._spec is None:
            return
        if not self._spec.wires:
            self.status.showMessage(DICA_VAZIA)
        elif self._draw.desenhando:
            self.status.showMessage(DICA_DESENHANDO)

    def _aplicar_correcao(self) -> None:
        if self._spec is None or self._correcao_atual is None:
            return
        self._hist.marcar(self._spec)
        ok, msg = rules.aplicar(self._spec, self._correcao_atual)
        if not ok:
            self._spec = self._hist.desfazer(self._spec) or self._spec
            self._erro("Nao consegui corrigir", msg)
            return
        self._apos_edicao()
        self.status.showMessage(msg, 5000)

    # ------------------------------------------------------------------
    # avancado (o que existia antes)
    # ------------------------------------------------------------------
    def _on_picked(self, kind: str, wi: int, ii: int) -> None:
        self.props.show_item(self._spec, (kind, wi, ii))

    def _on_wires_changed(self) -> None:
        tag = self.wires.current_tag()
        self.wires.load(self._spec, keep=tag)
        self._refresh()

    def _add_block(self, tipo: str) -> None:
        if self._spec is None:
            return
        tag = self.wires.current_tag()
        if tag is None and len(self._spec.wires) == 1:
            tag = ("wire", 0, -1)
        if tag is None:
            self._erro("Nenhum fio selecionado", "Escolha um fio na aba Fios.")
            return
        _, wi, ii = tag
        alvo = self._spec.wires[wi]
        if alvo.mirror_of:
            self._erro("Fio espelhado", f"{alvo.name!r} acompanha {alvo.mirror_of!r}.")
            return
        if alvo.vertices:
            self._erro("Fio por vertices", f"{alvo.name!r} usa vertices explicitos.")
            return
        self._hist.marcar(self._spec)
        onde = ii + 1 if tag[0] == "block" else len(alvo.blocks)
        alvo.blocks.insert(onde, default_block(tipo))
        self.wires.load(self._spec, keep=("block", wi, onde))
        self.props.show_item(self._spec, ("block", wi, onde))
        self._refresh()

    def _nova_antena(self) -> None:
        dlg = NewAntennaDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        r = dlg.resultado()
        try:
            spec = (
                spec_mod.AntennaSpec.empty(r.nome, r.f0_mhz)
                if r.receita is None
                else spec_mod.from_recipe(r.receita, r.nome)
            )
        except Exception as exc:
            self._erro("Nao consegui criar", str(exc))
            return
        self.nova(spec)

    def _novo_fio(self) -> None:
        if self._spec is None:
            return
        dlg = NewWireDialog([w.name for w in self._spec.wires], self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        r = dlg.resultado()
        if r.nome in {w.name for w in self._spec.wires}:
            self._erro("Nome repetido", f"Ja existe um fio {r.nome!r}.")
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
        self._hist.marcar(self._spec)
        self._spec.wires.append(novo)
        self._apos_edicao()

    def _editar_feed(self) -> None:
        if self._spec is None:
            return
        dlg = FeedDialog(self._spec.feed, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        p1, p2, z = dlg.resultado()
        self._hist.marcar(self._spec)
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
            self._erro("Nome ja usado", f"Ja existe {nome!r} (o CST ignora a caixa).")
            return
        self._hist.marcar(self._spec)
        set_param(self._spec, nome, expr, desc)
        self._refresh()

    def _remove_param(self) -> None:
        if self._spec is None:
            return
        linha = self.params.currentRow()
        if linha < 0:
            self._erro("Nenhum parametro selecionado", "Clique numa linha.")
            return
        nome = self.params.item(linha, 0).text()
        antes = dict(self._spec.params)
        self._hist.marcar(self._spec)
        del self._spec.params[nome]

        # Precisa avaliar a GEOMETRIA: um nome usado so dentro de um bloco nao
        # aparece na tabela de dependencias e a remocao passaria batida.
        problema = ""
        try:
            problemas = self._spec.to_wireset().validate()
            problema = problemas[0] if problemas else ""
        except Exception as exc:
            problema = str(exc)
        if problema:
            self._spec.params.clear()
            self._spec.params.update(antes)
            self._erro("Parametro em uso", f"{nome!r} nao pode sair: {problema}")
        self._refresh()

    # ------------------------------------------------------------------
    def _abrir(self) -> None:
        inicio = str(self._path.parent if self._path else spec_mod.recipes_dir())
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Abrir", inicio, "Antena (*.yaml *.yml)"
        )
        if f:
            self.open(f)

    def _salvar(self) -> None:
        if self._spec is None:
            return
        if self._path is None:
            f, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Salvar", str(Path.cwd() / f"{self._spec.name}.yaml"),
                "Antena (*.yaml)"
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
        d = (self._path.parent if self._path else Path.cwd()) / "saida"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _pronto(self) -> WireSet | None:
        if self._ws is None:
            self._erro("Antena incompleta",
                       "Desenhe pelo menos um braco clicando na tela.")
            return None
        problemas = self._ws.validate()
        if problemas:
            self._erro("Antena invalida", "\n".join(problemas))
            return None
        return self._ws

    def gerar_cst(self) -> tuple[Path, int]:
        """Grava a macro e devolve (caminho, blocos). Sem dialogo, para testar."""
        if self._ws is None:
            raise ValueError("a antena ainda nao tem geometria")
        from ..cst import vba

        sim = None
        if self._spec and self._spec.sim:
            s = self._spec.sim
            sim = vba.SimSetup(
                fmin_mhz=s.fmin_mhz, fmax_mhz=s.fmax_mhz,
                f0_mhz=s.f0_mhz or self._spec.f0_mhz,
                boundary=s.boundary, farfield_monitor=s.farfield_monitor,
            )
        blocos = vba.emit(self._ws, sim)
        out = self._outdir() / f"{self._ws.name}.bas"
        out.write_text(vba.render_macro(blocos, self._ws.name), encoding="utf-8")
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
            f"{out}\n\n{n} blocos.\n\nNo CST: Home > Macros > Run Macro. "
            "Rodar de novo PRESERVA o que voce ja calibrou.",
        )

    def _gerar_stl(self) -> None:
        ws = self._pronto()
        if ws is None:
            return
        spec, outdir = self._spec, self._outdir()

        def trabalho() -> str:
            from .. import report
            from ..cad import clamshell as cs
            from ..cad import export as ex

            clam = cs.build(ws)
            checks = ex.check(clam, spec.printer.bed_x, spec.printer.bed_y,
                              spec.printer.bed_z)
            escritos = ex.export(clam, outdir, ws.name)
            report.build(ws, clam).write(outdir / f"{ws.name}_print_card.txt")
            return "\n".join([str(c) for c in checks] + [""] + [str(p) for p in escritos])

        self._rodar(trabalho, "Gerando o radome...", "Radome gerado")

    def _sync(self) -> None:
        if self._spec is None:
            return
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Projeto do CST", str(self._path.parent if self._path else Path.cwd()),
            "Projeto CST (*.cst);;Parameters (*.json)"
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
            self._info("Sync", "Nada mudou.")
            return
        self._apos_edicao()
        texto = "\n".join(str(c) for c in mudancas)
        if ignorados:
            texto += "\n\nso no CST: " + ", ".join(sorted(ignorados))
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


def _com_botoes(widget: QtWidgets.QWidget, botoes) -> QtWidgets.QWidget:
    caixa = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(caixa)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    linha = QtWidgets.QHBoxLayout()
    linha.addStretch(1)
    for rotulo, slot, dica in botoes:
        b = QtWidgets.QToolButton()
        b.setText(rotulo)
        b.setToolTip(dica)
        b.setAutoRaise(True)
        b.clicked.connect(slot)
        linha.addWidget(b)
    lay.addLayout(linha)
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
