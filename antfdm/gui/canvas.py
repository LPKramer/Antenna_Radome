"""Canvas do editor: desenha a antena e o radome em escala real.

Truque de renderizacao que economiza muito codigo: em vez de calcular o offset
2D do contorno do radome, a linha de centro e tracada com uma caneta de
espessura igual a secao da peca.  O tracado do Qt E a varredura do perfil, entao
o desenho ja sai correto -- inclusive nos filetes, onde um offset ingenuo erraria.

**A cena e incremental.**  A primeira versao chamava ``scene.clear()`` e recriava
todos os itens a cada quadro: 117 ms num dipolo.  Por causa disso o arrasto so
aplicava ao SOLTAR, e a ferramenta parecia morta.  Agora ha um item por fio e o
que muda e o caminho dentro dele; a grade tambem virou um item so, com todas as
linhas num unico caminho.

Durante o arrasto entra o **modo leve**: sem os pontos dos vertices e sem o
contorno do radome.  Ninguem olha o contorno enquanto puxa um ponto, e sem eles
o quadro cabe no orcamento de 16 ms.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..core.geometry import sample_path
from ..core.wireset import WireSet

# Amostragem minima, em mm.  O passo real acompanha o zoom: nao adianta gerar um
# ponto a cada 0.15 mm quando um pixel na tela vale 2 mm.
STEP_MIN_MM = 0.15
STEP_PX = 0.8

# Movimento em pixels acima do qual o gesto vira arrasto em vez de clique.
LIMIAR_ARRASTO = 4


class Palette:
    fundo = QtGui.QColor("#1b1d21")
    grade = QtGui.QColor("#2a2d33")
    eixo = QtGui.QColor("#3d424a")
    radome = QtGui.QColor(200, 205, 215, 70)
    cobre = QtGui.QColor("#d98a4f")
    parasita = QtGui.QColor("#8fa8c8")
    centro = QtGui.QColor(255, 255, 255, 90)
    vertice = QtGui.QColor("#f0c040")
    alimentacao = QtGui.QColor("#e05252")
    fantasma = QtGui.QColor(126, 224, 160, 220)
    texto = QtGui.QColor("#c8ccd4")


class _ItensDoFio:
    """Itens persistentes de um fio. Trocar o caminho basta para redesenhar."""

    __slots__ = ("radome", "canal", "cobre", "centro", "pontos")

    def __init__(self, cena: QtWidgets.QGraphicsScene):
        def caminho(z: float) -> QtWidgets.QGraphicsPathItem:
            item = cena.addPath(QtGui.QPainterPath())
            item.setZValue(z)
            return item

        self.radome = caminho(-20)
        self.canal = caminho(-5)
        self.cobre = caminho(0)
        self.centro = caminho(5)
        self.pontos = caminho(20)

    def todos(self):
        return (self.radome, self.canal, self.cobre, self.centro, self.pontos)


class AntennaCanvas(QtWidgets.QGraphicsView):
    """Vista 2D da antena. O gesto decide a acao; nao ha botao de modo.

    apertar e arrastar no vazio -> desenha um fio, acompanhando o cursor
    apertar e arrastar num alvo -> move aquele alvo, ao vivo
    botao do meio (ou Shift)    -> move a vista
    """

    cliqueEm = QtCore.Signal(float, float, bool)  # x, y (mm), livre (Alt)
    arrastoIniciado = QtCore.Signal(float, float, bool)
    arrastoMovido = QtCore.Signal(float, float, bool)
    arrastoSolto = QtCore.Signal(float, float, bool)
    cursorEm = QtCore.Signal(float, float)
    escPressionado = QtCore.Signal()
    blocoSolto = QtCore.Signal(str, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QtGui.QPainter.Antialiasing)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(Palette.fundo)
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        # Y do mundo cresce para cima; o do Qt cresce para baixo.
        self.scale(1.0, -1.0)

        self._ws: WireSet | None = None
        self._itens: dict[str, _ItensDoFio] = {}
        self._grade: QtWidgets.QGraphicsPathItem | None = None
        self._eixos: QtWidgets.QGraphicsPathItem | None = None
        self._regua: list[QtWidgets.QGraphicsItem] = []
        self._feed: list[QtWidgets.QGraphicsItem] = []
        self._realce: QtWidgets.QGraphicsItem | None = None
        self._fantasma: QtWidgets.QGraphicsPathItem | None = None
        self._legenda: QtWidgets.QGraphicsSimpleTextItem | None = None

        self._picks: list[tuple[str, int, np.ndarray]] = []
        self._content = QtCore.QRectF()
        self._lambda_mm: float | None = None
        self._extent_grade = 0.0
        self._show_radome = True
        self._show_vertices = True
        self._leve = False

        self._press: QtCore.QPoint | None = None
        self._press_mundo: tuple[float, float] | None = None
        self._arrastando = False
        self._panning = False
        self._hit_test = None
        self._encaixe = None

    # ------------------------------------------------------------------
    def set_hit_test(self, fn) -> None:
        self._hit_test = fn

    def set_encaixe(self, fn) -> None:
        self._encaixe = fn

    def set_lambda(self, lam: float | None) -> None:
        self._lambda_mm = lam
        self._desenhar_regua()

    def set_show_radome(self, on: bool) -> None:
        self._show_radome = on
        self.atualizar()

    def set_show_vertices(self, on: bool) -> None:
        self._show_vertices = on
        self.atualizar()

    def scene(self) -> QtWidgets.QGraphicsScene:
        return self._scene

    # ------------------------------------------------------------------
    def set_wireset(self, ws: WireSet | None, keep_view: bool = True) -> str | None:
        del keep_view  # cena incremental: a vista nunca mais e perturbada
        self._ws = ws
        return self.atualizar()

    def modo_leve(self, on: bool) -> None:
        """Durante o arrasto some o que e caro e ninguem esta olhando."""
        if self._leve == on:
            return
        self._leve = on
        self.atualizar()

    def _passo(self) -> float:
        """Amostragem acompanhando o zoom: um ponto a cada ~0.8 pixel.

        No modo leve o passo triplica: durante o arrasto ninguem repara em
        suavidade sub-pixel, e a espiral -- com 1094 vertices -- so cabe no
        orcamento de quadro assim.
        """
        escala = max(abs(self.transform().m11()), 1e-6)
        px = STEP_PX * 3.0 if self._leve else STEP_PX
        return max(STEP_MIN_MM, px / escala)

    def atualizar(self) -> str | None:
        if self._ws is None:
            for itens in self._itens.values():
                for i in itens.todos():
                    self._scene.removeItem(i)
            self._itens.clear()
            self._content = QtCore.QRectF()
            self._picks.clear()
            self._limpar(self._feed)
            return None

        ws = self._ws
        try:
            bitola = ws.params.evaluate(ws.conductor.bitola)
            parede = ws.params.evaluate(ws.radome.parede)
        except Exception as exc:
            return str(exc)

        secao = 2.0 * (bitola / 2.0 + ws.radome.folga + parede)
        canal = bitola + 2.0 * ws.radome.folga
        passo = self._passo()

        self._picks.clear()
        conteudo = QtCore.QRectF()
        vivos: set[str] = set()
        erro: str | None = None

        for w in ws.wires:
            try:
                segs = w.centerline.resolve(ws.params)
                pts = sample_path(segs, passo)
                verts = w.centerline.points(ws.params)
            except Exception as exc:
                erro = f"{w.name}: {exc}"
                continue

            vivos.add(w.name)
            itens = self._itens.get(w.name)
            if itens is None:
                itens = self._itens[w.name] = _ItensDoFio(self._scene)

            caminho = _to_path(pts)
            cor = Palette.cobre if w.role == "driven" else Palette.parasita

            mostrar_radome = self._show_radome and not self._leve
            _por(itens.radome, caminho if mostrar_radome else None,
                 Palette.radome, secao, QtCore.Qt.FlatCap)
            _por(itens.canal, caminho, QtGui.QColor(30, 30, 30, 120), canal,
                 QtCore.Qt.RoundCap)
            _por(itens.cobre, caminho, cor, bitola, QtCore.Qt.RoundCap)
            _por(itens.centro, caminho, Palette.centro, 0, QtCore.Qt.FlatCap,
                 tracejado=True)
            if self._show_vertices and not self._leve:
                _por(itens.pontos, _pontos(verts, max(bitola * 0.75, 0.6)),
                     Palette.vertice, 0, QtCore.Qt.RoundCap, preenchido=True)
            else:
                itens.pontos.setPath(QtGui.QPainterPath())

            for i, v in enumerate(verts):
                self._picks.append((w.name, i, v[:2]))
            conteudo = conteudo.united(
                caminho.boundingRect().adjusted(-secao, -secao, secao, secao)
            )

        for nome in [n for n in self._itens if n not in vivos]:
            for i in self._itens.pop(nome).todos():
                self._scene.removeItem(i)

        self._content = conteudo
        self._desenhar_grade(conteudo)
        self._desenhar_regua()
        self._desenhar_feed(ws)
        return erro

    def _desenhar_grade(self, conteudo: QtCore.QRectF) -> None:
        extent = max(abs(conteudo.left()), abs(conteudo.right()),
                     abs(conteudo.top()), abs(conteudo.bottom()), 50.0) * 1.4
        # So refaz quando a antena cresce de verdade; a grade nao muda por quadro.
        if self._grade is not None and 0.7 < extent / max(self._extent_grade, 1e-9) < 1.4:
            return
        self._extent_grade = extent

        passo = _passo_bonito(extent / 6.0)
        n = int(extent / passo) + 1
        caminho = QtGui.QPainterPath()
        for k in range(-n, n + 1):
            x = k * passo
            caminho.moveTo(x, -extent)
            caminho.lineTo(x, extent)
            caminho.moveTo(-extent, x)
            caminho.lineTo(extent, x)

        caneta = QtGui.QPen(Palette.grade)
        caneta.setCosmetic(True)
        if self._grade is None:
            self._grade = self._scene.addPath(caminho, caneta)
            self._grade.setZValue(-100)
        else:
            self._grade.setPath(caminho)

        eixos = QtGui.QPainterPath()
        eixos.moveTo(-extent, 0)
        eixos.lineTo(extent, 0)
        eixos.moveTo(0, -extent)
        eixos.lineTo(0, extent)
        caneta_eixo = QtGui.QPen(Palette.eixo)
        caneta_eixo.setCosmetic(True)
        caneta_eixo.setWidth(2)
        if self._eixos is None:
            self._eixos = self._scene.addPath(eixos, caneta_eixo)
            self._eixos.setZValue(-99)
        else:
            self._eixos.setPath(eixos)

    def _desenhar_regua(self) -> None:
        self._limpar(self._regua)
        if not self._lambda_mm or self._content.isEmpty():
            return
        meia = self._lambda_mm / 2.0
        y = self._content.bottom() + max(self._content.height() * 0.3, 8.0)
        caneta = QtGui.QPen(QtGui.QColor(140, 150, 165, 200))
        caneta.setCosmetic(True)
        caminho = QtGui.QPainterPath()
        caminho.moveTo(-meia / 2, y)
        caminho.lineTo(meia / 2, y)
        for x in (-meia / 2, meia / 2):
            caminho.moveTo(x, y - 2)
            caminho.lineTo(x, y + 2)
        item = self._scene.addPath(caminho, caneta)
        item.setZValue(-50)
        self._regua.append(item)

        texto = self._scene.addSimpleText(f"lambda/2 = {meia:.0f} mm")
        texto.setBrush(QtGui.QBrush(QtGui.QColor(140, 150, 165)))
        texto.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations, True)
        texto.setPos(-meia / 2, y)
        texto.setZValue(-50)
        self._regua.append(texto)

    def _desenhar_feed(self, ws: WireSet) -> None:
        self._limpar(self._feed)
        if ws.feed is None:
            return
        try:
            p1 = [ws.params.evaluate(c) for c in ws.feed.p1]
            p2 = [ws.params.evaluate(c) for c in ws.feed.p2]
        except Exception:
            return
        caneta = QtGui.QPen(Palette.alimentacao)
        caneta.setCosmetic(True)
        caneta.setWidth(2)
        linha = self._scene.addLine(p1[0], p1[1], p2[0], p2[1], caneta)
        linha.setZValue(30)
        self._feed.append(linha)
        for p in (p1, p2):
            r = 0.8
            ponto = self._scene.addEllipse(
                p[0] - r, p[1] - r, 2 * r, 2 * r,
                QtGui.QPen(QtCore.Qt.NoPen), QtGui.QBrush(Palette.alimentacao),
            )
            ponto.setZValue(31)
            self._feed.append(ponto)

    def _limpar(self, itens: list) -> None:
        for i in itens:
            try:
                self._scene.removeItem(i)
            except RuntimeError:
                pass
        itens.clear()

    # ------------------------------------------------------------------
    def destacar(self, ponto, tipo: str = "vertice") -> None:
        if self._realce is not None:
            try:
                self._scene.removeItem(self._realce)
            except RuntimeError:
                pass
            self._realce = None
        if ponto is None:
            return
        cor = {
            "ponta": QtGui.QColor("#7ee0a0"),
            "vertice": QtGui.QColor("#f0c040"),
            "aresta": QtGui.QColor("#e0a052"),
        }.get(tipo, Palette.vertice)
        r = 2.4
        caneta = QtGui.QPen(cor)
        caneta.setCosmetic(True)
        caneta.setWidth(2)
        self._realce = self._scene.addEllipse(
            float(ponto[0]) - r, float(ponto[1]) - r, 2 * r, 2 * r,
            caneta, QtGui.QBrush(QtGui.QColor(cor.red(), cor.green(), cor.blue(), 70)),
        )
        self._realce.setZValue(40)

    def mostrar_fantasma(self, pontos) -> None:
        if self._fantasma is None:
            caneta = QtGui.QPen(Palette.fantasma)
            caneta.setCosmetic(True)
            caneta.setWidth(3)
            caneta.setStyle(QtCore.Qt.DashLine)
            self._fantasma = self._scene.addPath(QtGui.QPainterPath(), caneta)
            self._fantasma.setZValue(50)
        if pontos is None or len(pontos) < 2:
            self._fantasma.setPath(QtGui.QPainterPath())
            return
        self._fantasma.setPath(_to_path(np.asarray(pontos)))

    def legenda(self, texto: str, ponto=None) -> None:
        """Leitura ao vivo junto ao cursor, enquanto arrasta."""
        if self._legenda is None:
            self._legenda = self._scene.addSimpleText("")
            self._legenda.setBrush(QtGui.QBrush(QtGui.QColor("#e8ecf2")))
            self._legenda.setFlag(
                QtWidgets.QGraphicsItem.ItemIgnoresTransformations, True
            )
            self._legenda.setZValue(60)
        self._legenda.setText(texto or "")
        if ponto is not None:
            self._legenda.setPos(float(ponto[0]), float(ponto[1]))
        self._legenda.setVisible(bool(texto))

    # ------------------------------------------------------------------
    def fit(self) -> None:
        r = self._content if not self._content.isEmpty() else self._scene.itemsBoundingRect()
        if r.isEmpty():
            return
        margem = max(r.width(), r.height()) * 0.08 + 4.0
        self.fitInView(
            r.adjusted(-margem, -margem, margem, margem), QtCore.Qt.KeepAspectRatio
        )
        self.atualizar()

    def tolerancia_mm(self, pixels: float = 12.0) -> float:
        return pixels / max(abs(self.transform().m11()), 1e-6)

    def _mundo(self, pos) -> tuple[float, float]:
        p = self.mapToScene(pos)
        return p.x(), p.y()

    # ------------------------------------------------------------------
    # gestos
    # ------------------------------------------------------------------
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        pan = event.button() == QtCore.Qt.MiddleButton or (
            event.button() == QtCore.Qt.LeftButton
            and bool(event.modifiers() & QtCore.Qt.ShiftModifier)
        )
        if pan:
            # A vista se move com o botao do meio (ou Shift): o esquerdo desenha.
            self._panning = True
            self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
            super().mousePressEvent(
                QtGui.QMouseEvent(
                    QtCore.QEvent.MouseButtonPress, event.position(),
                    QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                )
            )
            return
        if event.button() != QtCore.Qt.LeftButton:
            return super().mousePressEvent(event)

        self._press = event.position().toPoint()
        self._press_mundo = self._mundo(self._press)
        self._arrastando = False

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._panning:
            return super().mouseMoveEvent(event)
        pos = event.position().toPoint()
        x, y = self._mundo(pos)
        livre = bool(event.modifiers() & QtCore.Qt.AltModifier)

        if self._press is not None:
            if not self._arrastando:
                if (pos - self._press).manhattanLength() <= LIMIAR_ARRASTO:
                    return
                self._arrastando = True
                self.modo_leve(True)
                self.arrastoIniciado.emit(
                    self._press_mundo[0], self._press_mundo[1], livre
                )
            self.arrastoMovido.emit(x, y, livre)
            return
        super().mouseMoveEvent(event)
        self.cursorEm.emit(x, y)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._panning:
            self._panning = False
            self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
            super().mouseReleaseEvent(event)
            self.atualizar()
            return
        if event.button() != QtCore.Qt.LeftButton or self._press is None:
            return super().mouseReleaseEvent(event)

        x, y = self._mundo(event.position().toPoint())
        livre = bool(event.modifiers() & QtCore.Qt.AltModifier)
        arrastava = self._arrastando
        self._press = self._press_mundo = None
        self._arrastando = False

        if arrastava:
            self.modo_leve(False)
            self.legenda("")
            self.arrastoSolto.emit(x, y, livre)
        else:
            self.cliqueEm.emit(x, y, livre)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        f = 1.0015 ** event.angleDelta().y()
        self.scale(f, f)
        self.atualizar()  # a amostragem acompanha o zoom

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key_Escape:
            self.escPressionado.emit()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        self._press = None
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        from .dragdrop import tipo_do_mime

        if tipo_do_mime(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        from .dragdrop import pontos_do_fantasma, tipo_do_mime

        tipo = tipo_do_mime(event.mimeData())
        if not tipo:
            return
        event.acceptProposedAction()
        x, y = self._mundo(event.position().toPoint())
        destino = self._encaixe(x, y) if self._encaixe else None
        if destino is None:
            self.destacar(None)
            self.mostrar_fantasma(pontos_do_fantasma(tipo, (x, y), 0.0))
            return
        _fio, ponto, rumo = destino
        self.destacar(ponto, "ponta")
        self.mostrar_fantasma(pontos_do_fantasma(tipo, ponto, rumo))

    def dragLeaveEvent(self, event) -> None:
        del event
        self.mostrar_fantasma(None)
        self.destacar(None)

    def dropEvent(self, event) -> None:
        from .dragdrop import tipo_do_mime

        tipo = tipo_do_mime(event.mimeData())
        self.mostrar_fantasma(None)
        self.destacar(None)
        if not tipo:
            return
        event.acceptProposedAction()
        x, y = self._mundo(event.position().toPoint())
        self.blocoSolto.emit(tipo, x, y)


# --------------------------------------------------------------------------


def _por(item, caminho, cor, espessura, cap, tracejado=False, preenchido=False):
    """Configura um item persistente. ``caminho`` None apaga o desenho dele."""
    if caminho is None:
        item.setPath(QtGui.QPainterPath())
        return
    if preenchido:
        item.setPen(QtGui.QPen(QtCore.Qt.NoPen))
        item.setBrush(QtGui.QBrush(cor))
        item.setPath(caminho)
        return
    caneta = QtGui.QPen(cor)
    if espessura > 0:
        caneta.setWidthF(espessura)
    else:
        caneta.setCosmetic(True)
        caneta.setWidth(1)
    caneta.setCapStyle(cap)
    caneta.setJoinStyle(QtCore.Qt.RoundJoin)
    if tracejado:
        caneta.setStyle(QtCore.Qt.DashLine)
        caneta.setDashPattern([6, 6])
    item.setPen(caneta)
    item.setBrush(QtGui.QBrush(QtCore.Qt.NoBrush))
    item.setPath(caminho)


def _to_path(pts: np.ndarray) -> QtGui.QPainterPath:
    path = QtGui.QPainterPath()
    if len(pts) == 0:
        return path
    path.moveTo(float(pts[0][0]), float(pts[0][1]))
    for p in pts[1:]:
        path.lineTo(float(p[0]), float(p[1]))
    return path


def _pontos(verts: np.ndarray, r: float) -> QtGui.QPainterPath:
    """Todos os vertices num caminho so, em vez de um item por ponto.

    A espiral tem 547 vertices; 547 itens de cena custavam mais que a antena.
    """
    path = QtGui.QPainterPath()
    for v in verts:
        path.addEllipse(QtCore.QPointF(float(v[0]), float(v[1])), r, r)
    return path


def _passo_bonito(raw: float) -> float:
    """Arredonda o passo da grade para 1, 2, 5 x 10^n."""
    if raw <= 0:
        return 1.0
    exp = math.floor(math.log10(raw))
    base = raw / (10**exp)
    nice = 1.0 if base < 1.5 else 2.0 if base < 3.5 else 5.0 if base < 7.5 else 10.0
    return nice * (10**exp)
