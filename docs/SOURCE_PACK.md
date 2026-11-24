# LicitaRadar | Source Pack v0.4

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

## Scope
MVP NECESSARY: auth, ingestão manual e periódica limitadas, base SQLite, dashboard neon glass acessível, atualização local, filtros por categoria, cotações privadas manuais, cálculo determinístico de margem, histórico, links oficiais, testes e CI. IMPORTANT (próximos WOs): operação persistente, ampliação da cobertura, identificação comprovável de republicações, fontes adicionais e alertas. FUTURE: SaaS multi-tenant. OUT OF SCOPE: lances automáticos, scraping autenticado, informações privadas de participantes, cadastro público.

## Architecture
Servidor Python com FastAPI + Jinja2, httpx e SQLite (primeira versão). Coleta opcional dentro do mesmo processo, com intervalo configurável, mutex e no máximo 20 publicações por modalidade/ciclo. Cálculos financeiros em Decimal, cotação única por item em item_quotes, independente da recriação dos itens no PNCP; fingerprint invalida cotação se descrição/quantidade mudar. Ingestão server-side com host PNCP fixo e paginação limitada. UI protegida por sessão assinada; cookies HttpOnly/SameSite; tokens em variáveis de ambiente. No deploy, disco persistente obrigatório para manter base de dados. Respeitar termos/limites de consulta e não depender de serviço pago.

## Security
Conta única: LOGIN_USERNAME + LOGIN_PASSWORD_HASH, SESSION_SECRET; falhar fechado em produção se ausentes. Sem segredos no Git, sem endpoint de registro, proteção CSRF em métodos de escrita, controle básico de tentativas de login, cotação privada com CSRF, fechamento e rollback SQLite, consulta externa apenas em hosts PNCP definidos, timeout HTTP, escaping HTML, dependências fixadas quando validadas.

## Test & benchmark plan
pytest para autenticação (sucesso/falha, proteção rota, CSRF), mapeamento PNCP, importação idempotente, falha de API e filtros. Ruff e compileall no CI. Benchmarks só após definição de volume real (não inventar SLO).

## Deployment
Sem deploy automático inicial. Variáveis secretas provisionadas no provedor; HTTPS obrigatório no ambiente público; configurar persistência do SQLite ou migrar para banco gerenciado; rodar somente com login definido. Deploy e domínio requerem gates específicos.

## Backlog
LR-MVP-WO-001: MVP funcional de consulta, itens, persistência, dashboard, login e CI.
LR-MVP-WO-002: execução periódica segura e histórico de mudanças (integrado na main, squash dc6aaa9c).
LR-UX-WO-003: redesign neon glass + atualização local (auditado na PR #3; implantação não inclusa).
LR-OPS-WO-003: operação persistente com segredos externos, HTTPS e validação de implantação.
LR-INTEL-WO-004: categorias, cotações manuais e cálculo determinístico de custos/margens (código auditado na PR #4; integração em curso).
LR-AI-WO-005: provider LLM configurável e análise assistida após INTEL.
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

## Checkpoint
2026-11-23: LR-MVP-WO-001 aprovado como **incremento de código pré-produção** após revisão da PR #1; baseline 85bacf56e4782fb6e1c10f8fd284e2ca0222408c; GitHub Actions run 45304898676: Python 3.12/3.13, 14/14 testes por matriz, lint/compileall PASS; smoke PNCP real PASS (10 publicações, 8 itens de material na amostra). Deploy, operação agendada e versão completa NÃO validados. PR #1 squash merge confirmado em `6c7692f0ada168cfda1514ed7c7629ba05a4c2c6`.
2026-11-23: LR-MVP-WO-002 aprovado como **código pré-produção**, PR #2, base `6c7692f0...`; CI run `45305787417`: Python 3.12/3.13, **18/18 testes em cada matriz**, Ruff/sintaxe PASS e smoke real PNCP PASS. Histórico de transições e coletor periódico implementados; sem credenciais, deploy ou validação operacional contínua. Próxima etapa somente depois de merge confirmado.

2026-11-23: LR-UX-WO-003 auditado **APPROVED para código pré-produção** na PR #3, base dc6aaa9c19cde4dbf0be1f86929ea4c17c86bd69, head auditado 9c5ff9e125b75d9971dfb0ccde4716b19b3a257b; CI run 45308363269: 20/20 testes por matriz (Python 3.12/3.13), Ruff, compileall, node --check, PNCP real e Chromium desktop/mobile PASS. Capturas no artifact de screenshots da run. Sem deploy, sem cotações em tempo real e sem LLM; polling é somente da base local. Próximo WO de código só após merge confirmado.

2026-11-23: LR-INTEL-WO-004 auditação **APPROVED para código pré-produção** na PR #4; base 0c4f0abd04fc1169517252f4ec0c9a4cce80be08; head auditado aa22696287a9c6fe46883720cf009794528b35a1; CI run 45311161805: **47/47 testes por versão Python 3.12/3.13**, Ruff/compileall/JS check, PNCP smoke real e navegador Chromium login/dashboard/cotação (desktop/mobile) PASS. Oráculo em centavos inteiros 100 casos e teste de rollback SQLite PASS. Não há deploy, cotação automática, prova de tributação nem modelo DeepSeek integrado. Próximo incremento de código só após merge e novo Source Check.
