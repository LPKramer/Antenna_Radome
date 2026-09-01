"""Geometria exata da linha de centro: retas, arcos e o filete entre elas.

Este modulo e o lado numerico do filete. O lado CST usa ``BlendCurve`` e resolve
o mesmo filete por conta propria; os dois precisam concordar, e o teste de
comprimento de arco em tests/test_geometry.py e o que verifica isso.

Todas as coordenadas sao vetores 3D, mesmo quando a antena e planar -- o nucleo
ja nasce generico para nao precisar de retrabalho quando entrarem helice e quad.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

Vec = np.ndarray

# Abaixo disto, dois vertices ou duas direcoes sao tratados como coincidentes.
EPS = 1e-9


class GeometryError(ValueError):
    """Geometria impossivel: filete grande demais, vertices repetidos, etc."""


def _v(p) -> Vec:
    a = np.asarray(p, dtype=float).reshape(-1)
    if a.size == 2:
        a = np.array([a[0], a[1], 0.0])
    if a.size != 3:
        raise GeometryError(f"ponto precisa ter 2 ou 3 coordenadas, recebeu {a.size}")
    return a


def _unit(v: Vec) -> Vec:
    n = float(np.linalg.norm(v))
    if n < EPS:
        raise GeometryError("vetor de comprimento nulo nao tem direcao")
    return v / n


def _rotate(v: Vec, axis: Vec, angle: float) -> Vec:
    """Rodrigues: gira ``v`` em torno de ``axis`` (unitario) por ``angle`` rad."""
    c, s = math.cos(angle), math.sin(angle)
    return v * c + np.cross(axis, v) * s + axis * float(np.dot(axis, v)) * (1.0 - c)


@dataclass(frozen=True)
class Line:
    start: Vec
    end: Vec

    @property
    def length(self) -> float:
        return float(np.linalg.norm(self.end - self.start))

    @property
    def start_tangent(self) -> Vec:
        return _unit(self.end - self.start)

    @property
    def end_tangent(self) -> Vec:
        return self.start_tangent

    def point_at(self, s: float) -> Vec:
        return self.start + self.start_tangent * s


@dataclass(frozen=True)
class Arc:
    center: Vec
    radius: float
    start: Vec
    end: Vec
    normal: Vec  # eixo de rotacao; girar (start-center) por +sweep leva a end
    sweep: float  # radianos, sempre positivo

    @property
    def length(self) -> float:
        return self.radius * self.sweep

    @property
    def start_tangent(self) -> Vec:
        return _unit(np.cross(self.normal, self.start - self.center))

    @property
    def end_tangent(self) -> Vec:
        return _unit(np.cross(self.normal, self.end - self.center))

    @property
    def midpoint(self) -> Vec:
        return self.center + _rotate(self.start - self.center, self.normal, self.sweep / 2)

    def point_at(self, s: float) -> Vec:
        return self.center + _rotate(self.start - self.center, self.normal, s / self.radius)


Segment = Line | Arc


@dataclass
class Fillet:
    """O filete resolvido num vertice: onde a reta para e onde o arco vai."""

    tangent_in: Vec  # ponto onde o segmento que chega encosta no arco
    tangent_out: Vec  # ponto onde o segmento que sai comeca
    arc: Arc
    trim: float  # distancia do vertice ate cada ponto de tangencia


def solve_fillet(prev: Vec, vertex: Vec, nxt: Vec, radius: float) -> Fillet | None:
    """Resolve o arco tangente as duas retas que se encontram em ``vertex``.

    Retorna ``None`` quando nao ha canto a arredondar (pontos colineares) ou
    quando o raio e zero. Levanta GeometryError se o canto for impossivel.

    Com ``theta`` o angulo interno do vertice, o recuo de tangencia e
    ``R/tan(theta/2)`` e o centro fica a ``R/sin(theta/2)`` do vertice, sobre a
    bissetriz. O arco varre ``pi - theta``.
    """
    if radius <= EPS:
        return None

    v1 = _unit(prev - vertex)
    v2 = _unit(nxt - vertex)

    cos_theta = float(np.clip(np.dot(v1, v2), -1.0, 1.0))
    theta = math.acos(cos_theta)

    if math.pi - theta < 1e-7:
        return None  # colinear: nao ha canto
    if theta < 1e-7:
        raise GeometryError(
            f"o caminho dobra 180 graus sobre si mesmo em {vertex.tolist()}; "
            "nao existe filete para esse vertice"
        )

    half = theta / 2.0
    trim = radius / math.tan(half)
    dist_center = radius / math.sin(half)

    t_in = vertex + v1 * trim
    t_out = vertex + v2 * trim
    center = vertex + _unit(v1 + v2) * dist_center

    u1 = _unit(t_in - center)
    u2 = _unit(t_out - center)
    axis_raw = np.cross(u1, u2)
    if float(np.linalg.norm(axis_raw)) < EPS:
        raise GeometryError(f"arco degenerado em {vertex.tolist()}")
    axis = _unit(axis_raw)
    sweep = math.acos(float(np.clip(np.dot(u1, u2), -1.0, 1.0)))

    arc = Arc(center=center, radius=radius, start=t_in, end=t_out, normal=axis, sweep=sweep)
    return Fillet(tangent_in=t_in, tangent_out=t_out, arc=arc, trim=trim)


def resolve_path(points, radii, closed: bool = False) -> list[Segment]:
    """Converte vertices + raios de filete numa cadeia de retas e arcos.

    ``radii[i]`` e o raio no vertice ``points[i]``; use 0 ou None para canto vivo.
    Numa cadeia aberta os raios das pontas sao ignorados, porque nao ha canto ali.
    """
    pts = [_v(p) for p in points]
    if len(pts) < 2:
        raise GeometryError("um caminho precisa de pelo menos 2 pontos")
    if len(radii) != len(pts):
        raise GeometryError(f"{len(pts)} pontos mas {len(radii)} raios")

    n = len(pts)
    edges = range(n) if closed else range(n - 1)
    for i in edges:
        j = (i + 1) % n
        if float(np.linalg.norm(pts[j] - pts[i])) < EPS:
            raise GeometryError(f"vertices {i} e {j} sao coincidentes")

    corners = range(n) if closed else range(1, n - 1)
    fillets: dict[int, Fillet] = {}
    for i in corners:
        r = radii[i]
        if not r:
            continue
        f = solve_fillet(pts[(i - 1) % n], pts[i], pts[(i + 1) % n], float(r))
        if f is not None:
            fillets[i] = f

    _check_overlap(pts, fillets, closed)

    segments: list[Segment] = []
    for i in edges:
        j = (i + 1) % n
        start = fillets[i].tangent_out if i in fillets else pts[i]
        end = fillets[j].tangent_in if j in fillets else pts[j]
        if float(np.linalg.norm(end - start)) > EPS:
            segments.append(Line(start=start, end=end))
        if j in fillets:
            segments.append(fillets[j].arc)

    if closed and 0 in fillets:
        # A volta fechada terminou re-emitindo o arco do vertice 0; ele pertence
        # ao inicio da cadeia, para que o caminho comece num ponto de tangencia.
        segments.insert(0, segments.pop())

    return segments


def _check_overlap(pts, fillets: dict[int, Fillet], closed: bool) -> None:
    """Rejeita filetes que se comem, com uma mensagem que diz o que reduzir."""
    n = len(pts)
    edges = range(n) if closed else range(n - 1)
    for i in edges:
        j = (i + 1) % n
        seg = float(np.linalg.norm(pts[j] - pts[i]))
        used = (fillets[i].trim if i in fillets else 0.0) + (
            fillets[j].trim if j in fillets else 0.0
        )
        if used > seg + EPS:
            raise GeometryError(
                f"os filetes dos vertices {i} e {j} consomem {used:.4f} mm de um trecho "
                f"de {seg:.4f} mm; reduza o raio ou afaste os vertices"
            )


def path_length(segments) -> float:
    return float(sum(s.length for s in segments))


def frame_at(segments, s: float) -> tuple[Vec, Vec]:
    """Ponto e tangente unitaria a ``s`` mm do inicio do caminho.

    Usado para posicionar pinos, orelhas e gravacao ao longo da peca. ``s`` fora
    do caminho e grampeado nas pontas em vez de dar erro, porque quem chama
    costuma iterar num passo fixo que nao divide o comprimento total.
    """
    total = path_length(segments)
    s = min(max(float(s), 0.0), total)
    acc = 0.0
    for seg in segments:
        if s <= acc + seg.length or seg is segments[-1]:
            local = min(max(s - acc, 0.0), seg.length)
            return seg.point_at(local), _unit(
                seg.end_tangent if local >= seg.length else _tangent_at(seg, local)
            )
        acc += seg.length
    raise GeometryError("caminho vazio")


def _tangent_at(seg: Segment, local: float) -> Vec:
    if isinstance(seg, Line):
        return seg.start_tangent
    return _unit(np.cross(seg.normal, seg.point_at(local) - seg.center))


def stations(segments, spacing: float, margin: float = 0.0) -> list[float]:
    """Posicoes ao longo do caminho, espacadas por ``spacing``.

    Sempre inclui as duas pontas (recuadas de ``margin``), porque e ali que as
    metades mais tendem a abrir.
    """
    total = path_length(segments)
    lo, hi = margin, total - margin
    if hi <= lo:
        return [total / 2.0]
    count = max(1, int(round((hi - lo) / max(spacing, 1e-6))))
    return [lo + (hi - lo) * k / count for k in range(count + 1)]


def sample_path(segments, step: float) -> np.ndarray:
    """Amostra o caminho a cada ``step`` mm, incluindo as duas pontas.

    Usado pelo emissor de deck NEC e pelas verificacoes; nao pelo CAD, que
    consome os segmentos exatos.
    """
    if step <= 0:
        raise GeometryError("passo de amostragem precisa ser positivo")
    out: list[Vec] = []
    for seg in segments:
        count = max(1, int(math.ceil(seg.length / step)))
        for k in range(count):
            out.append(seg.point_at(seg.length * k / count))
    out.append(segments[-1].point_at(segments[-1].length))
    return np.array(out)
