# Deploy — Share Your HTML

Stack: Flask + PostgreSQL, tudo no Railway. Sem dependências externas.

---

## 1. Subir no GitHub

Na pasta `share_your_html`, abra o terminal:

```bash
git init
git add .
git commit -m "feat: share your html"
git remote add origin https://github.com/SEU_USUARIO/share-your-html.git
git push -u origin main
```

---

## 2. Criar projeto no Railway

1. Acesse [railway.app](https://railway.app)
2. **New Project → Deploy from GitHub repo**
3. Selecione o repositório `share-your-html`
4. Railway detecta Python automaticamente via `Procfile`

---

## 3. Adicionar PostgreSQL

1. No projeto Railway, clique em **+ New**
2. **Database → Add PostgreSQL**
3. Aguarde provisionar (~1 min)

---

## 4. Configurar variáveis de ambiente

No serviço do app Flask → aba **Variables**, clique em **+ New Variable**:

| Variável | Valor |
|----------|-------|
| `DATABASE_URL` | Clique em "Add Reference" → selecione `DATABASE_URL` do PostgreSQL |
| `SECRET_KEY` | Qualquer string aleatória longa, ex: `sharehtml-opus-2026-xkq9` |
| `ADMIN_PASSWORD` | `Opus123!` |

> **Dica:** O Railway injeta `DATABASE_URL` automaticamente quando você usa "Add Reference" — não precisa copiar e colar manualmente.

---

## 5. Inicializar o banco (só na primeira vez)

Após o primeiro deploy com sucesso:

1. Serviço Flask → aba **Settings** → **Deploy → Railway Shell** (ou clique em "Open Terminal")
2. Execute:
```bash
python -c "from app import init_db; init_db(); print('Banco criado!')"
```

---

## 6. Domínio

### Domínio automático (gratuito)
- Serviço Flask → **Settings → Networking → Generate Domain**
- Gera algo como: `share-your-html.up.railway.app`

### Domínio próprio
1. **Settings → Networking → Custom Domain**
2. Digite seu domínio, ex: `share.seudominio.com.br`
3. Railway mostra um CNAME para apontar no seu DNS
4. No seu provedor de DNS:
   - Type: `CNAME`
   - Name: `share`
   - Value: o endereço que o Railway mostrou
5. Aguarde propagação (5 min no Cloudflare, até 24h em outros)

---

## Resumo (10 minutos)

```
1. git push → GitHub
2. Railway → New Project do GitHub
3. Railway → + PostgreSQL
4. Railway → 3 variáveis de ambiente (DATABASE_URL, SECRET_KEY, ADMIN_PASSWORD)
5. Railway Shell → python -c "from app import init_db; init_db()"
6. Railway → Generate Domain (ou Custom Domain)
```
