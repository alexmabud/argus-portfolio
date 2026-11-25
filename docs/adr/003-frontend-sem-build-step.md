# ADR 003 — Frontend sem build step

## Status
Aceito

## Contexto
O frontend é um PWA usado em campo, em aparelhos variados e com conexão
instável. O mantenedor é único: cada camada de ferramenta (bundler,
transpiler, gerenciador de pacotes no runtime) é superfície de manutenção,
de quebra por atualização e de risco de cadeia de suprimentos.

## Decisão
Servir o frontend como **arquivos estáticos**: HTML + Alpine.js + CSS escrito à mão
+ JS de módulo único por página, sem bundler. As poucas bibliotecas de
terceiros (mapa, gráficos, IndexedDB) são **vendorizadas** em
`frontend/vendor/`, com versões fixadas e integridade (sha512) verificada
offline por um script que roda no CI.

## Consequências
- Zero etapa de build: o que está no repositório é o que roda.
- Atualização de biblioteca JS é explícita (um comando sincroniza e
  recalcula o lockfile) e auditável no diff.
- Sem tree-shaking nem minificação agressiva: aceitável para o volume de
  JS atual.
- Testes e2e não podem usar um runner que importe módulos; o padrão
  adotado é um harness HTML mínimo que carrega os arquivos reais num
  Chromium headless (Playwright) com a API estubada.
- Limitação conhecida: Service Worker não registra em `file://`, então o
  fluxo de sync offline exige testar via HTTP.
