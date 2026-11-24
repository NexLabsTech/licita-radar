# LR-INTEL-WO-004 | Categorias, cotações e margem

**Status:** EXECUTING, aguardando CI e auditoria. **Base/head lock:** main 0c4f0abd04fc1169517252f4ec0c9a4cce80be08. **Branch:** feat/lr-intel-wo-004. **Risco:** ELEVATED para cálculos monetários; nenhuma transação de dinheiro ou lance automático.

**OBJECTIVE:** possibilitar análise financeira verificável por item PNCP, usando APENAS preços e custos inseridos pelo proprietário. Categorias automáticas indicativas para agilizar filtros.

**CONTEXT / SOURCE CHECK:** PR #3 UX integrada; docs/SOURCE_PACK.md v0.3; stack FastAPI/Jinja/SQLite; sessões com login único + CSRF; /api/items autenticada; dashboard com polling seguro. Git e código revisados em main. Mudanças de escopo: NECESSARY categoria e calculadora; IMPORTANT cotações automáticas de fornecedores e histórico de concorrentes; FUTURE LLM DeepSeek.

**SCOPE:** heurística transparente de categoria, filtro por categoria nos resultados; cotações manuais privadas com fornecedor informado, custo unitário, frete/embalagem/outros/reserva do lote, taxa variável sobre receita e margem mínima; custo total, equilíbrio, piso por margem, lucro/margem hipotéticos ao valor de referência; aviso quando PNCP item foi alterado; interface dark glass e vínculo direto ao edital. **OUT OF SCOPE:** cotação em tempo real sem fonte, análise de edital jurídico, cálculo tributário oficial, lance automático, previsão de competição, LLM, deploy.

**FILES/SOURCES:** docs/SOURCE_PACK.md, app/{main,storage,intelligence,quotes}.py, app/templates/{dashboard,quote}.html, app/static/{site.css,site.js}, tests/, scripts/visual_smoke.py, .github/workflows/ci.yml. **ARCHITECTURE:** Decimal com arredondamento seguro ao centavo, persistência em tabela item_quotes vinculada à contratação (não às linhas de item que são recriadas no PNCP). Fingerprint de descrição+quantidade invalida cotação defasada; schema extensível sem perda do banco legado. Credenciais somente ambiente; quote GET e POST autenticados; POST com CSRF.

**CONSTRAINTS:** não inventar preço, número de concorrentes, cotações ou score; não afirmar que deserta=aberta; não confundir piso econômico para vender ao governo com preço máximo competitivo. Preço de referência é teto comparativo hipotético, não lance assegurado.

**ACCEPTANCE:** categorias em rotas HTML e API sem vieses de filtro/paginação; apenas quote válida gera análise; cotação resiste a reimportação; mudança de produto/quantidade torna cotação desatualizada; aritmética exata, sem NaN/Infinity/percentuais impossíveis; CSRF, fail-closed, escape HTML; UI mobile/desktop; links oficiais; CI verde.

**TESTS:** pytest (matemática, segurança, persistência e API), ruff, compileall, node --check e Chromium desktop/mobile com screenshot; smoke PNCP real somente leitura (advisory). **DELIVERABLES:** branch+PR, códigos, testes, Evidence Bundle (base/head SHA, CI, riscos), auditoria pt-BR. **REVIEW FORMAT:** APPROVED / CORRECTION REQUIRED / BLOCKED. **STOP CONDITION:** sem WO seguinte, merge ou deploy antes de auditoria deste incremento.

**EVIDENCE BUNDLE:** pendente da execução dos testes e auditoria.
**CHECKPOINT DELTA (PROPOSTO):** registrar cálculo privado com cotações de origem manual e categoria indicativa; preservar gate de deploy e integração futura DeepSeek.
