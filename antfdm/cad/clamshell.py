"""Radome clamshell: duas metades que prendem o fio esmaltado.

O trabalho da peca e um so -- segurar o fio -- e o gerador foi reduzido a isso.
Sairam pinos, orelhas periodicas, alojamento de coax e gravacao: eram sete
conceitos e onze ajustes para uma peca que precisa de tres.

Decisoes que sobraram, e o porque de cada uma:

* **Corte em Z=0.**  A antena e planar e deitada, entao o plano de corte deixa as
  duas metades com uma face plana grande.  Cada uma imprime com essa face na mesa
  e o meio-canal virado para cima -- um vale, nao um balanco.  Sem suporte.

* **Corpo estreito, e o parafuso em aba no eixo.**  Alargar a fita inteira
  pareceu mais simples, mas nao passa em filete apertado: com meia-largura maior
  que o raio da curva a face interna se auto-intersecta.  A saida foi por a aba
  ALEM da ponta do fio, sobre o proprio eixo -- ali o caminho e reto por
  definicao, e nao ha curva para atrapalhar.

* **Conexao automatica.**  Elementos parasitas sao fios desconectados e os dois
  bracos de um dipolo tambem nao se tocam: sem ligacao a peca sai da impressora
  em varios pedacos soltos, e o Gap -- dimensao calibrada -- nao fica garantido.
  Em vez de "boom" e "ponte" como conceitos separados, ha uma regra so: se o
  solido saiu em mais de uma parte, liga as mais proximas ate virar uma.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import build123d as bd
import numpy as np

from ..core.geometry import path_length
from ..core.wireset import WireSet
from . import sweep as sw


class ClamshellError(ValueError):
    pass


@dataclass
class ClamshellOptions:
    """Tres ajustes e uma chave. Ver o teste que trava esse numero."""

    parafuso_passante: float = 3.4  # furo na metade de cima (M3 folgado)
    parafuso_guia: float = 2.5  # furo na metade de baixo (M3 auto-atarraxante)
    conectar: bool = True  # liga pedacos soltos numa peca so


@dataclass
class Clamshell:
    top: bd.Part
    bottom: bd.Part
    section_w: float
    section_h: float
    channel_r: float
    stats: dict = field(default_factory=dict)


def _union(parts: Iterable[bd.Part]) -> bd.Part:
    out = None
    for p in parts:
        out = p if out is None else out + p
    if out is None:
        raise ClamshellError("nada para unir")
    return out


def _cyl(centro, diametro: float, z0: float, z1: float) -> bd.Part:
    loc = bd.Location((float(centro[0]), float(centro[1]), z0))
    return loc * bd.Cylinder(
        diametro / 2.0, z1 - z0,
        align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN),
    )


def build(ws: WireSet, opts: ClamshellOptions | None = None) -> Clamshell:
    """Gera as duas metades do radome para a antena inteira."""
    opts = opts or ClamshellOptions()
    problemas = ws.validate()
    if problemas:
        raise ClamshellError("a antena tem problemas:\n  - " + "\n  - ".join(problemas))

    bitola = ws.params.evaluate(ws.conductor.bitola)
    parede = ws.params.evaluate(ws.radome.parede)
    r_canal = bitola / 2.0 + ws.radome.folga
    altura = 2.0 * (r_canal + parede)
    largura = altura  # fita quadrada; o parafuso vai nas abas, fora da curva
    aba_d = opts.parafuso_passante + 4.0 * parede

    caminhos = {}
    for w in ws.wires:
        sw.check_profile_fits(w.centerline, ws.params, largura / 2.0)
        caminhos[w.name] = (
            w.centerline.resolve(ws.params),
            sw.path_of(w.centerline, ws.params),
        )

    corpos = [sw.sweep_rect(p, largura, altura) for _, p in caminhos.values()]
    canais = [sw.sweep_circle(p, r_canal) for _, p in caminhos.values()]

    abas, furos = _abas(caminhos, aba_d, altura)
    solido = _union(corpos + abas)
    ligacoes = 0
    if opts.conectar:
        solido, ligacoes = _conectar(solido, largura / 2.0, altura)

    casca = solido - _union(canais)

    topo = bd.split(casca, bisect_by=bd.Plane.XY, keep=bd.Keep.TOP)
    base = bd.split(casca, bisect_by=bd.Plane.XY, keep=bd.Keep.BOTTOM)

    for centro in furos:
        topo = topo - _cyl(centro, opts.parafuso_passante, -0.1, altura)
        base = base - _cyl(centro, opts.parafuso_guia, -altura, 0.1)

    return Clamshell(
        top=topo, bottom=base, section_w=largura, section_h=altura,
        channel_r=r_canal,
        stats={
            "secao_mm": f"{largura:.1f} x {altura:.1f}",
            "raio_canal_mm": r_canal,
            "parafusos": len(furos),
            "ligacoes": ligacoes,
            "volume_topo_mm3": float(topo.volume),
            "volume_base_mm3": float(base.volume),
        },
    )


def _conectar(solido: bd.Part, meia_largura: float, altura: float):
    """Liga pedacos soltos ate a peca sair inteira.

    Substitui "boom" e "ponte": em vez de duas features com regras proprias, uma
    regra so, que cobre o gap do dipolo e o boom da Yagi pelo mesmo caminho.
    """
    ligacoes = 0
    for _ in range(20):  # limite: antena com mais pedacos que isso e outra coisa
        pedacos = solido.solids()
        if len(pedacos) <= 1:
            break
        centros = [np.array(p.center().to_tuple()[:2]) for p in pedacos]
        melhor = None
        for i in range(len(centros)):
            for j in range(i + 1, len(centros)):
                d = float(np.linalg.norm(centros[i] - centros[j]))
                if melhor is None or d < melhor[0]:
                    melhor = (d, i, j)
        if melhor is None:
            break
        _, i, j = melhor
        solido = solido + _barra(centros[i], centros[j], meia_largura, altura)
        ligacoes += 1
    return solido, ligacoes


def _barra(a: np.ndarray, b: np.ndarray, meia_largura: float, altura: float) -> bd.Part:
    """Barra reta de ``a`` a ``b``, larga o bastante para nao virar um fio de nylon."""
    d = b - a
    comprimento = float(np.linalg.norm(d)) + 2.0 * meia_largura
    angulo = float(np.degrees(np.arctan2(d[1], d[0])))
    meio = (a + b) / 2.0
    plano = bd.Plane(origin=(float(meio[0]), float(meio[1]), 0.0)).rotated(
        (0, 0, angulo)
    )
    return plano * bd.Box(
        comprimento, max(meia_largura, 3.0), altura, align=bd.Align.CENTER
    )


def _abas(caminhos, aba_d: float, altura: float):
    """Uma aba redonda alem de cada ponta de fio, com o furo do parafuso.

    Sobre o eixo do caminho, e nao ao lado: ali o fio ja acabou, entao nao ha
    canal nem curva -- e a aba pode ser mais larga que a fita sem se auto-cortar.
    """
    from ..core.geometry import frame_at

    solidos: list[bd.Part] = []
    furos: list[np.ndarray] = []
    for segs, _ in caminhos.values():
        total = path_length(segs)
        for s, sentido in ((0.0, -1.0), (total, 1.0)):
            ponto, tangente = frame_at(segs, s)
            # Recuo menor que o raio, para a aba SOBREPOR o corpo.  Encostar
            # tangencialmente nao une os solidos, e a peca sairia em pedacos.
            centro = (ponto + tangente * sentido * (aba_d * 0.35))[:2]
            loc = bd.Location((float(centro[0]), float(centro[1]), 0.0))
            solidos.append(
                loc * bd.Cylinder(aba_d / 2.0, altura, align=bd.Align.CENTER)
            )
            furos.append(centro)
    return solidos, furos
