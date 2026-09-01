"""Print card: o que cortar, como imprimir e como montar.

O campo mais importante aqui e o infill.  Ele entra no calculo de eps efetivo que
foi para o CST, entao imprimir com outro valor invalida a simulacao -- e nada no
STL registra isso.  Por isso o print card sai junto com a peca.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .cad.clamshell import Clamshell, _fingerprint
from .core.wireset import WireSet


@dataclass
class PrintCard:
    text: str

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.text, encoding="utf-8")
        return p


def build(ws: WireSet, clam: Clamshell | None = None) -> PrintCard:
    mat = ws.radome.material
    bitola = ws.params.evaluate(ws.conductor.bitola)
    lines: list[str] = []
    a = lines.append

    a("=" * 68)
    a(f"  {ws.name}" + (f"   f0 = {ws.f0_hz / 1e6:.1f} MHz" if ws.f0_hz else ""))
    a(f"  parametros: {_fingerprint(ws)}")
    a("=" * 68)
    a("")
    a("FIO A CORTAR")
    a(f"  bitola (diametro do cobre nu) : {bitola:.3f} mm")
    for name, L in ws.lengths().items():
        role = ws.wire(name).role
        a(f"  {name:<18} {L:9.2f} mm   ({role})")
    a(f"  {'TOTAL':<18} {ws.total_wire_length():9.2f} mm")
    a("  Corte com folga; o comprimento acima e da linha de centro, ponta a ponta.")
    a("")

    a("IMPRESSAO")
    a(f"  infill        : {mat.infill:.0%}   <-- OBRIGATORIO")
    a("                  O eps efetivo do modelo no CST vem deste valor.")
    a("                  Imprimir com outro infill invalida a simulacao.")
    a(f"  material      : PLA (eps macico assumido = {mat.eps_solid:.2f})")
    a(f"  eps efetivo   : {mat.eps_eff:.3f}   tan(d) = {mat.tand_eff:.4f}")
    a(f"  fator de vel. : {mat.velocity_factor:.3f}")
    a("  orientacao    : as duas metades com a face plana na mesa, canal p/ cima.")
    a("                  Nao precisa de suporte.")
    a("")

    if clam is not None:
        a("PECA")
        a(f"  secao do corpo  : {clam.section_w:.2f} x {clam.section_h:.2f} mm")
        a(f"  raio do canal   : {clam.channel_r:.3f} mm "
          f"(folga radial {ws.radome.folga:.2f} mm sobre o fio)")
        a(f"  orelhas         : {clam.stats.get('orelhas', 0)}")
        a(f"  pinos / parafusos: {clam.stats.get('pinos', 0)} / "
          f"{clam.stats.get('parafusos', 0)} ({ws.radome.parafuso})")
        a(f"  volume base/topo: {clam.stats.get('volume_base_mm3', 0):.0f} / "
          f"{clam.stats.get('volume_topo_mm3', 0):.0f} mm3")
        a("")

    a("MONTAGEM")
    a("  1. Assente o fio no canal da metade de baixo, seguindo o filete dos cantos.")
    a("  2. A ponte central fixa o Gap de alimentacao -- nao force o espacamento.")
    a("  3. Solde o cabo no alojamento da ponte, com a malha do lado indicado.")
    a("  4. Feche com a metade de cima; os pinos alinham antes de apertar.")
    a(f"  5. Aperte os parafusos {ws.radome.parafuso}.")
    a("")
    a("CALIBRACAO")
    a("  As dimensoes finais vem do CST. Depois de calibrar la, rode:")
    a("      antfdm sync <spec.yaml> --cst <projeto.cst>")
    a("      antfdm print <spec.yaml>")
    a("  para a peca sair com as dimensoes calibradas.")
    a("")
    return PrintCard("\n".join(lines))
