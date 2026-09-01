"""Exportacao das metades e verificacoes mecanicas antes de imprimir.

As checagens valem o custo: um erro de folga ou de interferencia so aparece
depois de horas de impressao, e a peca vai direto pro lixo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import build123d as bd

from .clamshell import Clamshell


class ExportError(ValueError):
    pass


@dataclass
class Check:
    name: str
    ok: bool
    detail: str

    def __str__(self) -> str:
        return f"[{'OK ' if self.ok else 'FALHA'}] {self.name}: {self.detail}"


def check(clam: Clamshell, bed_x: float, bed_y: float, bed_z: float) -> list[Check]:
    """Verificacoes mecanicas das duas metades."""
    out: list[Check] = []

    # As metades so podem se tocar nos pinos; qualquer outra interseccao impede
    # o fechamento. Os pinos entram com folga, entao a interseccao real e ~0.
    overlap = (clam.top & clam.bottom).volume
    out.append(
        Check(
            "interferencia entre as metades",
            overlap < 1e-6,
            f"volume comum = {overlap:.6f} mm3 (esperado ~0)",
        )
    )

    out.append(
        Check(
            "folga do canal",
            clam.channel_r > 0,
            f"raio do canal = {clam.channel_r:.3f} mm",
        )
    )

    for label, part in (("topo", clam.top), ("base", clam.bottom)):
        n = len(part.solids())
        out.append(
            Check(
                f"metade {label} e uma peca so",
                n == 1,
                f"{n} solido(s)" + ("" if n == 1 else " -- a peca sairia em pedacos soltos"),
            )
        )
        bb = part.bounding_box()
        fits = bb.size.X <= bed_x and bb.size.Y <= bed_y and bb.size.Z <= bed_z
        out.append(
            Check(
                f"metade {label} cabe na mesa",
                fits,
                f"{bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm "
                f"em mesa {bed_x:.0f} x {bed_y:.0f} x {bed_z:.0f}"
                + ("" if fits else " -- vai precisar de segmentacao (cad/segment.py)"),
            )
        )
    return out


def export(clam: Clamshell, outdir: str | Path, stem: str, step: bool = True) -> list[Path]:
    """Grava as duas metades. STL para fatiar, STEP para editar em CAD."""
    d = Path(outdir)
    d.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for label, part in (("base", clam.bottom), ("topo", clam.top)):
        stl = d / f"{stem}_{label}.stl"
        if not bd.export_stl(part, str(stl)):
            raise ExportError(f"falha ao gravar {stl}")
        written.append(stl)
        if step:
            stp = d / f"{stem}_{label}.step"
            if not bd.export_step(part, str(stp)):
                raise ExportError(f"falha ao gravar {stp}")
            written.append(stp)
    return written
