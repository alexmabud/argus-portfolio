"""Converte as regras de alerta do Grafana em um arquivo de regras do Prometheus.

Motivação (auditoria de observabilidade, 2026-07-28): as regras de alerta vivem
em ``monitoring/grafana/provisioning/alerting/rules.yml``, num formato que só o
Grafana entende. Nada validava esse arquivo antes do deploy — os bugs recorrentes
de observabilidade (``gte`` inexistente no motor de expressão, casamento de
vetores sem ``on()``, buckets saturados em 1s, ``NaN`` chegando ao threshold) só
apareciam em produção, geralmente como alerta preso no Telegram por horas.

Este script extrai de cada regra a query PromQL (refId ``A``) e o threshold
configurado, e gera uma regra de alerta equivalente no formato nativo do
Prometheus. Com isso o ``promtool`` passa a validar sintaxe (``check rules``) e
comportamento (``test rules``) da MESMA fonte de verdade que o Grafana carrega —
sem duplicar as expressões num arquivo de teste que fataria da produção.

Equivalência assumida: todas as regras usam ``instant: true``, cujo resultado é
um único ponto por série. Nesse caso o *reducer* do Grafana (``avg``/``last``)
é a identidade, e a condição vira simplesmente ``<query> <operador> <valor>``.

Uso:
    python monitoring/tests/build_promtool_rules.py <origem.yml> <destino.yml>
"""

import sys
from pathlib import Path
from typing import Any

import yaml

#: Operadores aceitos pelo motor de expressão do Grafana mapeados para PromQL.
#: `gte`/`lte` NÃO existem lá (achado 2026-07-15: uma regra com `gte` falha a
#: construção em toda avaliação e cai em execErrState). Manter esta lista
#: restrita é o que faz o build quebrar cedo se alguém escrever `gte` de novo.
OPERADORES = {"gt": ">", "lt": "<"}


def _regra_prometheus(regra: dict[str, Any]) -> dict[str, str]:
    """Traduz uma regra de alerta do Grafana para o formato do Prometheus.

    Args:
        regra: Dicionário de uma entrada de ``groups[].rules[]`` do provisioning.

    Returns:
        Dicionário com as chaves ``alert``, ``expr`` e ``for``.

    Raises:
        ValueError: Se a regra não tiver query PromQL, não for instantânea,
            usar um operador não suportado pelo Grafana, ou tiver mais de uma
            condição de threshold.
    """
    uid = regra["uid"]
    consultas = [d for d in regra["data"] if d.get("datasourceUid") == "prometheus-argus"]
    if len(consultas) != 1:
        raise ValueError(f"{uid}: esperava exatamente 1 query Prometheus, achei {len(consultas)}")
    modelo = consultas[0]["model"]
    if not modelo.get("instant"):
        raise ValueError(f"{uid}: query não é instant — a equivalência do reducer não vale")

    thresholds = [d for d in regra["data"] if d.get("datasourceUid") == "__expr__"]
    if len(thresholds) != 1:
        raise ValueError(f"{uid}: esperava exatamente 1 expressão de threshold")
    condicoes = thresholds[0]["model"]["conditions"]
    if len(condicoes) != 1:
        raise ValueError(f"{uid}: esperava exatamente 1 condição, achei {len(condicoes)}")

    avaliador = condicoes[0]["evaluator"]
    tipo = avaliador["type"]
    if tipo not in OPERADORES:
        raise ValueError(
            f"{uid}: evaluator '{tipo}' não é suportado pelo Grafana "
            f"(aceitos: {sorted(OPERADORES)}) — a regra falharia em toda avaliação"
        )
    limite = avaliador["params"][0]

    return {
        "alert": uid.replace("-", "_"),
        "expr": f"({modelo['expr']}) {OPERADORES[tipo]} {limite}",
        "for": regra["for"],
    }


def converter(origem: Path) -> dict[str, Any]:
    """Lê o provisioning de alertas do Grafana e devolve regras do Prometheus.

    Args:
        origem: Caminho do ``rules.yml`` do provisioning do Grafana.

    Returns:
        Estrutura ``{"groups": [...]}`` pronta para o ``promtool``.
    """
    dados = yaml.safe_load(origem.read_text(encoding="utf-8"))
    grupos = []
    for grupo in dados["groups"]:
        grupos.append(
            {
                "name": grupo["name"],
                "rules": [_regra_prometheus(r) for r in grupo["rules"]],
            }
        )
    return {"groups": grupos}


def main() -> None:
    """Converte o arquivo de origem e grava o resultado no destino.

    Raises:
        SystemExit: Código 2 se os argumentos de linha de comando estiverem
            incorretos.
    """
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    origem, destino = Path(sys.argv[1]), Path(sys.argv[2])
    resultado = converter(origem)
    destino.write_text(
        yaml.safe_dump(resultado, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    total = sum(len(g["rules"]) for g in resultado["groups"])
    print(f"{total} regras convertidas de {origem} para {destino}")


if __name__ == "__main__":
    main()
