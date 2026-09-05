# antfdm

Prototipagem rápida de antenas de fio esmaltado: uma curva paramétrica gera o
**modelo CST** e o **radome clamshell imprimível**, garantidamente a mesma antena.

A calibração final acontece **dentro do CST**. O programa não substitui esse
passo — ele o cerca.

```
  spec.yaml  ──①─→  antfdm build  ──→  macro VBA paramétrica  ──→  CST
                                       + STL/STEP das 2 metades
                                       + print card
                          ┌──────────────────────────────────┐
                          │ ② VOCÊ CALIBRA NO CST            │  ← autoridade
                          │   Parameter List, Par. Sweep,    │
                          │   Optimizer                      │
                          └──────────────────────────────────┘
  spec.yaml  ←──③──  antfdm sync --cst projeto.cst
                 │
                 └──④─→  antfdm print  ──→  peça com as dimensões calibradas
```

## Instalação

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e .
```

## Uso

```bash
antfdm new   minha_antena --freq 868                # cria do zero
antfdm gui   antfdm/recipes/dipolo_y.yaml          # editor gráfico
antfdm info  antfdm/recipes/dipolo_y.yaml          # comprimentos, eps efetivo, parâmetros
antfdm build antfdm/recipes/dipolo_y.yaml --out saida
# ... abra saida/dipolo_y.bas no CST e calibre ...
antfdm sync  antfdm/recipes/dipolo_y.yaml --cst Dipolo.cst --dry-run
antfdm print antfdm/recipes/dipolo_y.yaml --out saida
```

## Editor: a antena responde ao toque

```
┌────────────────────────────────────────────┬──────────┐
│ 868 MHz  Nova Abrir Salvar  CST  STL    ⚙  │ ──────   │
├────────────────────────────────────────────┤ ──╮      │
│                                            │ ─╱╲─     │
│         ●━━━━━━━━━━━╪━━━━━━━━━━━●          │ ∿∿∿∿     │
│         │←────── λ/2 ──────→│               │  ◎       │
├────────────────────────────────────────────┴──────────┤
│ fio 166 mm · 0.48 λ                                   │
└───────────────────────────────────────────────────────┘
```

Não há botão de modo. O que está sob o cursor decide:

| Onde você toca | Clicar | Arrastar |
|---|---|---|
| **ponta livre do fio** | seleciona | estica o trecho |
| **trecho (aresta)** | mostra o comprimento | muda o comprimento |
| **vértice** | seleciona | move o ponto |
| **espaço vazio** | desmarca — não cria nada | move a vista |
| **ficha da paleta** | — | **arrasta e encaixa** na ponta mais próxima |

Com a tela vazia, o primeiro clique cria um dipolo inteiro — braço, espelho e
alimentação, na frequência da barra.

**Arrastar uma ficha é o gesto principal.** A ponta mais próxima acende e um
fantasma mostra o resultado antes de soltar. Soltar longe cria um elemento
solto (refletor, diretor). As fichas são desenhadas *construindo cada bloco*,
então o que se vê na paleta é o que vai aparecer no fio — e os nomes são
`reta`, `dobra`, `serpentina`, `espiral`, não `straight`/`bend`/`meander`.

**Cada traço cria seu parâmetro em silêncio** (`L1`, `A1`, …). Você nunca digita
um nome, mas o CST recebe a Parameter List populada — que é a razão de existir
do projeto. Arrastar edita *o parâmetro*, preservando a forma da expressão.

Ctrl+Z desfaz. Ctrl+E abre o **Avançado** com parâmetros, árvore de blocos e
propriedades — nada foi apagado, só saiu da frente. Um teste falha se a tela
padrão passar de 8 controles.

## A peça: só segurando o fio

Duas metades, canal para o fio, parafusos M3. **Três ajustes**, contra os onze
de antes — saíram pinos de alinhamento, orelhas periódicas, alojamento de coax
e gravação.

Duas decisões que valem registro:

- **A aba do parafuso fica no eixo, além da ponta do fio.** Alargar a fita
  inteira parecia mais simples, mas não passa em filete apertado: com
  meia-largura maior que o raio da curva, a face interna se auto-intersecta.
  Além da ponta o caminho é reto por definição.

- **Ligação automática no lugar de "boom" e "ponte".** Elementos parasitas não
  se tocam e os dois braços de um dipolo também não; sem ligação a peça sairia
  em vários pedaços. Em vez de duas features com regras próprias, uma regra só:
  se o sólido saiu em mais de uma parte, liga as mais próximas até virar uma.
  Um dipolo precisa de 0 ligações (as abas já cobrem o gap); um Yagi, de 3.

## Avisos (`antfdm check`)

```
$ antfdm check minha_antena.yaml
!! o elemento alimentado esta 64% longo demais para 868 MHz (248.8 mm; o esperado e ~151.3 mm)
     -> sugestao: ajustar para 75.7 mm por braco  (use --fix para aplicar)
 ! a peca ficaria com 257 x 4 mm e nao cabe na mesa de 220 x 220 mm
