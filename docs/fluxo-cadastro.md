# Fluxo de cadastro (mapeado com Playwright, viewport Pixel 5)

Site: `/login` → `/cadastro` (wizard em várias etapas, mesma URL) → `/conta`.
Cada etapa avança com o botão **Próxima** (`button[type=submit]`).

| # | Tela | Campos / ação | Seletores |
|---|------|---------------|-----------|
| 0 | `/login` | Clicar em **Criar conta** | botão com o texto "Criar conta" |
| 1 | Nome | nome e sobrenome | `input[name=firstName]`, `input[name=lastName]` |
| 2 | Informações básicas | dia, mês (select), ano, gênero (select) | `input[name=day]`, `select[name=month]`, `input[name=year]`, `select[name=gender]` |
| 3 | Escolha seu endereço | 3 radios: 2 sugestões + "Criar seu próprio endereço"; ao marcar o 3º aparece o campo de usuário | `input[name=choice]` (nth 0..2), `input[name=username]` |
| 4 | Senha | senha e confirmação (8+ caracteres, letras/números/símbolos) | `input[name=password]`, `input[name=confirm]` |
| 5 | Telefone | **opcional** | `input[name=phone]`, botão "Pular" |
| 6 | E-mail de recuperação | **opcional** | `input[name=recoveryEmail]`, botão "Pular" |
| 7 | Revisão | só confere os dados | botão "Próxima" |
| 8 | Privacidade e Termos | aceitar | botão "Concordo" |
| 9 | `/conta` | **sucesso**: URL `/conta` e título "Boas-vindas, <Nome>" (a ferramenta confirma por ele) | — |

Observações:
- O endereço final é `<usuario>@auth4.app`; o usuário aceita letras, números e pontos.
- Não há captcha nem verificação por e-mail/SMS no fluxo observado.
- **Limite de tentativas:** depois de muitas contas seguidas o site responde "Muitas tentativas. Aguarde alguns minutos e tente novamente" na etapa de Termos. A ferramenta detecta a mensagem e espera (`rate_limit_wait`).
- Os selects de mês e gênero têm uma 1ª opção vazia e desabilitada; selecionar pelo `value` (mês `1`..`12`; gênero `female`, `male`, `unspecified`, `custom`), nunca pela posição.
- Os `id` dos inputs são dinâmicos (`f-<name>-<hash>`): usar sempre `name=`.
- Contas de teste podem ser removidas em `/conta` → Usuários.
