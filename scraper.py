import os, re, hashlib, yaml
from datetime import datetime, timedelta, timezone
from dateutil import tz, parser as dateparser
import pandas as pd
import feedparser
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419"

def dedup_key(title, link):
    base = (title or "") + (link or "")
    return hashlib.md5(base.encode("utf-8")).hexdigest()

def build_query(q):
    return q.replace(" ", "+").replace('"', '%22')

def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def parse_time(entry, fallback_tz):
    if "published" in entry:
        try:
            dt = dateparser.parse(entry.published)
        except Exception:
            dt = datetime.now(timezone.utc)
    elif "updated" in entry:
        dt = dateparser.parse(entry.updated)
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(fallback_tz)

def fetch_items(queries, tzinfo):
    items = []
    for q in queries:
        url = GOOGLE_NEWS_RSS.format(query=build_query(q))
        feed = feedparser.parse(url)
        for e in feed.entries:
            published = parse_time(e, tzinfo)
            link = getattr(e, "link", "")
            title = getattr(e, "title", "")
            source = getattr(e, "source", {}).get("title", "") if hasattr(e, "source") else ""
            items.append({
                "title": title,
                "link": link,
                "source": source,
                "published_at": published.isoformat(),
                "query": q
            })
    return items

def prioritize(df, prefer_list):
    if not prefer_list:
        return df
    def score(url):
        for i, dom in enumerate(prefer_list):
            if dom in (url or ""):
                return 100 - i
        return 0
    df["priority"] = df["link"].apply(score)
    return df.sort_values(["priority", "published_at"], ascending=[False, False]).drop(columns=["priority"])

def send_email(cfg, subject, body_text, body_html=None):
    """Envia email via SMTP (Gmail, Outlook, etc.)"""
    if not cfg.get("email", {}).get("enabled", False):
        return
    
    email_cfg = cfg["email"]
    provider = email_cfg.get("provider", "gmail").lower()
    
    # Configurações SMTP por provedor
    smtp_configs = {
        "gmail": {"server": "smtp.gmail.com", "port": 587},
        "outlook": {"server": "smtp-mail.outlook.com", "port": 587},
        "hotmail": {"server": "smtp-mail.outlook.com", "port": 587}
    }
    
    if provider not in smtp_configs:
        print(f"Provedor '{provider}' não suportado. Use: gmail, outlook, hotmail")
        return
    
    smtp_config = smtp_configs[provider]
    
    try:
        # Configurar mensagem
        msg = MIMEMultipart("alternative")
        msg["From"] = email_cfg["from"]
        msg["To"] = ", ".join(email_cfg["to"])
        msg["Subject"] = subject
        
        # Adicionar corpo em texto
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        
        # Adicionar corpo em HTML se fornecido
        if body_html:
            msg.attach(MIMEText(body_html, "html", "utf-8"))
        
        # Conectar e enviar
        with smtplib.SMTP(smtp_config["server"], smtp_config["port"]) as server:
            server.starttls()
            
            # Obter senha do ambiente
            if provider == "gmail":
                password = os.getenv("GMAIL_APP_PASSWORD")
                if not password:
                    print("GMAIL_APP_PASSWORD não configurado")
                    return
            else:  # outlook/hotmail
                password = os.getenv("OUTLOOK_APP_PASSWORD")
                if not password:
                    print("OUTLOOK_APP_PASSWORD não configurado")
                    return
            
            server.login(email_cfg["from"], password)
            server.send_message(msg)
            
        print(f"Email enviado com sucesso via {provider.title()}")
        
    except Exception as e:
        print(f"Erro ao enviar email: {e}")

def send_telegram(cfg, message):
    """Envia mensagem via Telegram"""
    if not cfg.get("telegram", {}).get("enabled", False):
        return
    
    try:
        import requests
        
        tg_cfg = cfg["telegram"]
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or tg_cfg.get("bot_token")
        chat_id = os.getenv("TELEGRAM_CHAT_ID") or tg_cfg.get("chat_id")
        
        if not bot_token or not chat_id:
            print("Token do bot ou chat_id do Telegram não configurados")
            return
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        
        response = requests.post(url, data=data)
        if response.status_code == 200:
            print("Mensagem enviada via Telegram")
        else:
            print(f"Erro ao enviar Telegram: {response.text}")
            
    except Exception as e:
        print(f"Erro ao enviar Telegram: {e}")

