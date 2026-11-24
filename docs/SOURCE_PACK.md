# LicitaRadar | Source Pack v0.6

## Source hierarchy
Source Check do GitHub (HEAD + arquivos existentes) > este Checkpoint > Decisions Ledger/ADRs > Scope > Definition of Done > Architecture > Requirements > evidências; Git/código/testes prevalecem sobre lembranças da conversa. Este documento é propositalmente compacto.

## Project overview
Ferramenta **de uso individual** para explorar compras públicas de produtos, com foco inicial no PNCP. Não participa automaticamente de licitações e não promete acesso a propostas sigilosas ou contagem de inscritos em tempo real.

## Requirements
R1 Login único, **sem cadastro público**; senhas e segredos somente via ambiente.
R2 Ler API oficial PNCP e exibir contratos/itens com fonte e última atualização.
R3 Identificar estado do item: 1 em andamento, 2 homologado, 3 cancelado, 4 deserto, 5 fracassado; não confundir status global de contratação com status de item.
R4 Filtros por período, palavra-chave e UF; navegação paginada; erros visíveis.
R5 Sem inventar concorrentes, preços, estoque ou oportunidades.
R6 Persistir histórico local e permitir reimportação idempotente.
R7 Categorizar produtos de forma indicativa e oferecer cotações privadas manuais com cálculos financeiros transparentes, sem inventar preços ou recomendar lances automaticamente.
R8 IA externa exclusivamente opt-in e com consentimento para envio de dados; provedores/modelos allowlisted, resultado JSON com limites, citação literal de documentos fornecidos, quota/cache e nenhuma execução de lance.
R9 Pacote de deploy auto-hospedado, sem criar custos: HTTPS proxy, app sem porta exposta, segredos privados, banco/backup persistentes, preflight, recuperação reversível e evidência de CI; produção exige validação na VPS real.

