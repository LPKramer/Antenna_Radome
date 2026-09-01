"""Filete exato: casos com resposta fechada conhecida."""

from __future__ import annotations

import math

import numpy as np
import pytest

from antfdm.core.geometry import (
    Arc,
    GeometryError,
    Line,
    frame_at,
    path_length,
    resolve_path,
    sample_path,
    solve_fillet,
    stations,
)


def test_canto_reto_tem_comprimento_fechado():
    """Canto de 90 graus com raio R: cada reta perde R, e o arco mede R*pi/2."""
    segs = resolve_path([(0, 0, 0), (10, 0, 0), (10, 10, 0)], [0, 3, 0])
    esperado = 7 + 3 * math.pi / 2 + 7
    assert path_length(segs) == pytest.approx(esperado, rel=1e-12)
    assert [type(s).__name__ for s in segs] == ["Line", "Arc", "Line"]


def test_arco_tem_centro_e_varredura_corretos():
    segs = resolve_path([(0, 0, 0), (10, 0, 0), (10, 10, 0)], [0, 3, 0])
    arc = next(s for s in segs if isinstance(s, Arc))
    assert arc.radius == pytest.approx(3.0)
    assert arc.sweep == pytest.approx(math.pi / 2, rel=1e-12)
    assert np.allclose(arc.center, [7, 3, 0])


def test_juntas_sao_continuas_em_posicao_e_tangente():
    """G1: sem degrau e sem quebra de tangente -- o que a varredura exige."""
    pts = [(0, 0, 0), (20, 0, 0), (28, 10, 0), (34, 0, 0), (54, 0, 0)]
    segs = resolve_path(pts, [0, 3, 3, 3, 0])
    for a, b in zip(segs, segs[1:]):
        assert np.linalg.norm(a.point_at(a.length) - b.point_at(0)) < 1e-9
        assert np.linalg.norm(a.end_tangent - b.start_tangent) < 1e-9


def test_filete_encurta_o_caminho():
    """Arredondar um canto sempre corta caminho em relacao a polilinha."""
    pts = [(0, 0, 0), (20, 0, 0), (28, 10, 0)]
    sem = resolve_path(pts, [0, 0, 0])
    com = resolve_path(pts, [0, 3, 0])
    assert path_length(com) < path_length(sem)


def test_colinear_nao_gera_arco():
    segs = resolve_path([(0, 0, 0), (5, 0, 0), (10, 0, 0)], [0, 3, 0])
    assert all(isinstance(s, Line) for s in segs)


def test_filete_grande_demais_e_recusado_com_mensagem_util():
    with pytest.raises(GeometryError, match="reduza o raio"):
        resolve_path([(0, 0, 0), (4, 0, 0), (4, 4, 0)], [0, 10, 0])


def test_dobra_de_180_graus_e_recusada():
    with pytest.raises(GeometryError, match="180"):
        solve_fillet(np.array([0.0, 0, 0]), np.array([5.0, 0, 0]), np.array([0.0, 0, 0]), 1.0)


def test_vertices_coincidentes_sao_recusados():
    with pytest.raises(GeometryError, match="coincidentes"):
        resolve_path([(0, 0, 0), (0, 0, 0), (5, 0, 0)], [0, 0, 0])


def test_caminho_fechado_fecha():
    """Quadrado com cantos arredondados: perimetro fechado tem formula conhecida."""
    r = 2.0
    pts = [(0, 0, 0), (20, 0, 0), (20, 20, 0), (0, 20, 0)]
    segs = resolve_path(pts, [r] * 4, closed=True)
    esperado = 4 * (20 - 2 * r) + 2 * math.pi * r
    assert path_length(segs) == pytest.approx(esperado, rel=1e-12)
    inicio = segs[0].point_at(0)
    fim = segs[-1].point_at(segs[-1].length)
    assert np.linalg.norm(inicio - fim) < 1e-9


def test_frame_at_da_ponto_e_tangente_no_arco():
    segs = resolve_path([(0, 0, 0), (10, 0, 0), (10, 10, 0)], [0, 3, 0])
    total = path_length(segs)
    p0, t0 = frame_at(segs, 0.0)
    p1, t1 = frame_at(segs, total)
    assert np.allclose(p0, [0, 0, 0])
    assert np.allclose(t0, [1, 0, 0])
    assert np.allclose(p1, [10, 10, 0])
    assert np.allclose(t1, [0, 1, 0])


def test_frame_at_grampeia_fora_do_caminho():
    segs = resolve_path([(0, 0, 0), (10, 0, 0)], [0, 0])
    assert np.allclose(frame_at(segs, -5)[0], [0, 0, 0])
    assert np.allclose(frame_at(segs, 999)[0], [10, 0, 0])


def test_stations_inclui_as_duas_pontas():
    segs = resolve_path([(0, 0, 0), (100, 0, 0)], [0, 0])
    ss = stations(segs, 30.0, margin=5.0)
    assert ss[0] == pytest.approx(5.0)
    assert ss[-1] == pytest.approx(95.0)
    assert all(b > a for a, b in zip(ss, ss[1:]))


def test_sample_path_cobre_o_caminho_inteiro():
    segs = resolve_path([(0, 0, 0), (10, 0, 0), (10, 10, 0)], [0, 3, 0])
    pts = sample_path(segs, 0.5)
    assert np.allclose(pts[0], [0, 0, 0])
    assert np.allclose(pts[-1], [10, 10, 0])
    passos = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    assert passos.max() <= 0.5 + 1e-9
