"""Avisos em linguagem de antena.

Duas propriedades sustentam estas regras:

* **Nenhuma receita do catalogo pode disparar erro ou aviso.** Se disparar, ou a
  regra esta errada ou a receita esta -- e as duas coisas ja aconteceram: a regra
  de meia onda acusava "525% longo demais" numa espiral correta, e a receita do
  meander realmente tinha dobra apertada demais para a bitola.

* **Aviso que dispara a toda hora vira ruido.** Por isso as tolerancias sao
  largas: o numero final vem do CST, e aqui so vale pegar o que esta claramente
  fora.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest

from antfdm.check import rules
from antfdm.core import spec as spec_mod

RECIPES = Path(__file__).resolve().parents[1] / "antfdm" / "recipes"
TODAS = sorted(p.stem for p in RECIPES.glob("*.yaml"))


# --------------------------------------------------------------------------
# o catalogo tem que passar limpo
# --------------------------------------------------------------------------


@pytest.mark.parametrize("receita", TODAS)
def test_receita_do_catalogo_nao_dispara_aviso(receita):
    s = spec_mod.load(RECIPES / f"{receita}.yaml")
    ws = s.to_wireset()
    avisos = rules.verificar(ws, (s.printer.bed_x, s.printer.bed_y, s.printer.bed_z))
    graves = [a for a in avisos if a.severidade in ("erro", "aviso")]
    assert not graves, "\n".join(str(a) for a in graves)


def test_antena_em_branco_esta_dentro_da_faixa():
    ws = spec_mod.AntennaSpec.blank("x", 868.0).to_wireset()
    assert rules.resumo(rules.verificar(ws)) == "tudo dentro da faixa"


# --------------------------------------------------------------------------
# elemento alimentado
# --------------------------------------------------------------------------


def _blank(**mudancas):
    s = spec_mod.AntennaSpec.blank("t", 868.0)
    for k, v in mudancas.items():
        s.params[k]["expr"] = v
    return s


def test_braco_longo_demais_e_apontado_com_a_porcentagem():
    ws = _blank(L_braco="0.36*Lambda").to_wireset()
    a = rules.verificar(ws)[0]
    assert a.severidade == "erro"
    assert "longo demais" in a.texto and "868 MHz" in a.texto
    assert a.correcao is not None


def test_braco_curto_demais_e_apontado():
    ws = _blank(L_braco="0.12*Lambda").to_wireset()
    a = rules.verificar(ws)[0]
    assert "curto demais" in a.texto


def test_desvio_pequeno_nao_vira_aviso():
    """Tolerancia larga de proposito: o numero final vem do CST."""
    ws = _blank(L_braco="0.225*Lambda").to_wireset()
    assert not [x for x in rules.verificar(ws) if x.severidade != "dica"]


def test_correcao_do_comprimento_resolve_o_aviso():
    s = _blank(L_braco="0.36*Lambda")
    aviso = rules.verificar(s.to_wireset())[0]
    ok, msg = rules.aplicar(s, aviso.correcao)
    assert ok, msg
    assert rules.resumo(rules.verificar(s.to_wireset())) == "tudo dentro da faixa"


def test_correcao_preserva_o_vinculo_com_a_frequencia():
    """Corrigir nao pode assar o numero: a antena segue reescalando com F0."""
    s = _blank(L_braco="0.36*Lambda")
    rules.aplicar(s, rules.verificar(s.to_wireset())[0].correcao)
    assert "Lambda" in s.params["L_braco"]["expr"]


def test_elemento_dobrado_dispensa_a_regra_de_meia_onda():
    """Serpentina e espiral tem mais fio que vao -- e para isso que existem."""
    ws = spec_mod.load(RECIPES / "espiral_cp.yaml").to_wireset()
    avisos = rules.verificar(ws)
    dobrado = [a for a in avisos if "dobrado" in a.texto]
    assert dobrado and dobrado[0].severidade == "dica"
    assert not [a for a in avisos if "longo demais" in a.texto]


# --------------------------------------------------------------------------
# parasitas
# --------------------------------------------------------------------------


def _yagi(**mudancas):
    s = spec_mod.load(RECIPES / "yagi.yaml")
    for k, v in mudancas.items():
        s.params[k]["expr"] = v
    return s


def test_refletor_curto_demais_e_apontado():
    ws = _yagi(L_ref="0.30*Lambda").to_wireset()
    textos = [a.texto for a in rules.verificar(ws)]
    assert any("refletor" in t and "refletor" in t for t in textos)


def test_diretor_fora_da_faixa_e_apontado():
    ws = _yagi(L_dir1="0.60*Lambda").to_wireset()
    assert any("diretor1" in a.texto for a in rules.verificar(ws))


def test_espacamento_fora_da_faixa_e_apontado():
    ws = _yagi(S_dir2="1.2*Lambda").to_wireset()
    assert any("longe demais" in a.texto for a in rules.verificar(ws))


def test_espacamento_nao_se_aplica_a_dipolo_simples():
    """Os dois bracos ficam colados de proposito; nao sao um arranjo."""
    ws = spec_mod.AntennaSpec.blank("x", 868.0).to_wireset()
    assert not [a for a in rules.verificar(ws) if "demais:" in a.texto]


# --------------------------------------------------------------------------
# mecanica
# --------------------------------------------------------------------------


def test_dobra_apertada_e_apontada_uma_vez_por_fio():
    """Serpentina tem dezenas de dobras iguais; listar todas afogaria o resto."""
    s = spec_mod.load(RECIPES / "meander.yaml")
    s.params["Radius"]["expr"] = "0.4"
    # Filtra por "esmalte", que so a regra de raio de dobra usa: "dobra" tambem
    # apareceria na dica sobre o elemento ser dobrado.
    avisos = [a for a in rules.verificar(s.to_wireset()) if "esmalte" in a.texto]
    assert len(avisos) == 2  # um por braco, nao um por vertice
    assert "dobras" in avisos[0].texto and "esmalte" in avisos[0].texto


def test_dobra_folgada_nao_avisa():
    s = spec_mod.load(RECIPES / "meander.yaml")
    assert not [a for a in rules.verificar(s.to_wireset()) if "esmalte" in a.texto]


def test_peca_maior_que_a_mesa_e_apontada():
    ws = _blank(L_braco="0.36*Lambda").to_wireset()
    avisos = rules.verificar(ws, (100.0, 100.0, 100.0))
    assert any("nao cabe na mesa" in a.texto for a in avisos)


def test_sem_mesa_declarada_nao_ha_checagem_de_tamanho():
    ws = _blank(L_braco="0.36*Lambda").to_wireset()
    assert not [a for a in rules.verificar(ws, None) if "mesa" in a.texto]


# --------------------------------------------------------------------------
# apresentacao e casos de borda
# --------------------------------------------------------------------------


def test_avisos_vem_do_mais_grave_para_o_menos():
    ws = _blank(L_braco="0.36*Lambda").to_wireset()
    ordem = [rules._ORDEM[a.severidade] for a in rules.verificar(ws, (50.0, 50.0, 50.0))]
    assert ordem == sorted(ordem)


def test_resumo_cabe_numa_linha():
    ws = _blank(L_braco="0.36*Lambda").to_wireset()
    resumo = rules.resumo(rules.verificar(ws))
    assert "\n" not in resumo and resumo


def test_antena_sem_frequencia_diz_o_que_falta():
    s = spec_mod.AntennaSpec.blank("x", 868.0)
    s.f0_mhz = None
    avisos = rules.verificar(s.to_wireset())
    assert any("frequencia alvo" in a.texto for a in avisos)


def test_geometria_quebrada_para_a_analise_ali():
    """Sem geometria valida nao da nem para medir; nao adianta listar o resto."""
    s = spec_mod.AntennaSpec.blank("x", 868.0)
    s.params["Radius"]["expr"] = "500"
    s.wires[0].blocks[0]["fillet"] = "Radius"
    s.wires[0].blocks.append({"type": "bend", "angle": "90", "fillet": "Radius"})
    s.wires[0].blocks.append({"type": "straight", "len": "10"})
    avisos = rules.verificar(s.to_wireset())
    assert avisos and all(a.severidade == "erro" for a in avisos)


def test_correcao_em_fio_espelhado_e_recusada_com_motivo():
    s = _blank(L_braco="0.36*Lambda")
    correcao = rules.Correcao("teste", "braco_esq", 70.0)
    ok, msg = rules.aplicar(s, correcao)
    assert not ok and "espelho" in msg


def test_correcao_em_fio_inexistente_e_recusada():
    s = _blank()
    ok, msg = rules.aplicar(s, rules.Correcao("teste", "nao_existe", 70.0))
    assert not ok and "nao existe" in msg
