# Destaques técnicos

Alguns dos problemas de engenharia mais interessantes resolvidos no
projeto. Descrição conceitual, sem código (ver nota no README).

## Busca híbrida num único banco

O sistema precisa responder três perguntas de busca muito diferentes:
"quem se parece com esse rosto", "quem foi abordado perto daqui" e "quem
tem um nome parecido com esse, mesmo com erro de digitação". Em vez de
introduzir um banco de busca vetorial e outro geoespacial separados, tudo
roda num único PostgreSQL com três extensões (`pgvector`, `PostGIS`,
`pg_trgm`), com índices especializados para cada tipo de busca (IVFFlat
para vetores, GiST para geografia). Menos peças móveis, menos
infraestrutura pra manter em produção.

## Captura em campo, sem depender de sinal

O requisito operacional era cadastrar uma abordagem em menos de 40
segundos — e no campo, sinal de dados não é garantido. A solução foi um
PWA offline-first: os dados entram em IndexedDB local imediatamente, e a
sincronização com o servidor acontece em background assim que a conexão
volta, sem bloquear o fluxo de quem está cadastrando.

## Pipeline de IA assíncrono

Reconhecimento facial e OCR de placas são caros o suficiente para nunca
rodar no caminho síncrono de uma requisição HTTP. Essas tarefas vão para
uma fila (Redis + `arq`) e são processadas por workers separados da API —
a guarnição recebe a confirmação do cadastro na hora, e o enriquecimento
por IA acontece em paralelo, sem travar a experiência de quem está em
campo.

## Observabilidade como código

Regras de alerta do Grafana costumam ser configuração solta, editada na
UI e nunca testada. Aqui elas são versionadas e validadas no CI: um script
converte o provisioning do Grafana pro formato de teste do Prometheus
(`promtool`), roda casos de teste de comportamento (não só sintaxe), e um
smoke test sobe a stack de monitoramento real antes do merge. Motivação
direta: alertas mal configurados que ficaram presos sem disparar em
produção — o tipo de bug que só aparece quando já é tarde.

## LGPD por padrão, não por exceção

Dado pessoal sensível (CPF, foto, biometria facial) passa por
criptografia em repouso, nunca é removido fisicamente (soft delete +
auditoria), e todo acesso é atribuído a um usuário e uma guarnição
específicos. Esses três princípios são aplicados nos mixins e na camada
de acesso a dados — não são uma checagem manual espalhada pelo código,
são parte da estrutura que qualquer nova entidade herda por padrão.
