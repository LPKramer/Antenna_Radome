"""A linha de centro do fio: vertices como expressao, filete nao resolvido.

Este e o formato de intercambio do projeto. Cada vertice guarda a EXPRESSAO
(``"Gap/2 + Sec_inical"``), nao o numero -- e isso que permite o modelo continuar
parametrico dentro do CST, onde a calibracao final acontece.

O filete tambem nao vem resolvido: o CST o resolve com ``BlendCurve`` e o lado
CAD o resolve em core.geometry. Deixar cada lado resolver por conta propria e
deliberado; o teste de comprimento de arco e que prova que concordam.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .expr import ParamTable
from .geometry import Segment, path_length, resolve_path


@dataclass
class Vertex:
    """Um vertice da polilinha, em expressoes."""

    x: str
    y: str = "0"
    z: str = "0"
    fillet: str | None = None  # raio do filete NESTE vertice; None = canto vivo

    def coords(self, params: ParamTable) -> np.ndarray:
        return np.array(
            [params.evaluate(self.x), params.evaluate(self.y), params.evaluate(self.z)]
        )

    def radius(self, params: ParamTable) -> float:
        return 0.0 if self.fillet is None else params.evaluate(self.fillet)


@dataclass
class Centerline:
    """Uma polilinha filetada, com nome, formando um condutor continuo."""

    name: str
    vertices: list[Vertex] = field(default_factory=list)
    closed: bool = False

    def points(self, params: ParamTable) -> np.ndarray:
        return np.array([v.coords(params) for v in self.vertices])

    def radii(self, params: ParamTable) -> list[float]:
        return [v.radius(params) for v in self.vertices]

    def resolve(self, params: ParamTable) -> list[Segment]:
        """Retas e arcos exatos, ja com os filetes aplicados."""
        return resolve_path(self.points(params), self.radii(params), self.closed)

    def length(self, params: ParamTable) -> float:
        """Comprimento real do fio -- o numero que vai para o print card."""
        return path_length(self.resolve(params))

    def polyline_length(self, params: ParamTable) -> float:
        """Comprimento sem filete, util so para comparacao e diagnostico."""
        pts = self.points(params)
        if self.closed:
            pts = np.vstack([pts, pts[:1]])
        return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())

    def mirrored(self, name: str, axis: str) -> "Centerline":
        """Copia espelhada num plano coordenado, com as expressoes negadas.

        Preserva o parametrismo: nega a expressao em vez de negar o valor, para
        que o espelho continue seguindo o parametro quando ele muda no CST.
        """
        if axis not in ("x", "y", "z"):
            raise ValueError(f"eixo de espelho invalido: {axis!r}")
        out = []
        for v in self.vertices:
            comps = {"x": v.x, "y": v.y, "z": v.z}
            comps[axis] = _negate(comps[axis])
            out.append(Vertex(fillet=v.fillet, **comps))
        return Centerline(name=name, vertices=out, closed=self.closed)

    def reversed_(self, name: str | None = None) -> "Centerline":
        return Centerline(
            name=name or self.name,
            vertices=list(reversed(self.vertices)),
            closed=self.closed,
        )


def _negate(expr: str) -> str:
    """Nega uma expressao mantendo-a legivel na Parameter List do CST."""
    e = expr.strip()
    if e in ("0", "0.0", "-0"):
        return "0"
    if e.startswith("-(") and e.endswith(")"):
        return e[2:-1]
    if e.startswith("-") and _IS_SIMPLE(e[1:]):
        return e[1:]
    if _IS_SIMPLE(e):
        return f"-{e}"
    return f"-({e})"


def _IS_SIMPLE(e: str) -> bool:
    """True quando negar com um prefixo ``-`` nao muda a precedencia."""
    return e.replace("_", "").replace(".", "").isalnum()