```

Faixas clássicas, não verdade: o número final vem do CST. Por isso as
tolerâncias são largas — aviso que dispara sempre vira ruído.

Elemento **dobrado** (serpentina, espiral) dispensa a conferência por meia onda:
comparar comprimento de fio com λ/2 acusaria "525% longo demais" numa espiral
correta. O quociente fio/vão separa os casos (reto ~1.0, serpentina 1.5,
espiral 6.3).

## Pela linha de comando

```bash
antfdm new minha_antena --freq 868     # dipolo de meia onda, já dimensionado
antfdm new minha_yagi --de yagi        # copia uma receita do catálogo
antfdm check minha_antena.yaml --fix   # avisa e corrige
```

`antfdm new` produz uma antena pronta (a GUI começa vazia, para o primeiro
clique criar a antena em vez de editar uma que já veio). Tudo é fração de
`Lambda`, então mudar `F0` reescala o conjunto.

## Bloquinhos

A inversão em relação ao Antenna Magus: a unidade não é *a antena*, é *o bloco*.
Uma antena é uma composição em YAML, e o catálogo são receitas editáveis — não
código. Um dipolo não é privilegiado; é uma receita de poucas linhas que você
bifurca.

```yaml
wires:
  - name: braco_dir
    start: {x: "Gap/2", y: "0", dir: "0"}
    blocks:
      - {type: straight, len: Sec_inical, fillet: Radius}
      - {type: vee, run: "cordenadaNosolda - Gap/2", height: cordenadaNosoldaY,
         back: Cotg, fillet: Radius}
      - {type: straight, len: "Ltotal/2 - cordenadaNosoldaX - Cotg"}
  - name: braco_esq
    mirror_of: braco_dir
    mirror_axis: x
