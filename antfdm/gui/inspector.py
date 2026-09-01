"""Paineis de edicao: parametros, arvore de fios, propriedades e paleta de blocos.

Todos editam diretamente o AntennaSpec, que continua sendo a unica fonte de
verdade -- a mesma que o CLI usa.  Salvar e so serializar o spec, e nada do que
a GUI faz e inacessivel por linha de comando.

A arvore mostra vertices OU blocos conforme o fio, e o painel de propriedades
serve aos dois: assim um bloco novo no catalogo aparece na interface sem
precisar de codigo de GUI.
"""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from .. import blocks as blk
from ..core.spec import AntennaSpec

MONO = QtGui.QFontDatabase.FixedFont


def param_expr(entry: Any) -> str:
    return str(entry["expr"] if isinstance(entry, dict) else entry)


def param_desc(entry: Any) -> str:
    return str(entry.get("description", "")) if isinstance(entry, dict) else ""


def set_param(spec: AntennaSpec, name: str, expr: str, desc: str | None = None) -> None:
    entry = spec.params.get(name)
    if isinstance(entry, dict):
        entry["expr"] = expr
        if desc is not None:
            entry["description"] = desc
    elif desc:
        spec.params[name] = {"expr": expr, "description": desc}
    else:
        spec.params[name] = expr


