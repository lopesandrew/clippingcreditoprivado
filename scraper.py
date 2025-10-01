import os, re, hashlib, yaml
from datetime import datetime, timedelta, timezone
from dateutil import tz, parser as dateparser
import pandas as pd
import feedparser
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Carregar variáveis de ambiente do arquivo .env se existir
def load_env():
    env_path = ".env"
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value

load_env()

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419"

def dedup_key(title, link):
    base = (title or "") + (link or "")
    return hashlib.md5(base.encode("utf-8")).hexdigest()

def calculate_similarity(text1, text2):
    """Calcula similaridade entre dois textos usando Jaccard similarity"""
    if not text1 or not text2:
        return 0.0

    # Normalizar: lowercase e remover pontuação
    import string
    text1 = text1.lower().translate(str.maketrans('', '', string.punctuation))
    text2 = text2.lower().translate(str.maketrans('', '', string.punctuation))

    # Criar conjuntos de palavras
    words1 = set(text1.split())
    words2 = set(text2.split())

    # Calcular Jaccard similarity
    intersection = words1.intersection(words2)
    union = words1.union(words2)

    if len(union) == 0:
        return 0.0

    return len(intersection) / len(union)

def remove_similar_news(df, similarity_threshold=0.7):
    """Remove notícias muito similares, mantendo apenas a primeira ocorrência"""
    if df.empty:
        return df

    to_remove = set()
    titles = df['title'].tolist()

    for i in range(len(titles)):
        if i in to_remove:
            continue
        for j in range(i + 1, len(titles)):
            if j in to_remove:
                continue
            similarity = calculate_similarity(titles[i], titles[j])
            if similarity >= similarity_threshold:
                to_remove.add(j)

    if to_remove:
        print(f"Removidas {len(to_remove)} notícias similares/duplicadas")
        df_filtered = df.drop(df.index[list(to_remove)]).reset_index(drop=True)
        return df_filtered

    return df

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

def filter_sources(df, sources_preferidas):
    """Filtra notícias apenas das fontes preferidas"""
    if not sources_preferidas:
        return df

    # Filtrar linhas onde o link contém alguma das fontes preferidas
    mask = df['link'].apply(lambda url: any(source in (url or "") for source in sources_preferidas))
    filtered_df = df[mask].copy()

    removed_count = len(df) - len(filtered_df)
    if removed_count > 0:
        print(f"Removidas {removed_count} notícias de fontes não preferidas")

    return filtered_df

def filter_blacklist(df, blacklist):
    """Remove notícias que contêm palavras da blacklist no título"""
    if not blacklist:
        return df

    # Criar padrão regex para buscar qualquer palavra da blacklist (case insensitive)
    pattern = '|'.join([r'\b' + re.escape(word) + r'\b' for word in blacklist])

    # Filtrar linhas onde o título NÃO contém palavras da blacklist
    mask = ~df['title'].str.contains(pattern, case=False, na=False, regex=True)
    filtered_df = df[mask].copy()

    removed_count = len(df) - len(filtered_df)
    if removed_count > 0:
        print(f"Removidas {removed_count} notícias pela blacklist")

    return filtered_df

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
    print("=== DEBUG EMAIL ===")
    print(f"Email enabled: {cfg.get('email', {}).get('enabled', False)}")
    
    if not cfg.get("email", {}).get("enabled", False):
        print("Email não está habilitado na configuração")
        return
    
    email_cfg = cfg["email"]
    provider = email_cfg.get("provider", "gmail").lower()
    print(f"Provider: {provider}")
    print(f"From: {email_cfg.get('from')}")
    print(f"To: {email_cfg.get('to')}")
    
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
    print(f"SMTP Config: {smtp_config}")
    
    try:
        print("Configurando mensagem...")
        # Configurar mensagem
        msg = MIMEMultipart("alternative")
        msg["From"] = email_cfg["from"]
        msg["To"] = ", ".join(email_cfg["to"])
        msg["Subject"] = subject
        print(f"Subject: {subject}")
        
        # Adicionar corpo em texto
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        
        # Adicionar corpo em HTML se fornecido
        if body_html:
            msg.attach(MIMEText(body_html, "html", "utf-8"))
        
        print("Conectando ao servidor SMTP...")
        # Conectar e enviar
        with smtplib.SMTP(smtp_config["server"], smtp_config["port"]) as server:
            print("Iniciando TLS...")
            server.starttls()
            
            # Obter senha do ambiente
            if provider == "gmail":
                password = os.getenv("GMAIL_APP_PASSWORD")
                if not password:
                    print("GMAIL_APP_PASSWORD não configurado")
                    return
            else:  # outlook/hotmail
                password = os.getenv("OUTLOOK_APP_PASSWORD")
                print(f"Password found: {'Yes' if password else 'No'}")
                if not password:
                    print("OUTLOOK_APP_PASSWORD não configurado")
                    return
            
            print("Fazendo login...")
            server.login(email_cfg["from"], password)
            print("Enviando mensagem...")
            server.send_message(msg)
            
        print(f"Email enviado com sucesso via {provider.title()}")
        
    except Exception as e:
        print(f"Erro ao enviar email: {e}")
        import traceback
        traceback.print_exc()

