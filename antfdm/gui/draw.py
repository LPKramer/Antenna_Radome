"""Criar e crescer a antena por gestos.

Nao ha maquina de estados nem modo de desenho.  Antes existia "fio ativo" e
"pendente" porque o clique caia no vazio e o programa precisava lembrar o que
estava sendo desenhado.  Com as pontas viraveis em alvo, o gesto ja diz tudo:
voce clica NA ponta que quer crescer, e a ponta nova fica pronta para o proximo
clique.  Isso apagou todo o estado.

Cada traco cria seu proprio parametro (``L1``, ``A1``, ...).  Voce nunca digita
um nome, mas o CST recebe a Parameter List populada -- assar o numero emitiria
``.X2 "42.5"`` e a ferramenta perderia a razao de existir.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.solve import format_number
from ..core.spec import AntennaSpec, FeedSpec, WireSpec

# Encaixes.  Meio milimetro e 15 graus cobrem quase todo desenho de antena sem
# obrigar a mirar com precisao de pixel.
PASSO_MM = 0.5
PASSO_GRAUS = 15.0


def _snap(v: float, passo: float) -> float:
    return round(v / passo) * passo


@dataclass
class Traco:
    """O que um gesto produziu, para a barra de estado contar."""

    descricao: str
    comprimento_mm: float
    wire: str


# --------------------------------------------------------------------------
# os tres gestos que criam geometria
# --------------------------------------------------------------------------


def primeiro_braco(spec: AntennaSpec, ponto, livre: bool = False) -> Traco:
    """Um clique so ja da um dipolo: braco, espelho e alimentacao.

    A alimentacao fica na origem porque e o unico ponto que deixa as expressoes
    legiveis (``Gap/2``, ``-Gap/2``) e o espelho exato.
    """
    p = np.asarray(ponto, dtype=float)[:2]
    gap = _valor(spec, "Gap", 4.0)
    comp, ang = _polar(p, np.zeros(2), livre)
    comp = max(comp - gap / 2.0, PASSO_MM)

    nome_l = _proximo(spec, "L")
    _add_param(spec, nome_l, comp, "Comprimento do braco (mm)")

    horizontal = abs(math.cos(math.radians(ang))) >= abs(math.sin(math.radians(ang)))
    eixo = "x" if horizontal else "y"
    if horizontal:
        inicio = {"x": "Gap/2" if p[0] >= 0 else "-Gap/2", "y": "0", "dir": _ang(ang)}
        meio, oposto = ("Gap/2", "0", "0"), ("-Gap/2", "0", "0")
    else:
        inicio = {"x": "0", "y": "Gap/2" if p[1] >= 0 else "-Gap/2", "dir": _ang(ang)}
        meio, oposto = ("0", "Gap/2", "0"), ("0", "-Gap/2", "0")

    spec.wires.append(
        WireSpec.model_validate({
            "name": "braco_1", "role": "driven", "start": inicio,
            "blocks": [{"type": "straight", "len": nome_l}],
        })
    )
    spec.wires.append(
        WireSpec.model_validate({
            "name": "braco_2", "role": "driven",
            "mirror_of": "braco_1", "mirror_axis": eixo,
        })
    )
    if spec.feed is None:
        spec.feed = FeedSpec.model_validate({"p1": list(oposto), "p2": list(meio)})
    return Traco("dipolo com dois bracos", comp, "braco_1")


def crescer(
    spec: AntennaSpec, wire: str, ponto, livre: bool = False
) -> Traco | None:
    """Anexa um trecho ao FIM do fio, indo ate ``ponto``.

    A ponta nova fica imediatamente clicavel, entao um fio de varios trechos sai
    de cliques seguidos sem nenhum modo.
    """
    alvo = _fio(spec, wire)
    if alvo is None or alvo.mirror_of:
        return None

    ws = spec.to_wireset()
    verts = ws.wire(wire).centerline.points(ws.params)
    p = np.asarray(ponto, dtype=float)[:2]
    comp, ang = _polar(p, verts[-1][:2], livre)
    if comp < PASSO_MM:
        return None

    virada = _normaliza(ang - _rumo(verts))
    nome_l = _proximo(spec, "L")
    _add_param(spec, nome_l, comp, "Comprimento do trecho (mm)")

    if abs(virada) > 0.01:
        nome_a = _proximo(spec, "A")
        _add_param(spec, nome_a, virada, "Angulo da dobra (graus)")
        alvo.blocks.append({"type": "bend", "angle": nome_a, "fillet": _raio(spec)})
    alvo.blocks.append({"type": "straight", "len": nome_l})
    return Traco(f"trecho em {wire}", comp, wire)


def novo_elemento(
    spec: AntennaSpec, centro, comprimento: float, angulo: float = 90.0,
    nome: str | None = None,
) -> Traco:
    """Elemento solto: refletor, diretor, qualquer fio que nao se conecta.

    Nasce CENTRADO no ponto, que e como se pensa um elemento de arranjo -- a
    posicao dele no boom e o que importa, nao onde a ponta comeca.
    """
    c = np.asarray(centro, dtype=float)[:2]
    comp = max(_snap(float(comprimento), PASSO_MM), PASSO_MM)
    ang = _snap(float(angulo), PASSO_GRAUS)

    nome_l = _proximo(spec, "L")
    _add_param(spec, nome_l, comp, "Comprimento do elemento (mm)")

    d = np.array([math.cos(math.radians(ang)), math.sin(math.radians(ang))])
    inicio = c - d * comp / 2.0
    nome = nome or _nome_livre(spec, "elemento")
    spec.wires.append(
        WireSpec.model_validate({
            "name": nome, "role": "parasitic",
            "start": {
                "x": format_number(_snap(float(inicio[0]), PASSO_MM)),
                "y": format_number(_snap(float(inicio[1]), PASSO_MM)),
                "dir": format_number(ang),
            },
            "blocks": [{"type": "straight", "len": nome_l}],
        })
    )
    return Traco(f"{nome} (elemento parasita)", comp, nome)


def anexar_bloco(
    spec: AntennaSpec, wire: str, tipo: str, campos: dict | None = None
) -> Traco | None:
    """Encaixa um bloco no fim do fio -- o alvo do arrasto vindo da paleta."""
    alvo = _fio(spec, wire)
    if alvo is None or alvo.mirror_of or alvo.vertices:
        return None
    from .inspector import default_block

    bloco = default_block(tipo)
    bloco.update(campos or {})
    antes = spec.to_wireset().wire(wire).centerline.length(spec.to_wireset().params)
    alvo.blocks.append(bloco)
    depois = spec.to_wireset().wire(wire).centerline.length(spec.to_wireset().params)
    return Traco(f"{tipo} em {wire}", depois - antes, wire)


# --------------------------------------------------------------------------
# apoio
# --------------------------------------------------------------------------


def novo_fio_com_bloco(
    spec: AntennaSpec, ponto, tipo: str, rumo: float = 0.0
) -> Traco | None:
    """Fio novo comecando naquele ponto, feito do bloco solto ali.

    Blocos como ``bend`` nao produzem geometria sozinhos -- eles dobram o que
    veio antes.  Nesses casos entra uma reta curta na frente, que e tambem o que
    a ficha da paleta desenha.
    """
    from ..blocks import BlockError, Cursor, build_chain
    from .inspector import default_block

    p = np.asarray(ponto, dtype=float)[:2]
    bloco = default_block(tipo)
    inicio = {
        "x": format_number(_snap(float(p[0]), PASSO_MM)),
        "y": format_number(_snap(float(p[1]), PASSO_MM)),
        "dir": format_number(_snap(float(rumo), PASSO_GRAUS)),
    }
    for blocos in ([bloco], [{"type": "straight", "len": "8"}, bloco]):
        try:
            build_chain(blocos, Cursor(x=inicio["x"], y=inicio["y"],
                                       heading=inicio["dir"]))
        except (BlockError, ValueError):
            continue
        nome = _nome_livre(spec, "elemento")
        spec.wires.append(
            WireSpec.model_validate({
                "name": nome, "role": "parasitic",
                "start": inicio, "blocks": blocos,
            })
        )
        ws = spec.to_wireset()
        return Traco(
            f"{nome} solto", ws.wire(nome).centerline.length(ws.params), nome
        )
    return None


def tem_antena(spec: AntennaSpec) -> bool:
    return bool(spec.wires)


def _fio(spec: AntennaSpec, nome: str):
    return next((w for w in spec.wires if w.name == nome), None)


def _polar(p: np.ndarray, origem: np.ndarray, livre: bool) -> tuple[float, float]:
    d = p - origem
    comp = float(np.hypot(d[0], d[1]))
    ang = math.degrees(math.atan2(d[1], d[0]))
    if not livre:
        comp = _snap(comp, PASSO_MM)
        ang = _snap(ang, PASSO_GRAUS)
    return max(comp, PASSO_MM), ang


def _rumo(verts: np.ndarray) -> float:
    if len(verts) < 2:
        return 0.0
    d = verts[-1][:2] - verts[-2][:2]
    return math.degrees(math.atan2(d[1], d[0]))


def _normaliza(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def _ang(a: float) -> str:
    return format_number(_normaliza(a))


def _raio(spec: AntennaSpec) -> str:
    return "Radius" if "Radius" in spec.params else format_number(2.0)


def _valor(spec: AntennaSpec, nome: str, padrao: float) -> float:
    try:
        return spec.to_wireset().params.values().get(nome, padrao)
    except Exception:
        return padrao


def _proximo(spec: AntennaSpec, prefixo: str) -> str:
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