class ParamTable(QtWidgets.QTableWidget):
    """Espelha a Parameter List do CST: nome, expressao, valor, descricao."""

    changed = QtCore.Signal()

    COLS = ["Nome", "Expressao", "Valor", "Descricao"]

    def __init__(self, parent=None):
        super().__init__(0, len(self.COLS), parent)
        self.setHorizontalHeaderLabels(self.COLS)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        h = self.horizontalHeader()
        h.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        h.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self._spec: AntennaSpec | None = None
        self._loading = False
        self.itemChanged.connect(self._on_item)

    def load(self, spec: AntennaSpec, values: dict[str, float] | None = None) -> None:
        self._spec = spec
        self._loading = True
        try:
            order = list(spec.params)
            self.setRowCount(len(order))
            for r, name in enumerate(order):
                entry = spec.params[name]
                self._cell(r, 0, name, editable=False)
                self._cell(r, 1, param_expr(entry))
                v = (values or {}).get(name)
                self._cell(r, 2, "--" if v is None else f"{v:.6g}", editable=False)
                self._cell(r, 3, param_desc(entry))
        finally:
            self._loading = False

    def _cell(self, r: int, c: int, text: str, editable: bool = True) -> None:
        item = self.item(r, c)
        if item is None:
            item = QtWidgets.QTableWidgetItem()
            self.setItem(r, c, item)
        item.setText(text)
        flags = QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
        if editable:
            flags |= QtCore.Qt.ItemIsEditable
        else:
            item.setForeground(QtGui.QBrush(QtGui.QColor("#8b919b")))
        item.setFlags(flags)
        if c == 1:
            item.setFont(QtGui.QFontDatabase.systemFont(MONO))

    def _on_item(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._loading or self._spec is None or item.column() not in (1, 3):
            return
        name = self.item(item.row(), 0).text()
        if item.column() == 1:
            set_param(self._spec, name, item.text().strip())
        else:
            set_param(self._spec, name, param_expr(self._spec.params[name]), item.text())
        self.changed.emit()


class WireTree(QtWidgets.QTreeWidget):
    """Fios e seus itens -- vertices num fio explicito, blocos num fio composto."""

    changed = QtCore.Signal()
    picked = QtCore.Signal(str, int, int)  # tipo do item, indice do fio, indice do item

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Fio / item", "Resumo"])
        self.setAlternatingRowColors(True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._spec: AntennaSpec | None = None
        self.currentItemChanged.connect(self._on_current)
        self.customContextMenuRequested.connect(self._menu)

    def load(self, spec: AntennaSpec, keep: tuple[str, int, int] | None = None) -> None:
        self._spec = spec
        self.blockSignals(True)
        try:
            self.clear()
            for wi, w in enumerate(spec.wires):
                rotulo = f"{w.name}  ({w.role})"
                top = QtWidgets.QTreeWidgetItem([rotulo, _wire_summary(w)])
                top.setData(0, QtCore.Qt.UserRole, ("wire", wi, -1))
                cor = "#d98a4f" if w.role == "driven" else "#8fa8c8"
                top.setForeground(0, QtGui.QBrush(QtGui.QColor(cor)))
                self.addTopLevelItem(top)

                if w.mirror_of:
                    top.setExpanded(False)
                elif w.blocks:
                    for bi, b in enumerate(w.blocks):
                        child = QtWidgets.QTreeWidgetItem(
                            [f"  {bi}. {b.get('type', '?')}", _block_summary(b)]
                        )
                        child.setData(0, QtCore.Qt.UserRole, ("block", wi, bi))
                        top.addChild(child)
                    top.setExpanded(True)
                else:
                    for vi, v in enumerate(w.vertices):
                        child = QtWidgets.QTreeWidgetItem(
                            [f"  v{vi}", f"x={v.x}   y={v.y}"
                             + (f"   filete={v.fillet}" if v.fillet else "")]
                        )
                        child.setData(0, QtCore.Qt.UserRole, ("vertex", wi, vi))
                        top.addChild(child)
                    top.setExpanded(True)
            self.resizeColumnToContents(0)
        finally:
            self.blockSignals(False)
        if keep:
            self.select(*keep)

    def select(self, kind: str, wi: int, ii: int) -> None:
        it = QtWidgets.QTreeWidgetItemIterator(self)
        while it.value():
            if it.value().data(0, QtCore.Qt.UserRole) == (kind, wi, ii):
                self.setCurrentItem(it.value())
                self.scrollToItem(it.value())
                return
            it += 1

    def select_vertex(self, wire_name: str, index: int) -> None:
        if self._spec is None:
            return
        for wi, w in enumerate(self._spec.wires):
            if w.name == wire_name:
                self.select("vertex", wi, index)
                return

    def current_tag(self) -> tuple[str, int, int] | None:
        it = self.currentItem()
        return it.data(0, QtCore.Qt.UserRole) if it else None

    def _on_current(self, cur, _prev) -> None:
        if cur is not None:
            self.picked.emit(*cur.data(0, QtCore.Qt.UserRole))

    def _menu(self, pos: QtCore.QPoint) -> None:
        tag = self.current_tag()
        if self._spec is None or tag is None or tag[0] != "block":
            return
        _, wi, bi = tag
        menu = QtWidgets.QMenu(self)
        acima = menu.addAction("Mover para cima")
        abaixo = menu.addAction("Mover para baixo")
        menu.addSeparator()
        remover = menu.addAction("Remover bloco")
        escolha = menu.exec(self.viewport().mapToGlobal(pos))
        if escolha is None:
            return
        lista = self._spec.wires[wi].blocks
        if escolha is remover:
            lista.pop(bi)
        elif escolha is acima and bi > 0:
            lista[bi - 1], lista[bi] = lista[bi], lista[bi - 1]
        elif escolha is abaixo and bi < len(lista) - 1:
            lista[bi + 1], lista[bi] = lista[bi], lista[bi + 1]
        else:
            return
        self.changed.emit()


class ItemProperties(QtWidgets.QTableWidget):
    """Campos do item selecionado -- vertice ou bloco, com o mesmo painel.

    Os campos de um bloco saem do proprio catalogo, entao um bloco novo aparece
    aqui sem precisar de codigo de interface.
    """

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["Campo", "Expressao"])
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self._spec: AntennaSpec | None = None
        self._tag: tuple[str, int, int] | None = None
        self._loading = False
        self.itemChanged.connect(self._on_item)

    def show_item(self, spec: AntennaSpec, tag: tuple[str, int, int] | None) -> None:
        self._spec, self._tag = spec, tag
        self._loading = True
        try:
            self.setRowCount(0)
            if tag is None or spec is None:
                return
            kind, wi, ii = tag
            if kind == "vertex":
                v = spec.wires[wi].vertices[ii]
                self._rows([("x", v.x), ("y", v.y), ("fillet", v.fillet or "")])
            elif kind == "block":
                b = spec.wires[wi].blocks[ii]
                campos = _fields_of(str(b.get("type", "")))
                self._rows(
                    [("type", str(b.get("type", "")))]
                    + [(k, str(b.get(k, ""))) for k in campos]
                )
            elif kind == "wire":
                w = spec.wires[wi]
                linhas = [("name", w.name), ("role", w.role)]
                if w.start:
                    linhas += [("start.x", w.start.x), ("start.y", w.start.y),
                               ("start.dir", w.start.dir)]
                self._rows(linhas, editable_first=False)
        finally:
            self._loading = False

    def _rows(self, pares, editable_first: bool = False) -> None:
        self.setRowCount(len(pares))
        for r, (k, v) in enumerate(pares):
            nome = QtWidgets.QTableWidgetItem(k)
            nome.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            nome.setForeground(QtGui.QBrush(QtGui.QColor("#8b919b")))
            self.setItem(r, 0, nome)
            val = QtWidgets.QTableWidgetItem(str(v or ""))
            editavel = editable_first or k != "type"
            if editavel:
                val.setFlags(val.flags() | QtCore.Qt.ItemIsEditable)
            else:
                val.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            val.setFont(QtGui.QFontDatabase.systemFont(MONO))
            self.setItem(r, 1, val)

    def _on_item(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._loading or self._spec is None or self._tag is None or item.column() != 1:
            return
        campo = self.item(item.row(), 0).text()
        texto = item.text().strip()
        kind, wi, ii = self._tag
        if kind == "vertex":
            v = self._spec.wires[wi].vertices[ii]
            if campo == "fillet":
                v.fillet = texto or None
            else:
                setattr(v, campo, texto or "0")
        elif kind == "block":
            b = self._spec.wires[wi].blocks[ii]
            if texto:
                b[campo] = texto
            else:
                b.pop(campo, None)
        elif kind == "wire":
            w = self._spec.wires[wi]
            if campo.startswith("start.") and w.start is not None:
                setattr(w.start, campo.split(".", 1)[1], texto or "0")
            elif campo == "name":
                w.name = texto
        self.changed.emit()


class BlockPalette(QtWidgets.QWidget):
    """Catalogo de bloquinhos disponiveis, lido do registro.

    Um bloco novo registrado em blocks/library.py aparece aqui sozinho.
    """

    add_requested = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.lista = QtWidgets.QListWidget()
        for tipo, resumo, campos in blk.describe():
            it = QtWidgets.QListWidgetItem(f"{tipo}")
            it.setData(QtCore.Qt.UserRole, tipo)
            it.setToolTip(f"{resumo}\n\ncampos: {', '.join(campos)}")
            self.lista.addItem(it)
        self.lista.itemDoubleClicked.connect(
            lambda it: self.add_requested.emit(it.data(QtCore.Qt.UserRole))
        )
        lay.addWidget(self.lista)

        self.botao = QtWidgets.QPushButton("Adicionar ao fio selecionado")
        self.botao.clicked.connect(self._emit)
        lay.addWidget(self.botao)

        self.dica = QtWidgets.QLabel("")
        self.dica.setWordWrap(True)
        self.dica.setStyleSheet("color:#8b919b; padding:2px 4px;")
        lay.addWidget(self.dica)
        self.lista.currentItemChanged.connect(self._dica)
        if self.lista.count():
            self.lista.setCurrentRow(0)

    def _emit(self) -> None:
        it = self.lista.currentItem()
        if it:
            self.add_requested.emit(it.data(QtCore.Qt.UserRole))

    def _dica(self, cur, _prev) -> None:
        if cur is None:
            self.dica.setText("")
            return
        tipo = cur.data(QtCore.Qt.UserRole)
        for t, resumo, campos in blk.describe():
            if t == tipo:
                self.dica.setText(f"{resumo}\ncampos: {', '.join(campos)}")
                return


def _fields_of(tipo: str) -> list[str]:
    for t, _resumo, campos in blk.describe():
        if t == tipo:
            return campos
    return []


def default_block(tipo: str) -> dict[str, Any]:
    """Bloco novo ja com valores plausiveis, para o canvas nao ficar vazio."""
    padroes = {
        "straight": {"len": "10"},
        "bend": {"angle": "90", "fillet": "2"},
        "vee": {"run": "10", "height": "8", "back": "10", "fillet": "2"},
        "meander": {"n": "4", "pitch": "6", "height": "7", "fillet": "1.2"},
        "arc": {"radius": "10", "angle": "90", "n": "12"},
        "spiral": {"turns": "2", "r0": "3", "r1": "30", "per_turn": "24"},
        "taper": {"len": "20", "angle": "20"},
        "jump": {"len": "10"},
    }
    return {"type": tipo, **padroes.get(tipo, {})}


def _wire_summary(w) -> str:
    if w.mirror_of:
        return f"espelho de {w.mirror_of} em {w.mirror_axis}"
    if w.blocks:
        return f"{len(w.blocks)} bloco(s)"
    return f"{len(w.vertices)} vertice(s)"


def _block_summary(b: dict[str, Any]) -> str:
    return "  ".join(f"{k}={v}" for k, v in b.items() if k != "type")
