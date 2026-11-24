# LicitaRadar ◉

Radar pessoal de licitações de **produtos** com login único, coleta oficial do PNCP e identificação de itens **desertos** (código 4) e **fracassados** (código 5).

> Código do MVP validado em CI; implantação pública ainda não concluída. **Não é uma plataforma de lances**, não revela propostas sigilosas e não presume que um item deserto ainda esteja disponível. Informações devem ser conferidas no edital.

## Iniciar localmente

Requer Python 3.12+.

```bash
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m app.security hash-password
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copie o **hash** e o **segredo aleatório** obtidos para `.env`, sem compartilhar esses valores nem fazer commit. Escolha `LOGIN_USERNAME`. Em HTTP local, mantenha `APP_ENV=development` e `COOKIE_SECURE=0`.

```bash
uvicorn --env-file .env app.main:app --host 127.0.0.1 --port 8000
```

Abra http://127.0.0.1:8000/login. Não existe endpoint de cadastro. `/healthz` apresenta apenas a condição de configuração do aplicativo.

## Executar testes

```bash
pip install -r requirements-dev.txt
ruff check app tests
python -m compileall -q app tests
python -m pytest -q
```

A CI no GitHub Actions executa os checks em Python 3.12 e 3.13 em PRs e pushes para a main, sem senhas. Não usa a API de produção em testes.

## Como o radar importa dados

1. Com a sessão autenticada, escolha intervalo de até **7 dias**, UF opcional e modalidade (pregão eletrônico ou dispensa).
2. O sistema consulta até **20 publicações por execução** e busca seus itens via API oficial PNCP, com limites/timeout e registro de falhas.
3. Armazena localmente **apenas itens de material** (`materialOuServico=M`), sem duplicar importações repetidas.
4. No dashboard, filtre descrição, UF e situação, veja valores quando publicados e abra o edital original.
5. Quando o PNCP falha, o sistema registra erro, **não infere concorrência zero**. Uma compra com itens incompletos não é salva como se estivesse completa.

O limite de 20 publicações é deliberado e significa que a consulta **não é uma cobertura exaustiva** do período. Com `AUTO_SCAN_ENABLED=1` e servidor ligado, o aplicativo consulta automaticamente as publicações de ontem e hoje a cada `AUTO_SCAN_INTERVAL_MINUTES` (30 a 1440; padrão 360) para a UF `AUTO_SCAN_UF`. São duas modalidades por ciclo, cada uma com limite de 20 publicações. A varredura não acontece se o servidor estiver desligado. O dashboard mostra apenas os registros efetivamente coletados, além de mudanças de situação observadas entre coletas. A rota autenticada `/api/changes` expõe esse histórico. Sem alertas externos ainda.

**Persistência:** banco SQLite no caminho `DB_PATH`. Em Docker/produção, monte volume persistente em `/app/data` e execute um worker. Use HTTPS, segredos externos e `COOKIE_SECURE=1`. Sem TLS ou volume persistente, não considere o deploy pronto para produção.


## Categorias e cálculo de margem

No radar, filtre por categoria indicativa (classificação por palavras da descrição), abra **Custo e margem** e informe uma cotação manual do fornecedor. A aplicação salva custos privados no SQLite sem divulgar credenciais, valida a entrada e recalcula o resultado ao acessar o item novamente. Se descrição/quantidade mudar no PNCP, a cotação antiga é marcada como desatualizada, nunca aplicada silenciosamente.

Matemática por lote (Decimal com arredondamento para cima no piso):
- Custo do lote = custo unitário × quantidade + frete + embalagem + outros + reserva.
- Ponto de equilíbrio = custo / (1 − alíquota sobre receita).
- **Piso de venda com margem alvo** = custo / (1 − alíquota sobre receita − margem desejada).
- Lucro estimado ao preço de referência = valor publicado × (1 − alíquota) − custo.

**Importante:** o piso é o menor preço viável para sua margem, não um "lance máximo" ou sugestão de preço vencedor. O valor de referência publicado pode ser sigiloso, não garante venda nem que o item esteja aberto. Faça conferência de tributos por seu regime, prazo, documentação e especificações do edital. Não há cotações de fornecedores em tempo real nem recomendação gerada por LLM nesta etapa.

## Assistente de IA (opcional, sem chave no repositório)

**DeepSeek oficial confirmado:** `AI_PROVIDER=deepseek` e `AI_MODEL=deepseek-flash` (modelo DeepSeek-V4.1-Flash-1017, conforme documentação 2026-11-23). Alternativa: `AI_PROVIDER=openrouter` e `AI_MODEL=deepseek/deepseek-v4.1-flash`. O host do provedor é fixo no código: nenhum endpoint arbitrário é aceito. Documentação: https://api-docs.deepseek.com/quick_start/pricing/ .

Para habilitar, configure somente no ambiente privado do servidor:

```ini
AI_ENABLED=1
AI_PROVIDER=deepseek
AI_MODEL=deepseek-flash
AI_API_KEY=SUA_CHAVE_PRIVADA_NUNCA_NO_GITHUB
AI_DAILY_LIMIT=10
```

A chave deve ficar fora do repositório e de arquivos versionados. Modelo e endpoint são validados; sem chave e `AI_ENABLED=1`, o assistente fica desativado sem interromper a aplicação. **Não foi testada uma chave real nem executada chamada faturável.**

No radar, clique **Analisar com IA**: confirme o consentimento por análise e opcionalmente cole texto (até 3.500 caracteres) OU envie um PDF textual de até 3 MiB e 12 páginas. Um trecho extraído (até 6.500 caracteres) é transmitido ao provedor escolhido, juntamente com descrição pública e resumo de seus custos calculados; o PDF original não é persistido. A leitura não contempla PDFs escaneados/OCR nem busca automática de anexos. O sistema usa JSON estrito, rejeita fontes documentais não encontradas no texto, impede números financeiros gerados pela IA, restringe decisões a cotar/investigar/descartar, reutiliza cache por contexto e limita tentativas a 10/dia por padrão (máximo 20). **Uma resposta não garante edital válido, disponibilidade, margem ou vitória.**

```bash
# Checagens locais sem chave e sem custos API:
python -m pytest -q tests/test_ai.py
```

## Links de referência

- [PNCP](https://pncp.gov.br/app/editais)
- [Documentação de itens](https://pncp.gov.br/manual/pt-br/latest/contratacao/consultar_itens_de_uma_contratacao.html)
- [API de consulta](https://pncp.gov.br/api/consulta/swagger-ui/index.html)
- [Source Pack reduzido](docs/SOURCE_PACK.md)
- [Work Order e evidências](docs/LR-MVP-WO-001.md)
