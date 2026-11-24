# LR-MVP-WO-001 | Work Order e Evidence Bundle

**Status:** EXECUTING / pendente de CI e auditoria. **Base SHA:** 85bacf56e4782fb6e1c10f8fd284e2ca0222408c. **Branch:** feat/lr-mvp-wo-001. **Risk:** STANDARD (autenticação e fonte externa); aumentar se deploy público.

## Objective
Entregar MVP real de radar PNCP de produtos com login de usuário único e CI.

## Context / Source Check / Context Lock
GitHub público NexLabsTech/licita-radar, inicializado e Source Pack no main; sem implementação preexistente. Source Pack v0.1 no SHA base. Reavaliar fingerprints se main, escopo ou decisões mudarem.

## Scope / Out of scope
NECESSARY: login sem registro, dashboard, itens/estado deserto e fracassado, SQLite, consulta PNCP manual limitada, API local protegida e CI. FORA: scanner global exaustivo, número de propostas não publicadas, automação de lances, integração de atos da prefeitura fora do PNCP, alertas e SaaS.

## Files / Sources to read
README.md; docs/SOURCE_PACK.md; app/{main,pncp,security,storage}.py; app/templates/*; tests/test_mvp.py; .github/workflows/ci.yml; manual PNCP v2.6.

## Requirements / Architecture / Constraints
R1-R6 do Source Pack, Python 3.12+, FastAPI/Jinja2/httpx/SQLite, segredos apenas ambiente; acesso único; cookies seguros e CSRF; API do PNCP com host fixo e timeout; nenhum custo obrigatório de cloud; sem deploy, merge ou cadastro externo automático.

## Acceptance criteria
- Anônimo não consulta dados locais;
- login válido autentica, inválido falha, não há cadastro;
- escritas exigem CSRF;
- itens 4 e 5 devidamente distinguidos, materiais somente;
- importação idempotente, filtros, paginação, fonte e atualização expostos;
- erros do PNCP não geram falsos zeros;
- testes unitários/integrados simulados e CI 3.12/3.13 verdes;
- auditoria pt-BR no PR antes do APPROVED.

## Tests / Deliverables / Review format
ruff; compileall; pytest; Evidence Bundle com base/head SHA, escopo, testes, limites, riscos e parecer. PR Draft. Auditoria deve reportar APPROVED / CORRECTION REQUIRED / BLOCKED, com itens rastreáveis.

## Stop condition
Nenhum próximo incremento, merge ou deploy sem CI/testes auditados e sem defeitos HIGH/CRITICAL.

## Evidence Bundle (pré-CI)
Implementados no branch: autenticação local sem cadastro, Jinja, persistência SQLite, cliente PNCP, testes e workflow. Testes **ainda não validados pelo CI** neste registro inicial. Limites declarados: importação manual até 20 contratações, até 500 itens por compra, sem análise de participantes, armazenamento local não escalável. Fonte oficial: https://pncp.gov.br/manual/pt-br/latest/contratacao/consultar_itens_de_uma_contratacao.html

## Checkpoint Delta proposto (NÃO promovido)
Se e somente se auditoria APPROVED: registrar baseline do MVP em desenvolvimento, resultado dos testes e próximos WOs para agendamento, ampliação da coleta, comparação de republicações e deployment com credenciais seguras. Não declarar versão deployada sem comprovação.
