# spotify_app — interface web local do Offtape

Servidor Flask que roda **só na sua máquina** (http://127.0.0.1:8888). Faz o
login no Spotify, lista suas playlists, gera o `tracks.json`, baixa os MP3 e
copia para o pen drive, tudo por botões.

## Rodar

Ative o ambiente virtual e rode o app de dentro desta pasta:

```bash
source ../.venv/bin/activate      # macOS / Linux
..\.venv\Scripts\Activate.ps1     # Windows (PowerShell)
python app.py
```

Antes da primeira vez, crie seu app no Spotify e o `config.json`, seguindo o
passo 3 do **[guia de uso](../docs/GUIA_DE_USO.md#3-criando-o-app-no-spotify)**.
Resumo:

- Redirect URI no Dashboard: `http://127.0.0.1:8888/callback`
- `cp config.example.json config.json` e cole o seu Client ID (não precisa do secret)
- Alternativa: `export SPOTIFY_CLIENT_ID=...`

## Arquivos locais (não versionados)

| Arquivo | O que é |
|---|---|
| `config.json` | seu Client ID |
| `history.db` | histórico das gerações (SQLite) |
| `.flask_secret` | chave que assina o cookie de sessão (criada com permissão 600) |

Todos estão no `.gitignore`.

## Para desenvolvedores

A arquitetura, o modelo de segurança e a tabela de endpoints estão documentados
na docstring do topo do `app.py`. O front-end é uma página única embutida no
próprio `app.py` (constante `PAGE`) e conversa apenas com os endpoints `/api/*`.
