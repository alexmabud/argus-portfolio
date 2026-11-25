# Práticas de engenharia

Como o Argus é construído e operado. O projeto tem um único mantenedor,
então o processo existe para substituir a "segunda pessoa na sala":
checagens automáticas, testes que travam regressões e documentação de
decisões.

## Processo de trabalho

Todo trabalho segue o mesmo caminho, com a ferramenta de IA (Claude Code)
operando dentro dele:

```
Spec → Plano (tarefas pequenas) → Branch → Build (testes primeiro) →
Verificação com evidência → Revisão → Simplificação → Entrega
```

- **Spec curta** com escopo, critérios de aceite, riscos e como verificar.
- **Tarefas verticais pequenas**: cada fatia entrega comportamento
  ponta a ponta e é verificável sozinha.
- **Testes primeiro** (RED → GREEN → refactor) em feature e em bug: o bug
  só está corrigido quando existe um teste que falha sem a correção.
- **Evidência antes de afirmação**: "funciona" só vale com saída de
  comando, requisição real ou teste — nunca por leitura de código.
- **Commits em português no formato `tipo(escopo): descrição`**, um por
  fatia.
- **Revisão** com foco em correção e segurança antes de promover o código.

## Testes

| Camada | O que cobre | Ferramenta |
|---|---|---|
| Unitários | Services, schemas, utilitários, configuração, contratos de CI | pytest (async) |
| Integração | Endpoints contra PostgreSQL + pgvector + PostGIS e Redis reais | pytest + httpx |
| E2E de frontend | Arquivos JS reais num Chromium headless, API estubada | Playwright |
| Observabilidade | Comportamento das regras de alerta | promtool |

Mais de 1.200 funções de teste. Algumas decisões que valem registro:

- **Testes de infraestrutura como código**: a ordem das etapas do script
  de deploy, a configuração do bot de dependências e as regras de alerta
  são verificadas por testes comuns de unidade (leem o YAML e afirmam os
  invariantes). Exemplo:
  [`test_grafana_alert_rules.py`](../code-samples/tests/test_grafana_alert_rules.py).
- **Banco de teste separado e protegido**: a suíte nunca aponta para o
  banco de desenvolvimento; um alvo `make test` configura o ambiente certo.
- **Frontend sem build step** → testes e2e copiam os arquivos reais para um
  diretório temporário e os abrem num harness mínimo (ver
  [ADR 003](adr/003-frontend-sem-build-step.md)).

## Pipeline de CI

Executado em todo pull request:

1. **Lint**: `ruff` (check + format) e `mypy` com plugin do Pydantic.
2. **Testes**: Postgres 16 com pgvector/PostGIS e Redis como service
   containers; o job instala o `requirements.lock` completo, ou seja, o
   mesmo conjunto de pacotes que vai para produção.
3. **Observabilidade**: `promtool check/test rules` + smoke test do Grafana.
4. **Verificações de consistência**: bibliotecas JS vendorizadas batem com o
   lockfile (sha512), pino de versão do `torch` igual entre Dockerfiles e lock.
5. **Segurança**: Bandit (análise estática), pip-audit (CVE em
   dependências), TruffleHog (segredos) e revisão automática de PR.

Documentação-only não dispara CI (`paths-ignore`) — importante para
economizar minutos de execução em repositório privado.

## Gestão de dependências

- **Lockfile com hashes** (`requirements.lock`), compilado na versão do
  Python de produção.
- Atualizações **mensais e agrupadas**: um PR por janela, com ondas de
  atualização e prova de que a suíte passa em cada onda. CVE novo vai
  direto, fora do ciclo.
- Atualizações **recusadas viram registro** com motivo, evidência e
  condição de desbloqueio (ex.: o teto do `redis-py` imposto pelo `arq`;
  ver [lições aprendidas](lessons-learned.md#7-dependência-que-quebra-o-worker-o-teto-do-redis-py)).
- Bibliotecas JS vendorizadas (sem npm no runtime) com verificação offline
  de integridade.

## Entrega

- Fluxo de branches: `feature/*` → PR → `develop` → PR → `main`. A
  promoção para `main` dispara **um** deploy.
- O script de deploy **builda antes de parar** a aplicação: falha de build
  ou de rede durante o build aborta o deploy com a versão antiga ainda no ar
  (travado por teste).
- Migrations com Alembic; as migrations rodam com um papel de banco
  diferente do usado pela aplicação (que é só-DML).
- Deploy da stack de monitoramento é manual e separado.

## Observabilidade e operação

- Métricas de HTTP, de domínio (fila de jobs, duração e falha por tipo de
  job), de infraestrutura (Postgres, Redis, host) e de disponibilidade
  externa (blackbox).
- 23 alertas testados; watchdog independente; relatório diário.
- Diagnóstico de banco: log de DDL/conexões, queries lentas (> 500 ms) e
  `pg_stat_statements`.
- Runbooks escritos para: criação do papel de banco da aplicação,
  rotação de segredos, restauração de backup, criptografia de disco.

## Backup e recuperação de desastre

Três camadas independentes:

1. **Local**: dump diário do Postgres em volume dedicado, 7 dias de retenção.
2. **Offsite**: réplica diária do banco, da configuração e dos dados do
   Grafana para **dois provedores de nuvem diferentes**, com cifra (GPG,
   AES-256) antes de sair da máquina.
3. **Restauração**: script interativo (origem, data, item) e plano de DR
   por cenário de falha.

Há métrica de "último backup bem-sucedido" com alerta de atraso — ver o
[postmortem do backup mudo](lessons-learned.md#5-backup-que-morria-em-silêncio).

## Qualidade de código

- **Docstrings em português, estilo Google**, em todos os módulos,
  classes, métodos públicos e testes; código e identificadores em inglês.
- Tipagem estática (`mypy`) e formatação automática (`ruff`).
- Camadas estritas (router → service → repository) — ver
  [ARCHITECTURE.md](../ARCHITECTURE.md).
