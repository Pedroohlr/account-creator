# account-creator

Ferramenta de terminal (Python) que cria contas em ambiente de homologação usando o
Chrome de um emulador Android (AVD do Android Studio), controlado via Appium.

## Pré-requisitos

- Python 3.11+
- Android Studio com SDK e um AVD (imagem Google APIs)
- Node.js e Appium 2+/3 com o driver UiAutomator2:
  `npm i -g appium` e `appium driver install uiautomator2`

## Instalação

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
copy .env.example .env
```

Edite `.env` com o nome do seu AVD e ajuste `config.yaml`.

## Uso

**Jeito fácil:** dê duplo clique em `iniciar.bat` (ou rode `iniciar.bat` no terminal).
Na primeira vez ele cria o ambiente e o `.env` sozinho. Abre o menu:

```
1  Criar 1 conta
2  Criar várias contas
3  Testar infraestrutura (emulador + Appium)
4  Ver contas criadas
5  Sair
```

Teclas: `1`-`5` escolhem direto, setas + Enter navegam, `S` para a execução em andamento,
`Esc` volta. As contas criadas ficam em `data/accounts.db` (SQLite).

**Linha de comando** (sem menu):

```powershell
.venv\Scripts\python -m automate_accounts smoke        # valida a infraestrutura
.venv\Scripts\python -m automate_accounts create-one   # cria 1 conta e imprime e-mail/senha
```

O mapeamento do cadastro está em `docs/fluxo-cadastro.md`.

## Status

Funcional: menu, criação de contas em fila com retries, registro em SQLite e parada com `S`.
