"""Canvas do editor: desenha a antena e o radome em escala real.

Trucke de renderizacao que economiza muito codigo: em vez de calcular o offset
2D do contorno do radome, a linha de centro e tracada com uma caneta de
espessura igual a secao da peca.  O tracado do Qt E a varredura do perfil, entao
o desenho ja sai correto -- inclusive nos filetes, onde um offset ingenuo erraria.

A mesma ideia serve para o canal do fio: outra caneta, com a espessura da bitola.
"""

from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..core.geometry import sample_path
from ..core.wireset import WireSet

# Passo de amostragem dos arcos, em mm.  Fino o bastante para o filete nao
# aparecer facetado em nenhum zoom razoavel.
STEP_MM = 0.15


class Palette:
    fundo = QtGui.QColor("#1b1d21")
    grade = QtGui.QColor("#2a2d33")
    eixo = QtGui.QColor("#3d424a")
    radome = QtGui.QColor(200, 205, 215, 70)
    radome_borda = QtGui.QColor(150, 158, 172, 130)
    cobre = QtGui.QColor("#d98a4f")
    parasita = QtGui.QColor("#8fa8c8")
    centro = QtGui.QColor(255, 255, 255, 90)
    vertice = QtGui.QColor("#f0c040")
    alimentacao = QtGui.QColor("#e05252")
    estacao = QtGui.QColor(120, 200, 160, 160)
    texto = QtGui.QColor("#c8ccd4")


