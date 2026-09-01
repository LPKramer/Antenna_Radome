"""Contrato dos bloquinhos e o registro de tipos.

A inversao em relacao ao Antenna Magus esta aqui: a unidade nao e "a antena", e
o bloco.  Uma antena e uma COMPOSICAO de blocos descrita em YAML, entao o
catalogo vira um conjunto de receitas editaveis em vez de um catalogo fechado de
templates em codigo.  Um dipolo nao e privilegiado: e uma receita de poucas
linhas que voce bifurca.

Cada bloco anexa vertices a uma cadeia e move o cursor.  Como o cursor e
simbolico (ver cursor.py), o que sai sao expressoes -- o modelo continua
parametrico dentro do CST, que e onde a calibracao final acontece.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.centerline import Vertex
from ..core.expr import simplify
from .cursor import Cursor


class BlockError(ValueError):
    pass


@dataclass
class Chain:
    """Estado acumulado enquanto os blocos de um fio sao percorridos.

    ``origins`` guarda, para cada vertice, o indice do bloco que o produziu
    (-1 = o ponto de partida do fio).  Sem essa procedencia nao ha como saber
    que campo editar quando o vertice e arrastado na tela.
    """

    cursor: Cursor
    vertices: list[Vertex] = field(default_factory=list)
    origins: list[int] = field(default_factory=list)
    current: int = -1  # bloco sendo percorrido agora

    def at_cursor(self, fillet: str | None = None) -> None:
        """Grava um vertice na posicao atual do cursor."""
        self.vertices.append(
            Vertex(x=self.cursor.x, y=self.cursor.y, z="0", fillet=fillet)
        )
        self.origins.append(self.current)

    def add_vertex(self, vertex: Vertex) -> None:
        """Grava um vertice ja montado (usado por blocos que calculam polar)."""
        self.vertices.append(vertex)
        self.origins.append(self.current)

    def clear(self) -> None:
        """Descarta o que foi acumulado, mantendo os dois lados em sincronia."""
        self.vertices.clear()
        self.origins.clear()

    def fillet_last(self, radius: str | None) -> None:
        """Arredonda o ultimo vertice -- e ali que o canto realmente esta."""
        if radius and self.vertices:
            self.vertices[-1].fillet = str(radius)


class Block(ABC):
    """Um pedaco de antena que sabe se desenhar e (opcionalmente) se dimensionar."""

    type: str = ""

    def __init__(self, **kwargs: Any):
        desconhecidos = set(kwargs) - set(self.fields())
        if desconhecidos:
            raise BlockError(
                f"bloco {self.type!r} nao conhece: {', '.join(sorted(desconhecidos))}. "
                f"Aceita: {', '.join(sorted(self.fields()))}"
            )
        for k, v in kwargs.items():
            setattr(self, k, None if v is None else str(v))

    @classmethod
    def fields(cls) -> set[str]:
        raise NotImplementedError

    @abstractmethod
    def emit(self, chain: Chain) -> None:
        """Anexa vertices a ``chain`` e avanca o cursor."""

    def _req(self, name: str) -> str:
        v = getattr(self, name, None)
        if v is None:
            raise BlockError(f"bloco {self.type!r}: falta o campo obrigatorio {name!r}")
        return str(v)

    def __repr__(self) -> str:
        campos = {k: getattr(self, k, None) for k in sorted(self.fields())}
        return f"{self.type}({', '.join(f'{k}={v!r}' for k, v in campos.items() if v)})"


_REGISTRY: dict[str, type[Block]] = {}


def register(cls: type[Block]) -> type[Block]:
    if not cls.type:
        raise BlockError(f"{cls.__name__} nao declarou 'type'")
    _REGISTRY[cls.type] = cls
    return cls


def create(spec: dict[str, Any]) -> Block:
    """Instancia um bloco a partir do dicionario do YAML."""
    data = dict(spec)
    tipo = data.pop("type", None)
    if tipo is None:
        raise BlockError(f"bloco sem 'type': {spec}")
    cls = _REGISTRY.get(str(tipo))
    if cls is None:
        raise BlockError(
            f"bloco desconhecido: {tipo!r}. Disponiveis: {', '.join(catalog())}"
        )
    return cls(**data)


def catalog() -> list[str]:
    return sorted(_REGISTRY)


def describe() -> list[tuple[str, str, list[str]]]:
    """(tipo, resumo, campos) de cada bloco -- alimenta a paleta da GUI."""
    out = []
    for name in catalog():
        cls = _REGISTRY[name]
        doc = (cls.__doc__ or "").strip().splitlines()
        out.append((name, doc[0] if doc else "", sorted(cls.fields())))
    return out


def build_chain(blocks: list[dict[str, Any]], start: Cursor) -> list[Vertex]:
    """Percorre a cadeia de blocos e devolve os vertices resultantes."""
    return build_chain_traced(blocks, start).vertices


def build_chain_traced(blocks: list[dict[str, Any]], start: Cursor) -> Chain:
    """Igual, mas devolve tambem de qual bloco veio cada vertice."""
    chain = Chain(cursor=start)
    chain.at_cursor()
    for i, spec in enumerate(blocks):
        chain.current = i
        try:
            create(spec).emit(chain)
        except (BlockError, ValueError) as exc:
            raise BlockError(f"bloco {i} ({spec.get('type', '?')}): {exc}") from exc
    if len(chain.vertices) < 2:
        raise BlockError(
            "a cadeia de blocos nao produziu geometria; um fio precisa de pelo "
            "menos um bloco que avance o cursor"
        )
    # Andar em passos acumula termos que se cancelam.  Reduzir aqui mantem a
    # Parameter List do CST legivel para quem vai calibrar.
    for v in chain.vertices:
        v.x = simplify(v.x)
        v.y = simplify(v.y)
    return chain
