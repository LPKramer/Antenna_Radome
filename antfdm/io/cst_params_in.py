"""Le de volta os parametros calibrados de um projeto CST.

Depois que voce calibra no CST, a autoridade sobre as dimensoes passa a ser o
projeto, nao o YAML.  Este modulo traz os valores de volta para que a peca saia
com as dimensoes calibradas.

Le ``<projeto>/Model/Parameters.json``, que o CST reescreve a cada salvamento e
ja e JSON legivel com ``name``/``expr``/``value``.  Nao precisa de licenca nem do
CST aberto -- so do projeto salvo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from ..core.expr import from_cst


class SyncError(ValueError):
    pass


@dataclass
class CstParameter:
    name: str
    expr: str  # ja na sintaxe canonica
    value: float


def locate(path: str | Path) -> Path:
    """Encontra o Parameters.json a partir do .cst, da pasta ou do proprio JSON."""
    p = Path(path)
    if p.is_file() and p.suffix.lower() == ".json":
        return p
    if p.is_file() and p.suffix.lower() == ".cst":
        candidate = p.with_suffix("") / "Model" / "Parameters.json"
    elif p.is_dir():
        candidate = p / "Model" / "Parameters.json"
    else:
        raise SyncError(f"nao encontrei o projeto em {p}")
    if not candidate.exists():
        raise SyncError(
            f"{candidate} nao existe. O CST grava esse arquivo ao SALVAR o projeto; "
            "salve no CST e tente de novo."
        )
    return candidate


def read(path: str | Path) -> dict[str, CstParameter]:
    src = locate(path)
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))["parameters"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise SyncError(f"{src}: nao consegui ler os parametros ({exc})") from exc

    names = [p["name"] for p in raw]
    out: dict[str, CstParameter] = {}
    for p in raw:
        out[p["name"]] = CstParameter(
            name=p["name"],
            expr=from_cst(str(p["expr"]), names),
            value=float(p["value"]),
        )
    return out


@dataclass
class Change:
    name: str
    de: str
    para: str

    def __str__(self) -> str:
        return f"  {self.name:<20} {self.de}  ->  {self.para}"


def apply_to_spec(spec, cst_params: dict[str, CstParameter]) -> tuple[list[Change], list[str]]:
    """Traz os valores do CST para o spec.

    So toca em parametros que o spec ja declara: um parametro criado a mao no CST
    nao entra sozinho, porque nada na geometria gerada o usaria.  Ele e reportado
    como ignorado, para voce decidir.
    """
    changes: list[Change] = []
    ignored: list[str] = []

    lower = {k.lower(): v for k, v in cst_params.items()}
    for name in list(spec.params):
        entry = spec.params[name]
        atual = str(entry["expr"] if isinstance(entry, dict) else entry)
        vindo = lower.get(name.lower())
        if vindo is None:
            continue
        if _same(atual, vindo.expr):
            continue
        changes.append(Change(name, atual, vindo.expr))
        if isinstance(entry, dict):
            entry["expr"] = vindo.expr
        else:
            spec.params[name] = vindo.expr

    declarados = {n.lower() for n in spec.params}
    ignored = [p.name for k, p in lower.items() if k not in declarados]
    return changes, ignored


def _same(a: str, b: str) -> bool:
    """Compara ignorando espaco: 'a+b' e 'a + b' sao a mesma expressao."""
    return a.replace(" ", "") == b.replace(" ", "")
