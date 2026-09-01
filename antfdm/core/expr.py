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

import math
import re
from dataclasses import dataclass, field
from typing import Iterable

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


def free_names(source: str) -> set[str]:
    """Identificadores citados na expressao que nao sao funcao nem constante.

    Trabalha sobre o texto e nao sobre a arvore sympy: um nome desconhecido ainda
    nao definido precisa aparecer aqui para que o erro seja "parametro X nao
    definido" em vez de uma falha de parse.
    """
    return {m.group(0) for m in _IDENT.finditer(source)} - set(_FUNCS)


def simplify(source: str) -> str:
    """Junta termos semelhantes, para a expressao caber na Parameter List.

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
        return canonicalize(str(source), self.params.keys())

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
        source = self.normalize(source)
        missing = free_names(source) - known.keys()
        if missing:
            raise ExprError(
                f"expressao {source!r} usa parametro nao definido: {', '.join(sorted(missing))}"
            )
        expr = parse(source, known.keys())
        subs = {sympy.Symbol(k): v for k, v in known.items()}
        try:
            value = complex(expr.subs(subs).evalf())
        except (TypeError, ValueError) as exc:
            raise ExprError(f"nao foi possivel avaliar {source!r}: {exc}") from exc
        if abs(value.imag) > 1e-12:
            raise ExprError(f"expressao {source!r} resultou em numero complexo: {value}")
        if math.isnan(value.real) or math.isinf(value.real):
            raise ExprError(f"expressao {source!r} resultou em {value.real}")
        return value.real
