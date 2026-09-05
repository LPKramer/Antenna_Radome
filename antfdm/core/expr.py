"""Expressoes parametricas, na sintaxe do Python e na sintaxe do CST.

A forma canonica (usada no spec YAML) e a sintaxe do Python: ``**`` para potencia,
funcoes em minusculas, ``pi`` disponivel.  O CST usa ``^`` para potencia e aceita
nomes de funcao sem distinguir maiusculas.

As funcoes trigonometricas do CST operam em RADIANOS.  Isso foi confirmado contra
Dipolo/Model/Parameters.json, onde ``Cotg = (TAN(Ang/(2*pi)))^-1`` vale 5.8205 para
``Ang = 1.06905``: tan(0.17015 rad) = 0.17182 e 1/0.17182 = 5.820.  Em graus daria
336.7, ou seja, nao bate.  ``deg()`` e ``rad()`` ficam disponiveis para conversao
explicita, e sao mais legiveis do que espalhar ``pi/180`` pelas expressoes.
"""

from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

import sympy


class ExprError(ValueError):
    """Expressao malformada, com ciclo, ou referenciando parametro inexistente."""


# Funcoes aceitas numa expressao.  Restringir o namespace mantem a avaliacao
# previsivel e garante que tudo que escrevemos tem equivalente do lado do CST.
_FUNCS: dict[str, object] = {
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "asin": sympy.asin,
    "acos": sympy.acos,
    "atan": sympy.atan,
    "atn": sympy.atan,  # nome do CST
    "sinh": sympy.sinh,
    "cosh": sympy.cosh,
    "tanh": sympy.tanh,
    "sqrt": sympy.sqrt,
    "exp": sympy.exp,
    "log": sympy.log,
    "abs": sympy.Abs,
    "max": sympy.Max,
    "min": sympy.Min,
    "deg": lambda x: x * 180 / sympy.pi,
    "rad": lambda x: x * sympy.pi / 180,
    "pi": sympy.pi,
}

_IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")

# O CST nao distingui maiusculas em nome de funcao nem de parametro: o historico
# do Dipolo escreve "PLA+Bitola/2" e "radius" para os parametros "Pla" e "Radius",
# e "(TAN(Ang/(2*pi)))^-1" para a funcao "tan".  Normalizar na entrada evita que
# isso vire um erro de parametro inexistente mais adiante.
_FUNCS_LOWER = {k.lower(): k for k in _FUNCS}


def _local_dict(names: Iterable[str]) -> dict[str, object]:
    d = dict(_FUNCS)
    for n in names:
        if n not in d:
            d[n] = sympy.Symbol(n)
    return d


def canonicalize(source: str, names: Iterable[str] = ()) -> str:
    """Ajusta a caixa dos identificadores a forma declarada.

    Funcoes viram minusculas; cada nome que casar com um parametro declarado,
    ignorando a caixa, assume a grafia declarada.  Nomes desconhecidos passam
    intactos, para que o erro venha depois com a mensagem certa.
    """
    declared = {n.lower(): n for n in names}

    def sub(m: re.Match[str]) -> str:
        raw = m.group(0)
        low = raw.lower()
        if low in _FUNCS_LOWER:
            return _FUNCS_LOWER[low]
        return declared.get(low, raw)

    return _IDENT.sub(sub, source)


def parse(source: str, names: Iterable[str] = ()) -> sympy.Expr:
    """Converte texto na sintaxe canonica para uma expressao sympy."""
    try:
        return sympy.sympify(source, locals=_local_dict(names), rational=False)
    except (sympy.SympifyError, SyntaxError, TypeError) as exc:
        raise ExprError(f"expressao invalida: {source!r} ({exc})") from exc


@functools.lru_cache(maxsize=8192)
def _canonicalize_cache(source: str, names: tuple[str, ...]) -> str:
    return canonicalize(source, names)


# Namespace da avaliacao rapida.  A sintaxe canonica ja E Python, entao nao ha
# traducao a fazer -- so garantir que as funcoes existam e que nada mais exista.
_EVAL_NS: dict[str, object] = {
    "__builtins__": {},
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atn": math.atan,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "sqrt": math.sqrt, "exp": math.exp, "log": math.log,
    "abs": abs, "max": max, "min": min,
    "deg": math.degrees, "rad": math.radians,
    "pi": math.pi,
}


