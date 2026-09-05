"""Linha de comando do antfdm.

    antfdm build  spec.yaml     -> macro VBA do CST + STLs + print card
    antfdm cst    spec.yaml     -> so a macro VBA
    antfdm print  spec.yaml     -> so a peca (usa as dimensoes que estao no spec)
    antfdm info   spec.yaml     -> comprimentos, eps efetivo, checagens

O ciclo pretendido e: ``build`` -> calibrar no CST -> ``sync`` -> ``print``.
``sync`` entra na fase 2.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import spec as spec_mod
from .core.wireset import WireSet


def _load(path: str) -> tuple[spec_mod.AntennaSpec, WireSet]:
    s = spec_mod.load(path)
    ws = s.to_wireset()
    problems = ws.validate()
    if problems:
        raise SystemExit(
            "a antena tem problemas:\n  - " + "\n  - ".join(problems)
        )
    return s, ws


def _sim_setup(s: spec_mod.AntennaSpec):
    from .cst.vba import SimSetup

    if s.sim is None:
        return None
    return SimSetup(
        fmin_mhz=s.sim.fmin_mhz,
        fmax_mhz=s.sim.fmax_mhz,
        f0_mhz=s.sim.f0_mhz or s.f0_mhz,
        boundary=s.sim.boundary,
        farfield_monitor=s.sim.farfield_monitor,
    )


def cmd_info(args) -> int:
    s, ws = _load(args.spec)
    print(f"antena     : {ws.name}")
    if ws.f0_hz:
        print(f"f0         : {ws.f0_hz / 1e6:.1f} MHz")
    print(f"radome     : {ws.radome.material.describe()}")
    print()
    print("comprimento de fio (linha de centro):")
    for name, L in ws.lengths().items():
        cl = ws.wire(name).centerline
        print(
            f"  {name:<16} {L:9.3f} mm  "
            f"(sem filete: {cl.polyline_length(ws.params):.3f} mm, "
            f"{len(cl.resolve(ws.params))} segmentos)"
        )
    print(f"  {'TOTAL':<16} {ws.total_wire_length():9.3f} mm")
    print()
    print("parametros (ordem de dependencia):")
    values = ws.params.values()
    for name in ws.params.order():
        p = ws.params.params[name]
        print(f"  {name:<20} = {p.expr:<32} = {values[name]:.6g}")
    return 0


def cmd_cst(args) -> int:
    from .cst import vba

    s, ws = _load(args.spec)
    blocks = vba.emit(ws, _sim_setup(s), overwrite_params=args.overwrite_params)
    outdir = Path(args.out or "saida")
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{ws.name}.bas"
    out.write_text(vba.render_macro(blocks, ws.name), encoding="utf-8")
    print(f"macro VBA: {out}  ({len(blocks)} blocos de historico)")
    if not args.overwrite_params:
        print(
            "  Os parametros usam MakeSureParameterExists: reexecutar no CST "
            "PRESERVA os valores ja calibrados.\n"
            "  Use --overwrite-params para forcar os valores do spec."
        )
    return 0


def cmd_print(args) -> int:
    from .cad import clamshell as cs
    from .cad import export as ex
    from . import report

    s, ws = _load(args.spec)
    opts = cs.ClamshellOptions(
        station_spacing=args.station_spacing,
        engrave=not args.no_engrave,
    )
    print("gerando o radome (pode levar alguns segundos)...")
    clam = cs.build(ws, opts)

    checks = ex.check(clam, s.printer.bed_x, s.printer.bed_y, s.printer.bed_z)
    for c in checks:
        print("  " + str(c))
    failed = [c for c in checks if not c.ok]

    outdir = Path(args.out or "saida")
    written = ex.export(clam, outdir, ws.name, step=not args.no_step)
    for p in written:
        print(f"  gravado: {p}")
    card = report.build(ws, clam).write(outdir / f"{ws.name}_print_card.txt")
    print(f"  gravado: {card}")

    if failed:
        print(f"\n{len(failed)} checagem(ns) falharam -- reveja antes de imprimir.")
        return 1
    return 0


def cmd_check(args) -> int:
    """Avisos sobre a antena, em linguagem de antena."""
    from .check import rules

    s, ws = _load(args.spec)
    avisos = rules.verificar(ws, (s.printer.bed_x, s.printer.bed_y, s.printer.bed_z))
    if not avisos:
        print("tudo dentro da faixa")
        return 0

    for a in avisos:
        print(a)
        if a.correcao and args.fix:
            ok, msg = rules.aplicar(s, a.correcao)
            print(f"     -> {'aplicado: ' if ok else 'nao deu: '}{msg}")
        elif a.correcao:
            print(f"     -> sugestao: {a.correcao.descricao}  (use --fix para aplicar)")

    if args.fix:
        spec_mod.dump(s, args.spec)
        print(f"\ngravado: {args.spec}")
        restantes = rules.verificar(s.to_wireset())
        print(f"restam {len([x for x in restantes if x.severidade != 'dica'])} aviso(s)")
        return 0

    graves = [a for a in avisos if a.severidade in ("erro", "aviso")]
    return 1 if graves else 0


def cmd_new(args) -> int:
    """Cria um spec novo, em branco ou copiado de uma receita do catalogo."""
    destino = Path(args.out or f"{args.nome}.yaml")
    if destino.exists() and not args.force:
        raise SystemExit(f"{destino} ja existe; use --force para sobrescrever")
    if args.de:
        s = spec_mod.from_recipe(args.de, args.nome)
    else:
        s = spec_mod.AntennaSpec.blank(args.nome, args.freq)
    spec_mod.dump(s, destino)
    ws = s.to_wireset()
    print(f"criado: {destino}")
    print(f"  {len(s.wires)} fio(s), {len(s.params)} parametro(s), "
          f"{ws.total_wire_length():.2f} mm de fio")
    print(f"  edite com:  antfdm gui {destino}")
    return 0


def cmd_gui(args) -> int:
    try:
        from .gui import run
    except ImportError as exc:
        raise SystemExit(
            "o editor grafico precisa do PySide6:\n"
            "    pip install PySide6-Essentials\n"
            f"({exc})"
        )
    return run(args.spec)


def cmd_sync(args) -> int:
    """Traz do CST os parametros calibrados para dentro do spec."""
    from .io import cst_params_in as sync

    s = spec_mod.load(args.spec)
    cst = sync.read(args.cst)
    changes, ignored = sync.apply_to_spec(s, cst)

    if not changes:
        print("nada mudou: o spec ja esta igual ao projeto do CST.")
    else:
        print(f"{len(changes)} parametro(s) calibrado(s) no CST:")
        for c in changes:
            print(str(c))
    if ignored:
        print(
            f"\nignorados (existem no CST mas nao no spec): {', '.join(sorted(ignored))}"
        )

    if changes and not args.dry_run:
        # Revalida antes de gravar: um valor calibrado pode tornar um filete
        # grande demais, e e melhor descobrir agora do que na hora de imprimir.
        ws = s.to_wireset()
        problems = ws.validate()
        if problems:
            print(
                "\nos valores do CST deixam a antena invalida:\n  - "
                + "\n  - ".join(problems),
                file=sys.stderr,
            )
            return 1
        spec_mod.dump(s, args.spec)
        print(f"\ngravado: {args.spec}")
        print("Rode 'antfdm print' para gerar a peca com as dimensoes calibradas.")
    elif changes:
        print("\n--dry-run: nada foi gravado.")
    return 0


def cmd_build(args) -> int:
    rc = cmd_cst(args)
    if rc:
        return rc
    print()
    return cmd_print(args)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="antfdm",
        description="Prototipagem rapida de antenas de fio: CST parametrico + radome FDM",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("spec", help="arquivo YAML da antena")
        p.add_argument("--out", help="arquivo ou diretorio de saida")

    p = sub.add_parser("new", help="cria uma antena nova, do zero ou de uma receita")
    p.add_argument("nome", help="nome da antena (vira o nome do arquivo)")
    p.add_argument("--freq", type=float, default=1300.0,
                   help="frequencia alvo em MHz (padrao 1300)")
    p.add_argument("--de", metavar="RECEITA",
                   help=f"copia uma receita do catalogo: {', '.join(spec_mod.catalog())}")
    p.add_argument("--out", help="arquivo de saida (padrao <nome>.yaml)")
    p.add_argument("--force", action="store_true", help="sobrescreve se ja existir")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("check", help="avisa o que esta fora da faixa tipica")
    p.add_argument("spec")
    p.add_argument("--fix", action="store_true",
                   help="aplica as correcoes sugeridas e grava o spec")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("gui", help="abre o editor grafico")
    p.add_argument("spec", nargs="?", help="spec a abrir (opcional)")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("info", help="mostra comprimentos, eps efetivo e parametros")
    p.add_argument("spec")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("cst", help="gera a macro VBA do CST")
    common(p)
    p.add_argument(
        "--overwrite-params",
        action="store_true",
        help="forca os valores do spec, sobrescrevendo o que foi calibrado no CST",
    )
    p.set_defaults(func=cmd_cst)

    p = sub.add_parser("print", help="gera as duas metades do radome")
    common(p)
    p.add_argument("--station-spacing", type=float, default=30.0,
                   help="espacamento das orelhas de fixacao, em mm (padrao 30)")
    p.add_argument("--no-engrave", action="store_true")
    p.add_argument("--no-step", action="store_true")
    p.set_defaults(func=cmd_print)

    p = sub.add_parser(
        "sync", help="traz do CST os parametros que voce calibrou, para dentro do spec"
    )
    p.add_argument("spec")
    p.add_argument("--cst", required=True, help="projeto .cst, sua pasta, ou o Parameters.json")
    p.add_argument("--dry-run", action="store_true", help="so mostra o que mudaria")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("build", help="gera macro VBA e radome de uma vez")
    common(p)
    p.add_argument("--overwrite-params", action="store_true")
    p.add_argument("--station-spacing", type=float, default=30.0)
    p.add_argument("--no-engrave", action="store_true")
    p.add_argument("--no-step", action="store_true")
    p.set_defaults(func=cmd_build)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
