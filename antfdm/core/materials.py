"""Permissividade efetiva do PLA impresso.

O fio fica dentro do radome, entao o plastico carrega a antena e encurta o
comprimento ressonante por cerca de 1/sqrt(eps_eff). Peca impressa em FDM nao e
plastico macico: com infill de 30%, dois tercos do volume e ar.

Usa a mistura logaritmica de Lichtenecker para as duas fases (PLA e ar):

    log(eps_eff) = v*log(eps_pla) + (1-v)*log(1)   =>   eps_eff = eps_pla**v

Com eps_pla = 2.75 e 30% de infill isso da 1.35, nao 2.75. Simular o valor
macico erraria a ressonancia por uma margem grande.

O modelo e aproximado de proposito: ``eps_cal`` existe para corrigi-lo a partir
de UMA medida real, e a autoridade sobre a dimensao final continua sendo o CST.
"""

from __future__ import annotations

from dataclasses import dataclass

# Valores tipicos de PLA em RF. Servem de ponto de partida, nao de verdade:
# lote, cor e umidade mudam eps em alguns porcento.
PLA_EPS_SOLID = 2.75
PLA_TAND_SOLID = 0.008


@dataclass
class Dielectric:
    """O material do radome como sera declarado no CST."""

    name: str
    eps: float
    tand: float

    def __post_init__(self) -> None:
        if self.eps < 1.0:
            raise ValueError(f"eps efetivo nao pode ser menor que 1 (ar): {self.eps}")


@dataclass
class RadomeMaterial:
    """Plastico macico + fracao de preenchimento -> material efetivo."""

    eps_solid: float = PLA_EPS_SOLID
    tand_solid: float = PLA_TAND_SOLID
    infill: float = 0.30  # fracao de volume ocupada por plastico, 0..1
    eps_cal: float = 1.0  # correcao a partir de medida real; 1.0 = sem correcao
    name: str = "PLA (impresso)"

    def __post_init__(self) -> None:
        if not 0.0 <= self.infill <= 1.0:
            raise ValueError(f"infill precisa estar entre 0 e 1, recebeu {self.infill}")
        if self.eps_solid < 1.0:
            raise ValueError(f"eps do plastico macico nao pode ser < 1: {self.eps_solid}")
        if self.eps_cal <= 0.0:
            raise ValueError(f"eps_cal precisa ser positivo, recebeu {self.eps_cal}")

    @property
    def eps_eff(self) -> float:
        """Permissividade efetiva pela mistura de Lichtenecker."""
        return (self.eps_solid**self.infill) * self.eps_cal

    @property
    def tand_eff(self) -> float:
        """Perda efetiva: so a fracao solida dissipa; o ar nao."""
        return self.tand_solid * self.infill

    @property
    def velocity_factor(self) -> float:
        """Fator de encurtamento do comprimento ressonante dentro do radome.

        Aproximacao de primeira ordem: o fio nao esta imerso num meio infinito,
        so envolvido por uma casca fina, entao o encurtamento real e menor que
        este. Serve para a geometria inicial da sintese; o CST da o numero final.
        """
        return 1.0 / (self.eps_eff**0.5)

    def dielectric(self) -> Dielectric:
        return Dielectric(name=self.name, eps=self.eps_eff, tand=self.tand_eff)

    def describe(self) -> str:
        return (
            f"{self.name}: eps_solido={self.eps_solid:.3g}, infill={self.infill:.0%} "
            f"-> eps_eff={self.eps_eff:.3f}, tand_eff={self.tand_eff:.4f}, "
            f"vf={self.velocity_factor:.3f}"
        )
