"""Catalogo de bloquinhos da v1.

Cobre as quatro familias pedidas -- dipolo/Y/bowtie, Yagi-Uda, meander e
polarizacao circular -- com sete blocos, porque as familias sao COMPOSICOES e
nao templates.  Bowtie e straight + bend; Yagi e um straight por elemento,
posicionado ao longo do boom; dipolo em Y e straight + vee + straight.

Nenhum bloco resolve o filete: ele so marca o raio no vertice.  Quem resolve e o
``BlendCurve`` do CST de um lado e core.geometry do outro -- ver README.
"""

from __future__ import annotations

import math

from .base import Block, Chain, register
from .cursor import Cursor, add, literal, scale


@register
class Straight(Block):
    """Trecho reto de comprimento ``len``."""

    type = "straight"

    @classmethod
    def fields(cls) -> set[str]:
        return {"len", "fillet"}

    def emit(self, chain: Chain) -> None:
        chain.cursor = chain.cursor.advance(self._req("len"))
        chain.at_cursor()
        chain.fillet_last(getattr(self, "fillet", None))


@register
class Bend(Block):
    """Dobra o caminho em ``angle`` graus, arredondando o canto com ``fillet``."""

    type = "bend"

    @classmethod
    def fields(cls) -> set[str]:
        return {"angle", "fillet"}

    def emit(self, chain: Chain) -> None:
        # O canto fica no vertice que ja foi emitido; o filete pertence a ele.
        chain.fillet_last(getattr(self, "fillet", None))
        chain.cursor = chain.cursor.turn(self._req("angle"))


@register
class Vee(Block):
    """Corcova em Y: sobe ``height`` avancando ``run``, e desce em ``back``.

    E a forma do Dipolo.cst existente. Serve de casamento e de carga: encurta a
    antena sem alongar o retangulo que a peca impressa precisa cobrir.
    """

    type = "vee"

    @classmethod
    def fields(cls) -> set[str]:
        return {"run", "height", "back", "fillet"}

    def emit(self, chain: Chain) -> None:
        fillet = getattr(self, "fillet", None)
        run, height = self._req("run"), self._req("height")
        back = getattr(self, "back", None) or run

        chain.fillet_last(fillet)  # o canto onde a subida comeca
        chain.cursor = chain.cursor.advance(run).strafe(height)
        chain.at_cursor(fillet)  # o pico
        chain.cursor = chain.cursor.advance(back).strafe(scale(height, -1.0))
        chain.at_cursor(fillet)  # a volta a linha de base


@register
class Meander(Block):
    """Serpentina de ``n`` dentes: encurta a antena dobrando o fio.

    Casa bem com FDM, porque o canal impresso mantem a geometria da dobra
    estavel -- que e justamente o que uma serpentina montada a mao nao tem.
    """

    type = "meander"

    @classmethod
    def fields(cls) -> set[str]:
        return {"n", "pitch", "height", "fillet"}

    def emit(self, chain: Chain) -> None:
        n = literal(self._req("n"))
        if n is None or n < 1 or n != int(n):
            raise ValueError(
                f"meander: 'n' precisa ser um inteiro positivo literal, recebeu "
                f"{self.n!r}. O numero de dentes muda a topologia, entao nao pode "
                "ser parametro do CST -- so as dimensoes podem."
            )
        pitch, height = self._req("pitch"), self._req("height")
        fillet = getattr(self, "fillet", None)
        meio = scale(pitch, 0.5)

        chain.fillet_last(fillet)
        for k in range(int(n)):
            lado = height if k % 2 == 0 else scale(height, -1.0)
            chain.cursor = chain.cursor.advance(meio).strafe(lado)
            chain.at_cursor(fillet)
            chain.cursor = chain.cursor.advance(meio).strafe(scale(lado, -1.0))
            chain.at_cursor(fillet)


@register
class Arc(Block):
    """Curva de raio ``radius`` por ``angle`` graus, como polilinha de ``n`` lados.

    A linha de centro so tem retas e filetes, entao um arco longo vira polilinha.
    Com ``n`` suficiente a diferenca some no comprimento -- e cada vertice
    continua sendo expressao, entao o raio segue calibravel no CST.
    """

    type = "arc"

    @classmethod
    def fields(cls) -> set[str]:
        return {"radius", "angle", "n", "fillet"}

    def emit(self, chain: Chain) -> None:
        ang = literal(self._req("angle"))
        if ang is None:
            raise ValueError(
                "arc: 'angle' precisa ser literal, porque define quantos lados a "
                "polilinha tem. Use 'radius' como parametro para calibrar o raio."
            )
        n = int(literal(getattr(self, "n", None) or "0") or max(3, round(abs(ang) / 15)))
        if n < 1:
            raise ValueError(f"arc: 'n' invalido ({n})")
        radius = self._req("radius")
        passo = ang / n
        # Corda de um arco: 2*R*sin(passo/2).
        corda = scale(radius, 2.0 * math.sin(math.radians(passo) / 2.0))

        chain.fillet_last(getattr(self, "fillet", None))
        chain.cursor = chain.cursor.turn(str(passo / 2.0))
        for k in range(n):
            chain.cursor = chain.cursor.advance(corda)
            chain.at_cursor()
            if k < n - 1:
                chain.cursor = chain.cursor.turn(str(passo))
        chain.cursor = chain.cursor.turn(str(passo / 2.0))


