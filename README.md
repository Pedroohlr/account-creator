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
| Painel | F1 | Totais, taxa de sucesso, tempo médio por conta, estado da saúde e contas recentes |
| Nova execução | F2 | Quantidade de contas, contas por dispositivo, wipe, User-Agent, headless e **estimativa de tempo** |
| Contas | F3 | Lista com busca por e-mail, filtro por status e **exportação para CSV** (`exports/`) |
| Saúde | F4 | Verifica SDK, AVD, aceleração, Java, Node, Appium, driver, RAM, site e banco |
| Configurações | F5 | Edita e salva as configurações (`Ctrl+S`); salva em `config.local.yaml` |

Durante uma execução a tela mostra criadas/falhas, **dispositivo atual (ex.: 2 / 4)**, tempo
decorrido, média por conta, tempo restante, a tabela de contas e o log. `S` para a execução
(depois da conta atual) e `Esc` volta ao painel.

## Troca de dispositivo

A cada `per_device` contas (padrão **5**) o orquestrador:

1. fecha a sessão do Chrome;
2. desliga o emulador;
3. liga de novo com `-wipe-data` (dados zerados, como um aparelho novo);
4. abre uma sessão nova (com User-Agent aleatório, se ativado).

O Appium continua ligado durante a troca. Se 3 contas seguidas falharem, a troca acontece
sozinha (recuperação); se mesmo assim falhar de novo, a execução é interrompida com aviso.

> A troca muda os dados do aparelho e do navegador. **Não muda o endereço IP** (o emulador usa a
> internet do seu PC).

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
