# LicitaRadar | Source Pack v0.13

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
R10 Monitor local: favoritos, regras de UF/status/categoria/palavra, alertas deduplicados no banco e candidatos conservadores de republicação, sempre apresentados como hipótese não comprovada.
R11 Resultados oficiais do PNCP consultados manualmente: quantidade e valor unitário homologados, situação, fornecedor PJ sem identificadores pessoais; snapshots persistentes com prova da fonte. Não inferir participantes de uma lista de resultados.
R12 Coleta progressiva por até 7 dias, UF/modalidade e município IBGE opcional; cursor persistente, lotes limitados, erro explícito e noção de cobertura parcial/concluída conforme API, sem alegar abrangência nacional.

R13 Workspace privado de oportunidades com etapa/prioridade manual, notas, prazo, checklist, histórico de mudanças e exportação CSV segura, separado do estado PNCP.

R14 Comparação de até 12 cotações privadas por item, com custo total e piso calculados pelo motor Decimal auditado; ativação manual/fingerprint, data e origem declaradas, sem preços automaticamente obtidos.

## Scope
MVP NECESSARY: auth, ingestão manual e periódica limitadas, base SQLite, dashboard neon glass acessível, atualização local, filtros por categoria, cotações privadas manuais, cálculo determinístico de margem, assistente IA opcional de riscos/documentos/margens com consentimento, histórico, links oficiais, testes e CI. IMPORTANT (próximos WOs): validação real da operação na VPS (OPS preparado em PR #6), ampliação da cobertura, identificação comprovável de republicações, fontes adicionais e alertas. FUTURE: SaaS multi-tenant. OUT OF SCOPE: lances automáticos, scraping autenticado, informações privadas de participantes, cadastro público.

## Architecture
Servidor Python com FastAPI + Jinja2, httpx e SQLite (primeira versão). Coleta opcional dentro do mesmo processo, com intervalo configurável, mutex e no máximo 20 publicações por modalidade/ciclo. Cálculos financeiros em Decimal, cotação única por item em item_quotes, independente da recriação dos itens no PNCP; fingerprint invalida cotação se descrição/quantidade mudar. A IA usa endpoints HTTPS fixos para DeepSeek/OpenRouter, modelo explicitamente permitido, cache SQLite por contexto e quota de chamadas por dia; documentos PDF são lidos localmente e o anexo não é persistido. Ingestão server-side com host PNCP fixo e paginação limitada. Modo cobertura separado do scanner automático: por clique, até 2 páginas x 20 publicações, filtro IBGE e cursor no SQLite; só marca como concluído quando a resposta PNCP prova última página. UI protegida por sessão assinada; cookies HttpOnly/SameSite; tokens em variáveis de ambiente. No deploy, disco persistente obrigatório para manter base de dados. Respeitar termos/limites de consulta e não depender de serviço pago.

## Security
Conta única: LOGIN_USERNAME + LOGIN_PASSWORD_HASH, SESSION_SECRET; falhar fechado em produção se ausentes. Sem segredos no Git, sem endpoint de registro, proteção CSRF em métodos de escrita, controle básico de tentativas de login, cotação privada com CSRF, fechamento e rollback SQLite, consentimento explícito antes de enviar custos/documentos à IA, limite de PDF 3 MiB/12 páginas, respostas externas validadas e sem HTML, consulta externa apenas em hosts PNCP definidos, timeout HTTP, escaping HTML, dependências fixadas quando validadas.

## Test & benchmark plan
pytest integrado para auth/CSRF/cookies corrompidos, PNCP mockado, ingestão idempotente, resultados, monitor/cobertura, Decimal e fornecedores, pipeline comercial/CSV e migrações reentrantes. CI com Python 3.12/3.13, Ruff/compileall/JS, Chromium desktop/mobile, Docker/backup. Benchmarks só após definição de volume real (não inventar SLO).

## Deployment
Pacote opcional para VPS existente em ops/compose.yaml, Caddy 2.11.9 + web 1 worker sem host ports + backup sem rede; volumes persistentes, segredos *_FILE com permissões/grupo, preflight local via scripts.ops_setup, backup SQLite online com restore-new testado. Sem deploy automático; HTTPS, domínio, custo/eligibilidade, quotas, portas/firewall, cópia off-host e login público exigem prova na VPS real. Guia ops/DEPLOY.md. Não declarar deployed.

## Backlog
LR-MVP-WO-001: MVP funcional de consulta, itens, persistência, dashboard, login e CI.
LR-MVP-WO-002: execução periódica segura e histórico de mudanças (integrado na main, squash dc6aaa9c).
LR-UX-WO-003: redesign neon glass + atualização local (auditado na PR #3; implantação não inclusa).
LR-OPS-WO-003: pacote de operação persistente/HTTPS/backup com CI e preflight (PR #6 aprovada para código; DEPLOY real não realizado).
LR-INTEL-WO-004: categorias, cotações manuais e cálculo determinístico (PR #4 merged, squash 631d6feba0f72f701f6bec7eb090d8da09acf77c).
LR-AI-WO-005: DeepSeek/OpenRouter opcional, análise de riscos/documentos e limites de custo (PR #5 integrada na main, squash 6a9f4dea86b1ddd114155c6b5185765e156a724b).
LR-INT-WO-001: monitor local de favoritos/regras/alertas e candidatos de republicação (PR #7 merged, squash 82d7b397f0a89b1f525bd142146b224f32750052).
LR-DATA-WO-002: resultados oficiais por item PNCP sem inferir concorrentes (PR #8 merged, squash 90bc1dd160c97191934d6e1810444fa2e2ad3088).
LR-COVER-WO-003: coleta por região/IBGE com cursor paginado e retomável (PR #9 merged, squash 430897aa4af8e83e8ca4a56e97997e0caf087cbd).
LR-FLOW-WO-004: workspace privado de etapas/notas/prazos/checklist e CSV seguro (PR #10 merged, squash b6e8eca978e74803a0e2512d56757efec3c89e27).
LR-SUP-WO-005: comparador privado de até 12 fornecedores por item e seleção explícita da cotação principal (PR #11 merged, squash 096effc5c28c006e04cbc07ccd5e9fd4c027b4cf).
LR-QA-WO-006: hardening de sessão e matriz E2E de aceite pré-produção (PR #12 merged, squash 5f04a6edf257a4dd76340f9d2b9df122ecd4e7c6).
LR-RELEASE-WO-007: preflight host somente leitura com relatório de gates não comprovados (PR #13 APPROVED apenas para código, merge pendente).
Fase de código: CODE_QUALIFIED_PREPRODUCTION após auditoria PR #12 (integrar somente se head final/CI verdes; confirmar merge SHA em main). PRs necessárias #1–#12; nenhuma próxima funcionalidade NECESSARY identificada nos requisitos R1–R14. Implantação/validação real na VPS são gates separados, explicitamente adiados pelo usuário. Sem custos e sem propostas automáticas.

## Definition of Done
Código, testes relevantes e CI verdes; sem secrets; login protege todas as telas/APIs privadas; importação idempotente; itens 4/5 rotulados corretamente; origem e datas visíveis; documentação de execução em README; Evidence Bundle e auditoria objetiva. **DoD da fase de código pré-produção** aprovado na PR #12 após 224/224 testes por versão e 4/4 jobs, integração E2E sintética. **DoD de versão completa (deploy, operação real e validação na VPS)** não atingido por decisão de adiamento, não confundir com `CODE_QUALIFIED_PREPRODUCTION`.

## Decisions Ledger / ADRs
ADR-001 APPROVED (2026-11-23): GitHub público para CI; uso individual; login sem registro; foco código; docs concisas. 
ADR-002 APPROVED: FastAPI + SQLite + PNCP REST para MVP; sujeito a testes e leitura de contratos.
ADR-003 APPROVED: credenciais ambientais e cookies com sessões criptograficamente assinadas; sem auth externa.
ADR-004 APPROVED: não automatizar merge ou deploy antes de CI e auditoria.
ADR-005 APPROVED (2026-11-23): UI dark grafite com forte glassmorphism, destaques lime (#c1ff42) e magenta (#ff4ca8); animações discretas e modo movimento reduzido. A preferência visual tem prioridade sobre aperfeiçoar docs, sem abandonar gates de qualidade.
ADR-006 APPROVED (2026-11-23): cotações apenas informadas pelo usuário; comparação com referência PNCP não implica lance competitivo; piso monetário Decimal arredondado para cima; nenhuma recomendação automática sem dados; endpoint de IA será separado e opt-in.
ADR-007 APPROVED (2026-11-23): DeepSeek oficial deepseek-flash e OpenRouter slug fixo permitidos somente com chave no servidor, habilitação e consentimento explícitos; PDF/texto local limitado e sem armazenar anexo, cache/limite diário para custos, IA não reescreve cálculos nem decide lance.
ADR-008 APPROVED (2026-11-24, SOMENTE CÓDIGO): self-host por Docker Compose em VPS já elegível, Caddy HTTPS, 1 worker Uvicorn, volumes separados para DB/backups/certificados, segredos privados via arquivos/grupo e backup não destrutivo. Não implica autorização de deploy ou de despesas.
ADR-009 APPROVED (2026-11-24): regras/alertas locais deduplicados e favoritos privados; correspondência entre itens de licitações distintas é classificada somente como candidata à republicação, com CNPJ, descrição, quantidade e data compatíveis e duas fontes oficiais, sem prova automática de vínculo.
ADR-010 APPROVED (2026-11-24): resultados por item na API oficial PNCP são observações homologadas e não participantes; endpoint de consulta explícita com cooldown/limites, nomes PJ somente (sem CPF/CNPJ pessoal), armazenamento e matemática Decimal sem arredondamento inventado.
ADR-011 APPROVED (2026-11-24): varredura PNCP avançada apenas sob comando explícito, lotes de 2 x 20, cursor SQLite, IBGE opcional, conclusão somente com prova da última página e sem mudar o coletor automático atual.

ADR-012 APPROVED (2026-11-24): pipeline de participação exclusivamente manual; etapas 'inscrito', 'ganho' e 'perdido' NÃO comprovam ação na plataforma de licitação; notas privadas não enviadas à IA e CSV neutraliza fórmulas.

ADR-013 APPROVED (2026-11-25): cotações de fornecedores múltiplos são informadas manualmente, com origem e data declaradas, sem scraping; promoção explícita, transacional e bloqueada quando item PNCP mudou. Fórmulas financeiras permanecem em analyze/validate_quote existentes, sem automação de lances.

ADR-014 APPROVED (2026-11-25): preflight da VPS executa exclusivamente observações sem escrita, custos nunca são aprovados automaticamente; deploy exige provas independentes de conta/quotas, domínio, firewall/HTTPS e backup off-host. Portas 80/443 ocupadas bloqueiam novo proxy, sem parar serviços existentes.

## Checkpoint
2026-11-23: LR-MVP-WO-001 aprovado como **incremento de código pré-produção** após revisão da PR #1; baseline 85bacf56e4782fb6e1c10f8fd284e2ca0222408c; GitHub Actions run 45304898676: Python 3.12/3.13, 14/14 testes por matriz, lint/compileall PASS; smoke PNCP real PASS (10 publicações, 8 itens de material na amostra). Deploy, operação agendada e versão completa NÃO validados. PR #1 squash merge confirmado em `6c7692f0ada168cfda1514ed7c7629ba05a4c2c6`.
2026-11-23: LR-MVP-WO-002 aprovado como **código pré-produção**, PR #2, base `6c7692f0...`; CI run `45305787417`: Python 3.12/3.13, **18/18 testes em cada matriz**, Ruff/sintaxe PASS e smoke real PNCP PASS. Histórico de transições e coletor periódico implementados; sem credenciais, deploy ou validação operacional contínua. Próxima etapa somente depois de merge confirmado.

2026-11-23: LR-UX-WO-003 auditado **APPROVED para código pré-produção** na PR #3, base dc6aaa9c19cde4dbf0be1f86929ea4c17c86bd69, head auditado 9c5ff9e125b75d9971dfb0ccde4716b19b3a257b; CI run 45308363269: 20/20 testes por matriz (Python 3.12/3.13), Ruff, compileall, node --check, PNCP real e Chromium desktop/mobile PASS. Capturas no artifact de screenshots da run. Sem deploy, sem cotações em tempo real e sem LLM; polling é somente da base local. Próximo WO de código só após merge confirmado.

2026-11-23: LR-INTEL-WO-004 auditação **APPROVED para código pré-produção** na PR #4; base 0c4f0abd04fc1169517252f4ec0c9a4cce80be08; head auditado aa22696287a9c6fe46883720cf009794528b35a1; CI run 45311161805: **47/47 testes por versão Python 3.12/3.13**, Ruff/compileall/JS check, PNCP smoke real e navegador Chromium login/dashboard/cotação (desktop/mobile) PASS. Oráculo em centavos inteiros 100 casos e teste de rollback SQLite PASS. Não há deploy, cotação automática, prova de tributação nem modelo DeepSeek integrado. Próximo incremento de código só após merge e novo Source Check.

2026-11-23: LR-AI-WO-005 APPROVED somente para código pré-produção na PR #5 (base `631d6feba0f72f701f6bec7eb090d8da09acf77c`, head auditado `88e39a11669f1d2167bdabf7bb136e1b2f591462`), CI #45312801791: **75/75 testes por matriz (Python 3.12/3.13)**, Ruff/compileall/JS, PNCP real e Chromium (desktop/mobile) PASS; 8 screenshots artifact #14883951578. DeepSeek Flash confirmado documentalmente, mas **sem chave, chamada paga ou deploy real testado**; serviço opcional desativado sem credencial. Próximo incremento de código somente após read-back do merge.

2026-11-24: LR-OPS-WO-003 **APPROVED para código pré-produção** na PR #6, base 6a9f4dea86b1ddd114155c6b5185765e156a724b, head auditado f246cb93751639ee8ddac7d431ef05d7a9430732, GitHub Actions #45315720365: **4/4 jobs PASS**, Python 3.12/3.13 **90/90 testes cada**, 15 testes OPS, Caddyfile valida, Docker rootless inicia com login private, backup sidecar e SQLite sobrevivem restart, browser desktop/mobile PASS. Sem deploy/HTTPS externo, sem prova de custo Always Free, sem DNS/servidor reais, sem offsite/encryption. Gate de produção BLOCKED; verificar VPS read-only, quotas, segurança, certificados e acesso antes de próximo WO operacional.

2026-11-24: LR-INT-WO-001 APPROVED para código pré-produção na PR #7, base 1b1a6df46229838fc6e3065bb082d4cec8dbb03f, head auditado 5a0bb0256f8c39cde29b7b0b153c44b11c721199; CI #45364645389: 4/4 jobs PASS, **110/110 pytest por versão Python 3.12/3.13**, Ruff/compileall/JS, PNCP smoke real, Docker/backup e Chromium desktop/mobile. Favoritos/regras/alertas locais com CSRF e candidatos de republicação com fonte antiga/nova, nunca confirmação automática. Deploy e cobertura exaustiva ainda não validados.

2026-11-24: LR-DATA-WO-002 APPROVED para código pré-produção na PR #8, base 82d7b397f0a89b1f525bd142146b224f32750052, head auditado 52d1fed320437c7fcea1da71e8245175d3a87dcd; CI #45366354177, **140/140 testes por versão Python 3.12/3.13**, 4 jobs sucesso, PNCP live smoke (publicações) + Chromium desktop/mobile + Docker backup. Consulta de resultados PNCP somente sob demanda; 200 vazio, erros e cancelados tratados; nenhuma inferência do número de participantes. API real de resultados para item particular, preços do mercado e deploy não validados.

2026-11-24: LR-COVER-WO-003 APPROVED para código pré-produção na PR #9, base 90bc1dd160c97191934d6e1810444fa2e2ad3088, head auditado 1ca5e8a90e849790ca83e24855379305e18bbf75; Actions #45368094055: **163/163 pytest por Python 3.12/3.13, 4 jobs PASS**, smoke PNCP publicações, Docker backup/restart, Chromium desktop/mobile, screenshot artifact #14908480562. Em /coverage, até 40 publicações por clique, filtros UF/IBGE/modality, estado parcial/erro/concluído e cursores persistentes; sem deploy, cobertura exaustiva nacional ou egress de múltiplas páginas reais validado.

2026-11-24: LR-FLOW-WO-004 APPROVED para código pré-produção na PR #10; base 430897aa4af8e83e8ca4a56e97997e0caf087cbd, head auditado 54a72f2069bddc24eeeed8c06cec5bab8b944df6. GitHub Actions #45369703934: 4/4 jobs SUCCESS, **179/179 pytest por matriz Python 3.12/3.13**, Ruff/JS, PNCP smoke, Docker+backup e Chromium desktop/mobile. Workspace de etapas manuais, notas, prazo, checklist e CSV privado protegido; não houve inscrição real, cotação de fornecedor automática nem deploy.

2026-11-25: LR-SUP-WO-005 APPROVED para código pré-produção, PR #11, base b6e8eca978e74803a0e2512d56757efec3c89e27, head auditado 1a8a59825f0dc86279e140f2eb42ee4e0dfd51f1. CI #45701421452 4/4 jobs SUCCESS: **205/205 testes Python 3.12 e 205/205 Python 3.13**, Ruff/JS, PNCP smoke publicações, Docker/backup, Chromium desktop/mobile, artifact screenshots #15062463907 sha256 57777e5ed728f7878702bae3b8f61dde721515e8a02848ba8b300572097233e5. Sem valores de mercado obtidos automaticamente, sem lances, sem deploy ou validação tributária real.

2026-11-25: LR-QA-WO-006 auditada **APPROVED para fase de código pré-produção** na PR #12; base 096effc5c28c006e04cbc07ccd5e9fd4c027b4cf, HEAD auditado d2b10bc898220579dcf73c237c8ada6d827845e1. CI #45702319423: 4/4 SUCCESS, **224/224 pytest por Python 3.12 e 3.13**, Ruff/compileall/JS, Chromium desktop/mobile e Docker rootless/backup/restart. Artifact #15063931964 digest sha256 71adda6b7a3ba7bedfca951f262c2bfe8ec69db6a3736830183a5b811b90737e. Cookie/base64 malformed fail-closed e jornada integrada sem rede externa. **CODE_QUALIFIED_PREPRODUCTION**, somente após merge aprovado. VPS/HTTPS/AI paga/mercado real e versão deployada ainda NÃO validados.

2026-11-25: LR-RELEASE-WO-007 auditada **APPROVED apenas para código de preflight host read-only** PR #13, base 5f04a6edf257a4dd76340f9d2b9df122ecd4e7c6, head auditado 85a154176ef40eb2ba4fdac146cc63d31a51fd64; CI #45703696746 **4/4 jobs SUCCESS**, 246/246 pytest em Python 3.12 e 3.13, 37/37 ops pytest, Ruff/JS, PNCP smoke, Chromium desktop/mobile, Docker/backup/restart. Artifact screenshots #15064965257 SHA256 d9a0d90c1dae86e95227d1ea24e286d4bcc9082b05aeaa2aae845f1947782f6f. Nenhum comando de inspeção foi executado na VPS real. Status: **HOST_PREFLIGHT_PREPARED**, billing/DNS/TLS/firewall/backup externo/VPS BLOCKED; ainda CODE_QUALIFIED_PREPRODUCTION, não DEPLOYED.
