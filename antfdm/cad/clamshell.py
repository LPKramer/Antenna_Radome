"""Radome clamshell: duas metades que prendem o fio esmaltado.

Decisoes mecanicas e o porque de cada uma:

* **Corte em Z=0.**  A antena e planar e deitada, entao o plano de corte deixa as
  duas metades com uma face plana grande.  Cada uma imprime com essa face na mesa
  e o meio-canal virado para cima -- um vale, nao um balanco.  Nenhuma precisa de
  suporte.

* **Corpo esbelto com orelhas periodicas**, em vez de um corpo largo continuo.
  Plastico perto do fio carrega a antena e desloca a ressonancia; entao a secao
  fica so com a parede necessaria, e alarga apenas nas estacoes onde ha pino de
  alinhamento e parafuso.  Menos PLA no campo, e ainda assim rigido.

* **Ponte na alimentacao.**  Os dois bracos sao fios separados, e sem uma ponte a
  peca sairia em dois pedacos soltos.  Pior: ``Gap`` e uma dimensao calibrada, e
  sem a ponte nada garantiria o espacamento depois de montado.  A ponte fixa o
  Gap mecanicamente e ainda aloja o cabo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import build123d as bd
import numpy as np

from ..core.geometry import frame_at, path_length, stations
from ..core.wireset import WireSet
from . import sweep as sw


class ClamshellError(ValueError):
    pass


@dataclass
class ClamshellOptions:
    station_spacing: float = 30.0  # espacamento das orelhas, em mm
    pin_diameter: float = 2.0
    pin_length: float = 2.0
    pin_clearance: float = 0.10  # folga radial do furo do pino
    screw_clearance_d: float = 3.4  # passante M3, na metade de cima
    screw_pilot_d: float = 2.5  # auto-atarraxante M3, na metade de baixo
    lug_along: float = 9.0  # comprimento da orelha na direcao do fio
    coax_diameter: float = 5.0  # RG-316 com capa: ~2.5 mm; folga p/ RG-58
    engrave: bool = True
    text_size: float = 3.5
    text_depth: float = 0.6


@dataclass
class Clamshell:
    top: bd.Part
    bottom: bd.Part
    section_w: float
    section_h: float
    channel_r: float
    stats: dict = field(default_factory=dict)


def _lug_width(opts: ClamshellOptions, section_w: float, parede: float) -> float:
    """Largura da orelha: canal no meio, pino de um lado e parafuso do outro."""
    feature = max(opts.pin_diameter, opts.screw_clearance_d)
    return section_w + 2.0 * (feature + 2.0 * parede)


def _feature_offset(opts: ClamshellOptions, section_w: float, parede: float) -> float:
    feature = max(opts.pin_diameter, opts.screw_clearance_d)
    return section_w / 2.0 + parede + feature / 2.0


def _oriented_box(
    center: np.ndarray, tangent: np.ndarray, along: float, across: float, height: float
) -> bd.Part:
    """Caixa centrada em ``center``, com ``along`` na direcao de ``tangent``.

    A antena e planar, entao a orelha so gira em torno de Z -- por isso o angulo
    sai de atan2 da tangente e nao de uma base 3D completa.
    """
    angle = float(np.degrees(np.arctan2(tangent[1], tangent[0])))
    plane = bd.Plane(
        origin=(float(center[0]), float(center[1]), 0.0)
    ).rotated((0, 0, angle))
    return plane * bd.Box(along, across, height, align=bd.Align.CENTER)


def _cyl(center: np.ndarray, diameter: float, z0: float, z1: float) -> bd.Part:
    height = z1 - z0
    if height <= 0:
        raise ClamshellError(f"cilindro com altura nao positiva: {height}")
    loc = bd.Location((float(center[0]), float(center[1]), z0))
    return loc * bd.Cylinder(
        diameter / 2.0, height, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)
    )


def _union(parts: Iterable[bd.Part]) -> bd.Part:
    out = None
    for p in parts:
        out = p if out is None else out + p
    if out is None:
        raise ClamshellError("nada para unir")
    return out


def build(ws: WireSet, opts: ClamshellOptions | None = None) -> Clamshell:
    """Gera as duas metades do radome para a antena inteira."""
    opts = opts or ClamshellOptions()
    problems = ws.validate()
    if problems:
        raise ClamshellError("a antena tem problemas:\n  - " + "\n  - ".join(problems))

    bitola = ws.params.evaluate(ws.conductor.bitola)
    parede = ws.params.evaluate(ws.radome.parede)
    r_ch = bitola / 2.0 + ws.radome.folga
    section = 2.0 * (r_ch + parede)

    paths = {}
    for w in ws.wires:
        sw.check_profile_fits(w.centerline, ws.params, section / 2.0)
        paths[w.name] = (
            w.centerline.resolve(ws.params),
            sw.path_of(w.centerline, ws.params),
        )

    bodies = [sw.sweep_rect(p, section, section) for _, p in paths.values()]
    channels = [sw.sweep_circle(p, r_ch) for _, p in paths.values()]

    lug_w = _lug_width(opts, section, parede)
    offset = _feature_offset(opts, section, parede)
    lugs, pins, screws = _stations(ws, paths, opts, section, lug_w, offset, parede)

    solid = _union(bodies + lugs)
    boom = _boom(ws, solid, section)
    if boom is not None:
        solid = solid + boom
    bridge, coax = _feed_bridge(ws, section, parede, opts)
    if bridge is not None:
        solid = solid + bridge

    shell = solid - _union(channels)
    if coax is not None:
        shell = shell - coax

    top = bd.split(shell, bisect_by=bd.Plane.XY, keep=bd.Keep.TOP)
    bottom = bd.split(shell, bisect_by=bd.Plane.XY, keep=bd.Keep.BOTTOM)

    # Pino sai da metade de baixo; o furo correspondente, com folga, vai na de cima.
    for center in pins:
        top_z = section / 2.0
        bottom = bottom + _cyl(center, opts.pin_diameter, 0.0, opts.pin_length)
        top = top - _cyl(
            center,
            opts.pin_diameter + 2.0 * opts.pin_clearance,
            0.0,
            opts.pin_length + opts.pin_clearance,
        )
        del top_z

    for center in screws:
        top = top - _cyl(center, opts.screw_clearance_d, -0.1, section)
        bottom = bottom - _cyl(center, opts.screw_pilot_d, -section, 0.1)

    if opts.engrave:
        bottom = _engrave(ws, bottom, opts, section)

    stats = {
        "secao_mm": section,
        "raio_canal_mm": r_ch,
        "orelhas": len(lugs),
        "pinos": len(pins),
        "parafusos": len(screws),
        "volume_topo_mm3": float(top.volume),
        "volume_base_mm3": float(bottom.volume),
    }
    return Clamshell(
        top=top, bottom=bottom, section_w=section, section_h=section,
        channel_r=r_ch, stats=stats,
    )


def _stations(ws, paths, opts, section, lug_w, offset, parede):
    """Orelhas com pino de um lado e parafuso do outro, ao longo de cada fio."""
    lugs: list[bd.Part] = []
    pins: list[np.ndarray] = []
    screws: list[np.ndarray] = []
    for segs, _ in paths.values():
        total = path_length(segs)
        margin = min(opts.lug_along / 2.0 + 1.0, total / 2.0)
        for s in stations(segs, opts.station_spacing, margin):
            point, tangent = frame_at(segs, s)
            lugs.append(_oriented_box(point, tangent, opts.lug_along, lug_w, section))
            normal = np.array([-tangent[1], tangent[0], 0.0])
            pins.append(point + normal * offset)
            screws.append(point - normal * offset)
    return lugs, pins, screws


def _boom(ws, solid: bd.Part, section: float):
    """Barra ao longo de um eixo, unindo elementos que nao se tocam.

    Dimensionada pela extensao real do que ja foi construido, para nao depender
    de o usuario recalcular o comprimento toda vez que muda um espacamento.
    """
    b = ws.radome.boom
    if b is None:
        return None
    bb = solid.bounding_box()
    if b.axis == "x":
        comprimento = bb.size.X + 2 * b.margin
        centro = ((bb.min.X + bb.max.X) / 2.0, b.at)
        tamanho = (comprimento, b.width)
    else:
        comprimento = bb.size.Y + 2 * b.margin
        centro = (b.at, (bb.min.Y + bb.max.Y) / 2.0)
        tamanho = (b.width, comprimento)
    loc = bd.Location((centro[0], centro[1], 0.0))
    return loc * bd.Box(tamanho[0], tamanho[1], section, align=bd.Align.CENTER)


def _feed_bridge(ws, section: float, parede: float, opts: ClamshellOptions):
    """Bloco que atravessa o gap de alimentacao, com o alojamento do cabo.

    Sem ele a peca sairia em dois pedacos soltos e nada garantiria o ``Gap``,
    que e justamente uma das dimensoes que voce calibra no CST.
    """
    if ws.feed is None:
        return None, None
    p1 = np.array([ws.params.evaluate(c) for c in ws.feed.p1])
    p2 = np.array([ws.params.evaluate(c) for c in ws.feed.p2])
    gap = float(np.linalg.norm(p2 - p1))
    if gap < 1e-6:
        return None, None

    mid = (p1 + p2) / 2.0
    tangent = (p2 - p1) / gap
    # Avanca sobre os dois bracos para a ponte agarrar, em vez de so encostar.
    along = gap + 2.0 * section
    across = max(section, opts.coax_diameter + 2.0 * parede)
    height = max(section, opts.coax_diameter + 2.0 * parede)
    bridge = _oriented_box(mid, tangent, along, across, height)

    # O cabo entra perpendicular ao dipolo, para o cabo nao correr paralelo aos
    # bracos -- corrente de modo comum na malha desequilibra o diagrama.
    normal = np.array([-tangent[1], tangent[0], 0.0])
    coax = _oriented_box(
        mid + normal * (across / 2.0),
        normal,
        across + 2.0,
        opts.coax_diameter,
        opts.coax_diameter,
    )
    return bridge, coax


def _engrave(ws, bottom: bd.Part, opts: ClamshellOptions, section: float) -> bd.Part:
    """Grava identificacao na face de baixo.

    Sem isso, duas versoes impressas da mesma antena com dimensoes diferentes
    ficam indistinguiveis na bancada -- que e o erro mais facil de cometer num
    fluxo de prototipagem rapida.
    """
    label = ws.name
    if ws.f0_hz:
        label += f" {ws.f0_hz / 1e6:.0f}MHz"
    label += f" {_fingerprint(ws)}"
    bb = bottom.bounding_box()
    try:
        text = bd.Text(label, font_size=opts.text_size, align=bd.Align.CENTER)
    except Exception:
        return bottom  # fonte indisponivel: a peca importa mais que a etiqueta
    plane = bd.Plane.XY.offset(-section / 2.0)
    solid = bd.extrude(plane * text, amount=opts.text_depth)
    solid = bd.Location((bb.center().X, bb.center().Y, 0)) * solid
    return bottom - solid


def _fingerprint(ws: WireSet) -> str:
    """Hash curto dos parametros avaliados, para casar peca com simulacao."""
    import hashlib

    values = ws.params.values()
    blob = ";".join(f"{k}={values[k]:.9g}" for k in sorted(values))
    return hashlib.sha256(blob.encode()).hexdigest()[:6]
