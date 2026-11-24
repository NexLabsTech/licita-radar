# LicitaRadar ◉

Radar pessoal de licitações de **produtos** com login único, coleta oficial do PNCP e identificação de itens **desertos** (código 4) e **fracassados** (código 5).

> MVP em desenvolvimento na branch LR-MVP-WO-001. **Não é uma plataforma de lances**, não revela propostas sigilosas e não presume que um item deserto ainda esteja disponível. Informações devem ser conferidas no edital.

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

O limite de 20 publicações é deliberado e significa que a consulta **não é uma cobertura exaustiva** do período. Não há atualização automática nesta versão. O dashboard mostra apenas os registros efetivamente coletados.

**Persistência:** banco SQLite no caminho `DB_PATH`. Em Docker/produção, monte volume persistente em `/app/data` e execute um worker. Use HTTPS, segredos externos e `COOKIE_SECURE=1`. Sem TLS ou volume persistente, não considere o deploy pronto para produção.

## Links de referência

- [PNCP](https://pncp.gov.br/app/editais)
- [Documentação de itens](https://pncp.gov.br/manual/pt-br/latest/contratacao/consultar_itens_de_uma_contratacao.html)
- [API de consulta](https://pncp.gov.br/api/consulta/swagger-ui/index.html)
- [Source Pack reduzido](docs/SOURCE_PACK.md)
- [Work Order e evidências](docs/LR-MVP-WO-001.md)
