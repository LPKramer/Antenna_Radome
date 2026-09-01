"""Round-trip de calibracao: CST -> spec.

Depois de calibrar no CST, a autoridade sobre as dimensoes e o projeto.  Estes
testes garantem que os valores voltam corretamente e que um valor calibrado
impossivel e recusado antes de virar peca impressa.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from antfdm.core import spec as spec_mod
from antfdm.io import cst_params_in as sync

RECIPE = Path(__file__).resolve().parents[1] / "antfdm" / "recipes" / "dipolo_y.yaml"


def _params_json(tmp_path: Path, params: dict[str, str]) -> Path:
    d = tmp_path / "Projeto" / "Model"
    d.mkdir(parents=True)
    payload = {
        "parameters": [
            {"name": k, "expr": v, "value": "0"} for k, v in params.items()
        ],
        "version": 1,
    }
    f = d / "Parameters.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "Projeto.cst").write_text("", encoding="utf-8")
    return tmp_path / "Projeto.cst"


def test_localiza_o_json_a_partir_do_cst(tmp_path):
    cst = _params_json(tmp_path, {"Gap": "10"})
    assert sync.locate(cst).name == "Parameters.json"
    assert sync.locate(tmp_path / "Projeto").name == "Parameters.json"


def test_projeto_nao_salvo_da_mensagem_acionavel(tmp_path):
    (tmp_path / "Vazio.cst").write_text("", encoding="utf-8")
    with pytest.raises(sync.SyncError, match="salve no CST"):
        sync.locate(tmp_path / "Vazio.cst")


def test_traz_valores_calibrados_e_converte_sintaxe(tmp_path):
    cst = _params_json(tmp_path, {"Ang": "1.5", "Cotg": "(TAN(Ang/(2*pi)))^-1"})
    lidos = sync.read(cst)
    assert lidos["Ang"].expr == "1.5"
    # ^ vira **, e a caixa das funcoes e normalizada
    assert lidos["Cotg"].expr == "(tan(Ang/(2*pi)))**-1"


def test_sync_altera_so_o_que_mudou(tmp_path):
    s = spec_mod.load(RECIPE)
    cst = sync.read(_params_json(tmp_path, {"Gap": "20", "Radius": "3"}))
    changes, ignored = sync.apply_to_spec(s, cst)
    assert [c.name for c in changes] == ["Gap"]  # Radius ja valia 3
    assert s.params["Gap"]["expr"] == "20"
    assert ignored == []


def test_parametro_so_do_cst_e_reportado_e_nao_injetado(tmp_path):
    """Um parametro criado a mao no CST nao entra sozinho: nada o usaria."""
    s = spec_mod.load(RECIPE)
    cst = sync.read(_params_json(tmp_path, {"Inventado": "7"}))
    changes, ignored = sync.apply_to_spec(s, cst)
    assert changes == []
    assert ignored == ["Inventado"]
    assert "Inventado" not in s.params


def test_diferenca_so_de_espaco_nao_conta_como_mudanca(tmp_path):
    s = spec_mod.load(RECIPE)
    cst = sync.read(_params_json(tmp_path, {"cordenadaNosoldaX": "Sec_inical+cordenadaNosolda"}))
    changes, _ = sync.apply_to_spec(s, cst)
    assert changes == []


def test_valor_calibrado_impossivel_e_detectado_antes_de_imprimir(tmp_path):
    """Um filete grande demais tem que falhar aqui, nao na hora de fatiar."""
    s = spec_mod.load(RECIPE)
    cst = sync.read(_params_json(tmp_path, {"Radius": "50"}))
    sync.apply_to_spec(s, cst)
    problems = s.to_wireset().validate()
    assert any("reduza o raio" in p for p in problems)
