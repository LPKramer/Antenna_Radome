"""Ponte entre a linha de centro exata e o kernel B-rep do build123d.

O CST resolve o filete com ``BlendCurve`` e aqui ele e resolvido por
core.geometry -- dois caminhos independentes para a mesma geometria.  Os arcos
sao reconstruidos por tres pontos (inicio, meio exato, fim), o que evita a
ambiguidade de lado que ``RadiusArc`` tem.
"""

from __future__ import annotations

import build123d as bd

from ..core.centerline import Centerline
from ..core.expr import ParamTable
from ..core.geometry import Arc, Line, Segment


class SweepError(ValueError):
    pass


def _pt(v) -> tuple[float, float, float]:
    return (float(v[0]), float(v[1]), float(v[2]))


def path_from_segments(segments: list[Segment]) -> bd.Curve:
    """Monta a curva do build123d a partir de retas e arcos exatos."""
    if not segments:
        raise SweepError("caminho vazio")
    curve = bd.Curve()
    for seg in segments:
        if isinstance(seg, Line):
            curve += bd.Line(_pt(seg.start), _pt(seg.end))
        elif isinstance(seg, Arc):
            curve += bd.ThreePointArc(_pt(seg.start), _pt(seg.midpoint), _pt(seg.end))
        else:  # pragma: no cover - Segment e uniao fechada
            raise SweepError(f"segmento de tipo inesperado: {type(seg).__name__}")
    return curve


def path_of(centerline: Centerline, params: ParamTable) -> bd.Curve:
    return path_from_segments(centerline.resolve(params))


def min_fillet_radius(centerline: Centerline, params: ParamTable) -> float:
    """Menor raio de arco do caminho, ou infinito se nao houver arco.

    Serve para checar se o perfil cabe na curva: varrer um perfil mais largo que
    o raio faz a face interna se auto-intersectar, e o kernel devolve um solido
    invalido em vez de um erro claro.
    """
    radii = [s.radius for s in centerline.resolve(params) if isinstance(s, Arc)]
    return min(radii) if radii else float("inf")


def check_profile_fits(centerline: Centerline, params: ParamTable, half_width: float) -> None:
    r = min_fillet_radius(centerline, params)
    if half_width >= r:
        raise SweepError(
            f"o perfil tem meia-largura {half_width:.3f} mm mas o menor filete do "
            f"caminho e {r:.3f} mm; a face interna se auto-intersecta. Aumente o "
            "raio de filete ou reduza a parede."
        )


def sweep_circle(path: bd.Curve, radius: float) -> bd.Part:
    """Varre um circulo -- usado para o canal do fio."""
    if radius <= 0:
        raise SweepError(f"raio precisa ser positivo, recebeu {radius}")
    return _sweep(path, bd.Circle(radius))


def sweep_rect(path: bd.Curve, width: float, height: float) -> bd.Part:
    """Varre um retangulo -- o corpo da clamshell.

    Retangulo, e nao circulo, porque a peca precisa de faces planas: a de baixo
    apoia na mesa e a do meio e o plano de corte das duas metades.
    """
    if width <= 0 or height <= 0:
        raise SweepError(f"secao invalida: {width} x {height}")
    return _sweep(path, bd.Rectangle(width, height))


def _sweep(path: bd.Curve, section: bd.Sketch) -> bd.Part:
    edges = path.edges()
    start = edges[0] @ 0
    tangent = edges[0] % 0
    plane = bd.Plane(origin=start, z_dir=tangent)
    result = bd.sweep(sections=plane * section, path=path, transition=bd.Transition.ROUND)
    if not _valid(result):
        raise SweepError("o kernel produziu um solido invalido ao varrer o caminho")
    return result


def _valid(shape) -> bool:
    """``is_valid`` mudou de metodo para propriedade entre versoes do build123d."""
    flag = getattr(shape, "is_valid", True)
    return bool(flag() if callable(flag) else flag)
