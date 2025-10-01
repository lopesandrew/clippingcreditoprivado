# 📊 Clipping Crédito Privado

Sistema automatizado de coleta e curadoria de notícias sobre crédito privado, mercado de capitais, macroeconomia e mercado internacional. Desenvolvido para BCP Securities.

## 🚀 Funcionalidades

### 📰 Coleta Inteligente
- **50+ queries** organizadas por categorias:
  - 💼 Instrumentos de Crédito Privado (Debêntures, CRI, CRA, FIDC, etc)
  - 💹 Mercado de Capitais (Ofertas públicas, IPOs, Ratings)
  - 🌎 Mercado Internacional (Bonds, Eurobonds, High Yield)
  - 📊 Macroeconomia (Inflação, PIB, Selic, Câmbio)
  - ⚖️ Regulação e Supervisão (CVM, Banco Central, CMN)
  - 🏗️ Infraestrutura e Concessões (PPP, Project Finance)
  - 🏦 BNDES e Bancos de Desenvolvimento

### 🎯 Filtros Avançados
- **Blacklist**: Remove automaticamente notícias sobre acidentes, crimes e outros tópicos irrelevantes
- **Detecção de duplicatas**: Algoritmo de similaridade Jaccard (70%) remove notícias repetidas
- **Priorização de fontes**: Ranking de fontes preferenciais (Valor, Bloomberg, Reuters, etc)
- **Filtro opcional**: Opção de restringir apenas a fontes preferidas

### 📧 Email Profissional
- Template HTML responsivo e moderno
- Organização por categorias com ícones
- Fundo branco limpo e professional
- Compatível com todos os clientes de email
- Suporte a Gmail, Outlook e Hotmail

### 📱 Telegram (Opcional)
- Envio formatado em Markdown
- Links clicáveis
- Preview de fontes desabilitado

### 💾 Exportação
- CSV para análise de dados
- Markdown para documentação
- Arquivos datados em `output/`

## ⚙️ Configuração

### 1. Instalar Dependências
```bash
pip install -r requirements.txt
```

### 2. Configurar Email (Gmail)

Crie um arquivo `.env` na raiz do projeto:
```bash
GMAIL_APP_PASSWORD=sua_senha_de_app_aqui
```

**Como obter senha de aplicativo do Gmail:**
1. Acesse https://myaccount.google.com/security
2. Ative a verificação em duas etapas
3. Vá em "Senhas de app"
4. Gere uma senha para "Email"

### 3. Editar config.yaml

```yaml
timezone: "America/Sao_Paulo"
lookback_hours: 30  # Janela de busca em horas

# Email
email:
  enabled: true
  provider: "gmail"  # gmail, outlook, hotmail
  from: "seu_email@gmail.com"
  to: ["destinatario@empresa.com"]
  subject_prefix: "[Clipping Crédito Privado]"

# Filtros
filter_only_preferred_sources: false  # true = apenas fontes da lista
blacklist:
  - "acidente"
  - "crime"
  # adicione mais palavras conforme necessário
```

## 🏃 Executar

### Localmente
```bash
python scraper.py
```

### GitHub Actions (Agendado)
O workflow roda automaticamente:
- **Horário**: 07:00 BRT (dias úteis)
- **Configuração**: `.github/workflows/scraper.yml`
- **Secrets necessários**:
  - `GMAIL_APP_PASSWORD`
  - `TELEGRAM_BOT_TOKEN` (opcional)
  - `TELEGRAM_CHAT_ID` (opcional)

## 📁 Estrutura de Arquivos

```
clippingcreditoprivado/
├── scraper.py              # Script principal
├── config.yaml             # Configurações e queries
├── .env                    # Credenciais (não commitar!)
├── requirements.txt        # Dependências Python
├── output/                 # Arquivos gerados
│   ├── clipping_2025-01-10.csv
│   └── clipping_2025-01-10.md
└── README.md
```

## 🔧 Customização

### Adicionar Novas Queries
Edite `config.yaml` na seção `queries`:
```yaml
queries:
  - '"sua query" OR termo alternativo'
```

### Adicionar Fontes Preferidas
```yaml
sources_preferidas:
  - "seu_site.com.br"
```

### Ajustar Blacklist
```yaml
blacklist:
  - "palavra_indesejada"
```

### Alterar Threshold de Duplicatas
Em `scraper.py`, linha 570:
```python
df = remove_similar_news(df, similarity_threshold=0.7)  # 0.7 = 70%
```

## 📊 Estatísticas Típicas

- **Notícias coletadas**: 200-300 por execução
- **Duplicatas removidas**: 5-10 (2-4%)
- **Blacklist**: 1-5 notícias filtradas
- **Fontes únicas**: 50-80 por dia
- **Tempo de execução**: ~30 segundos

## 🌟 Recursos Técnicos

- **Deduplicação**: Hash MD5 de título + link
- **Similaridade**: Jaccard Index para textos
- **Priorização**: Score baseado em ordem de fontes
- **Timezone-aware**: Conversão automática para BRT
- **Regex avançado**: Filtros case-insensitive com word boundaries

## 📝 Licença

Uso interno BCP Securities.

## 🤝 Suporte

Para dúvidas ou sugestões, entre em contato com a equipe de tecnologia.

---

**Última atualização**: Outubro 2025
**Desenvolvido com**: Python 3.13 + Claude Code
