"""Desenhar a antena clicando.

Nao existe botao de modo.  O gesto decide:

    clique em espaco vazio  -> poe um ponto do fio
    arrastar espaco vazio   -> move a vista
    arrastar sobre um ponto -> move aquele ponto
    Esc / duplo clique      -> termina o fio; o proximo clique comeca outro

A diferenca entre clique e arrasto sai do movimento do mouse, nao de um controle
na barra.  Era o ultimo botao que sobraria, e tirar ele e o que faz "simples
cliques" ser literalmente verdade.

Cada traco cria seu proprio parametro (``L1``, ``A1``, ...).  Voce nunca digita
um nome, mas o CST recebe um modelo parametrico e a Parameter List vem populada
-- que e a razao de existir do projeto inteiro.  Assar o numero aqui emitiria
``.X2 "42.5"`` e a ferramenta perderia o sentido.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.solve import format_number
from ..core.spec import AntennaSpec, FeedSpec, StartSpec, WireSpec

# Encaixes.  Comprimento em meio milimetro e angulo em 15 graus cobrem quase todo
# desenho de antena sem obrigar a mirar com precisao de pixel.
PASSO_MM = 0.5
PASSO_GRAUS = 15.0


def _snap(v: float, passo: float) -> float:
    return round(v / passo) * passo


@dataclass
class Traco:
    """O que um clique produziu, para a barra de estado contar."""

    descricao: str
    comprimento_mm: float


class DrawController:
    """Traduz cliques em edicoes do spec.

    Nao conhece Qt: recebe posicoes em milimetros e devolve o que mudou.  Isso
    deixa o desenho testavel sem abrir janela -- e o teste do dipolo em dois
    cliques roda sem tela.
    """

    def __init__(self) -> None:
        self.fio_ativo: int | None = None  # fio sendo estendido
        self.pendente: np.ndarray | None = None  # inicio de um fio ainda sem traco

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.fio_ativo = None
        self.pendente = None

    def terminar_fio(self) -> None:
        """Esc ou duplo clique: o proximo clique comeca outro fio."""
        self.reset()

    @property
    def desenhando(self) -> bool:
        return self.fio_ativo is not None or self.pendente is not None

    # ------------------------------------------------------------------
    def clicar(self, spec: AntennaSpec, ponto, livre: bool = False) -> Traco | None:
        """Processa um clique em ``ponto`` (mm). Devolve o que foi criado."""
        p = np.array([float(ponto[0]), float(ponto[1])])

        if self.fio_ativo is not None:
            return self._estender(spec, p, livre)
        if self.pendente is not None:
            traco = self._novo_fio(spec, self.pendente, p, livre)
            self.pendente = None
            return traco
        if not _tem_alimentado(spec):
            return self._primeiro_braco(spec, p, livre)
        # Fio novo: o primeiro clique so marca de onde ele sai.  Guardar aqui, e
        # nao no spec, evita um fio sem nenhum traco -- que seria invalido.
        self.pendente = p
        return None

    # ------------------------------------------------------------------
    def _primeiro_braco(self, spec: AntennaSpec, p: np.ndarray, livre: bool) -> Traco:
        """Um clique so ja da um dipolo: braco, espelho e alimentacao.

        A alimentacao fica na origem porque e o unico ponto que deixa as
        expressoes legiveis (``Gap/2``, ``-Gap/2``) e o espelho exato.
        """
        gap = spec_valor(spec, "Gap", 4.0)
        comp, ang = _polar(p, np.zeros(2), livre)
        comp = max(comp - gap / 2.0, PASSO_MM)

        nome_l = _proximo(spec, "L")
        nome_a = _proximo(spec, "A")
        _add_param(spec, nome_l, comp, "Comprimento do braco (mm)")

        eixo = "x" if abs(math.cos(math.radians(ang))) >= abs(math.sin(math.radians(ang))) else "y"
        if eixo == "x":
            inicio = {"x": "Gap/2" if p[0] >= 0 else "-Gap/2", "y": "0", "dir": _ang(ang)}
        else:
            inicio = {"x": "0", "y": "Gap/2" if p[1] >= 0 else "-Gap/2", "dir": _ang(ang)}

        spec.wires.append(
            WireSpec.model_validate(
                {
                    "name": "braco_1",
                    "role": "driven",
                    "start": inicio,
                    "blocks": [{"type": "straight", "len": nome_l}],
                }
            )
        )
        spec.wires.append(
            WireSpec.model_validate(
                {
                    "name": "braco_2",
                    "role": "driven",
                    "mirror_of": "braco_1",
                    "mirror_axis": eixo,
                }
            )
        )
        if spec.feed is None:
            meio = ("Gap/2", "0", "0") if eixo == "x" else ("0", "Gap/2", "0")
            oposto = ("-Gap/2", "0", "0") if eixo == "x" else ("0", "-Gap/2", "0")
            spec.feed = FeedSpec.model_validate({"p1": list(oposto), "p2": list(meio)})

        del nome_a
        self.fio_ativo = 0
        return Traco("dipolo com dois bracos", comp)

    def _novo_fio(
        self, spec: AntennaSpec, inicio: np.ndarray, p: np.ndarray, livre: bool
    ) -> Traco:
        """Fio separado: refletor, diretor, qualquer elemento que nao se conecta."""
        comp, ang = _polar(p, inicio, livre)
        nome_l = _proximo(spec, "L")
        _add_param(spec, nome_l, comp, "Comprimento do elemento (mm)")

        nome = _nome_livre(spec, "elemento")
        spec.wires.append(
            WireSpec.model_validate(
                {
                    "name": nome,
                    "role": "parasitic",
                    "start": {
                        "x": format_number(_snap(float(inicio[0]), PASSO_MM)),
                        "y": format_number(_snap(float(inicio[1]), PASSO_MM)),
                        "dir": _ang(ang),
                    },
                    "blocks": [{"type": "straight", "len": nome_l}],
                }
            )
        )
        self.fio_ativo = len(spec.wires) - 1
        return Traco(f"{nome} (elemento parasita)", comp)

    def _estender(self, spec: AntennaSpec, p: np.ndarray, livre: bool) -> Traco | None:
        """Mais um trecho no fio que esta sendo desenhado."""
        fio = spec.wires[self.fio_ativo]
        ws = spec.to_wireset()
        verts = ws.wire(fio.name).centerline.points(ws.params)
        ultimo = verts[-1][:2]
        rumo_atual = _rumo(verts)

        comp, ang = _polar(p, ultimo, livre)
        if comp < PASSO_MM:
            return None

        virada = _normaliza_angulo(ang - rumo_atual)
        nome_l = _proximo(spec, "L")
        _add_param(spec, nome_l, comp, "Comprimento do trecho (mm)")

        if abs(virada) > 0.01:
            nome_a = _proximo(spec, "A")
            _add_param(spec, nome_a, virada, "Angulo da dobra (graus)")
            fio.blocks.append(
                {"type": "bend", "angle": nome_a, "fillet": _raio(spec)}
            )
        fio.blocks.append({"type": "straight", "len": nome_l})
        return Traco(f"trecho em {fio.name}", comp)


# --------------------------------------------------------------------------
# apoio
# --------------------------------------------------------------------------


def _tem_alimentado(spec: AntennaSpec) -> bool:
    return any(w.role == "driven" for w in spec.wires)


def _polar(p: np.ndarray, origem: np.ndarray, livre: bool) -> tuple[float, float]:
    """Comprimento e angulo do traco, ja encaixados."""
    d = p - origem
    comp = float(np.hypot(d[0], d[1]))
    ang = math.degrees(math.atan2(d[1], d[0]))
    if not livre:
        comp = _snap(comp, PASSO_MM)
        ang = _snap(ang, PASSO_GRAUS)
    return max(comp, PASSO_MM), ang


def _rumo(verts: np.ndarray) -> float:
    """Direcao do ultimo trecho, em graus."""
    if len(verts) < 2:
        return 0.0
    d = verts[-1][:2] - verts[-2][:2]
    return math.degrees(math.atan2(d[1], d[0]))


def _normaliza_angulo(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def _ang(a: float) -> str:
    return format_number(_normaliza_angulo(a))


def _raio(spec: AntennaSpec) -> str:
    return "Radius" if "Radius" in spec.params else format_number(2.0)


def spec_valor(spec: AntennaSpec, nome: str, padrao: float) -> float:
    try:
        return spec.to_wireset().params.values().get(nome, padrao)
    except Exception:
        return padrao


def _proximo(spec: AntennaSpec, prefixo: str) -> str:
    """Proximo nome livre da serie L1, L2, ... ou A1, A2, ..."""
    n = 1
    existentes = {k.lower() for k in spec.params}
    while f"{prefixo}{n}".lower() in existentes:
        n += 1
    return f"{prefixo}{n}"


def _nome_livre(spec: AntennaSpec, base: str) -> str:
    usados = {w.name for w in spec.wires}
    n = 1
    while f"{base}_{n}" in usados:
        n += 1
    return f"{base}_{n}"


def _add_param(spec: AntennaSpec, nome: str, valor: float, descricao: str) -> None:
    spec.params[nome] = {"expr": format_number(valor), "description": descricao}
