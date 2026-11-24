# LR-UX-WO-003 · Neon Glass UI

**Status:** EXECUTING / AWAITING CI. **Base SHA:** dc6aaa9c19cde4dbf0be1f86929ea4c17c86bd69. **Branch:** feat/lr-ux-wo-003. **Risk:** STANDARD (interface privada com login existente).

**OBJECTIVE:** redesenhar LicitaRadar com vidro forte, fundo grafite e somente dois destaques cromáticos, lime #c1ff42 e magenta #ff4ca8; tornar a interface responsiva e acessível e atualizar a visualização local periodicamente.

**CONTEXT / SOURCE CHECK:** Source Pack v0.2, main com PRs #1/#2 integradas; backend FastAPI/Jinja2/SQLite e controle de acesso sem registro; /api/items e /api/changes autenticados. Source Check: HEAD main igual ao SHA base acima. Novo direcionamento do proprietário: prioridade ao visual premium sem mudar infraestrutura.

**SCOPE (NECESSARY):** login, dashboard, filtros, KPIs, sincronização manual e histórico com CSS; JS local usando DOM seguro; validação de sintaxe no CI e testes de auth/CSRF. **IMPORTANT:** calculadora de margem, categorias e classificação em outro WO. **FUTURE:** provider DeepSeek configurável após confirmar nome e endpoint real. **OUT OF SCOPE:** número de concorrentes não divulgado, streaming PNCP, deploy, LLM nesta PR.

**FILES/SOURCES TO READ:** docs/SOURCE_PACK.md, README.md, app/main.py, app/templates/dashboard.html, app/templates/login.html, app/static/site.css, app/static/site.js, tests/test_mvp.py, .github/workflows/ci.yml. **REQUIREMENTS:** preservar rotas/cookies/CSRF, dados verificáveis e URLs oficiais; não criar margens simuladas nem prometer PNCP em tempo real.

**ARCHITECTURE / CONSTRAINTS:** manter SSR Jinja2 e CSS/JS puros, sem CDN, sem scripts inline proibidos pelo CSP, sem alterações no banco; atualização apenas dos endpoints autenticados; links cliente exclusivamente HTTPS pncp.gov.br; renderização com textContent/DOM, polling pausado em aba oculta; respeitar prefers-reduced-motion.

**ACCEPTANCE CRITERIA:** dark lime + magenta + neutros, blur/fallback, responsivo, login e filtros preservados, links oficiais, estados vazio/erro, atualização local distinguível de coleta PNCP, navegação por teclado, sem HTML não confiável via JS.

**TESTS:** ruff check app tests, python -m compileall -q app tests, python -m pytest -q, node --check app/static/site.js; smoke PNCP não bloqueante. **DELIVERABLES:** código, testes, CI, PR, Evidence Bundle e auditoria pt-BR. **REVIEW FORMAT:** APPROVED / CORRECTION REQUIRED / BLOCKED + base/head SHA e evidências. **STOP CONDITION:** não iniciar motor financeiro/LLM antes de auditar esta PR, não declarar deploy.

**Evidence Bundle:** pendente de CI. **Checkpoint Delta proposto:** registrar UX e atualização visual local, sem sugerir monitoramento instantâneo do PNCP ou versão publicada.