class AntennaCanvas(QtWidgets.QGraphicsView):
    """Vista 2D da antena, com pan, zoom e selecao de vertice."""

    vertexPicked = QtCore.Signal(str, int)  # nome do fio, indice do vertice

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform
        )
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(Palette.fundo)
        # Y do mundo cresce para cima; o do Qt cresce para baixo.
        self.scale(1.0, -1.0)
        self._ws: WireSet | None = None
        self._picks: list[tuple[str, int, np.ndarray]] = []
        self._show_radome = True
        self._show_vertices = True
        # Enquadrar pelos itens incluiria a grade, que e bem maior que a antena
        # e deixaria a peca minuscula na tela.  Guarda so o retangulo da antena.
        self._content = QtCore.QRectF()

    # ------------------------------------------------------------------
    def set_wireset(self, ws: WireSet | None, keep_view: bool = True) -> str | None:
        """Redesenha. Devolve a mensagem de erro se a geometria for invalida."""
        self._ws = ws
        transform = self.transform()
        center = self.mapToScene(self.viewport().rect().center())
        err = self._rebuild()
        if keep_view and not self._scene.sceneRect().isEmpty():
            self.setTransform(transform)
            self.centerOn(center)
        return err

    def fit(self) -> None:
        r = self._content if not self._content.isEmpty() else self._scene.itemsBoundingRect()
        if r.isEmpty():
            return
        margem = max(r.width(), r.height()) * 0.06 + 2.0
        self.fitInView(
            r.adjusted(-margem, -margem, margem, margem), QtCore.Qt.KeepAspectRatio
        )

    def set_show_radome(self, on: bool) -> None:
        self._show_radome = on
        self._rebuild()

    def set_show_vertices(self, on: bool) -> None:
        self._show_vertices = on
        self._rebuild()

    # ------------------------------------------------------------------
    def _rebuild(self) -> str | None:
        self._scene.clear()
        self._picks.clear()
        self._content = QtCore.QRectF()
        if self._ws is None:
            return None

        ws = self._ws
        try:
            bitola = ws.params.evaluate(ws.conductor.bitola)
            parede = ws.params.evaluate(ws.radome.parede)
        except Exception as exc:
            self._draw_grid(100.0)
            return str(exc)

        secao = 2.0 * (bitola / 2.0 + ws.radome.folga + parede)
        canal = bitola + 2.0 * ws.radome.folga

        paths: list[tuple[str, str, QtGui.QPainterPath, np.ndarray]] = []
        erro: str | None = None
        for w in ws.wires:
            try:
                segs = w.centerline.resolve(ws.params)
                pts = sample_path(segs, STEP_MM)
                verts = w.centerline.points(ws.params)
            except Exception as exc:
                erro = f"{w.name}: {exc}"
                continue
            paths.append((w.name, w.role, _to_path(pts), verts))

        for _, _, path, _ in paths:
            self._content = self._content.united(
                path.boundingRect().adjusted(-secao / 2, -secao / 2, secao / 2, secao / 2)
            )

        extent = max(
            (float(np.abs(v).max()) for _, _, _, v in paths if len(v)), default=50.0
        )
        self._draw_grid(extent * 1.4)

        if self._show_radome:
            for _, _, path, _ in paths:
                self._stroke(path, Palette.radome, secao, QtCore.Qt.FlatCap)
                self._stroke(path, Palette.radome_borda, secao, QtCore.Qt.FlatCap, outline=True)

        for name, role, path, _ in paths:
            cor = Palette.cobre if role == "driven" else Palette.parasita
            self._stroke(path, QtGui.QColor(30, 30, 30, 120), canal, QtCore.Qt.RoundCap)
            self._stroke(path, cor, bitola, QtCore.Qt.RoundCap)
            self._stroke(path, Palette.centro, 0.0, QtCore.Qt.FlatCap, dashed=True)
            del name

        if self._show_vertices:
            for name, _, _, verts in paths:
                for i, v in enumerate(verts):
                    self._dot(v, Palette.vertice, 1.1)
                    self._picks.append((name, i, v[:2]))

        self._draw_feed(ws)
        self._scene.setSceneRect(self._scene.itemsBoundingRect())
        return erro

    def _stroke(self, path, color, width, cap, dashed=False, outline=False):
        pen = QtGui.QPen(color)
        pen.setWidthF(max(width, 0.0))
        pen.setCapStyle(cap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        if width <= 0:
            pen.setCosmetic(True)
            pen.setWidth(1)
        if dashed:
            pen.setStyle(QtCore.Qt.DashLine)
            pen.setDashPattern([6, 6])
        if outline:
            # So a borda: caneta fina sobre o mesmo tracado grosso, para o
            # contorno do radome ficar legivel sobre o fundo escuro.
            stroker = QtGui.QPainterPathStroker()
            stroker.setWidth(width)
            stroker.setCapStyle(cap)
            stroker.setJoinStyle(QtCore.Qt.RoundJoin)
            borda = QtGui.QPen(color)
            borda.setCosmetic(True)
            borda.setWidth(1)
            item = self._scene.addPath(stroker.createStroke(path), borda)
            item.setZValue(-5)
            return item
        item = self._scene.addPath(path, pen)
        item.setZValue(-10 if width > 1 else 5)
        return item

    def _dot(self, p, color, r: float):
        item = self._scene.addEllipse(
            float(p[0]) - r, float(p[1]) - r, 2 * r, 2 * r,
            QtGui.QPen(QtCore.Qt.NoPen), QtGui.QBrush(color),
        )
        item.setZValue(20)
        return item

    def _draw_feed(self, ws: WireSet) -> None:
        if ws.feed is None:
            return
        try:
            p1 = [ws.params.evaluate(c) for c in ws.feed.p1]
            p2 = [ws.params.evaluate(c) for c in ws.feed.p2]
        except Exception:
            return
        pen = QtGui.QPen(Palette.alimentacao)
        pen.setCosmetic(True)
        pen.setWidth(2)
        item = self._scene.addLine(p1[0], p1[1], p2[0], p2[1], pen)
        item.setZValue(30)
        for p in (p1, p2):
            self._dot(p, Palette.alimentacao, 0.8).setZValue(31)

    def _draw_grid(self, extent: float) -> None:
        extent = max(extent, 10.0)
        passo = _nice_step(extent / 6.0)
        n = int(extent / passo) + 1
        pen = QtGui.QPen(Palette.grade)
        pen.setCosmetic(True)
        for k in range(-n, n + 1):
            x = k * passo
            for a, b in (((x, -extent), (x, extent)), ((-extent, x), (extent, x))):
                item = self._scene.addLine(a[0], a[1], b[0], b[1], pen)
                item.setZValue(-100)
        eixo = QtGui.QPen(Palette.eixo)
        eixo.setCosmetic(True)
        eixo.setWidth(2)
        self._scene.addLine(-extent, 0, extent, 0, eixo).setZValue(-99)
        self._scene.addLine(0, -extent, 0, extent, eixo).setZValue(-99)

    # ------------------------------------------------------------------
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        f = 1.0015 ** event.angleDelta().y()
        self.scale(f, f)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        p = self.mapToScene(event.position().toPoint())
        alvo = np.array([p.x(), p.y()])
        melhor, dist = None, float("inf")
        for name, i, v in self._picks:
            d = float(np.linalg.norm(v - alvo))
            if d < dist:
                melhor, dist = (name, i), d
        # Tolerancia em pixels, convertida para o mundo, para o clique ter a
        # mesma sensibilidade em qualquer zoom.
        tol = 12.0 / max(abs(self.transform().m11()), 1e-6)
        if melhor and dist <= tol:
            self.vertexPicked.emit(*melhor)
        super().mouseDoubleClickEvent(event)


def _to_path(pts: np.ndarray) -> QtGui.QPainterPath:
    path = QtGui.QPainterPath()
    path.moveTo(float(pts[0][0]), float(pts[0][1]))
    for p in pts[1:]:
        path.lineTo(float(p[0]), float(p[1]))
    return path


def _nice_step(raw: float) -> float:
    """Arredonda o passo da grade para 1, 2, 5 x 10^n."""
    if raw <= 0:
        return 1.0
    import math

    exp = math.floor(math.log10(raw))
    base = raw / (10**exp)
    nice = 1.0 if base < 1.5 else 2.0 if base < 3.5 else 5.0 if base < 7.5 else 10.0
    return nice * (10**exp)
