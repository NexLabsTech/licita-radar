# LicitaRadar | VPS sem novo serviço pago

**Status:** pacote para operador, **NÃO implantado**. Não existe evidência de acesso, hostname, DNS, HTTPS ou quota gratuita validada na VPS real.

## Arquitetura e custo

Uma VPS Linux já disponível e dentro dos seus limites gratuitos (ex.: Oracle Always Free **somente se instância/volume forem elegíveis**) pode receber três contêineres via Docker Compose:

- proxy: Caddy 2.11.9, único ingresso 80/443, HTTPS automático, certificados em volume persistente
- web: FastAPI, um worker, sem porta publicada no host, usuário sem root, SQLite em volume nomeado
- backup: processo sem rede, leitura somente do SQLite e até 7 cópias locais validadas

**Não crie VPS, registre domínio ou ative recurso com cobrança automática.** O domínio precisa estar sob controle do operador. Se já houver proxy ocupando 80/443, integre ao proxy existente em outro WO; **não pare serviços existentes sem autorização**.

## Pré-requisitos reais (gate de deploy)

Verificar na VPS: instância e volumes elegíveis/sem custo adicional, arquitetura AMD64/ARM64, Docker/Compose, memória e disco, portas 80 e 443 livres (TCP e opcional UDP 443), DNS A/AAAA do subdomínio apontando à VPS, saída Internet para ACME e PNCP, firewall externo restrito, isolamento de outros serviços e backup externo planejado. Nenhum item acima foi confirmado no ambiente do usuário.

## Preflight não destrutivo do host (antes de configurar segredos)

Com o repositório disponível na VPS e Python 3.12+ instalado, execute como usuário não root:

~~~bash
python -m scripts.ops_host_preflight
# Após definir/controlar um subdomínio real:
python -m scripts.ops_host_preflight --domain radar.seudominio.com.br
~~~

Este comando **não inicia contêiner, altera DNS, abre portas, exibe IP ou coleta senhas**. Retorna JSON com PASS/WARN/BLOCKED e termina com código 2 quando faltar qualquer gate externo. O diagnóstico de portas 80/443 é local; porta já ocupada pode significar proxy de outro serviço. **Não desligue o proxy existente**: nesse caso, uma integração com ele precisa de plano próprio. DNS resolvido **não comprova** que aponta para a VPS correta. O script nunca aprova gratuidade da Oracle nem firewall/HTTPS real, e não autentica em painel de faturamento. Não enviar IP, senhas ou logs confidenciais pelo chat.

## Instalação no host (somente após autorização)

Na raiz do repositório, como usuário Linux **não root** que opera o Docker:

~~~bash
python -m scripts.ops_setup init --domain radar.seudominio.com.br --email voce@seudominio.com.br --user admin
python -m scripts.ops_setup check
docker compose --env-file ops/runtime/compose.env -f ops/compose.yaml config --quiet
docker compose --env-file ops/runtime/compose.env -f ops/compose.yaml build
# SOMENTE após gates de segurança, DNS, custo e autorização:
docker compose --env-file ops/runtime/compose.env -f ops/compose.yaml up -d
~~~

O init pede a senha interativamente (sem eco), gera hash PBKDF2 e segredo HMAC. Arquivos exclusivos no host ops/runtime/ ficam fora do Git. Segredos são legíveis apenas pelo proprietário/grupo do usuário Linux (chmod 640); o app de UID 10001 recebe somente o grupo suplementar necessário. Escolha usuário/grupo dedicado se houver outras pessoas no grupo. **Não execute init com sudo/root.** O preflight rejeita diretórios, hashes, permissões, domínios de exemplo e uso pago de IA.

**Nunca** cole segredos no chat, PR, Issues, Actions, Portainer screenshots ou logs. Não execute docker compose config sem --quiet com segredos adicionais. Senhas não são passadas como argumentos.

## Validação pós-deploy (necessária antes de declarar DEPLOYED)

Acesse https://seu-domínio/login com certificado válido em navegador externo. Confira HTTP→HTTPS, HSTS, cookie Secure/HttpOnly/SameSite=Strict, login inválido/CSRF 403, /api/items anônima 401, dashboard autenticado, PNCP manual, scanner sem duplicações e docker compose ps com health healthy. Teste login pelo celular.

~~~bash
docker compose --env-file ops/runtime/compose.env -f ops/compose.yaml ps
docker compose --env-file ops/runtime/compose.env -f ops/compose.yaml logs --tail=60 --no-log-prefix web backup proxy
~~~

Não compartilhe logs com dados pessoais. Retenção local do Docker está limitada. O job GitHub Actions **não** faz deploy e nunca contém senhas reais.

## Backup, restauração e reversão

O sidecar inicia com cópia online do SQLite, repete a cada 24 h e mantém 7 arquivos locais validados com PRAGMA integrity_check. Cópia manual sem interromper o servidor:

~~~bash
docker compose --env-file ops/runtime/compose.env -f ops/compose.yaml exec backup python -m scripts.ops_backup once --db /app/data/licitaradar.db --dir /app/backups --keep 7
~~~

Os arquivos contêm custos e dados privados. Permanecem em volume nomeado, sem criptografia nem cópia externa nesta versão. Isto **não** substitui cópia fora da VPS, nem garante recuperação de falha completa da conta/disco.

Restauração é intencionalmente **não destrutiva**: use scripts.ops_backup restore-new --source ARQUIVO --dest NOVO_ARQUIVO para gerar outro banco verificado, NUNCA para sobrescrever o banco ativo. Para usá-lo, pare web e backup, preserve uma cópia do banco atual e faça a troca/reversão apenas com plano de recuperação aprovado. Não use docker compose down -v, docker volume rm ou substitua SQLite com a aplicação ligada.

Rollback de código exige preservar os volumes, conferir compatibilidade do esquema e testar; voltar a imagem não reverte migração. Este incremento não muda tabelas de negócio.

## Limites

Coleta PNCP continua limitada a até 20 publicações por modalidade/ciclo. IA desativada por padrão (AI_ENABLED=0); ativação e possível gasto exigem gate separado. Sem deploy ou HTTPS real confirmado até leitura legítima e validação externa.
