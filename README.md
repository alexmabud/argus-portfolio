# Argus AI

Sistema de apoio operacional com IA para equipes de patrulhamento —
memória operacional da guarnição: abordagens, ocorrências, reconhecimento
facial, OCR de placas, análise geoespacial.

**Este é um repositório de portfólio**: uma cópia curada do sistema real
(que roda em produção, código-fonte privado). Aqui ficam apenas README,
documentação de arquitetura e trechos de código selecionados — sem
credenciais, dados operacionais, ou lógica de segurança sensível
(regras de permissão, criptografia, rate limiting).

## Stack

- Python 3.11+ / FastAPI / SQLAlchemy 2.0 async / Alembic
- PostgreSQL 16 + pgvector + PostGIS + pg_trgm
- Redis (cache + arq worker)
- SentenceTransformers (busca semântica multilíngue)
- InsightFace (reconhecimento facial) + EasyOCR (placas)
- PWA frontend (HTML + Alpine.js + Tailwind), offline-first
- Deploy self-hosted (Docker + Oracle Cloud)

## Sobre este repositório

Conteúdo curado e sincronizado manualmente a partir do repositório privado
principal — não é um mirror automático nem recebe releases do sistema real.