def main():
    cfg = load_config()
    tzinfo = tz.gettz(cfg.get("timezone", "America/Sao_Paulo"))
    lookback_hours = int(cfg.get("lookback_hours", 30))
    since_dt = datetime.now(tzinfo) - timedelta(hours=lookback_hours)

    raw = fetch_items(cfg["queries"], tzinfo)
    if not raw:
        print("Sem itens.")
        return

    df = pd.DataFrame(raw)
    df["published_at"] = pd.to_datetime(df["published_at"])
    df = df[df["published_at"] >= since_dt].copy()
    df["dedup"] = df.apply(lambda r: dedup_key(r["title"], r["link"]), axis=1)
    df = df.drop_duplicates(subset=["dedup"]).drop(columns=["dedup"])

    if df.empty:
        print("Sem novidades nas últimas horas.")
        return

    df = prioritize(df, cfg.get("sources_preferidas", []))

    outdir = cfg.get("output_dir", "output")
    os.makedirs(outdir, exist_ok=True)
    today_str = datetime.now(tzinfo).strftime("%Y-%m-%d")
    csv_path = os.path.join(outdir, f"clipping_{today_str}.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8")

    md_lines = [f"# Clipping — {today_str}\n"]
    for _, r in df.iterrows():
        when = r["published_at"].astimezone(tzinfo).strftime("%d/%m %H:%M")
        src = f" — *{r['source']}*" if r.get("source") else ""
        md_lines.append(f"- **{r['title']}**{src} ({when})\n  {r['link']}")
    md = "\n".join(md_lines)
    md_path = os.path.join(outdir, f"clipping_{today_str}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"Salvo: {csv_path} e {md_path}")
    
    # Enviar por email se configurado
    if cfg.get("email", {}).get("enabled", False):
        subject_prefix = cfg["email"].get("subject_prefix", "[Clipping]")
        subject = f"{subject_prefix} {today_str} - {len(df)} notícias"
        
        # Corpo do email em texto
        email_body = f"Clipping de {today_str}\n"
        email_body += f"Total: {len(df)} notícias\n\n"
        
        for _, r in df.iterrows():
            when = r["published_at"].astimezone(tzinfo).strftime("%d/%m %H:%M")
            src = f" — {r['source']}" if r.get("source") else ""
            email_body += f"• {r['title']}{src} ({when})\n"
            email_body += f"  {r['link']}\n\n"
        
        # Corpo HTML (opcional, mais bonito)
        html_body = f"""
        <h2>Clipping de {today_str}</h2>
        <p><strong>Total:</strong> {len(df)} notícias</p>
        <ul>
        """
        
        for _, r in df.iterrows():
            when = r["published_at"].astimezone(tzinfo).strftime("%d/%m %H:%M")
            src = f" — <em>{r['source']}</em>" if r.get("source") else ""
            html_body += f"""
            <li>
                <strong><a href="{r['link']}">{r['title']}</a></strong>{src} ({when})
            </li>
            """
        
        html_body += "</ul>"
        
        send_email(cfg, subject, email_body, html_body)
    
    # Enviar por Telegram se configurado
    if cfg.get("telegram", {}).get("enabled", False):
        tg_message = f"*Clipping {today_str}*\n"
        tg_message += f"Total: {len(df)} notícias\n\n"
        
        for _, r in df.iterrows():
            when = r["published_at"].astimezone(tzinfo).strftime("%d/%m %H:%M")
            src = f" — _{r['source']}_" if r.get("source") else ""
            # Escapar caracteres especiais do Markdown
            title = r['title'].replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace(']', '\\]')
            tg_message += f"• *{title}*{src} ({when})\n"
            tg_message += f"  {r['link']}\n\n"
        
        send_telegram(cfg, tg_message)

if __name__ == "__main__":
    main()
