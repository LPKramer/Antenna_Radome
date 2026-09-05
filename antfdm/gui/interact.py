"""O que esta sob o cursor, e o que cada gesto faz com aquilo.

Sem Qt de proposito: recebe posicoes em milimetros e devolve o alvo.  Assim o
comportamento e testavel sem abrir janela, que e o que permite provar "clicar na
ponta cresce o fio" sem depender de captura de tela.

A antena deixa de ser um desenho passivo e passa a ser um objeto onde cada parte
reage: pontas crescem, arestas esticam, vertices movem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from ..core.expr import ParamTable
from ..core.wireset import WireSet

Tipo = Literal["ponta", "vertice", "aresta"]

# Prioridade quando varios alvos caem sob o cursor.  Ponta na frente porque e o
# gesto principal (crescer o fio); aresta por ultimo porque cobre area grande e
# roubaria o clique dos outros dois.
_PRIORIDADE: dict[Tipo, int] = {"ponta": 0, "vertice": 1, "aresta": 2}


@dataclass
class Alvo:
    tipo: Tipo
    wire: str
    indice: int  # vertice, ou indice do trecho quando tipo == "aresta"
    ponto: np.ndarray  # ponto exato (no vertice, ou o mais proximo da aresta)
    distancia: float
    editavel: bool = True  # False em fio espelhado: quem manda e o original

    @property
    def chave(self) -> tuple[str, str, int]:
        return (self.tipo, self.wire, self.indice)


def _dist_ao_trecho(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[float, np.ndarray]:
    """Distancia de ``p`` ao segmento ``ab``, e o ponto mais proximo nele."""
    ab = b - a
    n2 = float(ab @ ab)
    if n2 < 1e-12:
        return float(np.linalg.norm(p - a)), a
    t = float(np.clip((p - a) @ ab / n2, 0.0, 1.0))
    perto = a + ab * t
    return float(np.linalg.norm(p - perto)), perto


def alvos(ws: WireSet, spec_wires=None) -> list[Alvo]:
    """Todos os alvos da antena, com distancia ainda por preencher.

    ``spec_wires`` traz os fios do spec para saber quais sao espelhos -- um fio
    espelhado nao se edita direto, acompanha o original.
    """
    espelhos = set()
    if spec_wires is not None:
        espelhos = {w.name for w in spec_wires if getattr(w, "mirror_of", None)}

    out: list[Alvo] = []
    for w in ws.wires:
        try:
            verts = w.centerline.points(ws.params)
        except Exception:
            continue
        if len(verts) < 2:
            continue
        editavel = w.name not in espelhos
        ultimos = {0, len(verts) - 1}
        for i, v in enumerate(verts):
            tipo: Tipo = "ponta" if (i in ultimos and not w.centerline.closed) else "vertice"
            out.append(Alvo(tipo, w.name, i, v[:2].copy(), 0.0, editavel))
        for i in range(len(verts) - 1):
            out.append(
                Alvo("aresta", w.name, i, (verts[i][:2] + verts[i + 1][:2]) / 2.0,
                     0.0, editavel)
            )
    return out


def localizar(
    ws: WireSet, pos, tolerancia: float, params: ParamTable | None = None,
    spec_wires=None,
) -> Alvo | None:
    """Alvo sob ``pos`` (mm), ou None. ``tolerancia`` tambem em mm.

    Empate resolve por tipo antes de distancia: com o cursor entre uma ponta e a
    aresta que sai dela, o que se quer quase sempre e a ponta.
    """
    del params
    p = np.asarray(pos, dtype=float)[:2]
    candidatos: list[Alvo] = []

    espelhos = set()
    if spec_wires is not None:
        espelhos = {w.name for w in spec_wires if getattr(w, "mirror_of", None)}

    for w in ws.wires:
        try:
            verts = w.centerline.points(ws.params)
        except Exception:
            continue
        if len(verts) < 2:
            continue
        editavel = w.name not in espelhos
        ultimos = {0, len(verts) - 1}

        for i, v in enumerate(verts):
            d = float(np.linalg.norm(p - v[:2]))
            if d > tolerancia:
                continue
            tipo: Tipo = "ponta" if (i in ultimos and not w.centerline.closed) else "vertice"
            candidatos.append(Alvo(tipo, w.name, i, v[:2].copy(), d, editavel))

        for i in range(len(verts) - 1):
            d, perto = _dist_ao_trecho(p, verts[i][:2], verts[i + 1][:2])
            if d <= tolerancia:
                candidatos.append(Alvo("aresta", w.name, i, perto, d, editavel))

    if not candidatos:
        return None
    return min(candidatos, key=lambda a: (_PRIORIDADE[a.tipo], a.distancia))


def ponta_mais_proxima(
    ws: WireSet, pos, alcance: float, spec_wires=None
) -> Alvo | None:
    """Ponta livre mais proxima de ``pos``, para o encaixe do bloco arrastado.

    Alcance maior que a tolerancia de clique: ao arrastar um bloco a mira e
    grosseira, e exigir precisao de pixel derrubaria o gesto.
    """
    p = np.asarray(pos, dtype=float)[:2]
    espelhos = set()
    if spec_wires is not None:
        espelhos = {w.name for w in spec_wires if getattr(w, "mirror_of", None)}

    melhor: Alvo | None = None
    for w in ws.wires:
        if w.name in espelhos or w.centerline.closed:
            continue
        try:
            verts = w.centerline.points(ws.params)
        except Exception:
            continue
        if len(verts) < 2:
            continue
        # So a ULTIMA ponta: a cadeia de blocos cresce pelo fim, e encaixar no
        # inicio exigiria inverter o fio inteiro.
        i = len(verts) - 1
        d = float(np.linalg.norm(p - verts[i][:2]))
        if d <= alcance and (melhor is None or d < melhor.distancia):
            melhor = Alvo("ponta", w.name, i, verts[i][:2].copy(), d, True)
    return melhor


def descrever(alvo: Alvo | None, ws: WireSet | None) -> str:
    """Texto curto para a barra de estado, em linguagem de antena."""
    if alvo is None or ws is None:
        return ""
    if not alvo.editavel:
        return f"{alvo.wire} acompanha o outro braco; edite o original"
    if alvo.tipo == "ponta":
        return f"ponta de {alvo.wire} — arraste para esticar, ou solte um bloco aqui"
    if alvo.tipo == "vertice":
        return f"vertice {alvo.indice} de {alvo.wire} — arraste para mover"
    try:
        verts = ws.wire(alvo.wire).centerline.points(ws.params)
        comp = float(np.linalg.norm(verts[alvo.indice + 1][:2] - verts[alvo.indice][:2]))
        return f"trecho de {alvo.wire}: {comp:.1f} mm — arraste para mudar"
    except Exception:
        return f"trecho de {alvo.wire}"
