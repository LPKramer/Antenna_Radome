"""Dialogos para construir uma antena do zero.

Sem eles a GUI so editava YAML que ja existia -- comecar do zero exigia escrever
o arquivo a mao, que e exatamente o que a interface deveria evitar.

Cada dialogo devolve dados simples e quem aplica ao spec e a janela principal,
para a validacao acontecer num lugar so.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets

from .. import blocks as blk
from ..core import spec as spec_mod


def _mono(w: QtWidgets.QWidget) -> QtWidgets.QWidget:
    w.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
    return w


class _Dialog(QtWidgets.QDialog):
    def __init__(self, parent, titulo: str, dica: str = ""):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(460)
        self._lay = QtWidgets.QVBoxLayout(self)
        if dica:
            label = QtWidgets.QLabel(dica)
            label.setWordWrap(True)
            label.setStyleSheet("color:#8b919b; padding:2px 0 8px 0;")
            self._lay.addWidget(label)
        self.form = QtWidgets.QFormLayout()
        self.form.setLabelAlignment(QtCore.Qt.AlignRight)
        self._lay.addLayout(self.form)

    def add_buttons(self) -> None:
        botoes = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        self._lay.addStretch(1)
        self._lay.addWidget(botoes)


# ----------------------------------------------------------------------
# nova antena
# ----------------------------------------------------------------------


@dataclass
class NovaAntena:
    nome: str
    f0_mhz: float
    receita: str | None  # None = dipolo em branco


class NewAntennaDialog(_Dialog):
    """Cria uma antena nova, em branco ou semeada por uma receita."""

    def __init__(self, parent=None):
        super().__init__(
            parent,
            "Nova antena",
            "Comece de um dipolo simples ou de uma receita do catalogo. "
            "Seja qual for, o resultado e seu para editar -- receita aqui e "
            "ponto de partida, nao template travado.",
        )
        self.nome = QtWidgets.QLineEdit("minha_antena")
        self.f0 = QtWidgets.QDoubleSpinBox()
        self.f0.setRange(1.0, 100000.0)
        self.f0.setDecimals(1)
        self.f0.setValue(1300.0)
        self.f0.setSuffix(" MHz")

        self.origem = QtWidgets.QComboBox()
        self.origem.addItem("Dipolo de meia onda (em branco)", None)
        for r in spec_mod.catalog():
            self.origem.addItem(f"Receita: {r}", r)

        self.form.addRow("Nome", self.nome)
        self.form.addRow("Frequencia alvo", self.f0)
        self.form.addRow("Comecar de", self.origem)

        self._aviso = QtWidgets.QLabel("")
        self._aviso.setWordWrap(True)
        self._aviso.setStyleSheet("color:#d98a4f;")
        self._lay.addWidget(self._aviso)
        self.origem.currentIndexChanged.connect(self._explica)
        self._explica()
        self.add_buttons()

    def _explica(self) -> None:
        if self.origem.currentData() is None:
            self._aviso.setText(
                "Um dipolo de dois bracos, com F0 e Lambda ja definidos. "
                "Todo comprimento e fracao de Lambda, entao mudar F0 reescala tudo."
            )
        else:
            self._aviso.setText(
                "A receita traz os proprios parametros e a frequencia dela; "
                "o campo de frequencia acima e ignorado."
            )

    def resultado(self) -> NovaAntena:
        return NovaAntena(
            nome=self.nome.text().strip() or "minha_antena",
            f0_mhz=float(self.f0.value()),
            receita=self.origem.currentData(),
        )


# ----------------------------------------------------------------------
# novo fio
# ----------------------------------------------------------------------


@dataclass
class NovoFio:
    nome: str
    papel: str
    espelho_de: str | None
    espelho_eixo: str
    x: str
    y: str
    direcao: str
    primeiro_bloco: str | None


class NewWireDialog(_Dialog):
    """Adiciona um fio: uma cadeia de blocos nova, ou o espelho de outro fio."""

    def __init__(self, existentes: list[str], parent=None):
        super().__init__(
            parent,
            "Novo fio",
            "Um fio e uma cadeia de blocos. Elemento parasita (refletor, diretor) "
            "e um fio separado: nao se conecta eletricamente, so mecanicamente "
            "pelo boom do radome.",
        )
        self.nome = QtWidgets.QLineEdit(f"fio{len(existentes) + 1}")
        self.papel = QtWidgets.QComboBox()
        self.papel.addItem("driven (alimentado)", "driven")
        self.papel.addItem("parasitic (refletor / diretor)", "parasitic")

        self.modo = QtWidgets.QComboBox()
        self.modo.addItem("Cadeia de blocos nova", "blocks")
        if existentes:
            self.modo.addItem("Espelho de outro fio", "mirror")

        self.espelho = QtWidgets.QComboBox()
        self.espelho.addItems(existentes)
        self.eixo = QtWidgets.QComboBox()
        self.eixo.addItems(["x", "y"])

        self.x = _mono(QtWidgets.QLineEdit("0"))
        self.y = _mono(QtWidgets.QLineEdit("0"))
        self.direcao = _mono(QtWidgets.QLineEdit("0"))
        self.bloco = QtWidgets.QComboBox()
        self.bloco.addItem("straight (comeca com um trecho reto)", "straight")
        for t in blk.catalog():
            if t not in ("straight", "jump"):
                self.bloco.addItem(t, t)

        self.form.addRow("Nome", self.nome)
        self.form.addRow("Papel", self.papel)
        self.form.addRow("Definir por", self.modo)
        self._linhas_espelho = [
            self.form.addRow("Espelhar", self.espelho) or self.espelho,
            self.form.addRow("No eixo", self.eixo) or self.eixo,
        ]
        self.form.addRow("Comeca em X", self.x)
        self.form.addRow("Comeca em Y", self.y)
        self.form.addRow("Apontando (graus)", self.direcao)
        self.form.addRow("Primeiro bloco", self.bloco)

        self.modo.currentIndexChanged.connect(self._modo)
        self._modo()
        self.add_buttons()

    def _modo(self) -> None:
        espelhando = self.modo.currentData() == "mirror"
        for w in (self.espelho, self.eixo):
            w.setVisible(espelhando)
            lbl = self.form.labelForField(w)
            if lbl:
                lbl.setVisible(espelhando)
        for w in (self.x, self.y, self.direcao, self.bloco):
            w.setVisible(not espelhando)
            lbl = self.form.labelForField(w)
            if lbl:
                lbl.setVisible(not espelhando)
        self.adjustSize()

    def resultado(self) -> NovoFio:
        espelhando = self.modo.currentData() == "mirror"
        return NovoFio(
            nome=self.nome.text().strip() or "fio",
            papel=self.papel.currentData(),
            espelho_de=self.espelho.currentText() if espelhando else None,
            espelho_eixo=self.eixo.currentText(),
            x=self.x.text().strip() or "0",
            y=self.y.text().strip() or "0",
            direcao=self.direcao.text().strip() or "0",
            primeiro_bloco=None if espelhando else self.bloco.currentData(),
        )


# ----------------------------------------------------------------------
# alimentacao
# ----------------------------------------------------------------------


class FeedDialog(_Dialog):
    """Porta discreta: dois pontos, em expressao."""

    def __init__(self, feed, parent=None):
        super().__init__(
            parent,
            "Alimentacao",
            "A porta liga dois pontos. Como sao expressoes, o Gap continua "
            "calibravel no CST -- e a ponte do radome garante o espacamento "
            "na peca impressa.",
        )
        p1 = list(feed.p1) if feed else ["-Gap/2", "0", "0"]
        p2 = list(feed.p2) if feed else ["Gap/2", "0", "0"]
        self.campos = []
        for rotulo, p in (("Ponto 1", p1), ("Ponto 2", p2)):
            linha = QtWidgets.QHBoxLayout()
            trio = []
            for i, eixo in enumerate("xyz"):
                e = _mono(QtWidgets.QLineEdit(str(p[i])))
                e.setPlaceholderText(eixo)
                linha.addWidget(e)
                trio.append(e)
            self.campos.append(trio)
            caixa = QtWidgets.QWidget()
            caixa.setLayout(linha)
            self.form.addRow(rotulo, caixa)

        self.z = QtWidgets.QDoubleSpinBox()
        self.z.setRange(1.0, 1000.0)
        self.z.setValue(float(feed.impedance) if feed else 50.0)
        self.z.setSuffix(" Ohm")
        self.form.addRow("Impedancia", self.z)
        self.add_buttons()

    def resultado(self) -> tuple[list[str], list[str], float]:
        return (
            [e.text().strip() or "0" for e in self.campos[0]],
            [e.text().strip() or "0" for e in self.campos[1]],
            float(self.z.value()),
        )


# ----------------------------------------------------------------------
# parametro
# ----------------------------------------------------------------------


class NewParamDialog(_Dialog):
    """Um parametro novo, que vira linha na Parameter List do CST."""

    def __init__(self, parent=None):
        super().__init__(
            parent,
            "Novo parametro",
            "Vai para a Parameter List do CST com a descricao junto. "
            "Pode referenciar outros parametros: 0.25*Lambda, Gap/2, "
            "sqrt(2)*L_braco.",
        )
        self.nome = _mono(QtWidgets.QLineEdit("L_novo"))
        self.expr = _mono(QtWidgets.QLineEdit("10"))
        self.desc = QtWidgets.QLineEdit("")
        self.form.addRow("Nome", self.nome)
        self.form.addRow("Expressao", self.expr)
        self.form.addRow("Descricao", self.desc)
        self.add_buttons()

    def resultado(self) -> tuple[str, str, str]:
        return (
            self.nome.text().strip(),
            self.expr.text().strip() or "0",
            self.desc.text().strip(),
        )