@functools.lru_cache(maxsize=8192)
def compilar(source: str) -> tuple[tuple[str, ...], object]:
    """Compila a expressao uma unica vez.

    Antes cada coordenada voltava pelo ``sympify`` a cada avaliacao, e como o
    canvas reavalia a antena inteira a cada quadro isso aparecia como lentidao:
    44 ms so de vertices num dipolo, 2.9 s numa espiral.

    ``lambdify`` foi a primeira tentativa e piorou a espiral para 1.9 s: ela tem
    547 vertices com expressoes todas diferentes, e lambdify faz geracao de
    codigo para cada uma.  ``compile`` e a ferramenta certa aqui, porque a
    sintaxe canonica ja e Python -- nao ha o que traduzir.

    O cache e limitado porque arrastar gera expressoes novas a cada quadro
    (``108.5``, ``108.6``, ...); sem limite ele cresceria sem parar.
    """
    livres = tuple(sorted(free_names(source)))
    try:
        codigo = compile(source, "<antfdm>", "eval")
    except (SyntaxError, ValueError) as exc:
        raise ExprError(f"expressao invalida: {source!r} ({exc})") from exc
    return livres, codigo


def free_names(source: str) -> set[str]:
    """Identificadores citados na expressao que nao sao funcao nem constante.

    Trabalha sobre o texto e nao sobre a arvore sympy: um nome desconhecido ainda
    nao definido precisa aparecer aqui para que o erro seja "parametro X nao
    definido" em vez de uma falha de parse.
    """
    return {m.group(0) for m in _IDENT.finditer(source)} - set(_FUNCS)


@functools.lru_cache(maxsize=8192)
def simplify(source: str) -> str:
    """Junta termos semelhantes, para a expressao caber na Parameter List.

    Em cache porque roda a cada reconstrucao da cadeia de blocos, e o sympy
    aqui dentro era o custo dominante: 1.9 s so nos 547 vertices da espiral.
    As expressoes se repetem entre quadros (o que muda no arrasto sao os
    VALORES dos parametros, nao os textos), entao o cache acerta quase sempre.

    Uma cadeia de bloquinhos acumula termos que se cancelam --
    ``Gap/2 + Sec_inical + cordenadaNosolda - Gap/2`` -- e uma expressao assim
    atrapalha justamente quem vai calibrar no CST lendo o historico.

    Conservador de proposito: se o sympy falhar, ou devolver algo MAIOR do que
    entrou, a expressao original e mantida.  Simplificar nunca pode piorar a
    legibilidade nem arriscar mudar o valor.
    """
    s = str(source).strip()
    if not s or _IDENT.fullmatch(s) or literal_value(s) is not None:
        return s
    try:
        reduced = str(sympy.sympify(s, locals=_local_dict(free_names(s)), rational=False))
    except (sympy.SympifyError, SyntaxError, TypeError, AttributeError):
        return s
    return reduced if len(reduced) < len(s) else s


def literal_value(source: str) -> float | None:
    """Valor da expressao se ela for um numero puro, senao None."""
    try:
        return float(str(source).strip())
    except (TypeError, ValueError):
        return None


def to_cst(source: str) -> str:
    """Traduz da sintaxe canonica para a do CST (``**`` vira ``^``)."""
    return source.replace("**", "^")


def from_cst(source: str, names: Iterable[str] = ()) -> str:
    """Traduz da sintaxe do CST para a canonica.

    ``^`` vira ``**`` -- seguro porque expressao geometrica nunca usa XOR bit a
    bit, o outro significado de ``^`` em Python.  Passando ``names``, a caixa dos
    identificadores tambem e normalizada para a grafia declarada.
    """
    return canonicalize(source.replace("^", "**"), names)


@dataclass
class Parameter:
    name: str
    expr: str
    description: str = ""

    def __post_init__(self) -> None:
        if not _IDENT.fullmatch(self.name):
            raise ExprError(f"nome de parametro invalido: {self.name!r}")


