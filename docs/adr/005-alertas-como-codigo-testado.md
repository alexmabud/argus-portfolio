# ADR 005 — Regras de alerta como código testado

## Status
Aceito

## Contexto
As regras de alerta do Grafana vivem em YAML de provisioning, num formato
que só o Grafana entende. Nada as validava antes do deploy, e os bugs
recorrentes (operador inexistente, casamento de vetores sem `on()`, buckets
saturados, `NaN` chegando ao threshold, vetor vazio com `noDataState`
errado) só apareciam em produção — geralmente como alerta preso por horas.

## Decisão
Tratar as regras como código:

1. Um script **converte o provisioning real** do Grafana para regras do
   Prometheus (query + threshold + `for`).
2. O `promtool` valida a **sintaxe** (`check rules`) e o **comportamento**
   (`test rules`) com cenários que reproduzem cada modo de falha que já
   ocorreu.
3. Um **smoke test** sobe o Grafana de produção com o provisioning
   completo antes do merge.
4. O conversor só aceita os operadores que o Grafana suporta — escrever um
   inexistente quebra o build, não a produção.

As regras de teste são **geradas**, nunca escritas à mão, para não
divergirem do que roda em produção.

## Consequências
- Toda mudança em regra de alerta exige cenário de teste correspondente.
- O CI ganha um job a mais (custo de minutos), compensado por tirar a
  classe inteira de "alerta quebrado descoberto em produção".
- A equivalência assumida (queries `instant`, redutor identidade) é
  checada pelo conversor: fora dela, ele falha explicitamente.

Código:
[`build_promtool_rules.py`](../../code-samples/monitoring/build_promtool_rules.py),
[`promql_unit_tests.yml`](../../code-samples/monitoring/promql_unit_tests.yml).
