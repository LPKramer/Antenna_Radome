"""A antena inteira: fios, alimentacao, condutor e radome.

Um WireSet e o que todos os emissores consomem -- VBA do CST, CAD da clamshell e
(na fase 4) o deck NEC. Guarda varias linhas de centro porque elementos parasitas
de Yagi sao fios DESCONECTADOS: nao da para representar a antena como uma curva so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .centerline import Centerline
from .expr import ParamTable
from .materials import RadomeMaterial

Role = Literal["driven", "parasitic"]


@dataclass
class Conductor:
    """O fio esmaltado. ``bitola`` e o DIAMETRO do cobre nu, em mm."""

    bitola: str = "Bitola"
    material: str = "Copper (annealed)"
    kappa: float = 5.8e7  # S/m, cobre recozido

    @property
    def radius_expr(self) -> str:
        return f"({self.bitola})/2"


@dataclass
class Boom:
    """Barra que une elementos desconectados numa peca so.

    Yagi, log-periodica e qualquer arranjo com parasitas precisam disso: os
    elementos nao se tocam eletricamente, entao sem uma barra mecanica a peca
    sairia da impressora em varios pedacos soltos e nada garantiria o
    espacamento -- que e uma dimensao calibrada.
    """

    axis: Literal["x", "y"] = "x"
    at: float = 0.0  # posicao no eixo perpendicular, em mm
    width: float = 6.0  # largura da barra, em mm
    margin: float = 4.0  # quanto a barra passa das pontas, em mm


@dataclass
class Radome:
    """A casca impressa em volta do fio."""

    parede: str = "Parede"  # espessura de PLA sobre o fio, em mm
    folga: float = 0.15  # folga radial do canal, em mm
    material: RadomeMaterial = field(default_factory=RadomeMaterial)
    passo_pino: float = 25.0  # espacamento dos pinos de alinhamento, em mm
    diametro_pino: float = 3.0
    parafuso: str = "M3"
    boom: Boom | None = None

    def outer_radius_expr(self, conductor: Conductor) -> str:
        return f"{conductor.radius_expr} + ({self.parede})"


@dataclass
class Feed:
    """Porta discreta entre dois pontos, dados como expressao.

    Coordenadas explicitas em vez de referencia a ponta de curva: e o que evita
    a cadeia Pick/xp()/yp() que torna o historico atual fragil quando um
    parametro muda.
    """

    p1: tuple[str, str, str]
    p2: tuple[str, str, str]
    impedance: float = 50.0
    kind: Literal["discrete"] = "discrete"


@dataclass
class Wire:
    name: str
    centerline: Centerline
    role: Role = "driven"


@dataclass
class WireSet:
    """Uma antena completa e pronta para emitir."""

    name: str
    params: ParamTable
    wires: list[Wire] = field(default_factory=list)
    feed: Feed | None = None
    conductor: Conductor = field(default_factory=Conductor)
    radome: Radome = field(default_factory=Radome)
    f0_hz: float | None = None  # frequencia alvo, so informativa no nucleo

    def wire(self, name: str) -> Wire:
        for w in self.wires:
            if w.name == name:
                return w
        raise KeyError(f"fio {name!r} nao existe em {self.name!r}")

    def driven(self) -> list[Wire]:
        return [w for w in self.wires if w.role == "driven"]

    def total_wire_length(self) -> float:
        """Comprimento total de fio a cortar, somando todos os elementos."""
        return sum(w.centerline.length(self.params) for w in self.wires)

    def lengths(self) -> dict[str, float]:
        """Comprimento por elemento -- vai para o print card como lista de corte."""
        return {w.name: w.centerline.length(self.params) for w in self.wires}

    def validate(self) -> list[str]:
        """Problemas que impediriam gerar CST ou STL. Vazio = tudo certo.

        Devolve uma lista em vez de levantar na primeira falha, para o usuario
        ver tudo que precisa corrigir de uma vez.
        """
        problems: list[str] = []
        if not self.wires:
            problems.append("a antena nao tem nenhum fio")
        seen: set[str] = set()
        for w in self.wires:
            if w.name in seen:
                problems.append(f"nome de fio repetido: {w.name!r}")
            seen.add(w.name)
            try:
                w.centerline.resolve(self.params)
            except Exception as exc:  # geometria ou expressao
                problems.append(f"fio {w.name!r}: {exc}")
        if self.feed is None:
            problems.append("a antena nao tem alimentacao definida")
        if not self.driven():
            problems.append("nenhum fio marcado como 'driven'")
        try:
            bitola = self.params.evaluate(self.conductor.bitola)
            if bitola <= 0:
                problems.append(f"bitola precisa ser positiva, vale {bitola}")
        except Exception as exc:
            problems.append(f"bitola: {exc}")
        try:
            parede = self.params.evaluate(self.radome.parede)
            if parede <= 0:
                problems.append(f"parede do radome precisa ser positiva, vale {parede}")
        except Exception as exc:
            problems.append(f"parede: {exc}")
        return problems
