"""Desfazer e refazer.

Manipulacao direta sem Ctrl+Z e inutilizavel: um clique errado no canvas cria um
traco, e sem volta o usuario passa a ter medo de clicar -- que e o oposto do que
esta ferramenta precisa.

Guarda copias inteiras do spec em vez de diffs.  Um spec tem alguns kB, entao a
copia e barata, e a alternativa (registrar cada operacao com seu inverso) erra
calado quando alguma operacao esquece de registrar a volta.
"""

from __future__ import annotations

from ..core.spec import AntennaSpec

LIMITE = 100


class History:
    def __init__(self, limite: int = LIMITE):
        self._passado: list[AntennaSpec] = []
        self._futuro: list[AntennaSpec] = []
        self._limite = limite

    def marcar(self, spec: AntennaSpec) -> None:
        """Guarda o estado ANTES de uma alteracao. Chame antes de mexer."""
        self._passado.append(spec.model_copy(deep=True))
        if len(self._passado) > self._limite:
            self._passado.pop(0)
        self._futuro.clear()

    def limpar(self) -> None:
        self._passado.clear()
        self._futuro.clear()

    @property
    def pode_desfazer(self) -> bool:
        return bool(self._passado)

    @property
    def pode_refazer(self) -> bool:
        return bool(self._futuro)

    def desfazer(self, atual: AntennaSpec) -> AntennaSpec | None:
        if not self._passado:
            return None
        self._futuro.append(atual.model_copy(deep=True))
        return self._passado.pop()

    def refazer(self, atual: AntennaSpec) -> AntennaSpec | None:
        if not self._futuro:
            return None
        self._passado.append(atual.model_copy(deep=True))
        return self._futuro.pop()