@dataclass
class ParamTable:
    """Parametros nomeados com expressoes que podem se referenciar entre si.

    Espelha a Parameter List do CST: cada entrada guarda a expressao original
    (que vai para o CST como string) e o valor avaliado (usado pelo lado CAD).
    """

    params: dict[str, Parameter] = field(default_factory=dict)
    _cache: dict[str, float] = field(default_factory=dict, repr=False)

    @classmethod
    def from_mapping(cls, data: dict[str, object]) -> "ParamTable":
        table = cls()
        for name, value in data.items():
            if isinstance(value, dict):
                table.add(name, str(value["expr"]), str(value.get("description", "")))
            else:
                table.add(name, str(value))
        return table

    def add(self, name: str, expr: str, description: str = "") -> None:
        clash = next(
            (n for n in self.params if n.lower() == name.lower() and n != name), None
        )
        if clash is not None:
            raise ExprError(
                f"parametros {clash!r} e {name!r} diferem so na caixa; o CST trata "
                "os dois como o mesmo parametro"
            )
        self.params[name] = Parameter(name, str(expr), description)
        self._cache.clear()

    def normalize(self, source: str) -> str:
        """Ajusta a caixa dos identificadores a grafia declarada nesta tabela."""
        return _canonicalize_cache(str(source), tuple(self.params))

    def __contains__(self, name: object) -> bool:
        return name in self.params

    def __iter__(self):
        return iter(self.params.values())

    def order(self) -> list[str]:
        """Nomes em ordem de dependencia, para o CST poder criar um a um.

        Levanta ExprError em ciclo ou referencia pendente, apontando os nomes
        envolvidos -- diagnosticar isso depois, dentro do CST, seria bem pior.
        """
        resolved: list[str] = []
        state: dict[str, int] = {}  # 0 = visitando, 1 = pronto

        def visit(name: str, trail: tuple[str, ...]) -> None:
            if state.get(name) == 1:
                return
            if state.get(name) == 0:
                cycle = " -> ".join(trail[trail.index(name):] + (name,))
                raise ExprError(f"ciclo entre parametros: {cycle}")
            if name not in self.params:
                origin = trail[-1] if trail else "?"
                raise ExprError(f"parametro {name!r} nao definido (usado por {origin!r})")
            state[name] = 0
            for dep in sorted(free_names(self.normalize(self.params[name].expr))):
                visit(dep, trail + (name,))
            state[name] = 1
            resolved.append(name)

        for name in self.params:
            visit(name, ())
        return resolved

    def values(self) -> dict[str, float]:
        """Avalia todos os parametros para numeros."""
        if self._cache:
            return dict(self._cache)
        out: dict[str, float] = {}
        for name in self.order():
            out[name] = self._eval(self.params[name].expr, out)
        self._cache = out
        return dict(out)

    def evaluate(self, source: str) -> float:
        """Avalia uma expressao avulsa contra a tabela."""
        return self._eval(str(source), self.values())

    def _eval(self, source: str, known: dict[str, float]) -> float:
        # Numero puro nao precisa de sympy nem de cache -- e o caso mais comum
        # durante um arrasto, em que o parametro vira literal a cada quadro.
        direto = literal_value(source)
        if direto is not None:
            return direto

        source = self.normalize(source)
        livres, fn = compilar(source)

        missing = set(livres) - known.keys()
        if missing:
            raise ExprError(
                f"expressao {source!r} usa parametro nao definido: {', '.join(sorted(missing))}"
            )
        ambiente = dict(_EVAL_NS)
        for n in livres:
            ambiente[n] = known[n]
        try:
            value = eval(fn, ambiente)  # noqa: S307 - namespace restrito acima
        except (TypeError, ValueError, ZeroDivisionError, OverflowError,
                NameError, AttributeError) as exc:
            raise ExprError(f"nao foi possivel avaliar {source!r}: {exc}") from exc

        if isinstance(value, complex):
            if abs(value.imag) > 1e-12:
                raise ExprError(
                    f"expressao {source!r} resultou em numero complexo: {value}"
                )
            value = value.real
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            raise ExprError(f"expressao {source!r} resultou em {value}")
        return value
