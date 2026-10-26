# account-creator

Ferramenta de terminal (Python) que cria contas de teste em ambiente de homologação usando o
**Chrome de um emulador Android** (AVD do Android Studio), controlado via Appium. Tem painel
interativo em Textual (tema verde), registro das contas em SQLite e **troca de dispositivo**
a cada N contas.

## Como usar (jeito fácil)

Dê duplo clique em **`iniciar.bat`**. Na primeira vez ele cria o ambiente virtual e o `.env`
sozinho. Depois abre o painel.

Pré-requisitos instalados na máquina: Python 3.11+, Android Studio (com SDK e um AVD de imagem
*Google APIs*), Node.js e Appium com o driver UiAutomator2
(`npm i -g appium` e `appium driver install uiautomator2`).
A aba **Saúde** do painel confere tudo isso para você.

## O painel

| Aba | Tecla | Para que serve |
|---|---|---|
| Painel | F1 | Totais, taxa de sucesso, tempo típico por conta, estado da saúde e contas recentes |
| Novo lote | F2 | Configura **um lote**: nome, quantidade, contas por dispositivo, wipe, User-Agent, proxy, preço do tráfego, notas e **estimativa de tempo** |
| Lotes | F3 | Histórico de lotes: status, progresso, tempo, tráfego, **custo**, configuração usada e **log completo**; iniciar/retomar, relatório e exclusão |
| Contas | F4 | Lista com busca por e-mail, filtro por status e **exportação para CSV** (`exports/`) |
| Saúde | F5 | Verifica SDK, AVD, aceleração, Java, Node, Appium, driver, RAM, domínio, site e banco |
| Configurações | F6 | Padrões globais (`Ctrl+S` salva em `config.local.yaml`) |

## Lotes

Cada execução é um **lote**: você configura (aba *Novo lote*), e o lote guarda a própria
configuração, as contas criadas, métricas e um log de tudo que aconteceu.

- **Registro**: início/fim, tempo ativo (sem contar pausas), criadas/falhas, dispositivos,
  esperas por limite do site, trocas de IP, tráfego do proxy e **custo** (`tráfego × preço por GB`).
- **Pausar/retomar**: `P` na execução pausa depois da conta atual; `S` para. Um lote parado,
  pausado ou interrompido (inclusive se o programa fechar) aparece em *Lotes* e **continua de onde parou**.
- **Relatório**: botão *Relatório* gera `exports/lote_<id>_<data>/` com `relatorio.md`,
  `contas.csv` e `log.csv`.

Na execução: `S` parar · `P` pausar/retomar · `Esc` voltar (quando terminar).

## Proxy (IP)

O site limita a criação **por IP**. Com proxy, o lote sai por outro IP quando isso acontece (em vez
de esperar ~15 min) e a cada dispositivo novo. Modos (por lote):

- **Dinâmico**: um gateway rotativo no `.env`: `PROXY_URL=https://host:porta:usuario:senha`
  (também aceita `usuario:senha@host:porta`). IP novo = nova sessão (`{password}_session-<id>`,
  configurável em `proxy.session_template`).
- **Estático**: lista em `proxies.txt` (uma por linha, `host:porta:usuario:senha`); trocar = próximo da lista.

Por dentro, um proxy local no PC (`127.0.0.1`) autentica no provedor, troca o IP e conta os bytes;
o Chrome do emulador sai por ele (`--proxy-server=http://10.0.2.2:<porta>`). Antes de começar, o
lote consulta e mostra o **IP de saída**. `.env` e `proxies.txt` ficam fora do git; senhas de proxy
nunca vão para logs ou telas. A ferramenta só roda nos domínios de `allowed_domains`.

## Troca de dispositivo

A cada `per_device` contas (padrão **5**) o orquestrador:

1. fecha a sessão do Chrome;
2. desliga o emulador;
3. liga de novo com `-wipe-data` (dados zerados, como um aparelho novo);
4. abre uma sessão nova (com User-Agent aleatório, se ativado).

O Appium continua ligado durante a troca. Se 3 contas seguidas falharem, a troca acontece
sozinha (recuperação); se mesmo assim falhar de novo, a execução é interrompida com aviso.

> A troca muda os dados do aparelho e do navegador. **Sozinha não muda o endereço IP**: para isso
> use proxy (veja abaixo), que troca o IP junto com o dispositivo.

## Limite do site ("Muitas tentativas")

O site de homologação limita a criação de contas **por IP**: depois de muitas contas seguidas ele
responde *"Muitas tentativas. Aguarde alguns minutos e tente novamente"*. A ferramenta reconhece
isso, mostra uma contagem regressiva no painel e espera (`rate_limit_wait`, 180 s, até
`rate_limit_max_waits` vezes) sem gastar tentativas. Se o bloqueio persistir, o lote para com um
aviso. No teste, o bloqueio durou ~15 minutos. Trocar de dispositivo **não** resolve (é por IP).

## Configuração

`config.yaml` traz os padrões; o painel grava alterações em `config.local.yaml` (ignorado pelo
git). `.env` guarda `TARGET_URL`, `AVD_NAME` e, opcionalmente, `ANDROID_HOME`.

```yaml
accounts:
  count: 5               # quantidade padrão
  retries: 2             # tentativas extras por conta
  per_device: 5          # contas por dispositivo antes da troca
  wipe_on_rotate: true   # troca = reinício com -wipe-data
  random_user_agent: false
emulator:
  headless: false
  boot_timeout: 240
  settle_seconds: 20     # folga após o boot
```

## Linha de comando (opcional)

```powershell
.venv\Scripts\python -m automate_accounts              # painel (padrão)
.venv\Scripts\python -m automate_accounts smoke        # valida emulador + Appium + Chrome
.venv\Scripts\python -m automate_accounts create-one   # cria 1 conta e imprime e-mail/senha
```

## Dicas e problemas comuns

- **Lento ou a sessão falha na 1ª tentativa:** pouca RAM livre. Feche o navegador e outros
  programas; a aba Saúde avisa quando a RAM está baixa.
- **Logs:** `logs/app.log` e `logs/appium.log`. Screenshots de erro em `screenshots/`.
- **Contas criadas:** `data/accounts.db` (SQLite). As senhas ficam em texto puro porque são
  contas de teste; não use este banco para contas reais.
- Mapa do cadastro e seletores: `docs/fluxo-cadastro.md`.

## Testes

```powershell
.venv\Scripts\python -m pytest              # rápidos, sem emulador (~20 s)
.venv\Scripts\python -m pytest -m live      # integração no Chrome desktop contra o site (cria contas de teste)
```

## Desenvolvimento

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m pytest
```

```
src/automate_accounts/
  config.py           configuração (config.yaml < config.local.yaml, .env)
  core/               emulador, Appium, DeviceManager (troca), orquestrador, saúde, User-Agent
  flows/              fluxo de criação de conta (Selenium, wizard em /cadastro)
  data/               gerador de dados (Faker) e repositório SQLite
  ui/                 painel Textual (app, abas, tela de execução, tema)
```
