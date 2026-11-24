# LR-MVP-WO-002 | Varredura automática e histórico

**Estado:** APPROVED (código pré-produção; deploy e release ainda bloqueados). Base/main: `6c7692f0ada168cfda1514ed7c7629ba05a4c2c6`. Branch: `feat/lr-mvp-wo-002`. Risco: STANDARD para coleta; autenticação herdada exige verificações de segurança. Não há deploy.

## Objective / Context
Automatizar consultas periódicas, persistir alterações de situação por item e exibir histórico no painel autenticado. Source Check: PR #1 merged, Source Pack v0.1 e app funcional confirmados no GitHub.

## Scope / Out of Scope
NECESSARY: worker periódico com desligamento limpo, mutex contra sincronizações simultâneas, UF/intervalo por env, duas modalidades, registro de transições idempotente, UI e API protegidas. FORA: SaaS, e-mail, mensagens, lances, scraping de propostas, cobertura completa nacional e deploy.

## Files / Requirements / Architecture / Constraints
Ler `docs/SOURCE_PACK.md`, `app/main.py`, `app/pncp.py`, `app/storage.py`, `tests/test_mvp.py`, `.env.example`. Python/FastAPI/SQLite sem banco externo, worker em um processo; `AUTO_SCAN_ENABLED=1` quando configurado, frequência 30..1440 min, último dia + hoje, duas modalidades (6/8), sem requisições se login não configurado. Nunca representar ausência de dados como zero concorrência.

## Acceptance criteria / Tests
- Importação repetida sem gerar eventos extras; mudança 1→4, 4→5 detectada; recém-observados 4/5 registrados.
- Endpoint `/api/changes` protegido; interface exibe fontes PNCP e data.
- Execução periódica somente quando configurada, sem credenciais no repo, com encerramento limpo e sem varreduras simultâneas.
- Erro em uma modalidade não impede a outra; pytest, compileall, Ruff, CI Python 3.12/3.13.

## Deliverables / Review / Stop condition
Arquivos de código, testes e CI, Evidence Bundle com base/head SHA, auditoria pt-BR e checkpoint delta proposto; PR Draft. Parar ante falha HIGH/CRITICAL, inconformidade do DoD ou pendência de CI. Sem merge antes de APPROVED.

## Evidence Bundle / Checkpoint Delta auditado
Base SHA `6c7692f0ada168cfda1514ed7c7629ba05a4c2c6`; head de auditoria `a20239179f3c4992ee00aa7bb37e1913bf3d2bc6`. PR #2, GitHub Actions run `45305787417`: Python 3.12/3.13, **18/18 testes em cada matriz**; lint/compileall PASS; smoke da API PNCP real PASS (10 publicações, 8 itens de material na amostra). Auditoria em pt-BR na PR #2: APPROVED para código, não para produção. Mudanças registradas nos arquivos app/storage.py, app/scheduler.py, app/main.py, dashboard, CSS, env, README e testes.

**Correções:** importação dos testes formatada após falha de lint. **Riscos:** execução só enquanto servidor funciona, até 20 publicações por modalidade e coleta (não exaustiva), banco SQLite único requer volume e worker único, ausência de alerta externo, necessidade de credenciais e HTTPS. **Checkpoint Delta:** aprovado para registro canônico, implementação validada por CI; deploy/versão completa não comprovados.
