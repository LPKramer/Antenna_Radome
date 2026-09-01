"""Schema do spec YAML e a conversao para WireSet.

O YAML e o formato nativo do projeto e a fonte de verdade ANTES da calibracao.
Depois que voce calibra no CST, ``antfdm sync`` traz os valores de volta para ca,
entao o arquivo tambem e o registro do que foi efetivamente construido.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .centerline import Centerline, Vertex
from .expr import ParamTable
from .materials import RadomeMaterial
from .wireset import Boom, Conductor, Feed, Radome, Wire, WireSet


class SpecError(ValueError):
    pass


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VertexSpec(_Model):
    x: str = "0"
    y: str = "0"
    z: str = "0"
    fillet: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        # Numeros no YAML viram expressao: "x: 10" e o mesmo que "x: '10'".
        if isinstance(data, dict):
            return {k: (None if v is None else str(v)) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            keys = ("x", "y", "z")
            return {keys[i]: str(v) for i, v in enumerate(data)}
        return data


class StartSpec(_Model):
    """Onde a cadeia de blocos comeca, e para onde aponta."""

    x: str = "0"
    y: str = "0"
    dir: str = "0"  # graus, anti-horario a partir de +X

    @model_validator(mode="before")
    @classmethod
    def _strify(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: str(v) for k, v in data.items()}
        return data


class WireSpec(_Model):
    name: str
    role: Literal["driven", "parasitic"] = "driven"
    closed: bool = False
    vertices: list[VertexSpec] = Field(default_factory=list)
    start: StartSpec | None = None
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    mirror_of: str | None = None
    mirror_axis: Literal["x", "y", "z"] = "x"

    @model_validator(mode="after")
    def _check(self) -> "WireSpec":
        fontes = [
            bool(self.vertices),
            bool(self.blocks),
            self.mirror_of is not None,
        ]
        if sum(fontes) > 1:
            raise ValueError(
                f"fio {self.name!r}: escolha UMA forma de definir a geometria -- "
                "'vertices', 'blocks' ou 'mirror_of'"
            )
        if not any(fontes):
            raise ValueError(
                f"fio {self.name!r}: precisa de 'vertices', 'blocks' ou 'mirror_of'"
            )
        if self.vertices and len(self.vertices) < 2:
            raise ValueError(f"fio {self.name!r}: precisa de pelo menos 2 vertices")
        return self


class ConductorSpec(_Model):
    bitola: str = "Bitola"
    material: str = "Copper (annealed)"
    kappa: float = 5.8e7


class BoomSpec(_Model):
    """Barra mecanica que une elementos desconectados (Yagi, log-periodica)."""

    axis: Literal["x", "y"] = "x"
    at: float = 0.0
    width: float = 6.0
    margin: float = 4.0


class RadomeSpec(_Model):
    parede: str = "Parede"
    folga: float = 0.15
    infill: float = 0.30
    eps_solid: float = 2.75
    tand_solid: float = 0.008
    eps_cal: float = 1.0
    passo_pino: float = 25.0
    diametro_pino: float = 3.0
    parafuso: str = "M3"
    boom: BoomSpec | None = None


class FeedSpec(_Model):
    p1: list[str]
    p2: list[str]
    impedance: float = 50.0

    @model_validator(mode="before")
    @classmethod
    def _strify(cls, data: Any) -> Any:
        if isinstance(data, dict):
            out = dict(data)
            for k in ("p1", "p2"):
                if k in out and isinstance(out[k], (list, tuple)):
                    out[k] = [str(v) for v in out[k]]
            return out
        return data

    @model_validator(mode="after")
    def _check(self) -> "FeedSpec":
        for label, p in (("p1", self.p1), ("p2", self.p2)):
            if len(p) != 3:
                raise ValueError(f"feed.{label} precisa de 3 coordenadas, tem {len(p)}")
        return self


class SimSpec(_Model):
    fmin_mhz: float
    fmax_mhz: float
    f0_mhz: float | None = None
    boundary: str = "expanded open"
    farfield_monitor: bool = True


class PrintSpec(_Model):
    """Limites da impressora, usados para segmentar a peca."""

    bed_x: float = 220.0
    bed_y: float = 220.0
    bed_z: float = 250.0


class AntennaSpec(_Model):
    name: str
    f0_mhz: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    conductor: ConductorSpec = Field(default_factory=ConductorSpec)
    radome: RadomeSpec = Field(default_factory=RadomeSpec)
    feed: FeedSpec | None = None
    wires: list[WireSpec] = Field(default_factory=list)
    sim: SimSpec | None = None
    printer: PrintSpec = Field(default_factory=PrintSpec)

    def to_wireset(self) -> WireSet:
        params = ParamTable.from_mapping(self.params)

        built: dict[str, Centerline] = {}
        wires: list[Wire] = []
        for w in self.wires:
            if w.mirror_of is not None:
                src = built.get(w.mirror_of)
                if src is None:
                    raise SpecError(
                        f"fio {w.name!r} espelha {w.mirror_of!r}, que ainda nao foi "
                        "definido; declare o original antes"
                    )
                cl = src.mirrored(w.name, w.mirror_axis)
            elif w.blocks:
                # Import tardio: blocks importa de core, e o inverso fecharia ciclo.
                from ..blocks import BlockError, Cursor, build_chain

                s = w.start or StartSpec()
                try:
                    verts = build_chain(w.blocks, Cursor(x=s.x, y=s.y, heading=s.dir))
                except BlockError as exc:
                    raise SpecError(f"fio {w.name!r}: {exc}") from exc
                cl = Centerline(name=w.name, vertices=verts, closed=w.closed)
            else:
                cl = Centerline(
                    name=w.name,
                    vertices=[
                        Vertex(x=v.x, y=v.y, z=v.z, fillet=v.fillet) for v in w.vertices
                    ],
                    closed=w.closed,
                )
            built[w.name] = cl
            wires.append(Wire(name=w.name, centerline=cl, role=w.role))

        radome = Radome(
            parede=self.radome.parede,
            folga=self.radome.folga,
            passo_pino=self.radome.passo_pino,
            diametro_pino=self.radome.diametro_pino,
            parafuso=self.radome.parafuso,
            boom=(
                Boom(
                    axis=self.radome.boom.axis,
                    at=self.radome.boom.at,
                    width=self.radome.boom.width,
                    margin=self.radome.boom.margin,
                )
                if self.radome.boom
                else None
            ),
            material=RadomeMaterial(
                eps_solid=self.radome.eps_solid,
                tand_solid=self.radome.tand_solid,
                infill=self.radome.infill,
                eps_cal=self.radome.eps_cal,
            ),
        )
        feed = None
        if self.feed is not None:
            feed = Feed(
                p1=(self.feed.p1[0], self.feed.p1[1], self.feed.p1[2]),
                p2=(self.feed.p2[0], self.feed.p2[1], self.feed.p2[2]),
                impedance=self.feed.impedance,
            )
        return WireSet(
            name=self.name,
            params=params,
            wires=wires,
            feed=feed,
            conductor=Conductor(
                bitola=self.conductor.bitola,
                material=self.conductor.material,
                kappa=self.conductor.kappa,
            ),
            radome=radome,
            f0_hz=self.f0_mhz * 1e6 if self.f0_mhz else None,
        )

    # ------------------------------------------------------------------
    @classmethod
    def blank(cls, name: str = "nova_antena", f0_mhz: float = 1300.0) -> "AntennaSpec":
        """Um dipolo de meia onda pronto para editar.

        Comeca com geometria valida de proposito: uma tela vazia nao diz o que
        fazer, e uma antena que ja desenha da onde pegar.  Tudo aqui e fracao de
        Lambda, entao mudar F0 reescala o conjunto.
        """
        return cls.model_validate(
            {
                "name": name,
                "f0_mhz": f0_mhz,
                "params": {
                    "F0": {
                        "expr": f"{f0_mhz:g}",
                        "description": "Frequencia alvo (MHz). Mude e a antena reescala.",
                    },
                    "Lambda": {
                        "expr": "300000/F0",
                        "description": "Comprimento de onda no vacuo (mm)",
                    },
                    "L_braco": {
                        "expr": "0.235*Lambda",
                        "description": "Comprimento de cada braco (mm)",
                    },
                    "Gap": {
                        "expr": "4",
                        "description": "Abertura no ponto de alimentacao (mm)",
                    },
                    "Radius": {
                        "expr": "2",
                        "description": "Raio de filete dos cantos (mm)",
                    },
                    "Bitola": {
                        "expr": "1.5",
                        "description": "DIAMETRO do cobre nu do fio esmaltado (mm)",
                    },
                    "Parede": {
                        "expr": "1",
                        "description": "Espessura de PLA sobre o fio (mm)",
                    },
                },
                "feed": {"p1": ["-Gap/2", "0", "0"], "p2": ["Gap/2", "0", "0"]},
                "wires": [
                    {
                        "name": "braco_dir",
                        "role": "driven",
                        "start": {"x": "Gap/2", "y": "0", "dir": "0"},
                        "blocks": [{"type": "straight", "len": "L_braco"}],
                    },
                    {"name": "braco_esq", "role": "driven",
                     "mirror_of": "braco_dir", "mirror_axis": "x"},
                ],
                "sim": {
                    "fmin_mhz": round(f0_mhz * 0.4),
                    "fmax_mhz": round(f0_mhz * 2.0),
                    "f0_mhz": f0_mhz,
                },
            }
        )


def recipes_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "recipes"


def catalog() -> list[str]:
    """Receitas que acompanham o antfdm, para semear uma antena nova."""
    return sorted(p.stem for p in recipes_dir().glob("*.yaml"))


def from_recipe(recipe: str, name: str | None = None) -> AntennaSpec:
    """Copia uma receita do catalogo para servir de ponto de partida.

    Copia, e nao referencia: a partir daqui e sua, e editar nao mexe no catalogo.
    """
    caminho = recipes_dir() / f"{recipe}.yaml"
    if not caminho.exists():
        raise SpecError(
            f"receita {recipe!r} nao existe. Disponiveis: {', '.join(catalog())}"
        )
    spec = load(caminho)
    if name:
        spec.name = name
    return spec


def load(path: str | Path) -> AntennaSpec:
    p = Path(path)
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecError(f"{p}: YAML invalido: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"{p}: o spec precisa ser um mapa no topo")
    return AntennaSpec.model_validate(data)


def dump(spec: AntennaSpec, path: str | Path) -> None:
    """Grava o spec preservando a ordem dos campos, para o diff ficar legivel."""
    data = spec.model_dump(exclude_none=True)
    Path(path).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
