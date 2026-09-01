"""Cursor simbolico: uma tartaruga que anda em expressoes, nao em numeros.

Esta e a peca que faz os bloquinhos conviverem com a calibracao no CST.  Um
cursor comum acumularia ``x += L*cos(a)`` em ponto flutuante e o bloco emitiria
coordenadas assadas -- o modelo pararia de ser parametrico.  Aqui a posicao e um
par de STRINGS, e andar 10 mm a partir de ``Gap/2`` produz ``Gap/2 + 10``, que
segue vivo na Parameter List.

Quando o rumo e um multiplo exato de 90 graus, a trigonometria e resolvida na
hora (``cos(0) = 1``) para a expressao nao encher de ``cos(rad(0))`` sem
necessidade.  Rumo parametrico -- ``AnguloYperna``, por exemplo -- emite a
trigonometria de verdade, que e justamente o que permite girar o segmento
mudando o parametro no CST.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


def literal(expr: str) -> float | None:
    """Valor numerico da expressao, ou None se ela depender de parametro."""
    try:
        return float(str(expr).strip())
    except (TypeError, ValueError):
        return None


def is_zero(expr: str) -> bool:
    v = literal(expr)
    return v is not None and v == 0.0


def _atom(expr: str) -> bool:
    """True quando a expressao dispensa parenteses para multiplicar ou negar."""
    e = str(expr).strip()
    if not e:
        return False
    if e.startswith("-"):
        e = e[1:]
    return e.replace("_", "").replace(".", "").isalnum()


def paren(expr: str) -> str:
    e = str(expr).strip()
    return e if _atom(e) or (e.startswith("(") and e.endswith(")")) else f"({e})"


def add(a: str, b: str) -> str:
    """Soma duas expressoes, mantendo o resultado legivel."""
    a, b = str(a).strip(), str(b).strip()
    if is_zero(b):
        return a
    if is_zero(a):
        return b
    va, vb = literal(a), literal(b)
    if va is not None and vb is not None:
        return _num(va + vb)
    if b.startswith("-"):
        return f"{a} - {b[1:].strip()}"
    return f"{a} + {b}"


def scale(expr: str, factor: float) -> str:
    """Multiplica por uma constante, tratando os casos 0, 1 e -1."""
    if factor == 0:
        return "0"
    v = literal(expr)
    if v is not None:
        return _num(v * factor)
    if factor == 1:
        return str(expr).strip()
    if factor == -1:
        return f"-{paren(expr)}"
    return f"{_num(factor)}*{paren(expr)}"


def mul(a: str, b: str) -> str:
    """Produto de duas expressoes."""
    fa, fb = literal(a), literal(b)
    if fa is not None:
        return scale(b, fa)
    if fb is not None:
        return scale(a, fb)
    return f"{paren(a)}*{paren(b)}"


def _num(v: float) -> str:
    if v == int(v):
        return str(int(v))
    return repr(round(v, 12))


# Direcoes em que a trigonometria some.
_AXIS = {0: (1.0, 0.0), 90: (0.0, 1.0), 180: (-1.0, 0.0), 270: (0.0, -1.0)}


def delta(length: str, heading: str) -> tuple[str, str]:
    """Deslocamento (dx, dy) ao andar ``length`` no rumo ``heading`` (graus)."""
    h = literal(heading)
    if h is not None:
        m = h % 360.0
        for ang, (cx, cy) in _AXIS.items():
            if abs(m - ang) < 1e-9:
                return scale(length, cx), scale(length, cy)
        # Angulo numerico mas fora dos eixos: resolve o cosseno aqui, para nao
        # deixar cos(rad(45)) no historico do CST sem necessidade.
        import math

        r = math.radians(m)
        return scale(length, math.cos(r)), scale(length, math.sin(r))
    # rad() esta disponivel nos dois lados: o CST usa radianos, e a conversao
    # explicita e mais legivel que espalhar pi/180 pelas expressoes.
    return (
        f"{paren(length)}*cos(rad({heading}))",
        f"{paren(length)}*sin(rad({heading}))",
    )


@dataclass(frozen=True)
class Cursor:
    """Posicao e rumo, tudo em expressao. Imutavel: cada passo devolve um novo."""

    x: str = "0"
    y: str = "0"
    heading: str = "0"  # graus, sentido anti-horario a partir de +X

    def advance(self, length: str) -> "Cursor":
        dx, dy = delta(str(length), self.heading)
        return replace(self, x=add(self.x, dx), y=add(self.y, dy))

    def strafe(self, offset: str) -> "Cursor":
        """Anda perpendicular ao rumo (positivo para a esquerda)."""
        dx, dy = delta(str(offset), add(self.heading, "90"))
        return replace(self, x=add(self.x, dx), y=add(self.y, dy))

    def turn(self, degrees: str) -> "Cursor":
        return replace(self, heading=add(self.heading, str(degrees)))

    def facing(self, degrees: str) -> "Cursor":
        return replace(self, heading=str(degrees))
