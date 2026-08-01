# Argus AI

Sistema de apoio operacional com IA para equipes de patrulhamento —
memória operacional da guarnição: abordagens, ocorrências, reconhecimento
facial, OCR de placas, análise geoespacial.

> **Este é um repositório de portfólio.** O código-fonte real roda em
> produção num repositório privado. Aqui há apenas documentação de
> arquitetura e decisões técnicas — sem código, credenciais, dados
> operacionais ou lógica de segurança do sistema.

## O problema

Guarnições em patrulhamento acumulam conhecimento operacional (quem já foi
abordado, com quem, onde, em que veículo) que hoje fica espalhado em
memória, boletins e sistemas que não conversam entre si. O Argus centraliza
essa memória operacional e usa IA para acelerar reconhecimento e busca —
sem nunca inventar fatos: a IA organiza e conecta dados que já existem,
não gera informação nova.

## Principais funcionalidades

- Cadastro de abordagem em campo em menos de 40 segundos, offline-first
- Reconhecimento facial e OCR de placas para identificação rápida
- Busca híbrida (semântica + geoespacial + fuzzy) sobre o histórico de
  abordagens e ocorrências
- Mapeamento de relacionamentos entre pessoas abordadas juntas
- Conformidade LGPD: criptografia, trilha de auditoria, retenção
  controlada

Ver [ARCHITECTURE.md](ARCHITECTURE.md) para a arquitetura do sistema e
[TECH-HIGHLIGHTS.md](TECH-HIGHLIGHTS.md) para os problemas de engenharia
mais interessantes resolvidos no projeto.

## Stack

- Python 3.11+ / FastAPI / SQLAlchemy 2.0 async / Alembic
- PostgreSQL 16 + pgvector + PostGIS + pg_trgm
- Redis (cache + fila de background jobs via `arq`)
- SentenceTransformers (busca semântica multilíngue)
- InsightFace (reconhecimento facial) + EasyOCR (placas)
- PWA frontend (HTML + Alpine.js + Tailwind), offline-first com IndexedDB
- Observabilidade: Prometheus + Grafana, com regras de alerta testadas em
  CI (promtool)
- Deploy self-hosted (Docker Compose + Oracle Cloud)