@register
class Spiral(Block):
    """Espiral arquimediana de ``turns`` voltas, de ``r0`` a ``r1``.

    Polarizacao circular em geometria plana: a espiral irradia CP de forma banda
    larga, sem precisar de linha de atraso nem de segundo alimentador.
    """

    type = "spiral"

    @classmethod
    def fields(cls) -> set[str]:
        return {"turns", "r0", "r1", "per_turn", "start_angle"}

    def emit(self, chain: Chain) -> None:
        turns = literal(self._req("turns"))
        if turns is None or turns <= 0:
            raise ValueError("spiral: 'turns' precisa ser um numero literal positivo")
        per_turn = int(literal(getattr(self, "per_turn", None) or "24") or 24)
        r0, r1 = self._req("r0"), self._req("r1")
        a0 = literal(getattr(self, "start_angle", None) or "0") or 0.0

        # O cursor marca o CENTRO da espiral, nao um ponto do fio, entao o
        # vertice de partida precisa ser descartado -- o que so faz sentido se a
        # espiral for o primeiro bloco do fio.
        if len(chain.vertices) != 1:
            raise ValueError(
                "spiral precisa ser o primeiro bloco do fio: o cursor marca o "
                "centro da espiral, e nao daria para emendar o que veio antes"
            )
        cx, cy = chain.cursor.x, chain.cursor.y
        total = int(round(turns * per_turn))
        chain.clear()

        for k in range(total + 1):
            t = k / total
            ang = a0 + 360.0 * turns * t
            raio = add(scale(r0, 1.0 - t), scale(r1, t))
            chain.add_vertex(_polar(cx, cy, raio, ang))

        ultimo = chain.vertices[-1]
        chain.cursor = Cursor(
            x=ultimo.x, y=ultimo.y, heading=str((a0 + 360.0 * turns + 90.0) % 360.0)
        )


def _polar(cx: str, cy: str, radius: str, angle_deg: float):
    from ..core.centerline import Vertex

    c = math.cos(math.radians(angle_deg))
    s = math.sin(math.radians(angle_deg))
    return Vertex(x=add(cx, scale(radius, c)), y=add(cy, scale(radius, s)), z="0")


@register
class Jump(Block):
    """Move o cursor sem desenhar fio -- para posicionar sem emendar.

    Existe porque um elemento parasita de Yagi nao se conecta a nada: o boom e
    mecanico, nao eletrico.
    """

    type = "jump"

    @classmethod
    def fields(cls) -> set[str]:
        return {"len", "side", "angle"}

    def emit(self, chain: Chain) -> None:
        # Andar sem desenhar deixaria um buraco no meio do fio, e uma Centerline
        # e continua por definicao. So faz sentido antes de qualquer traco.
        if len(chain.vertices) != 1:
            raise ValueError(
                "jump so pode ser usado antes do primeiro traco: mover sem "
                "desenhar no meio do fio deixaria a linha de centro descontinua. "
                "Para um elemento separado, declare outro fio."
            )
        if getattr(self, "angle", None):
            chain.cursor = chain.cursor.turn(self.angle)
        if getattr(self, "len", None):
            chain.cursor = chain.cursor.advance(self.len)
        if getattr(self, "side", None):
            chain.cursor = chain.cursor.strafe(self.side)
        chain.clear()
        chain.at_cursor()


@register
class Taper(Block):
    """Abre em ``angle`` e anda ``len``: o lado de um bowtie.

    Bowtie nao e um template: e ``taper`` + ``bend`` + ``taper``, o que deixa o
    angulo de abertura livre em vez de escolhido por um catalogo.
    """

    type = "taper"

    @classmethod
    def fields(cls) -> set[str]:
        return {"len", "angle", "fillet"}

    def emit(self, chain: Chain) -> None:
        chain.fillet_last(getattr(self, "fillet", None))
        chain.cursor = chain.cursor.turn(self._req("angle"))
        chain.cursor = chain.cursor.advance(self._req("len"))
        chain.at_cursor()
        chain.cursor = chain.cursor.turn(scale(self._req("angle"), -1.0))


__all__ = ["Straight", "Bend", "Vee", "Meander", "Arc", "Spiral", "Jump", "Taper"]
