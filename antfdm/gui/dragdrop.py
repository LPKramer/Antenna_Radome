"""Arrastar um bloco da paleta e soltar na antena.

O gesto que faltava.  Antes, acrescentar um bloco custava quatro passos: abrir o
Avancado, achar o fio na arvore, selecionar, clicar num botao.  Agora e um
arrasto -- a ponta mais proxima acende, um fantasma mostra o resultado, e soltar
encaixa.

Os icones da paleta sao gerados CONSTRUINDO cada bloco com seus valores padrao.
O desenho na ficha e, literalmente, o que vai aparecer na antena; nao ha imagem
para manter em sincronia com o codigo.
"""

from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui

from ..blocks import BlockError, Cursor, build_chain
from ..core.centerline import Centerline
from ..core.expr import ParamTable

MIME = "application/x-antfdm-bloco"

# Alcance do encaixe, em pixels: ao arrastar a mira e grossa, e exigir precisao
# de pixel derrubaria o gesto.
ALCANCE_PX = 45.0

# Nome do bloco em portugues.  O usuario nao precisa aprender 'straight' e 'vee'
# para desenhar uma antena.
NOMES = {
    "straight": "reta",
    "bend": "dobra",
    "vee": "corcova",
    "meander": "serpentina",
    "arc": "curva",
    "spiral": "espiral",
    "taper": "abertura",
    "jump": "salto",
}


def nome_amigavel(tipo: str) -> str:
    return NOMES.get(tipo, tipo)


def _pontos_do_bloco(tipo: str) -> np.ndarray | None:
    """Geometria de uma amostra do bloco, para desenhar a ficha e o fantasma.

    Tenta com uma reta antes e outra depois, que e como o bloco aparece de fato
    no meio de um fio.  Blocos que exigem ser os primeiros caem no plano B.
    """
    from .inspector import default_block

    padrao = default_block(tipo)
    tentativas = (
        [{"type": "straight", "len": "8"}, padrao, {"type": "straight", "len": "8"}],
        [{"type": "straight", "len": "8"}, padrao],
        [padrao],
    )
    for blocos in tentativas:
        try:
            verts = build_chain(blocos, Cursor())
        except (BlockError, ValueError):
            continue
        try:
            cl = Centerline(name="i", vertices=verts)
            segs = cl.resolve(ParamTable())
        except Exception:
            continue
        from ..core.geometry import sample_path

        pts = sample_path(segs, 0.4)
        if len(pts) >= 2:
            return pts[:, :2]
    return None


def icone_do_bloco(tipo: str, largura: int = 64, altura: int = 34) -> QtGui.QPixmap:
    """Miniatura do bloco, desenhada a partir da geometria real dele."""
    pm = QtGui.QPixmap(largura, altura)
    pm.fill(QtCore.Qt.transparent)
    pts = _pontos_do_bloco(tipo)
    if pts is None or len(pts) < 2:
        return pm

    lo, hi = pts.min(axis=0), pts.max(axis=0)
    tam = np.maximum(hi - lo, 1e-6)
    margem = 5.0
    escala = min((largura - 2 * margem) / tam[0], (altura - 2 * margem) / tam[1])
    centro = (lo + hi) / 2.0

    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    caneta = QtGui.QPen(QtGui.QColor("#d98a4f"))
    caneta.setWidthF(2.2)
    caneta.setCapStyle(QtCore.Qt.RoundCap)
    caneta.setJoinStyle(QtCore.Qt.RoundJoin)
    p.setPen(caneta)

    caminho = QtGui.QPainterPath()
    for i, ponto in enumerate(pts):
        # Y da tela cresce para baixo; o do mundo cresce para cima.
        x = largura / 2.0 + (ponto[0] - centro[0]) * escala
        y = altura / 2.0 - (ponto[1] - centro[1]) * escala
        caminho.moveTo(x, y) if i == 0 else caminho.lineTo(x, y)
    p.drawPath(caminho)
    p.end()
    return pm


def pontos_do_fantasma(tipo: str, origem, rumo_graus: float) -> np.ndarray | None:
    """Onde o bloco vai cair se for solto naquela ponta, em coordenadas do mundo.

    Constroi so o bloco (sem as retas de contexto do icone) partindo da ponta,
    para o fantasma mostrar exatamente o que sera anexado.
    """
    from .inspector import default_block

    o = np.asarray(origem, dtype=float)[:2]
    padrao = default_block(tipo)
    for blocos in ([padrao], [{"type": "straight", "len": "8"}, padrao]):
        try:
            verts = build_chain(
                blocos,
                Cursor(x=str(float(o[0])), y=str(float(o[1])),
                       heading=str(float(rumo_graus))),
            )
            segs = Centerline(name="f", vertices=verts).resolve(ParamTable())
        except (BlockError, ValueError, Exception):
            continue
        from ..core.geometry import sample_path

        pts = sample_path(segs, 0.5)
        if len(pts) >= 2:
            return pts[:, :2]
    return None


def mime_do_bloco(tipo: str) -> QtCore.QMimeData:
    dados = QtCore.QMimeData()
    dados.setData(MIME, tipo.encode("utf-8"))
    dados.setText(nome_amigavel(tipo))
    return dados


def tipo_do_mime(dados: QtCore.QMimeData) -> str | None:
    if not dados.hasFormat(MIME):
        return None
    return bytes(dados.data(MIME)).decode("utf-8")
