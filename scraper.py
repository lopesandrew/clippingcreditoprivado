import os, re, hashlib, yaml
from datetime import datetime, timedelta, timezone
from dateutil import tz, parser as dateparser
import pandas as pd
import feedparser

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

if __name__ == "__main__":
    main()
