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

## Status

Em construção. Ver o histórico de commits para o andamento.
