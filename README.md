# Clipping Diário de Crédito (Brasil)

Script que coleta notícias via Google News RSS sobre crédito privado e mercado de capitais, salva CSV/Markdown e (opcionalmente) envia por e-mail e/ou Telegram. Agendado com GitHub Actions.

## Como usar
1. Edite `config.yaml` (queries, fontes preferidas, e-mail/Telegram).
2. (Opcional) Configure *secrets* no repositório:
   - `GMAIL_APP_PASSWORD`: senha de aplicativo do Gmail para envio.
   - `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` (se usar Telegram).
3. O workflow diário roda em dias úteis às 07:00 BRT.
4. Saídas ficam em `output/` como `clipping_YYYY-MM-DD.csv` e `.md`.

## Rodar local
```bash
pip install -r requirements.txt
python scraper.py
```

## Observações
- Respeita termos de uso (RSS), sem burlar paywalls.
- Dedup e janela de horas configuráveis.
- Fácil adicionar novas queries (ex.: empresas-alvo, termos regulatórios).
