# Amostras de código

Arquivos reais, copiados do sistema em produção — cada um revisado
individualmente antes de entrar aqui. Critério de seleção: nenhum toca
autenticação, permissões, rate limiting, criptografia ou multi-tenancy
(a parte sensível do sistema fica de fora, de propósito).

| Arquivo | O que mostra |
|---|---|
| [`backend/validators.py`](backend/validators.py) | Validador Pydantic reutilizável via tipo anotado (`Annotated` + `BeforeValidator`) |
| [`backend/embedding_service.py`](backend/embedding_service.py) | Serviço async com cache Redis para embeddings de busca semântica (SentenceTransformers) |
| [`backend/geocoding_service.py`](backend/geocoding_service.py) | Integração com API externa (geocoding), com fallback entre provedores e degradação graciosa |
| [`frontend/sync.js`](frontend/sync.js) | Gerenciador de sincronização offline → online do PWA (fila local, retry, batch) |
| [`tests/test_schemas_abordagem.py`](tests/test_schemas_abordagem.py) | Testes unitários de schema Pydantic, incluindo normalização de texto |

Contexto arquitetural em [ARCHITECTURE.md](../ARCHITECTURE.md) e
[TECH-HIGHLIGHTS.md](../TECH-HIGHLIGHTS.md).
