"""Inversao: de uma posicao arrastada na tela para uma edicao de parametro.

Arrastar produz NUMERO, mas o projeto inteiro depende de as coordenadas serem
EXPRESSAO -- e o que mantem o modelo ajustavel na Parameter List do CST, onde a
calibracao final acontece.  Gravar o numero direto emitiria ``.X2 "42.5"`` e a
ferramenta perderia a razao de existir.

A saida e nao editar a geometria, e sim o parametro que a produz.  Efeito
colateral desejavel: o braco espelhado se move junto, e o acoplamento
parametrico fica visivel em vez de escondido.

Ao ajustar uma expressao, a FORMA e preservada e so o numero muda:

    0.235*Lambda  ->  0.271*Lambda      (nao vira "81.2")
    Gap/2 + 10    ->  Gap/2 + 12.5      (mexe na parcela constante)
    L_braco       ->  1.15*L_braco      (sem numero onde mexer, escala)

Preservar a forma e o que faz a antena continuar reescalando com F0 depois de
arrastada -- se virasse literal, a relacao com Lambda se perderia no primeiro
arrasto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import sympy

from .expr import ExprError, ParamTable, free_names, literal_value, parse

Kind = Literal["param", "literal", "ambiguous", "impossible"]


@dataclass
class Edit:
    """O que fazer para que o campo passe a valer o alvo.

    Nao aplica nada: quem chama decide, porque em ``ambiguous`` e preciso
    perguntar ao usuario qual parametro mexer.
    """

    kind: Kind
    param: str | None = None  # parametro a alterar
    new_expr: str | None = None  # nova expressao dele (ou do campo, se literal)
    candidates: list[str] = field(default_factory=list)  # para 'ambiguous'
    affects: list[str] = field(default_factory=list)  # outros parametros que mudam junto
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.kind in ("param", "literal")


def format_number(v: float) -> str:
    """Numero legivel na Parameter List, sem perder precisao.

    Escolhe a forma MAIS CURTA que ainda reproduz o valor.  Cortar em um numero
    fixo de casas parecia bastar, mas um coeficiente como 100/345.622 perde
    precisao suficiente para a antena nao cair onde foi arrastada -- e o erro
    aparece calado, como alguns micrometros de diferenca.
    """
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    for sig in range(4, 18):
        s = f"{v:.{sig}g}"
        if abs(float(s) - v) <= 1e-12 * max(abs(v), 1e-300):
            return s
    return repr(v)


def adjust_expression(expr: str, current: float, target: float) -> str:
    """Reescreve ``expr`` para valer ``target``, preservando a forma.

    Tres casos, nesta ordem, do mais especifico ao mais generico:

    1. literal        -> substitui o numero
    2. tem parcela constante (``Gap/2 + 10``) -> desloca a constante
    3. tem coeficiente (``0.235*Lambda``)     -> escala o coeficiente

    Preferir a parcela constante ao coeficiente importa: em ``Gap/2 + 10``,
    escalar tudo mexeria no Gap tambem, e o Gap nao e o que esta sendo
    arrastado.
    """
    src = str(expr).strip()
    if literal_value(src) is not None:
        return format_number(target)

    try:
        e = parse(src, free_names(src))
    except ExprError:
        return format_number(target)

    delta = target - current

    const, rest = e.as_coeff_Add()
    if const != 0:
        return _render(rest + sympy.Float(float(const) + delta))

    if abs(current) > 1e-12:
        coeff, rest_mul = e.as_coeff_Mul()
        return _render(sympy.Float(float(coeff) * target / current) * rest_mul)

    # Valor atual zero: escalar seria divisao por zero, e somar a uma expressao
    # sem parcela constante inventaria um termo.  Vira soma explicita.
    return _render(e + sympy.Float(delta))


def _render(e) -> str:
    """Texto da expressao com os numeros na forma mais curta que preserva o valor."""
    texto = str(e)
    for atom in sorted(e.atoms(sympy.Float), key=lambda a: -len(str(a))):
        texto = texto.replace(str(atom), format_number(float(atom)))
    return texto


def solve_field(
    expr: str, target: float, params: ParamTable, prefer: str | None = None
) -> Edit:
    """Decide como fazer o campo ``expr`` passar a valer ``target``.

    ``prefer`` resolve a ambiguidade quando o campo cita varios parametros --
    e o nome que o usuario escolheu no dialogo.
    """
    src = str(expr).strip()
    if not src:
        return Edit(kind="impossible", reason="campo vazio")

    normalizado = params.normalize(src)
    citados = sorted(free_names(normalizado) & set(params.params))

    if not citados:
        # Campo literal: da para gravar o numero, mas o modelo perde o ajuste no
        # CST.  Quem chama deve oferecer promover a parametro.
        return Edit(
            kind="literal",
            new_expr=format_number(target),
            reason="o campo e um numero fixo; promova a parametro para poder "
            "calibrar no CST",
        )

    if prefer is not None:
        if prefer not in citados:
            return Edit(
                kind="impossible",
                reason=f"{prefer!r} nao aparece em {src!r}",
            )
        escolhido = prefer
    elif len(citados) == 1:
        escolhido = citados[0]
    else:
        return Edit(
            kind="ambiguous",
            candidates=citados,
            reason=f"{src!r} depende de {len(citados)} parametros; escolha qual ajustar",
        )

    # Quanto o parametro escolhido precisa valer para o campo dar o alvo.
    try:
        preciso = _value_for(normalizado, escolhido, target, params)
    except ExprError as exc:
        return Edit(kind="impossible", reason=str(exc))

    atual = params.values()[escolhido]
    nova = adjust_expression(params.params[escolhido].expr, atual, preciso)

    # Mexer num parametro do qual outros dependem propaga.  As vezes e o que se
    # quer (o braco espelhado acompanhar), as vezes nao (mexer em Lambda mudaria
    # a velocidade da luz).  Reportar deixa a decisao com quem esta arrastando.
    afetados = dependents(params, escolhido)
    return Edit(kind="param", param=escolhido, new_expr=nova, affects=afetados)


def dependents(params: ParamTable, name: str) -> list[str]:
    """Parametros que mudam de valor se ``name`` mudar, direta ou indiretamente."""
    direto: dict[str, set[str]] = {
        n: free_names(params.normalize(p.expr)) & set(params.params)
        for n, p in params.params.items()
    }
    afetados: set[str] = set()
    fila = [name]
    while fila:
        atual = fila.pop()
        for n, deps in direto.items():
            if atual in deps and n not in afetados and n != name:
                afetados.add(n)
                fila.append(n)
    return sorted(afetados)


def _value_for(
    expr: str, name: str, target: float, params: ParamTable
) -> float:
    """Valor que ``name`` precisa ter para ``expr`` valer ``target``."""
    valores = params.values()
    sym = sympy.Symbol(name)
    e = parse(expr, free_names(expr))
    e = e.subs({sympy.Symbol(k): v for k, v in valores.items() if k != name})

    if sym not in e.free_symbols:
        raise ExprError(f"{name!r} some da expressao ao substituir os outros valores")

    try:
        raizes = sympy.solve(sympy.Eq(e, sympy.Float(target)), sym)
    except (NotImplementedError, TypeError) as exc:
        raise ExprError(f"nao consegui inverter {expr!r}: {exc}") from exc

    reais = []
    for r in raizes:
        try:
            v = complex(r.evalf())
        except (TypeError, AttributeError):
            continue
        if abs(v.imag) < 1e-9:
            reais.append(v.real)
    if not reais:
        raise ExprError(f"{expr!r} nao tem solucao real para o alvo {target:.4g}")

    # Varias raizes: fica com a mais proxima do valor atual, que e a que o
    # usuario reconhece como "a mesma antena, um pouco diferente".
    atual = valores[name]
    return min(reais, key=lambda v: abs(v - atual))


def apply_edit(spec, edit: Edit, wire: int | None = None,
               block: int | None = None, field_name: str | None = None) -> bool:
    """Grava a edicao no spec. Devolve False se ela nao for aplicavel."""
    if not edit.ok:
        return False
    if edit.kind == "param":
        entrada = spec.params.get(edit.param)
        if isinstance(entrada, dict):
            entrada["expr"] = edit.new_expr
        else:
            spec.params[edit.param] = edit.new_expr
        return True
    if wire is None or block is None or field_name is None:
        return False
    spec.wires[wire].blocks[block][field_name] = edit.new_expr
    return True


def promote_to_param(spec, name: str, value: str, description: str = "") -> None:
    """Transforma um numero solto em parametro, para o CST poder calibra-lo."""
    spec.params[name] = {"expr": value, "description": description}