## Scope
MVP NECESSARY: auth, ingestão manual e periódica limitadas, base SQLite, dashboard neon glass acessível, atualização local, filtros por categoria, cotações privadas manuais, cálculo determinístico de margem, assistente IA opcional de riscos/documentos/margens com consentimento, histórico, links oficiais, testes e CI. IMPORTANT (próximos WOs): validação real da operação na VPS (OPS preparado em PR #6), ampliação da cobertura, identificação comprovável de republicações, fontes adicionais e alertas. FUTURE: SaaS multi-tenant. OUT OF SCOPE: lances automáticos, scraping autenticado, informações privadas de participantes, cadastro público.

## Architecture
Servidor Python com FastAPI + Jinja2, httpx e SQLite (primeira versão). Coleta opcional dentro do mesmo processo, com intervalo configurável, mutex e no máximo 20 publicações por modalidade/ciclo. Cálculos financeiros em Decimal, cotação única por item em item_quotes, independente da recriação dos itens no PNCP; fingerprint invalida cotação se descrição/quantidade mudar. A IA usa endpoints HTTPS fixos para DeepSeek/OpenRouter, modelo explicitamente permitido, cache SQLite por contexto e quota de chamadas por dia; documentos PDF são lidos localmente e o anexo não é persistido. Ingestão server-side com host PNCP fixo e paginação limitada. UI protegida por sessão assinada; cookies HttpOnly/SameSite; tokens em variáveis de ambiente. No deploy, disco persistente obrigatório para manter base de dados. Respeitar termos/limites de consulta e não depender de serviço pago.

## Security
Conta única: LOGIN_USERNAME + LOGIN_PASSWORD_HASH, SESSION_SECRET; falhar fechado em produção se ausentes. Sem segredos no Git, sem endpoint de registro, proteção CSRF em métodos de escrita, controle básico de tentativas de login, cotação privada com CSRF, fechamento e rollback SQLite, consentimento explícito antes de enviar custos/documentos à IA, limite de PDF 3 MiB/12 páginas, respostas externas validadas e sem HTML, consulta externa apenas em hosts PNCP definidos, timeout HTTP, escaping HTML, dependências fixadas quando validadas.

## Test & benchmark plan
pytest para autenticação (sucesso/falha, proteção rota, CSRF), mapeamento PNCP, importação idempotente, falha de API e filtros. Ruff e compileall no CI. Benchmarks só após definição de volume real (não inventar SLO).

## Deployment
Pacote opcional para VPS existente em ops/compose.yaml, Caddy 2.11.9 + web 1 worker sem host ports + backup sem rede; volumes persistentes, segredos *_FILE com permissões/grupo, preflight local via scripts.ops_setup, backup SQLite online com restore-new testado. Sem deploy automático; HTTPS, domínio, custo/eligibilidade, quotas, portas/firewall, cópia off-host e login público exigem prova na VPS real. Guia ops/DEPLOY.md. Não declarar deployed.

## Backlog
LR-MVP-WO-001: MVP funcional de consulta, itens, persistência, dashboard, login e CI.
LR-MVP-WO-002: execução periódica segura e histórico de mudanças (integrado na main, squash dc6aaa9c).
LR-UX-WO-003: redesign neon glass + atualização local (auditado na PR #3; implantação não inclusa).
LR-OPS-WO-003: pacote de operação persistente/HTTPS/backup com CI e preflight (PR #6 aprovada para código; DEPLOY real não realizado).
LR-INTEL-WO-004: categorias, cotações manuais e cálculo determinístico (PR #4 merged, squash 631d6feba0f72f701f6bec7eb090d8da09acf77c).
LR-AI-WO-005: DeepSeek/OpenRouter opcional, análise de riscos/documentos e limites de custo (PR #5 integrada na main, squash 6a9f4dea86b1ddd114155c6b5185765e156a724b).
LR-INT-WO-001: atas, histórico de concorrência comprovável e republicações.

## Definition of Done
Código, testes relevantes e CI verdes; sem secrets; login protege todas as telas/APIs privadas; importação idempotente; itens 4/5 rotulados corretamente; origem e datas visíveis; documentação de execução em README; Evidence Bundle e auditoria objetiva. Deploy/validação em produção só contam quando efetivamente comprovados.

## Decisions Ledger / ADRs
ADR-001 APPROVED (2026-11-23): GitHub público para CI; uso individual; login sem registro; foco código; docs concisas. 
ADR-002 APPROVED: FastAPI + SQLite + PNCP REST para MVP; sujeito a testes e leitura de contratos.
ADR-003 APPROVED: credenciais ambientais e cookies com sessões criptograficamente assinadas; sem auth externa.
ADR-004 APPROVED: não automatizar merge ou deploy antes de CI e auditoria.
ADR-005 APPROVED (2026-11-23): UI dark grafite com forte glassmorphism, destaques lime (#c1ff42) e magenta (#ff4ca8); animações discretas e modo movimento reduzido. A preferência visual tem prioridade sobre aperfeiçoar docs, sem abandonar gates de qualidade.
ADR-006 APPROVED (2026-11-23): cotações apenas informadas pelo usuário; comparação com referência PNCP não implica lance competitivo; piso monetário Decimal arredondado para cima; nenhuma recomendação automática sem dados; endpoint de IA será separado e opt-in.
ADR-007 APPROVED (2026-11-23): DeepSeek oficial deepseek-flash e OpenRouter slug fixo permitidos somente com chave no servidor, habilitação e consentimento explícitos; PDF/texto local limitado e sem armazenar anexo, cache/limite diário para custos, IA não reescreve cálculos nem decide lance.
ADR-008 APPROVED (2026-11-24, SOMENTE CÓDIGO): self-host por Docker Compose em VPS já elegível, Caddy HTTPS, 1 worker Uvicorn, volumes separados para DB/backups/certificados, segredos privados via arquivos/grupo e backup não destrutivo. Não implica autorização de deploy ou de despesas.

## Checkpoint
2026-11-23: LR-MVP-WO-001 aprovado como **incremento de código pré-produção** após revisão da PR #1; baseline 85bacf56e4782fb6e1c10f8fd284e2ca0222408c; GitHub Actions run 45304898676: Python 3.12/3.13, 14/14 testes por matriz, lint/compileall PASS; smoke PNCP real PASS (10 publicações, 8 itens de material na amostra). Deploy, operação agendada e versão completa NÃO validados. PR #1 squash merge confirmado em `6c7692f0ada168cfda1514ed7c7629ba05a4c2c6`.
2026-11-23: LR-MVP-WO-002 aprovado como **código pré-produção**, PR #2, base `6c7692f0...`; CI run `45305787417`: Python 3.12/3.13, **18/18 testes em cada matriz**, Ruff/sintaxe PASS e smoke real PNCP PASS. Histórico de transições e coletor periódico implementados; sem credenciais, deploy ou validação operacional contínua. Próxima etapa somente depois de merge confirmado.

2026-11-23: LR-UX-WO-003 auditado **APPROVED para código pré-produção** na PR #3, base dc6aaa9c19cde4dbf0be1f86929ea4c17c86bd69, head auditado 9c5ff9e125b75d9971dfb0ccde4716b19b3a257b; CI run 45308363269: 20/20 testes por matriz (Python 3.12/3.13), Ruff, compileall, node --check, PNCP real e Chromium desktop/mobile PASS. Capturas no artifact de screenshots da run. Sem deploy, sem cotações em tempo real e sem LLM; polling é somente da base local. Próximo WO de código só após merge confirmado.

2026-11-23: LR-INTEL-WO-004 auditação **APPROVED para código pré-produção** na PR #4; base 0c4f0abd04fc1169517252f4ec0c9a4cce80be08; head auditado aa22696287a9c6fe46883720cf009794528b35a1; CI run 45311161805: **47/47 testes por versão Python 3.12/3.13**, Ruff/compileall/JS check, PNCP smoke real e navegador Chromium login/dashboard/cotação (desktop/mobile) PASS. Oráculo em centavos inteiros 100 casos e teste de rollback SQLite PASS. Não há deploy, cotação automática, prova de tributação nem modelo DeepSeek integrado. Próximo incremento de código só após merge e novo Source Check.

2026-11-23: LR-AI-WO-005 APPROVED somente para código pré-produção na PR #5 (base `631d6feba0f72f701f6bec7eb090d8da09acf77c`, head auditado `88e39a11669f1d2167bdabf7bb136e1b2f591462`), CI #45312801791: **75/75 testes por matriz (Python 3.12/3.13)**, Ruff/compileall/JS, PNCP real e Chromium (desktop/mobile) PASS; 8 screenshots artifact #14883951578. DeepSeek Flash confirmado documentalmente, mas **sem chave, chamada paga ou deploy real testado**; serviço opcional desativado sem credencial. Próximo incremento de código somente após read-back do merge.

2026-11-24: LR-OPS-WO-003 **APPROVED para código pré-produção** na PR #6, base 6a9f4dea86b1ddd114155c6b5185765e156a724b, head auditado f246cb93751639ee8ddac7d431ef05d7a9430732, GitHub Actions #45315720365: **4/4 jobs PASS**, Python 3.12/3.13 **90/90 testes cada**, 15 testes OPS, Caddyfile valida, Docker rootless inicia com login private, backup sidecar e SQLite sobrevivem restart, browser desktop/mobile PASS. Sem deploy/HTTPS externo, sem prova de custo Always Free, sem DNS/servidor reais, sem offsite/encryption. Gate de produção BLOCKED; verificar VPS read-only, quotas, segurança, certificados e acesso antes de próximo WO operacional.
