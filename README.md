# Pluxee — login direto e demonstração pública

Dashboard em Flask para o cartão refeição Pluxee Portugal. O login usa o mesmo
**email e palavra-passe da app**, sem registo de outra conta e **sem base de dados**.
A demonstração pública usa dados fictícios e não faz pedidos à API privada.

## Android

A aplicação nativa está em [`android/`](android/README.md): login direto, dashboard,
biometria opcional, demonstração e notificações de movimentos com verificações no
dispositivo. Não precisa de base de dados na cloud. Os alertas usam WorkManager
(cerca de 15 minutos, sujeitos às restrições de bateria do Android).

## Utilização

```powershell
pip install -r requirements.txt
python -m flask --app app run --port 5000
```

- `http://127.0.0.1:5000/login`: entrar com a conta da app Pluxee Portugal.
- `http://127.0.0.1:5000/`: dashboard autenticado.
- `http://127.0.0.1:5000/demo`: demonstração sem conta e com dados sintéticos.

Não são necessárias variáveis Pluxee nem Supabase para usar o login web.
Em produção, configurar `APP_ORIGIN` com a origem HTTPS exata do backend.
Localmente, deixar essa variável vazia. Usar HTTPS em qualquer acesso remoto.

## Login encontrado no APK 3.0.7

A análise estática do APK fornecido pelo proprietário identificou:

1. `POST /api/user/login?idLanguage=1`, com email/password cifrados no backend.
2. A resposta da Pluxee fornece o `sessionId` e o identificador do utilizador.
3. O backend gera um `ApiClaim` novo para cada pedido, seguindo o algoritmo da app.
4. Os cartões são descobertos a partir do utilizador autenticado; não se usam
   referências globais do cartão do servidor.
5. O dashboard lê saldo e movimentos apenas do cartão associado àquela sessão.

O algoritmo foi validado contra o vetor de teste incluído no APK. Um claim novo,
gerado a partir da sessão já configurada no projeto, também foi aceite pelo endpoint
real de saldo. O utilizador validou depois o login real no formulário local: o
backend concluiu a autenticação e a consulta de saldo/movimentos com resposta 200.
Não se reutilizaram passwords das capturas. Os testes automatizados de login
simulam respostas da Pluxee. Se a Pluxee exigir reCAPTCHA/SSO/verificação adicional,
o fluxo web atual pode não concluir o login; não tenta contornar esses controlos.
Neste momento, contas com vários cartões refeição exigem uma futura seleção de cartão.

Para testar uma única vez num terminal local privado:

```powershell
python scripts/check_pluxee_login.py
```

A palavra-passe fica oculta. O verificador não guarda nem mostra credenciais,
tokens ou dados financeiros, e não repete tentativas automaticamente.

## Proteção dos dados

- Sessões opacas de até 8 horas em cookie HttpOnly, SameSite=Lax e Secure em produção.
- Password e email não são persistidos. A sessão Pluxee, referências do cartão e
  último resultado ficam apenas na memória do processo, isolados por sessão.
- Logout, expiração ou reinício do servidor eliminam a sessão. Será preciso voltar
  a entrar quando o Render reiniciar ou suspender o processo.
- Pedidos que alteram estado exigem proteção CSRF e validação de origem.
- O backend limita tentativas; erros não repetem o login nem mostram respostas
  brutas da Pluxee. Após duas tentativas falhadas por email, aguarda 15 minutos.
- Os utilizadores web não podem consultar logs, modificar o monitor ou subscrever
  notificações do cartão configurado no servidor.
- A cache de uma sessão nunca usa ficheiros nem dados de outro utilizador.
- Páginas privadas e dados financeiros não são guardados na cache HTTP ou na PWA.
  O service worker remove as caches antigas `pluxee-*`.
- `/data.json`, `/static/data.json` e ficheiros de runtime não são públicos.
- A demo não chama a API privada e identifica explicitamente os dados fictícios.
- Usar **um worker** com várias threads: as sessões são locais ao processo.
  `run.py` já configura Gunicorn com um worker e quatro threads.

**Dados anteriormente publicados:** remover ficheiros atuais não apaga versões
anteriores do Git nem cópias descarregadas. A visibilidade e o histórico do repo
precisam de revisão se contiverem dados pessoais. Não se reescreveu o histórico
automaticamente. O antigo snapshot público foi preservado apenas localmente em
`data/previous_public_snapshot.json`, ignorado pelo Git.

## Publicar só a demo

```powershell
python scripts/build_demo.py --output _site
```

O destino tem de estar vazio. A compilação usa uma lista explícita de ficheiros
públicos e não copia dados de runtime, `.env`, APK ou código descompilado.
O GitHub Pages aloja apenas essa demo; o login privado requer o backend Flask.
A origem do backend está definida em `public-site.json`. A variável opcional
`PRIVATE_APP_URL` permite substituí-la no build. O botão Entrar e o antigo endereço
`login.html` encaminham para o login no Render. O artefacto estático não inclui
formulários de password nem tenta chamar `/api/auth` no GitHub Pages.

## Monitor pessoal separado — opcional

O monitor Telegram existente continua separado das sessões web. Pode usar as
credenciais do proprietário definidas apenas no servidor. O login de um visitante
nunca as utiliza nem atualiza o seu histórico. As notificações web desse monitor
não estão disponíveis nas sessões de login direto.

```powershell
python monitor.py --once
python monitor.py
python monitor.py --status
python monitor.py --stop
python run.py
python -m unittest discover -s tests -v
```

Para o monitor, a persistência por ficheiros privados continua disponível.
O adaptador opcional Supabase fica preparado para quem precisar de histórico durável,
mas não foi provisionado e não é dependência do dashboard. A migração e ferramenta
`scripts/setup_cloud.py` destinam-se apenas a essa opção de monitorização.

O workflow GitHub não grava commits com movimentos nem publica ficheiros privados.
O trabalho de monitorização cloud só é ativado com a variável de repositório
`ENABLE_PRIVATE_MONITOR=true` e respetivos secrets; o trabalho de publicação serve
apenas a demo.

- `/ping`: estado público sem dados financeiros.
- `/api/cron/check`: exige `Authorization: Bearer <CRON_SECRET>`.
- `/api/telegram/webhook`: exige `X-Telegram-Bot-Api-Secret-Token`, igual a
  `TELEGRAM_WEBHOOK_SECRET`.
- Sem esses segredos, os endpoints automáticos recusam pedidos.

## Diagnosticar uma recusa de login sem repetir tentativas

A mensagem HTTP 400 / código 214 veio da etapa de autenticação, não da consulta
de cartões. Esse código, por si só, não demonstra se há diferença nos dados
introduzidos ou no formato enviado pela integração.

Para comparar localmente com um pedido da app que teve resposta 200:

```powershell
python scripts/compare_login_capture.py "C:\caminho\pluxee-login.json"
```

Aceita o corpo JSON desse pedido ou um HAR. O ficheiro deve permanecer local e
não ser publicado: contém campos de autenticação cifrados. O comparador pede o
email/password num terminal privado, usa o IV da captura e compara os resultados.
Não decifra a password capturada, não faz pedidos à API nem guarda credenciais.
Mostra apenas se cada campo corresponde. Partilhar só esses dois resultados.

A página de login usa agora `login.css` independente e ficheiros com versão.
Um teste de browser com a cache antiga `pluxee-v2` confirmou a atualização para
`pluxee-public-v5` e o carregamento correto do novo layout na primeira visita.
