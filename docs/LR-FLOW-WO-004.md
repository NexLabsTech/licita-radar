# LR-FLOW-WO-004 | Workspace privado de oportunidades

**Estado:** EXECUTING, código pré-produção. **Source Check / Context Lock:** main \`430897aa4af8e83e8ca4a56e97997e0caf087cbd\`, compare identical, Source Pack v0.9 blob \`d2f8d8ffd6f58e3d6f0ee82c7d0eb598b4d69a87\`, app/main.py blob \`e7a2b9e3d85f2fde8eaa9ac122ffb3eda108f43c\`. **Risk:** STANDARD (dados privados armazenados); nenhum pagamento/lance ou autenticação externa.

**OBJECTIVE:** acompanhar trabalho de cada oportunidade da descoberta até o resultado, sem depender de planilhas externas, com etapas manuais, notas, prazos e checklist.

**CONTEXT:** FastAPI/Jinja2 SQLite, PNCP, cálculo de margem, assistente IA opcional, favoritos e resultados públicos, Source Pack/ADRs v0.9. **FILES/SOURCES TO READ:** docs/SOURCE_PACK.md, app/{main,storage,quotes,monitor,security}.py, templates/dashboard.html, CSS/JS, tests, CI.

**SCOPE NECESSARY:** workspace /workspace e /api/workspace privados, até 200 casos; etapa manual 'avaliar', 'cotando', 'documentos', 'pronto', 'inscrito', 'ganho', 'perdido', 'arquivado'; prioridade baixa/normal/alta; prazo opcional e notas privadas <=1200 caracteres; histórico imutável de mudanças de etapa; checklist até 20 tarefas por oportunidade; links PNCP, cálculo, IA, resultados e monitor; dashboard com botão contextual; exportação CSV sob autenticação com saneamento anti-formula injection; realce de prazos vencidos. **IMPORTANT futuro:** múltiplos fornecedores/cotações, exportação PDF, lembrete opcional; **OUT OF SCOPE:** registro no portal PNCP, garantia de inscrição, enviar propostas, auto-lances, deploy, contas e serviços pagos.

**REQUIREMENTS:** status manual não substitui estado PNCP; nunca dizer que inscrição ocorreu por marcar 'inscrito'; sem atualizar automaticamente etapa a partir de LLM; persistência após reimportação (FK só na tender e item solto); CAS/regressão de concorrência; limites de entrada; sem XSS/CSRF, exportação sem fórmula em planilhas; no automatic data deletion.

**ARCHITECTURE RULES:** SQLite aditivo com CREATE TABLE IF NOT EXISTS, transações e rollback; ON DELETE CASCADE somente de tarefas/histórico quando caso é apagado (sem endpoint de exclusão de caso nesta WO); estágio 'arquivado' preserva dados; compartilhamento local restrito ao usuário único; notas nunca transmitidas à IA automaticamente.

**ACCEPTANCE CRITERIA:** login/CSRF obrigatórios em GET e POST, critérios de estágios e prioridade, 200 casos/20 tarefas, read-back e histórico de transições; UI responsiva e acessível no desktop/celular; CSV seguro e identificado como anotação do usuário, não dado oficial; nenhum efeito remoto ao mudar etapa. Prazos só alertam localmente e não enviam notificações externas.

**TESTS:** pytest de CRUD, validação, persistent reimport, transição idempotente, checklist, CSV injection, unauthorized/CSRF/XSS, regressão SQLite; Ruff, compileall, JS, Chromium mobile/desktop, Docker + backups existentes, CI. **DELIVERABLES:** código/tests, PR Draft, auditoria pt-BR, Evidence Bundle, checkpoint mínimo. **REVIEW FORMAT:** APPROVED / CORRECTION REQUIRED / BLOCKED. **STOP CONDITION:** sem merge/avançar com falha HIGH/CRITICAL, CI não verde ou inconsistência nas fontes. **Checkpoint Delta:** PROPOSED até auditoria.
