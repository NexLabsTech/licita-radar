# LR-OPS-WO-003 | Deploy auto-hospedado, gratuito e reversível

**Estado:** EXECUTING (pré-produção, sem deploy). **Risk:** ELEVATED (autenticação, persistência e recuperação; sem mover dados reais nem criar custos). **Base/Context Lock:** main `6a9f4dea86b1ddd114155c6b5185765e156a724b`, compare identical; Source Pack v0.5 (blob `79fff385096a6122298ae5b554b03b31ffa06cf0`), Dockerfile (blob `34c32f7266887cce52642341506e3b1f6b1b61f3`) e app/main.py (blob `87ed209cf5196a92a2f122edc6e3b0dd5a947d16`).

## OBJECTIVE
Preparar execução em VPS já existente e elegível, usando Docker Compose + Caddy/HTTPS + SQLite persistente + backup/restauração verificados, sem criar contas ou lançar serviços pagos e **sem fazer deploy público sem autorização e DNS/credenciais confirmados**.

## CONTEXT / SOURCE CHECK
Projeto privado no uso, GitHub público no código; app single-user FastAPI/Jinja2, SQLite e agendador interno (somente um worker). Saúde atual /healthz e segredos por env; não existe deploy real, nem operador autorizado conectado à VPS. Documentação oficial: Caddy auto-HTTPS (https://caddyserver.com/docs/automatic-https), Docker Compose prod (https://docs.docker.com/compose/how-tos/production/), Oracle Always Free (https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

## SCOPE / OUT OF SCOPE
NECESSARY: pacote Compose para app + Caddy e backup sem portas públicas no app; persistência de volumes; cookie secure e produção fail-closed; **segredos via arquivos não rastreados**, verificações pré-deploy; backup SQLite online com checksum, retenção limitada, restauração para arquivo novo (sem sobrescrever), smoke local/container, CI e docs operacionais concisas. OUT: criar VPS/domínio, modificar DNS/firewall, executar shell no host do usuário, ativar serviços faturáveis, migrar de banco, integrar provedores de IA, publicação no ar sem prova externa.

## FILES / SOURCES TO READ
README.md; docs/SOURCE_PACK.md; Dockerfile; app/main.py, app/storage.py, app/security.py; .github/workflows/ci.yml; requirements.txt; scripts/visual_smoke.py. Preservar ADR-001..007 e alterações anteriores.

## REQUIREMENTS / ARCHITECTURE RULES / CONSTRAINTS
Somente Docker Compose local na VPS (AMD64 ou ARM64), Caddy com certificado automático para domínio real previamente apontado; app em rede interna sem ports; volumes nomeados para SQLite, backups e certificados; containers sem privilégios desnecessários; Caddy é único ingresso 80/443; APP_ENV=production, COOKIE_SECURE=1; login/sessão via Docker secret files, nunca GitHub/argumentos; AI desativada por padrão; backups nunca enviados à CI pública; não presumir plano Always Free, cotas, disponibilidade de domínio ou portas. Um único processo Uvicorn para agendador. Arquivo de restauração novo e teste de integridade; nenhuma restauração destrutiva.

## ACCEPTANCE CRITERIA
- Compose e configuração Caddy parseáveis, sem publicar porta 8000, sem senha real versionada.
- Inicialização da app em produção falha quando faltam segredos ou cookie seguro; suporte via *_FILE sem divulgar conteúdo.
- Banco e backup sobrevivem reinício/recriação de contêiner; backup online consistente sob leitura/escrita; retenção, sha256 e restauração em destino novo com dados idênticos, rollback operacional documentado.
- CI de lint, testes, scripts de preflight/config e smoke de container (se runner suportar), além de Chromium existente; rede pública não acionada no smoke de app.
- Nenhuma tentativa de DNS, login em VPS, emissão de certificado ou deploy sem Source Check/authorization.

## TESTS / DELIVERABLES / REVIEW FORMAT / STOP CONDITION
pytest (incluindo falhas, backup/recovery, env secrets e limites), ruff, compileall, docker compose config + Dockerfile build/smoke se possível, Playwright existente. Evidence Bundle: base/head sha, arquivos, testes, riscos e proof obligations de recuperação. PR Draft, auditoria pt-BR: APPROVED / CORRECTION REQUIRED / BLOCKED. Só promover checkpoint e merge se CI verde sem HIGH/CRITICAL. Parar antes de deploy público se domínio, TLS, acesso/planos ou custos não comprovados.

## EVIDENCE / CHECKPOINT DELTA
Pendente de CI e auditoria. Release não deve ser declarada DEPLOYED/VALIDATED. Próximo incremento após aprovação: verificar VPS (read-only), DNS, portas, quotas e realizar deploy controlado e smoke HTTPS/backup real.
