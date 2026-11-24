# LicitaRadar | Source Pack v0.1

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

## Scope
MVP NECESSARY: auth, ingestão manual com limites, base SQLite, dashboard, filtros, links oficiais, testes e CI. IMPORTANT (próximos WOs): agendamento, normalização por item, análise de republicações, fontes adicionais e alertas. FUTURE: SaaS multi-tenant. OUT OF SCOPE: lances automáticos, scraping autenticado, informações privadas de participantes, cadastro público.

## Architecture
Servidor Python com FastAPI + Jinja2, httpx e SQLite (primeira versão). Ingestão server-side com host PNCP fixo e paginação limitada. UI protegida por sessão assinada; cookies HttpOnly/SameSite; tokens em variáveis de ambiente. No deploy, disco persistente obrigatório para manter base de dados. Respeitar termos/limites de consulta e não depender de serviço pago.

## Security
Conta única: LOGIN_USERNAME + LOGIN_PASSWORD_HASH, SESSION_SECRET; falhar fechado em produção se ausentes. Sem segredos no Git, sem endpoint de registro, proteção CSRF em métodos de escrita, controle básico de tentativas de login, consulta externa apenas em hosts PNCP definidos, timeout HTTP, escaping HTML, dependências fixadas quando validadas.

## Test & benchmark plan
pytest para autenticação (sucesso/falha, proteção rota, CSRF), mapeamento PNCP, importação idempotente, falha de API e filtros. Ruff e compileall no CI. Benchmarks só após definição de volume real (não inventar SLO).

## Deployment
Sem deploy automático inicial. Variáveis secretas provisionadas no provedor; HTTPS obrigatório no ambiente público; configurar persistência do SQLite ou migrar para banco gerenciado; rodar somente com login definido. Deploy e domínio requerem gates específicos.

## Backlog
LR-MVP-WO-001: MVP funcional de consulta, itens, persistência, dashboard, login e CI.
LR-MVP-WO-002: execução periódica segura e validação de dados públicos reais.
LR-INT-WO-001: atas, histórico de concorrência comprovável e republicações.

## Definition of Done
Código, testes relevantes e CI verdes; sem secrets; login protege todas as telas/APIs privadas; importação idempotente; itens 4/5 rotulados corretamente; origem e datas visíveis; documentação de execução em README; Evidence Bundle e auditoria objetiva. Deploy/validação em produção só contam quando efetivamente comprovados.

## Decisions Ledger / ADRs
ADR-001 APPROVED (2026-11-23): GitHub público para CI; uso individual; login sem registro; foco código; docs concisas. 
ADR-002 APPROVED: FastAPI + SQLite + PNCP REST para MVP; sujeito a testes e leitura de contratos.
ADR-003 APPROVED: credenciais ambientais e cookies com sessões criptograficamente assinadas; sem auth externa.
ADR-004 APPROVED: não automatizar merge ou deploy antes de CI e auditoria.

## Checkpoint
2026-11-23: LR-MVP-WO-001 aprovado como **incremento de código pré-produção** após revisão da PR #1; baseline 85bacf56e4782fb6e1c10f8fd284e2ca0222408c; GitHub Actions run 45304898676: Python 3.12/3.13, 14/14 testes por matriz, lint/compileall PASS; smoke PNCP real PASS (10 publicações, 8 itens de material na amostra). Deploy, operação agendada e versão completa NÃO validados. Próximo: LR-MVP-WO-002 somente após merge.
