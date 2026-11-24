# LR-DATA-WO-002 | Resultados oficiais de itens e preços homologados

**Status:** EXECUTING, sem deploy ou consumo pago. **Source Check / Context Lock:** main 82d7b397f0a89b1f525bd142146b224f32750052 (compare identical), Source Pack v0.7 blob 20dd0a80c17e7e105fe8569ac90d56ef7e79c348; app/main.py blob 51d8f90d95827dd63a0c1dbbd8c014af15566529. **Risco:** STANDARD, leitura PNCP sem assinatura financeira.

**OBJECTIVE:** mostrar resultados oficiais publicados de um item PNCP sem inferir número de licitantes, cotação atual de fornecedor ou margem vencedora.

**CONTEXT:** login privado, SQLite, UI dark glass lime/magenta; Manual PNCP 2.6, [consultar resultados de item](https://pncp.gov.br/manual/pt-br/latest/contratacao/consultar_resultados_de_item_de_uma_contratacao.html): GET caminho orgaos/CNPJ/compras/ANO/SEQUENCIAL/itens/NUMERO/resultados; payload listaResultados; campos preço unitário e quantidade homologados, nome fornecedor, classificação SRP e status resultado (1 informado, 2 cancelado). Não informa quantidade de participantes.

**SCOPE NECESSARY:** GET autenticado /results e /api/results; POST CSRF atualização sob demanda somente do item; host PNCP fixo, timeout, limite de tamanho/200 registros, Decimals de 4 casas; status de consulta não consultado/disponível/vazio/falhou + data UTC; snapshot persistente e substituição atômica somente com HTTP 200 validado. Exibir informados/cancelados corretamente e nunca dizer n licitantes. Guardar razão social apenas de fornecedor PJ, sem CPF/CNPJ ou dados de pessoas físicas. Preservar snapshot após falha. Links do edital, cotação e IA. Cooldown 60s.

**OUT OF SCOPE:** preços de mercado em tempo real, scraping, anexo automático, contagem de participantes inferida, benchmarking de unidades heterogêneas, auto-lance, deploy/serviço pago.

**FILES/SOURCES TO READ:** Source Pack, app/pncp.py, storage.py, quotes.py, main.py, templates dashboard/quote, site.js/site.css, visual_smoke, testes/CI, manual PNCP 2.6. **REQUIREMENTS/ARCHITECTURE RULES:** 1/2 de resultado não é 1/2 de estado item; validar CNPJ/ano/sequencial/número do DB; Decimal com max 4 casas; GET apenas remoto PNCP, sem redirects e sem retry; falha não apaga dados prévios; 200 lista vazia não é 404.

**ACCEPTANCE CRITERIA:** URL fixed-host derivada de item armazenado; não persistir payload incompleto; consultas idempotentes e com cache/cooldown; rótulo 'resultados registrados' nunca 'concorrentes'; privacidade PF/PE; UI dark e acessível; testes auth/CSRF/status/erros/decimais/rollback/escapamento; sem egress/custos no CI.

**TESTS:** pytest MockTransport, Ruff/compileall, JS syntax, Chromium mobile/desktop e Docker regression. **DELIVERABLES:** código, PR, Evidence Bundle, auditoria pt-BR, Checkpoint Delta mínimo. **REVIEW FORMAT:** APPROVED/CORRECTION REQUIRED/BLOCKED. **STOP CONDITION:** sem merge/next com falha HIGH/CRITICAL ou checks pendentes; sem deploy. **Checkpoint Delta:** PROPOSED.
