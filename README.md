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

Valida a infraestrutura (sobe o emulador e o Appium, abre a página de login no Chrome
do emulador e salva `screenshots/smoke.png`):

```powershell
python -m automate_accounts smoke
```

Cria uma conta de teste de ponta a ponta (imprime e-mail e senha):

```powershell
python -m automate_accounts create-one
```

O mapeamento do cadastro está em `docs/fluxo-cadastro.md`.

## Status

Em construção. Pronto: configuração, logging, emulador, Appium, sessão mobile, smoke test,
gerador de dados e fluxo de criação de conta.
Próximos passos: SQLite, orquestrador (fila, retries) e painel Textual.