```

Oito blocos: `straight` `bend` `vee` `meander` `arc` `spiral` `taper` `jump`.

**O cursor é simbólico.** Uma tartaruga comum acumularia `x += L*cos(a)` em ponto
flutuante e emitiria coordenadas assadas — o modelo pararia de ser paramétrico.
Aqui a posição é um par de *strings*: andar `Sec_inical` a partir de `Gap/2` dá
`Gap/2 + Sec_inical`, que segue vivo na Parameter List. Rumo nos eixos resolve o
cosseno na hora; rumo paramétrico emite `cos(rad(AnguloYperna))` de verdade, que
é o que permite girar o segmento mudando o parâmetro no CST.

Andar em passos acumula termos que se cancelam, então a cadeia é reduzida no fim
(`Gap/2 + Sec + Cotg - Gap/2 - Cotg` → `Cotg + Sec`) — expressão inchada atrapalha
justamente quem vai calibrar lendo o histórico.

### Receitas

| Receita | Família | Fio |
|---|---|---|
| `dipolo_y.yaml` | dipolo em Y, vértices explícitos | 110.9 mm |
| `dipolo_y_blocos.yaml` | o mesmo, em blocos (prova de equivalência) | 110.9 mm |
| `yagi.yaml` | Yagi-Uda 4 elementos | 421.6 mm |
| `meander.yaml` | dipolo carregado por serpentina | 144.9 mm |
| `espiral_cp.yaml` | espiral de 2 braços, polarização circular | 631.0 mm |

O Yagi mostra o que a composição dá de graça: toda dimensão é fração de `Lambda`,
então mudar `F0` na Parameter List reescala a antena inteira. Não há nenhum número
absoluto para reajustar à mão.

Elementos parasitas são fios **desconectados** — o boom é mecânico, não elétrico.
Por isso o radome declara `boom`, sem o qual a peça sairia em 4 pedaços soltos e
nada garantiria os espaçamentos, que são dimensões calibradas.

**Topologia não é parâmetro.** `meander.n`, `arc.angle` e `spiral.turns` precisam
ser literais: mudam quantos vértices existem, e o Parametric Update do CST
reconstrói dimensões, não cria vértices. Dimensões continuam calibráveis.

## As três decisões que governam o código

**1. Todo vértice sai como expressão, nunca como número.**
`.X1 "Gap/2"`, não `.X1 "5.7996"`. O CST guarda a string, registra a dependência
e reavalia no Parametric Update — é isso que mantém a Parameter List útil para
calibrar. A macro `3D Linear Helical Spiral` da própria biblioteca do CST faz o
contrário e por isso precisa de um `Brick` descartável só para forçar a
dependência; não seguimos esse caminho. Protegido por
`test_vba_usa_expressoes_e_nao_numeros`.

**2. O filete é resolvido três vezes, de propósito.**
`BlendCurve` no CST, `core/geometry.py` no lado analítico, OCCT no build123d.
Deixar o CST filetar é o que mantém as expressões curtas; se resolvêssemos o
filete aqui, as coordenadas de tangência virariam expressões ilegíveis. A
concordância entre os três é verificada por
`test_comprimento_bate_entre_python_e_build123d` (erro medido: 0.0).

**3. O PLA é dielétrico, não metal.**
O modelo original criava um fio de cobre com raio `Pla+Bitola/2` — o plástico
simulado como condutor, o que desloca a ressonância. Aqui saem dois sólidos
coaxiais, e o εr do PLA é corrigido pelo infill via Lichtenecker
(`ε_eff = ε_pla^v`): com 30% de infill, **1.35 e não 2.75**.

> O infill impresso precisa ser o mesmo que entrou no cálculo. O print card
> registra isso porque nada no STL o registraria.

## Estado

**Fases 1, 3, 5 e parte da 2 implementadas.** 171 testes passando.

| Módulo | Estado |
|---|---|
| `core/` — expr, geometry, centerline, wireset, materials, spec | pronto |
| `cst/vba.py` — emissor VBA paramétrico | pronto |
| `cad/` — sweep, clamshell, export | pronto |
| `io/cst_params_in.py` + `antfdm sync` | pronto |
| `gui/` — editor por gestos, paleta arrastável, undo | pronto |
| `check/rules.py` + `antfdm check` — avisos com correção | pronto |
| `core/solve.py` — arrastar edita o parâmetro | pronto |
| `blocks/` — cursor simbólico, 8 blocos, registro | pronto |
| `recipes/` — dipolo, Yagi, meander, espiral CP | pronto |
| `cst/driver.py` — rodar solver e ler S11 pela API | pendente (Fase 2) |
| `synth/` — dimensionar por f₀ | pendente (Fase 3) |
| `nec/` — estimativa rápida | pendente (Fase 4) |
| DXF/SVG, curvas 3D | pendente (Fase 6) |

Curvas fora do plano (`z != 0`) são recusadas com mensagem explícita, em vez de
gerar geometria silenciosamente errada.

## Ambiente

Python 3.13 · CST Studio Suite 2026 (`_cst_interface.cp313-win_amd64.pyd`) ·
build123d 0.11.1 sobre `cadquery-ocp-novtk` 7.9.3.

Para a API Python do CST (Fase 2):
`pip install -e "C:/Program Files/CST Studio Suite 2026/AMD64/python_cst_libraries"`
— modo editable é obrigatório, o `__backend__.py` recusa qualquer outro.
