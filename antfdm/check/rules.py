"""Avisos sobre a antena, em linguagem de antena.

Responde "isso vai funcionar?" sem jargao e sem solver.  As faixas sao guias
classicas, nao verdade: quem decide a dimensao final e o CST.  Por isso as
tolerancias sao largas de proposito -- um aviso que dispara a toda hora vira
ruido e para de ser lido.

Cada aviso carrega a correcao, entao aceitar a sugestao e um clique.  E a sintese
entrando pela porta do desenho, em vez de virar um gerador separado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from ..core.wireset import WireSet

Severidade = Literal["erro", "aviso", "dica"]

_ORDEM = {"erro": 0, "aviso": 1, "dica": 2}

# Fracao do campo proximo ocupada pelo radome.  O fio nao esta imerso num meio
# infinito, so envolvido por uma casca fina, entao o encurtamento real fica entre
# nenhum e o da imersao total.  Este e o numero para calibrar depois de UMA medida.
COBERTURA_RADOME = 0.5

# Encurtamento classico de um dipolo de fio fino em relacao a meia onda exata.
K_RESSONANCIA = 0.95

# Acima disto o elemento e considerado DOBRADO (serpentina, espiral), e a regra
# de meia onda deixa de valer: o que ressoa nao e o comprimento de fio.  Medido
# nas receitas: reto fica em 0.97-1.03, serpentina em 1.46, espiral em 6.33.
DOBRADO = 1.15


@dataclass
class Correcao:
    """O que aplicar para resolver o aviso."""

    descricao: str
    wire: str
    alvo_mm: float


@dataclass
class Aviso:
    severidade: Severidade
    texto: str
    wire: str | None = None
    correcao: Correcao | None = None

    def __str__(self) -> str:
        marca = {"erro": "!!", "aviso": " !", "dica": " ."}[self.severidade]
        return f"{marca} {self.texto}"


# --------------------------------------------------------------------------


def lambda_mm(ws: WireSet) -> float | None:
    """Comprimento de onda no vacuo, em mm. None se a antena nao tem f0."""
    if not ws.f0_hz:
        return None
    return 300000.0 / (ws.f0_hz / 1e6)


def velocity_factor(ws: WireSet, cobertura: float = COBERTURA_RADOME) -> float:
    """Encurtamento causado pelo radome, com cobertura parcial.

    ``materials.velocity_factor`` supoe imersao total e e o limite inferior;
    aqui a permissividade e interpolada entre o ar e o valor efetivo do PLA.
    """
    eps = 1.0 + (ws.radome.material.eps_eff - 1.0) * cobertura
    return eps**-0.5


def _centroide(ws: WireSet, wire) -> np.ndarray:
    return wire.centerline.points(ws.params).mean(axis=0)


def _eixo_do_arranjo(centros: list[np.ndarray]) -> int:
    """Eixo (0=X, 1=Y) em que os elementos estao espalhados."""
    arr = np.array(centros)
    return int(np.argmax(arr.max(axis=0) - arr.min(axis=0)))


# --------------------------------------------------------------------------
# regras
# --------------------------------------------------------------------------


def _regra_elemento_alimentado(ws: WireSet, lam: float) -> list[Aviso]:
    driven = ws.driven()
    if not driven:
        return [Aviso("erro", "nenhum fio esta ligado a alimentacao")]

    atual = sum(w.centerline.length(ws.params) for w in driven)

    # Serpentina e espiral tem muito mais fio que vao fisico -- e justamente
    # para isso que existem.  Comparar o comprimento de fio com meia onda
    # acusaria "525% longo demais" numa espiral que esta correta.
    pts = np.vstack([w.centerline.points(ws.params) for w in driven])
    vao = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
    if vao > 0 and atual / vao > DOBRADO:
        return [
            Aviso(
                "dica",
                f"o elemento alimentado e dobrado ({atual:.0f} mm de fio em "
                f"{vao:.0f} mm de vao); a conferencia por meia onda nao se aplica, "
                "confirme a ressonancia no CST",
                wire=driven[0].name,
            )
        ]

    alvo = K_RESSONANCIA * (lam / 2.0) * velocity_factor(ws)
    desvio = atual / alvo - 1.0

    if abs(desvio) <= 0.15:
        return []
    severidade: Severidade = "erro" if abs(desvio) > 0.30 else "aviso"
    lado = "longo" if desvio > 0 else "curto"
    return [
        Aviso(
            severidade,
            f"o elemento alimentado esta {abs(desvio) * 100:.0f}% {lado} demais "
            f"para {ws.f0_hz / 1e6:.0f} MHz "
            f"({atual:.1f} mm; o esperado e ~{alvo:.1f} mm)",
            wire=driven[0].name,
            correcao=Correcao(
                f"ajustar para {alvo / len(driven):.1f} mm por braco",
                driven[0].name,
                alvo / len(driven),
            ),
        )
    ]


def _regra_parasitas(ws: WireSet, lam: float) -> list[Aviso]:
    driven = ws.driven()
    parasitas = [w for w in ws.wires if w.role == "parasitic"]
    if not driven or not parasitas:
        return []

    l_driven = sum(w.centerline.length(ws.params) for w in driven)
    if l_driven <= 0:
        return []

    avisos: list[Aviso] = []
    for w in parasitas:
        comp = w.centerline.length(ws.params)
        razao = comp / l_driven
        # Mais longo que o alimentado reflete; mais curto dirige.  Quem decide o
        # papel e o comprimento, nao o nome que o fio recebeu.
        if razao >= 1.0:
            lo, hi, papel = 1.02, 1.10, "refletor"
        else:
            lo, hi, papel = 0.90, 0.98, "diretor"
        if lo <= razao <= hi:
            continue
        ideal = (lo + hi) / 2.0 * l_driven
        avisos.append(
            Aviso(
                "aviso",
                f"{w.name}: como {papel}, deveria medir entre "
                f"{lo * l_driven:.1f} e {hi * l_driven:.1f} mm "
                f"({comp:.1f} mm hoje, {razao:.0%} do alimentado)",
                wire=w.name,
                correcao=Correcao(f"ajustar para {ideal:.1f} mm", w.name, ideal),
            )
        )
    return avisos


def _regra_espacamento(ws: WireSet, lam: float) -> list[Aviso]:
    # So faz sentido num arranjo.  Os dois bracos de um dipolo, ou os dois bracos
    # de uma espiral, ficam colados de proposito e nao sao elementos separados.
    if not any(w.role == "parasitic" for w in ws.wires) or len(ws.wires) < 2:
        return []
    centros = [_centroide(ws, w) for w in ws.wires]
    eixo = _eixo_do_arranjo(centros)
    posicoes = sorted((float(c[eixo]), w.name) for c, w in zip(centros, ws.wires))

    avisos: list[Aviso] = []
    for (p1, n1), (p2, n2) in zip(posicoes, posicoes[1:]):
        d = abs(p2 - p1) / lam
        if d < 1e-6:
            continue  # mesmo plano: bracos de um dipolo, nao elementos de arranjo
        if 0.10 <= d <= 0.35:
            continue
        fora = "perto" if d < 0.10 else "longe"
        avisos.append(
            Aviso(
                "aviso" if d < 0.5 else "dica",
                f"{n1} e {n2} estao {fora} demais: {d:.2f} lambda "
                f"(a faixa util e 0.10 a 0.35)",
                wire=n2,
            )
        )
    return avisos


def _regra_alimentacao(ws: WireSet, lam: float) -> list[Aviso]:
    if ws.feed is None:
        return [Aviso("erro", "a antena nao tem alimentacao definida")]
    p1 = np.array([ws.params.evaluate(c) for c in ws.feed.p1])
    p2 = np.array([ws.params.evaluate(c) for c in ws.feed.p2])
    gap = float(np.linalg.norm(p2 - p1))
    if gap <= 0.05 * lam:
        return []
    # Dica, e nao aviso: um gap grande e escolha de projeto, nao erro.  Desloca a
    # ressonancia, e o CST mostra quanto -- aqui so vale registrar.
    return [
        Aviso(
            "dica",
            f"a abertura de alimentacao tem {gap:.1f} mm ({gap / lam:.2f} lambda); "
            "acima de 0.05 lambda ela ja desloca a ressonancia de forma perceptivel",
        )
    ]


def _regra_dobra(ws: WireSet) -> list[Aviso]:
    """Dobra apertada trinca o esmalte, e o fio passa a oxidar por dentro."""
    bitola = ws.params.evaluate(ws.conductor.bitola)
    minimo = 2.0 * bitola
    avisos: list[Aviso] = []
    for w in ws.wires:
        # Uma serpentina tem dezenas de dobras iguais; listar uma a uma afogaria
        # todo o resto.  Conta e reporta uma vez por fio.
        apertadas = [
            v.radius(ws.params)
            for v in w.centerline.vertices
            if v.fillet and 0 < v.radius(ws.params) < minimo
        ]
        if not apertadas:
            continue
        quantas = (
            "a dobra" if len(apertadas) == 1 else f"{len(apertadas)} dobras"
        )
        avisos.append(
            Aviso(
                "aviso",
                f"{w.name}: {quantas} de raio {min(apertadas):.1f} mm sao apertadas "
                f"para fio de {bitola:.1f} mm; o esmalte pode trincar "
                f"(use {minimo:.1f} mm ou mais)",
                wire=w.name,
            )
        )
    return avisos


def _regra_mesa(ws: WireSet, bed: tuple[float, float, float] | None) -> list[Aviso]:
    """Estimativa barata: contorno dos fios mais a secao do radome.

    Nao constroi o solido de proposito -- os booleanos do OCCT levam segundos, e
    isto roda a cada clique.  A checagem exata continua em cad/export.py, na hora
    de gerar a peca.
    """
    if bed is None:
        return []
    pts = np.vstack([w.centerline.points(ws.params) for w in ws.wires])
    folga = 2.0 * (
        ws.params.evaluate(ws.conductor.bitola) / 2.0
        + ws.radome.folga
        + ws.params.evaluate(ws.radome.parede)
    )
    tamanho = (pts.max(axis=0) - pts.min(axis=0))[:2] + folga
    if tamanho[0] <= bed[0] and tamanho[1] <= bed[1]:
        return []
    return [
        Aviso(
            "aviso",
            f"a peca ficaria com {tamanho[0]:.0f} x {tamanho[1]:.0f} mm e nao cabe "
            f"na mesa de {bed[0]:.0f} x {bed[1]:.0f} mm",
        )
    ]


# --------------------------------------------------------------------------


def verificar(
    ws: WireSet, bed: tuple[float, float, float] | None = None
) -> list[Aviso]:
    """Todos os avisos da antena, do mais grave para o menos."""
    avisos: list[Aviso] = []

    for problema in ws.validate():
        avisos.append(Aviso("erro", problema))
    if avisos:
        return avisos  # geometria quebrada: o resto nem da para medir

    lam = lambda_mm(ws)
    if lam is None:
        avisos.append(
            Aviso(
                "dica",
                "a antena nao tem frequencia alvo; sem ela nao da para conferir "
                "os comprimentos",
            )
        )
    else:
        avisos += _regra_elemento_alimentado(ws, lam)
        avisos += _regra_parasitas(ws, lam)
        avisos += _regra_espacamento(ws, lam)
        avisos += _regra_alimentacao(ws, lam)

    avisos += _regra_dobra(ws)
    avisos += _regra_mesa(ws, bed)

    return sorted(avisos, key=lambda a: _ORDEM[a.severidade])


def resumo(avisos: list[Aviso]) -> str:
    """Uma linha para o rodape."""
    if not avisos:
        return "tudo dentro da faixa"
    pior = avisos[0]
    resto = len(avisos) - 1
    return pior.texto + (f"   (+{resto})" if resto else "")


# --------------------------------------------------------------------------
# aplicar a correcao
# --------------------------------------------------------------------------


def aplicar(spec, correcao: Correcao) -> tuple[bool, str]:
    """Ajusta o spec para o fio medir ``alvo_mm``. Devolve (deu certo, motivo)."""
    from ..core.solve import apply_edit, solve_field

    alvo = next((w for w in spec.wires if w.name == correcao.wire), None)
    if alvo is None:
        return False, f"o fio {correcao.wire!r} nao existe mais"
    if alvo.mirror_of:
        return False, f"{alvo.name!r} e espelho de {alvo.mirror_of!r}; ajuste o original"

    retos = [
        i for i, b in enumerate(alvo.blocks) if b.get("type") == "straight"
    ]
    if len(retos) != 1:
        return False, (
            f"{alvo.name!r} tem {len(retos)} trechos retos; nao da para decidir "
            "sozinho qual encurtar. Ajuste pelo painel Avancado."
        )

    ws = spec.to_wireset()
    bloco = alvo.blocks[retos[0]]
    atual = ws.wire(alvo.name).centerline.length(ws.params)
    campo = str(bloco.get("len", ""))
    # O bloco reto pode nao ser o fio inteiro (pode haver arcos e dobras junto),
    # entao o alvo do CAMPO e o alvo do fio menos o que os outros blocos somam.
    resto = atual - ws.params.evaluate(campo)
    edit = solve_field(campo, correcao.alvo_mm - resto, ws.params)

    if edit.kind == "ambiguous":
        return False, (
            f"o comprimento depende de {', '.join(edit.candidates)}; "
            "escolha qual ajustar pelo painel Avancado"
        )
    if not edit.ok:
        return False, edit.reason
    if not apply_edit(spec, edit, wire=spec.wires.index(alvo),
                      block=retos[0], field_name="len"):
        return False, "nao consegui gravar a alteracao"

    extra = f" (tambem muda {', '.join(edit.affects)})" if edit.affects else ""
    return True, f"{correcao.descricao}{extra}"
