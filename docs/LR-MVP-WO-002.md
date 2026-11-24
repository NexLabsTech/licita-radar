# LR-MVP-WO-002 | Varredura automática e histórico

**Estado:** EXECUTING (não aprovado). Base/main: `6c7692f0ada168cfda1514ed7c7629ba05a4c2c6`. Branch: `feat/lr-mvp-wo-002`. Risco: STANDARD para coleta; autenticação herdada exige verificações de segurança. Não há deploy.

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

## Evidence Bundle / Checkpoint Delta (pendente)
Código proposto no branch. Não declarar agendamento nem release operacional até CI e auditoria. Após aprovação, registrar novo comportamento e riscos: scanner depende do servidor em execução, coleta limitada e sem notificações externas.
