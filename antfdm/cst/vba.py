"""Emissor de VBA para o CST: um modelo que continua PARAMETRICO la dentro.

Duas regras governam este modulo, e as duas existem porque a calibracao final
acontece no CST e nao aqui.

1. Todo vertice sai como EXPRESSAO, nunca como numero.  ``.X1 "Gap/2"``, nao
   ``.X1 "5.7996"``.  O CST guarda a string, registra a dependencia do parametro
   e reavalia no Parametric Update.  A macro ``3D Linear Helical Spiral`` da
   propria biblioteca do CST faz o contrario -- le os parametros com
   ``RestoreDoubleParameter`` e emite pontos numericos -- e por isso precisa de
   um Brick descartavel so para forcar a dependencia.  Nao seguimos esse caminho.

2. O filete continua sendo ``BlendCurve``.  Deixar o CST fazer a trigonometria e
   o que mantem as expressoes curtas e legiveis; se resolvessemos o filete aqui,
   as coordenadas de tangencia virariam expressoes ilegiveis e a Parameter List
   deixaria de ser util.

A fragilidade do modelo atual (``Pick.NextPickToDatabase`` + ``xp(n)``/``yp(n)``)
some porque cada vertice recebe coordenada explicita.  O ``BlendCurve`` opera
sobre itens nomeados com VertexId fixo, e a topologia nao muda quando so as
dimensoes variam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core.expr import to_cst
from ..core.materials import Dielectric
from ..core.wireset import Wire, WireSet

COMPONENT = "antena"
WIRE_FOLDER = "fios"


class VbaError(ValueError):
    pass


@dataclass
class HistoryBlock:
    """Um item da History List: legenda + codigo VBA."""

    caption: str
    code: str


@dataclass
class SimSetup:
    """Ajustes de solver que acompanham o modelo."""

    fmin_mhz: float
    fmax_mhz: float
    f0_mhz: float | None = None
    boundary: str = "expanded open"
    background: str = "normal"
    farfield_monitor: bool = True
    accuracy_db: float = -40.0

    def __post_init__(self) -> None:
        if self.fmax_mhz <= self.fmin_mhz:
            raise VbaError(
                f"faixa de frequencia invalida: {self.fmin_mhz}..{self.fmax_mhz} MHz"
            )


_SAFE = re.compile(r"[^A-Za-z0-9_]")


def _ident(name: str) -> str:
    """Nome seguro para item de curva/solido no CST."""
    clean = _SAFE.sub("_", name).strip("_")
    if not clean:
        raise VbaError(f"nome {name!r} nao produz identificador valido")
    return clean


def _q(expr: str) -> str:
    """Coloca uma expressao entre aspas na sintaxe do CST."""
    s = to_cst(str(expr)).strip()
    if '"' in s:
        raise VbaError(f"expressao nao pode conter aspas: {expr!r}")
    if not s:
        raise VbaError("expressao vazia")
    return f'"{s}"'


def _block(caption: str, lines: list[str]) -> HistoryBlock:
    return HistoryBlock(caption=caption, code="\n".join(lines))


# --------------------------------------------------------------------------
# parametros
# --------------------------------------------------------------------------


def emit_parameters(ws: WireSet, overwrite: bool = False) -> HistoryBlock:
    """Popula a Parameter List, em ordem de dependencia.

    Por padrao usa ``MakeSureParameterExists``, que -- conforme a ajuda do CST --
    "if it is already defined it is left unchanged".  Isso preserva o valor que
    voce calibrou no CST quando o projeto e regerado: a calibracao e a autoridade,
    e o gerador nao pode atropela-la.  ``overwrite=True`` forca o valor do spec.
    """
    lines: list[str] = []
    for name in ws.params.order():
        p = ws.params.params[name]
        expr = _q(p.expr)
        if overwrite:
            lines.append(f"StoreParameterWithDescription {_q(name)}, {expr}, {_q_desc(p.description)}")
        else:
            lines.append(f"MakeSureParameterExists {_q(name)}, {expr}")
            if p.description:
                lines.append(f"SetParameterDescription {_q(name)}, {_q_desc(p.description)}")
    return _block("antfdm: parametros", lines)


def _q_desc(desc: str) -> str:
    return '"' + str(desc).replace('"', "'") + '"'


# --------------------------------------------------------------------------
# materiais
# --------------------------------------------------------------------------


def emit_conductor_material(ws: WireSet) -> HistoryBlock:
    name = ws.conductor.material
    return _block(
        f"antfdm: material {name}",
        [
            "With Material",
            "     .Reset",
            f"     .Name {_q(name)}",
            '     .Folder ""',
            '     .FrqType "all"',
            '     .Type "Lossy metal"',
            '     .SetMaterialUnit "GHz", "mm"',
            '     .Mu "1.0"',
            f'     .Kappa "{ws.conductor.kappa:g}"',
            '     .Rho "8930.0"',
            '     .ThermalType "Normal"',
            '     .ThermalConductivity "401.0"',
            '     .Colour "1", "0.6", "0.2"',
            '     .Transparency "0"',
            "     .Create",
            "End With",
        ],
    )


def emit_radome_material(die: Dielectric) -> HistoryBlock:
    """Declara o PLA com a permissividade EFETIVA, ja corrigida pelo infill.

    Declarar o eps do plastico macico seria errado: a peca e majoritariamente ar.
    Ver core/materials.py.
    """
    return _block(
        f"antfdm: material {die.name}",
        [
            "With Material",
            "     .Reset",
            f"     .Name {_q(die.name)}",
            '     .Folder ""',
            '     .FrqType "all"',
            '     .Type "Normal"',
            '     .SetMaterialUnit "GHz", "mm"',
            f'     .Epsilon "{die.eps:.6g}"',
            '     .Mu "1.0"',
            '     .Kappa "0"',
            f'     .TanD "{die.tand:.6g}"',
            '     .TanDFreq "0.0"',
            '     .TanDGiven "True"',
            '     .TanDModel "ConstTanD"',
            '     .ThermalType "Normal"',
            '     .ThermalConductivity "0.13"',
            '     .Colour "0.85", "0.85", "0.9"',
            '     .Transparency "60"',
            "     .Create",
            "End With",
        ],
    )


# --------------------------------------------------------------------------
# curvas
# --------------------------------------------------------------------------


def _seg_name(wire: Wire, i: int) -> str:
    return f"{_ident(wire.name)}_s{i + 1}"


def emit_curve(wire: Wire) -> HistoryBlock:
    """Emite a polilinha como retas com coordenadas simbolicas.

    Usa o objeto ``Line`` (2D, no plano de trabalho), igual ao modelo atual do
    Dipolo.  Curvas fora do plano ficam para a fase 3D e sao rejeitadas aqui com
    uma mensagem explicita, em vez de gerar geometria silenciosamente errada.
    """
    curve = f"cl_{_ident(wire.name)}"
    verts = wire.centerline.vertices
    if len(verts) < 2:
        raise VbaError(f"fio {wire.name!r} precisa de pelo menos 2 vertices")

    for k, v in enumerate(verts):
        if str(v.z).strip() not in ("0", "0.0", "-0"):
            raise VbaError(
                f"fio {wire.name!r}, vertice {k}: z={v.z!r}. O emissor atual so "
                "cobre antenas planares (z=0); curvas 3D entram na fase 6."
            )

    lines = [f"Curve.NewCurve {_q(curve)}"]
    pairs = list(zip(verts, verts[1:]))
    if wire.centerline.closed:
        pairs.append((verts[-1], verts[0]))

    for i, (a, b) in enumerate(pairs):
        lines += [
            "With Line",
            "     .Reset",
            f"     .Name {_q(_seg_name(wire, i))}",
            f"     .Curve {_q(curve)}",
            f"     .X1 {_q(a.x)}",
            f"     .Y1 {_q(a.y)}",
            f"     .X2 {_q(b.x)}",
            f"     .Y2 {_q(b.y)}",
            "     .Create",
            "End With",
        ]
    return _block(f"antfdm: curva {wire.name}", lines)


def emit_blends(wire: Wire) -> HistoryBlock | None:
    """Aplica ``BlendCurve`` em cada vertice interno que tenha raio.

    VertexId 2 e o fim do segmento que chega, VertexId 1 e o inicio do que sai --
    mesma convencao do historico atual do Dipolo.  O blend apara os dois
    segmentos no lugar e eles conservam os nomes, entao os blends seguintes
    continuam podendo referencia-los.
    """
    curve = f"cl_{_ident(wire.name)}"
    verts = wire.centerline.vertices
    n = len(verts)
    corners = range(n) if wire.centerline.closed else range(1, n - 1)

    lines: list[str] = []
    for i in corners:
        if not verts[i].fillet:
            continue
        prev_seg = _seg_name(wire, (i - 1) % n)
        next_seg = _seg_name(wire, i % n)
        lines += [
            "With BlendCurve",
            "     .Reset",
            f"     .Name {_q(f'{_ident(wire.name)}_b{i}')}",
            f"     .Radius {_q(verts[i].fillet)}",
            f"     .Curve {_q(curve)}",
            f"     .CurveItem1 {_q(prev_seg)}",
            f"     .CurveItem2 {_q(next_seg)}",
            '     .EdgeId1 "1"',
            '     .EdgeId2 "1"',
            '     .VertexId1 "2"',
            '     .VertexId2 "1"',
            "     .Create",
            "End With",
        ]
    if not lines:
        return None
    return _block(f"antfdm: filetes {wire.name}", lines)


# --------------------------------------------------------------------------
# solidos
# --------------------------------------------------------------------------


def _emit_sweep(
    wire: Wire, solid: str, radius_expr: str, material: str, caption: str
) -> HistoryBlock:
    """Varre um circulo ao longo da curva e converte o resultado em solido."""
    curve = f"cl_{_ident(wire.name)}"
    tmp = f"{solid}_w"
    return _block(
        caption,
        [
            "With Wire",
            "     .Reset",
            f"     .Name {_q(tmp)}",
            f"     .Folder {_q(WIRE_FOLDER)}",
            f"     .Radius {_q(radius_expr)}",
            '     .Type "CurveWire"',
            f"     .Curve {_q(f'{curve}:{_seg_name(wire, 0)}')}",
            f"     .Material {_q(material)}",
            '     .SolidWireModel "True"',
            '     .Termination "Natural"',
            '     .AdvancedChainSelection "True"',
            "     .Add",
            "End With",
            "",
            "With Wire",
            "     .Reset",
            f"     .Name {_q(tmp)}",
            f"     .Folder {_q(WIRE_FOLDER)}",
            f"     .SolidName {_q(f'{COMPONENT}:{solid}')}",
            f"     .Material {_q(material)}",
            '     .KeepWire "False"',
            "     .ConvertToSolidShape",
            "End With",
        ],
    )


def copper_name(wire: Wire) -> str:
    return f"cobre_{_ident(wire.name)}"


def sheath_name(wire: Wire) -> str:
    return f"pla_{_ident(wire.name)}"


def emit_solids(ws: WireSet, wire: Wire) -> list[HistoryBlock]:
    """Cobre e casca de PLA como dois solidos coaxiais.

    O modelo atual do Dipolo cria UM fio de cobre com raio ``PLA+Bitola/2``, ou
    seja, simula o plastico como metal e desloca a ressonancia.  Aqui o cobre tem
    o raio do cobre e o PLA e um dieletrico separado.

    ``Solid.Insert(a, b)`` faz ``a - b`` preservando ``b`` (confirmado na ajuda do
    CST), entao a casca perde exatamente o volume ocupado pelo condutor.
    """
    cobre = copper_name(wire)
    pla = sheath_name(wire)
    r_cu = ws.conductor.radius_expr
    r_pla = ws.radome.outer_radius_expr(ws.conductor)

    blocks = [
        _emit_sweep(wire, cobre, r_cu, ws.conductor.material, f"antfdm: cobre {wire.name}"),
        _emit_sweep(
            wire, pla, r_pla, ws.radome.material.name, f"antfdm: casca PLA {wire.name}"
        ),
        _block(
            f"antfdm: cobre dentro do PLA ({wire.name})",
            [f"Solid.Insert {_q(f'{COMPONENT}:{pla}')}, {_q(f'{COMPONENT}:{cobre}')}"],
        ),
    ]
    return blocks


# --------------------------------------------------------------------------
# alimentacao e solver
# --------------------------------------------------------------------------


def emit_feed(ws: WireSet) -> HistoryBlock:
    if ws.feed is None:
        raise VbaError("a antena nao tem alimentacao definida")
    f = ws.feed
    return _block(
        "antfdm: porta discreta",
        [
            "With DiscretePort",
            "     .Reset",
            '     .PortNumber "1"',
            '     .Type "SParameter"',
            f'     .Impedance "{f.impedance:g}"',
            f"     .SetP1 \"False\", {_q(f.p1[0])}, {_q(f.p1[1])}, {_q(f.p1[2])}",
            f"     .SetP2 \"False\", {_q(f.p2[0])}, {_q(f.p2[1])}, {_q(f.p2[2])}",
            '     .LocalCoordinates "False"',
            '     .Monitor "True"',
            '     .Radius "0.0"',
            "     .Create",
            "End With",
        ],
    )


def emit_units() -> HistoryBlock:
    return _block(
        "antfdm: unidades",
        [
            "With Units",
            '     .SetUnit "Length", "mm"',
            '     .SetUnit "Frequency", "MHz"',
            '     .SetUnit "Time", "ns"',
            '     .SetUnit "Temperature", "degC"',
            '     .SetUnit "Voltage", "V"',
            '     .SetUnit "Current", "A"',
            '     .SetUnit "Resistance", "Ohm"',
            '     .SetUnit "Conductance", "S"',
            '     .SetUnit "Capacitance", "pF"',
            '     .SetUnit "Inductance", "nH"',
            "End With",
        ],
    )


def emit_solver(sim: SimSetup) -> list[HistoryBlock]:
    blocks = [
        _block(
            "antfdm: faixa de frequencia",
            [f'Solver.FrequencyRange "{sim.fmin_mhz:g}", "{sim.fmax_mhz:g}"'],
        ),
        _block(
            "antfdm: fronteiras",
            [
                "With Boundary",
                *[f'     .{s} "{sim.boundary}"' for s in ("Xmin", "Xmax", "Ymin", "Ymax", "Zmin", "Zmax")],
                '     .ApplyInAllDirections "False"',
                "End With",
            ],
        ),
        _block(
            "antfdm: material de fundo",
            [
                "With Background",
                "     .Reset",
                f'     .Type "{sim.background}"',
                '     .Epsilon "1.0"',
                '     .Mu "1.0"',
                "End With",
            ],
        ),
    ]
    if sim.farfield_monitor and sim.f0_mhz:
        blocks.append(
            _block(
                "antfdm: monitor de campo distante",
                [
                    "With Monitor",
                    "     .Reset",
                    f'     .Name "farfield (f={sim.f0_mhz:g})"',
                    '     .Domain "Frequency"',
                    '     .FieldType "Farfield"',
                    f'     .Frequency "{sim.f0_mhz:g}"',
                    '     .ExportFarfieldSource "False"',
                    "     .Create",
                    "End With",
                ],
            )
        )
    return blocks


# --------------------------------------------------------------------------
# montagem
# --------------------------------------------------------------------------


def emit(
    ws: WireSet, sim: SimSetup | None = None, overwrite_params: bool = False
) -> list[HistoryBlock]:
    """Modelo completo, como lista de itens da History List."""
    problems = ws.validate()
    if problems:
        raise VbaError("a antena tem problemas:\n  - " + "\n  - ".join(problems))

    blocks: list[HistoryBlock] = [
        emit_units(),
        emit_parameters(ws, overwrite_params),
        emit_conductor_material(ws),
        emit_radome_material(ws.radome.material.dielectric()),
        _block("antfdm: componente", [f"Component.New {_q(COMPONENT)}"]),
    ]
    for wire in ws.wires:
        blocks.append(emit_curve(wire))
        blend = emit_blends(wire)
        if blend is not None:
            blocks.append(blend)
        blocks.extend(emit_solids(ws, wire))
    blocks.append(emit_feed(ws))
    if sim is not None:
        blocks.extend(emit_solver(sim))
    return blocks


def _vba_str(s: str) -> str:
    """Literal de string VBA. A aspa se escapa dobrando, nao com barra."""
    return '"' + str(s).replace('"', '""') + '"'


def render_macro(blocks: list[HistoryBlock], title: str = "antena") -> str:
    """Renderiza os blocos como macro .bas, para rodar dentro do CST.

    Cada bloco vira uma chamada ``AddToHistory``, que e o que faz o modelo
    aparecer na History List e continuar reconstruivel por Parametric Update --
    e nao apenas ser desenhado uma vez.

    As linhas sao concatenadas com ``vbNewLine``, e nao com ``\\n``: VBA nao tem
    escape de barra invertida, entao ``"\\n"`` seria a barra e a letra n, e o
    historico chegaria ao CST como uma linha so, invalida.  E o mesmo idioma das
    macros da biblioteca do proprio CST.
    """
    out = [
        f"' Gerado por antfdm -- {title}",
        "' Modelo parametrico: os valores vivem na Parameter List e podem ser",
        "' calibrados no CST. Reexecutar preserva os valores ja calibrados.",
        "",
        "Sub Main",
        "",
        "    Dim s As String",
        "",
    ]
    for b in blocks:
        out.append(f"    ' {b.caption}")
        out.append('    s = ""')
        for line in b.code.splitlines():
            out.append(f"    s = s + {_vba_str(line)} + vbNewLine")
        out.append(f"    AddToHistory {_vba_str(b.caption)}, s")
        out.append("")
    out += ["End Sub", ""]
    return "\n".join(out)