def build_html_email(df, today_str, tzinfo):
    """Cria template HTML profissional para o email"""

    # Agrupar notícias por query/categoria
    categories = {}
    for _, r in df.iterrows():
        query = r.get('query', 'Outras')
        if query not in categories:
            categories[query] = []
        categories[query].append(r)

    # Template HTML com design profissional
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 800px;
                margin: 0 auto;
                padding: 0;
                background-color: #ffffff;
            }}
            .container {{
                background-color: #ffffff;
                overflow: hidden;
            }}
            .header {{
                background-color: #ffffff;
                color: #1e3a8a;
                padding: 30px;
                text-align: center;
                border-bottom: 3px solid #3b82f6;
            }}
            .header h1 {{
                margin: 0;
                font-size: 28px;
                font-weight: 600;
                color: #1e3a8a;
            }}
            .header .date {{
                font-size: 14px;
                color: #64748b;
                margin-top: 8px;
            }}
            .summary {{
                background-color: #f8fafc;
                padding: 20px 30px;
                border-bottom: 2px solid #e2e8f0;
            }}
            .summary-stats {{
                display: flex;
                justify-content: space-around;
                flex-wrap: wrap;
                gap: 15px;
            }}
            .stat {{
                text-align: center;
            }}
            .stat-number {{
                font-size: 32px;
                font-weight: bold;
                color: #1e3a8a;
            }}
            .stat-label {{
                font-size: 14px;
                color: #64748b;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            .content {{
                padding: 30px;
            }}
            .category {{
                margin-bottom: 35px;
            }}
            .category-header {{
                font-size: 18px;
                font-weight: 600;
                color: #1e3a8a;
                margin-bottom: 15px;
                padding-bottom: 8px;
                border-bottom: 2px solid #3b82f6;
            }}
            .news-item {{
                margin-bottom: 20px;
                padding: 15px;
                background-color: #ffffff;
                border-left: 4px solid #3b82f6;
                border-radius: 4px;
                border: 1px solid #e2e8f0;
                transition: all 0.2s;
            }}
            .news-item:hover {{
                background-color: #f8fafc;
                border-color: #3b82f6;
            }}
            .news-title {{
                font-size: 16px;
                font-weight: 600;
                margin-bottom: 8px;
            }}
            .news-title a {{
                color: #1e3a8a;
                text-decoration: none;
            }}
            .news-title a:hover {{
                color: #3b82f6;
                text-decoration: underline;
            }}
            .news-meta {{
                font-size: 13px;
                color: #64748b;
                display: flex;
                gap: 15px;
                flex-wrap: wrap;
            }}
            .news-meta span {{
                display: inline-flex;
                align-items: center;
            }}
            .source {{
                color: #0ea5e9;
                font-weight: 500;
            }}
            .time {{
                color: #64748b;
            }}
            .footer {{
                background-color: #f8fafc;
                padding: 20px 30px;
                text-align: center;
                font-size: 12px;
                color: #64748b;
                border-top: 2px solid #e2e8f0;
            }}
            @media only screen and (max-width: 600px) {{
                body {{
                    padding: 10px;
                }}
                .header {{
                    padding: 20px;
                }}
                .header h1 {{
                    font-size: 22px;
                }}
                .content {{
                    padding: 20px;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 Clipping Crédito Privado</h1>
                <div class="date">{datetime.strptime(today_str, '%Y-%m-%d').strftime('%d de %B de %Y')}</div>
            </div>

            <div class="content">
    """

    # Mapear queries para nomes amigáveis
    category_names = {
        'debêntures OR "debenture incentivada" OR "lei 12.431"': '💼 Debêntures',
        'CRA OR "certificado de recebíveis do agronegócio"': '🌾 CRA - Recebíveis do Agronegócio',
        'CRI OR "certificado de recebíveis imobiliários"': '🏢 CRI - Recebíveis Imobiliários',
        'FIDC OR "fundo de investimento em direitos creditórios"': '📈 FIDC - Fundos de Direitos Creditórios',
        'securitização OR "direitos creditórios" OR cessão crédito': '🔄 Securitização e Cessão de Crédito',
        '"letra financeira" OR LF OR LCA OR LCI': '📝 Letras Financeiras (LF, LCA, LCI)',
        '"nota comercial" OR "commercial paper"': '📄 Notas Comerciais',
        '"cédula de crédito bancário" OR CCB': '🏦 Cédulas de Crédito Bancário',
        'CDCA OR "cédula de produto rural" OR CPR': '🌾 Cédulas Rurais (CDCA, CPR)',
        '"mercado de capitais" OR DCM OR "debt capital markets"': '💹 Mercado de Capitais',
        '"oferta pública" OR IPO OR follow-on OR "emissão primária"': '🚀 Ofertas Públicas e IPOs',
        '"CVM 400" OR "CVM 476" OR "oferta restrita"': '📋 Ofertas Reguladas CVM',
        'ANBIMA OR "código ANBIMA" OR "agente fiduciário"': '📊 ANBIMA e Agentes Fiduciários',
        '"rating de crédito" OR Fitch OR Moodys OR "S&P"': '⭐ Ratings de Crédito',
        '(underwriting OR coordenador OR bookbuilding) AND (debêntures OR bonds OR ações OR "oferta pública" OR emissão)': '🤝 Underwriting e Coordenação',
        '"mercado primário" OR "mercado secundário" bonds': '💱 Mercado Primário e Secundário',
        '"mercado internacional" bonds OR dívida': '🌎 Mercado Internacional de Dívida',
        'eurobonds OR "bonds internacionais" OR "dívida externa"': '🌐 Eurobonds e Dívida Externa',
        '"treasury bonds" OR "corporate bonds" internacional': '💵 Bonds Corporativos Internacionais',
        '"high yield" OR "investment grade" internacional': '📊 High Yield e Investment Grade',
        '"spreads de crédito" OR "credit spreads" internacional': '📈 Spreads de Crédito Internacional',
        '"fed" OR "federal reserve" taxa juros': '🏦 Federal Reserve',
        '"banco central europeu" OR BCE taxa': '🇪🇺 Banco Central Europeu',
        'inflação OR IPCA OR IGP-M economia': '📊 Inflação',
        'PIB OR "produto interno bruto" crescimento': '📈 PIB e Crescimento',
        '"taxa Selic" OR "taxa de juros" Copom': '💰 Taxa Selic e Copom',
        'câmbio OR dólar OR "taxa de câmbio" economia': '💵 Câmbio e Dólar',
        'déficit OR superávit fiscal OR "resultado primário"': '🏛️ Contas Públicas',
        'balança comercial OR exportação OR importação': '📦 Balança Comercial',
        'desemprego OR "mercado de trabalho" OR emprego economia': '👔 Mercado de Trabalho',
        'IBC-Br OR "atividade econômica" OR "indicadores econômicos"': '📊 Indicadores Econômicos',
        '"CVM 175" OR "ICVM 160" OR "ICVM 158" OR "CVM 88"': '⚖️ Instruções CVM',
        'CVM regulação OR "Comissão de Valores Mobiliários"': '⚖️ Regulação CVM',
        '"Banco Central" crédito OR "resolução CMN" OR "circular BACEN"': '🏛️ Banco Central e CMN',
        '"Conselho Monetário Nacional" OR CMN resolução': '🏛️ Conselho Monetário Nacional',
        'Basileia OR "acordo de capital" OR "índice de Basileia"': '🌍 Acordos de Basileia',
        'concessão OR "leilão de concessão" OR PPP OR "parceria público-privada"': '🛣️ Concessões e PPPs',
        '"project finance" OR "financiamento de projetos"': '🏗️ Project Finance',
        'BNDES OR "banco de desenvolvimento" financiamento': '🏦 BNDES e Bancos de Desenvolvimento',
        '"debênture de infraestrutura" OR "lei 12.431"': '🏗️ Debêntures de Infraestrutura',
        'rodovia OR ferrovia OR aeroporto OR porto concessão': '🚄 Transporte e Logística',
        'saneamento OR energia OR telecomunicações concessão': '⚡ Utilities e Telecomunicações',
        '"emissão de debêntures" OR "programa de debêntures"': '📊 Emissões de Debêntures',
        'reestruturação dívida OR refinanciamento OR amortização': '🔧 Reestruturação de Dívidas',
        '"disclosure" OR "fato relevante" CVM': '📢 Fatos Relevantes',
        'default OR inadimplência OR "covenant breach"': '⚠️ Defaults e Inadimplência',
        '"assembléia de debenturistas" OR AGD': '🗳️ Assembleias de Debenturistas',
        'rebaixamento rating OR upgrade rating': '📈 Mudanças de Rating',
        '"agronegócio" financiamento OR crédito rural': '🌱 Financiamento do Agronegócio',
        '"setor elétrico" OR "energia renovável" financiamento': '⚡ Financiamento de Energia',
        '"real estate" OR "incorporação imobiliária" CRI': '🏘️ Real Estate e Incorporação',
        'petróleo OR "óleo e gás" financiamento': '🛢️ Petróleo e Gás',
        '"fundo de investimento" OR "gestor de recursos" debêntures': '💼 Fundos de Investimento',
        '"investidor institucional" OR "investidor qualificado"': '🏢 Investidores Institucionais',
        'tesouraria OR "gestão de caixa" OR liquidez empresas': '💰 Tesouraria e Liquidez',
    }

    # Adicionar notícias por categoria
    for query, items in categories.items():
        category_name = category_names.get(query, '📰 ' + query[:50])

        html += f'<div class="category">'
        html += f'<div class="category-header">{category_name}</div>'

        for item in items:
            when = item["published_at"].astimezone(tzinfo).strftime("%d/%m às %H:%M")
            source = item.get('source', 'Fonte desconhecida')

            html += f'''
                <div class="news-item">
                    <div class="news-title">
                        <a href="{item['link']}" target="_blank">{item['title']}</a>
                    </div>
                    <div class="news-meta">
                        <span class="source">📰 {source}</span>
                        <span class="time">🕐 {when}</span>
                    </div>
                </div>
            '''

        html += '</div>'

    html += """
            </div>

            <div class="footer">
                <p>📧 Este é um clipping automático de notícias sobre crédito privado</p>
                <p style="margin-top: 10px;">Gerado automaticamente • BCP Securities</p>
            </div>
        </div>
    </body>
    </html>
    """

    return html

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

    # Filtrar apenas fontes preferidas (se configurado)
    if cfg.get("filter_only_preferred_sources", False):
        df = filter_sources(df, cfg.get("sources_preferidas", []))
        if df.empty:
            print("Sem novidades das fontes preferidas.")
            return

    # Aplicar filtro de blacklist
    df = filter_blacklist(df, cfg.get("blacklist", []))

    if df.empty:
        print("Sem novidades após aplicar filtros.")
        return

    # Remover notícias similares/duplicadas
    df = remove_similar_news(df, similarity_threshold=0.7)

    if df.empty:
        print("Sem novidades após remover duplicatas.")
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
        subject = f"{subject_prefix} {datetime.strptime(today_str, '%Y-%m-%d').strftime('%d/%m/%Y')} - {len(df)} notícias"

        # Corpo do email em texto (fallback)
        email_body = f"Clipping de {today_str}\n"
        email_body += f"Total: {len(df)} notícias\n\n"

        for _, r in df.iterrows():
            when = r["published_at"].astimezone(tzinfo).strftime("%d/%m %H:%M")
            src = f" — {r['source']}" if r.get("source") else ""
            email_body += f"• {r['title']}{src} ({when})\n"
            email_body += f"  {r['link']}\n\n"

        # Gerar HTML profissional
        html_body = build_html_email(df, today_str, tzinfo)

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
