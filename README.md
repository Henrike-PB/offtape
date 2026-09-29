# 📼 Offtape

**Sua playlist, offline.** O Offtape pega uma playlist sua do Spotify, encontra
cada música no YouTube (dando preferência ao *official audio*), baixa como MP3
e copia para um pen drive, organizada e na ordem certa, pronta para tocar no carro.

Tudo roda **localmente, na sua máquina**, e dá para usar só clicando, pela
interface web local.

```
Spotify ──► tracks.json ──► YouTube (melhor versão) ──► MP3 ──► pen drive
 (login)     (lista de       (pontuação: official        (320 kbps,   (pasta por
             faixas)          audio, duração…)            com tags)    playlist)
```

> ⚠️ **Uso pessoal.** O Offtape é para montar a *sua* biblioteca offline.
> Respeite os direitos autorais e os termos de uso do YouTube e do Spotify no
> seu país. O projeto não é afiliado ao Spotify nem ao YouTube.

---

## Índice

- [Recursos](#recursos)
- [Requisitos](#requisitos)
- [Instalação (uma vez só)](#instalação-uma-vez-só)
- [Uso rápido](#uso-rápido)
- [Uso pelo terminal (opcional)](#uso-pelo-terminal-opcional)
- [Como a melhor versão é escolhida](#como-a-melhor-versão-é-escolhida)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Segurança e privacidade](#segurança-e-privacidade)
- [Problemas comuns](#problemas-comuns)
- [Contribuindo](#contribuindo)

O passo a passo detalhado, com dicas para o carro, está em
**[docs/GUIA_DE_USO.md](docs/GUIA_DE_USO.md)**.

---

## Recursos

- **Login com o Spotify** (OAuth + PKCE, sem *client secret*) e lista das suas
  playlists, com busca, filtro "Minhas" e pré-visualização paginada das faixas.
- **Gerar tracks.json** com um clique, salvo por data e nome, com histórico em SQLite.
- **Baixar MP3** direto pela interface: 3 downloads em paralelo, progresso ao
  vivo, *fallback* automático quando um vídeo está indisponível ou tem restrição
  de idade, e tags ID3 (título/artista).
- **Idempotente**: rodar de novo pula o que já foi baixado. Dá para interromper
  e continuar depois.
- **→ Pen drive**: copia a playlist para o pen drive em uma pasta com nome
  amigável (sem acentos, compatível com FAT32 e com o som do carro).
- **Relatórios CSV** de cada execução e um **notebook** para explorar
  resultados e falhas.
- **Modo terminal (CLI)** para quem prefere, com `--dry-run`, faixas
  específicas, bitrate etc.

## Requisitos

| O quê | Versão | Para quê |
|---|---|---|
| Python | 3.9+ | rodar o projeto |
| [ffmpeg](https://ffmpeg.org/) | qualquer recente | converter o áudio em MP3 |
| Conta no Spotify | grátis ou Premium | ler suas playlists |
| App no [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) | grátis | obter o *Client ID* |

Funciona em **macOS, Linux e Windows**. O pen drive é detectado automaticamente
em cada sistema: `/Volumes` no macOS, `/media`, `/run/media` ou `/mnt` no Linux,
e drives removíveis no Windows. O disco do sistema nunca aparece na lista.

## Instalação (uma vez só)

**1) Baixe o projeto e entre na pasta:**

```bash
git clone <url-do-repositorio> offtape
cd offtape
```

**2) Instale o ffmpeg:**

| Sistema | Comando |
|---|---|
| macOS | `brew install ffmpeg` (Homebrew: https://brew.sh) |
| Windows | `winget install Gyan.FFmpeg`, depois feche e abra o terminal |
| Linux (Debian/Ubuntu) | `sudo apt install ffmpeg` (Fedora: `sudo dnf install ffmpeg` · Arch: `sudo pacman -S ffmpeg`) |

**3) Crie o ambiente virtual e instale as dependências:**

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> No Windows, se o PowerShell bloquear o `Activate.ps1`, rode uma vez
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, ou use o Prompt de
> Comando com `.venv\Scripts\activate.bat`.

**4) Crie seu app no Spotify** (2 minutos, grátis):

1. Acesse https://developer.spotify.com/dashboard e clique em **Create app**.
2. Em **Redirect URIs**, cadastre **exatamente** `http://127.0.0.1:8888/callback`
   (o Spotify não aceita `localhost`; tem que ser `127.0.0.1`).
3. Em *APIs used*, marque **Web API** e salve.
4. Em **Settings**, copie o **Client ID**. O *Client Secret* **não** é necessário.
5. Enquanto o app estiver em *Development mode*, só entram as contas cadastradas
   em **User Management**. Adicione ali a sua conta e a de quem mais for usar.

**5) Informe o Client ID ao Offtape:**

Copie `spotify_app/config.example.json` para `spotify_app/config.json` e cole
seu Client ID no lugar do texto de exemplo:

```bash
cp spotify_app/config.example.json spotify_app/config.json      # macOS / Linux
copy spotify_app\config.example.json spotify_app\config.json    # Windows
```

(Alternativa: definir a variável de ambiente `SPOTIFY_CLIENT_ID` antes de rodar.)

## Uso rápido

Com o ambiente virtual ativo (veja o passo 3 da instalação):

```bash
cd spotify_app
python app.py
```

Abra **http://127.0.0.1:8888** e:

1. **Conectar com Spotify** → autorize.
2. Encontre a playlist (use a busca) → **Ver faixas** para conferir, depois **Gerar**.
3. Abra **Histórico de gerações** → **Baixar MP3**. Deixe o app rodando até terminar.
4. Plugue o pen drive → escolha-o no seletor **Pen drive** (clique em *atualizar*
   se não aparecer) → **→ Pen drive**.

Os MP3 ficam em `exported-musics/<playlist>/` e os relatórios em `relatorios/`.
Para parar o app, use `Ctrl+C` no terminal.

Configuração opcional por variável de ambiente: `SPOTIFY_CLIENT_ID` (em vez do
`config.json`) e `DOWNLOAD_WORKERS` (downloads simultâneos, padrão `3`).

## Uso pelo terminal (opcional)

O app é o caminho recomendado, mas tudo também funciona via linha de comando.

```bash
# 1) Monte o tracks.json — escolha UMA opção (cada uma substitui o arquivo):
cp tracks.example.json tracks.json            # A) exemplo pronto, edite à mão (Windows: copy)
python make_tracks.py minha_playlist.csv      # B) CSV exportado do https://exportify.net
python make_tracks.py lista.txt               # C) uma faixa por linha: "Artista - Título"

# 2) Baixe
python download_playlist.py --dry-run         # só mostra o que escolheria
python download_playlist.py                   # baixa tudo do tracks.json
python download_playlist.py --tracks tracks_json/2026-01-01_minha-playlist.json
```

| Opção | O que faz |
|---|---|
| `--tracks ARQ` | usa outro tracks.json |
| `--start N --end M` | baixa só as faixas N a M |
| `--dry-run` | mostra os vídeos escolhidos sem baixar |
| `--bitrate 192` | qualidade do MP3 (padrão 320 kbps) |
| `--batch-size 10 --batch-pause 30` | tamanho do lote e pausa entre lotes |
| `--out PASTA` / `--reports-dir PASTA` | muda as pastas de saída |
| `--cookies-from-browser chrome` | usa seu login do navegador em vídeos com restrição de idade |

Formato do `tracks.json` (a duração em segundos é opcional, mas melhora a escolha):

```json
[{"n": 1, "title": "Blue Monday", "artist": "New Order", "duration": 449}]
```

## Como a melhor versão é escolhida

Para cada faixa, o Offtape busca vários resultados no YouTube e dá uma nota a cada um:

- **Sobe muito:** canal `Artista - Topic` (áudio oficial da gravadora) e títulos com "official audio".
- **Sobe:** canal oficial do artista ou VEVO, e duração igual à do Spotify.
- **Desce:** videoclipes ("official video", "music video") perdem para o áudio.
- **Desce muito:** ao vivo, cover de terceiros, remix, slowed/sped up, 8D, "1 hour loop", karaokê.

Vence a maior nota. Se o vídeo vencedor estiver indisponível, o próximo da lista
é tentado automaticamente.

## Estrutura do projeto

```
offtape/
├── spotify_app/
│   ├── app.py                 # app web local (BFF Flask + página)
│   ├── config.example.json    # modelo do config.json (Client ID)
│   └── README.md
├── docs/
│   └── GUIA_DE_USO.md         # passo a passo completo + dicas do carro
├── download_playlist.py       # downloader (CLI e funções reutilizadas pelo app)
├── make_tracks.py             # gera tracks.json a partir de CSV/TXT
├── explore_report.ipynb       # análise dos relatórios
├── tracks.example.json        # exemplo de lista de faixas
├── requirements.txt
├── CONTRIBUTING.md            # como contribuir (DCO, padrão, checklist)
├── LICENSE                    # MIT
└── README.md

# Criados ao usar (ficam só na sua máquina, fora do git):
├── tracks.json / tracks_json/ # suas listas de faixas
├── exported-musics/<playlist>/# seus MP3
├── relatorios/                # relatórios CSV
└── spotify_app/config.json, history.db, .flask_secret
```

## Segurança e privacidade

O Offtape foi feito para rodar **só no seu computador**:

- O servidor escuta apenas em `127.0.0.1` e recusa requisições com outro `Host`
  (proteção contra *DNS rebinding*).
- Todo `POST` exige JSON vindo da própria página local (proteção contra CSRF
  de outros sites abertos no seu navegador).
- Login via OAuth **PKCE**: não existe *client secret* no projeto.
- Os tokens ficam num cookie de sessão assinado e `HttpOnly`, e a chave de
  assinatura (`.flask_secret`) é criada com permissão `600`.
- Caminhos, IDs de playlist e drives recebidos da página são validados: o app
  só lê listas de `tracks_json/` e só escreve nos pen drives detectados (nunca no
  disco do sistema).

**Nada pessoal é versionado.** O `.gitignore` já exclui `config.json`,
`history.db`, `.flask_secret`, suas listas (`tracks.json`, `tracks_json/`),
MP3 e relatórios. Antes de publicar um fork, confira com `git status`.

## Problemas comuns

| Sintoma | Causa provável e solução |
|---|---|
| Downloads falhando em massa | yt-dlp desatualizado (o YouTube muda sempre): `pip install -U yt-dlp` |
| `ffmpeg não encontrado` / MP3 não gerado | instale o ffmpeg (veja a tabela da Instalação) e reabra o terminal |
| Windows: `python` não é reconhecido | use `py` no lugar de `python`/`python3`, ou reinstale o Python marcando "Add to PATH" |
| Aviso "SPOTIFY_CLIENT_ID não definido" | crie o `spotify_app/config.json` (veja a Instalação) |
| `INVALID_CLIENT` / erro de redirect no login | a Redirect URI no Dashboard precisa ser exatamente `http://127.0.0.1:8888/callback` |
| Login recusado para outra pessoa | adicione a conta dela em **User Management** no Dashboard |
| Playlist com "O Spotify não permite ler esta playlist" | playlists editoriais/algorítmicas ou de terceiros podem ser bloqueadas pela API |
| "Sign in to confirm your age" | o Offtape tenta o próximo vídeo; na CLI dá para usar `--cookies-from-browser chrome` |
| Pen drive não aparece no seletor | plugue e clique em **atualizar**; formate em exFAT/FAT32 se o carro não ler |
| Página responde 403 | acesse por `http://127.0.0.1:8888` ou `http://localhost:8888`, e não pelo IP da rede |

Mais detalhes no [guia de uso](docs/GUIA_DE_USO.md#perguntas-frequentes).

## Contribuindo

Contribuições são bem-vindas! Ideias no radar:

- **Caminho inverso (pen drive → playlist):** identificar as músicas de uma pasta
  (tags ID3, nome do arquivo e, em último caso, impressão digital de áudio, por
  exemplo via AcoustID) e criar uma playlist no Spotify com elas.
- Exportar todas as playlists do histórico de uma vez.
- Suporte a pen drive no Windows/Linux.

Como contribuir (ambiente, padrão de código, assinatura DCO com `git commit -s`
e checklist do PR) está em **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## Licença

[MIT](LICENSE) © 2026 Henrike Braga. Você pode usar, modificar e redistribuir,
desde que mantenha o aviso de copyright e a licença.

"Offtape" é o nome do projeto original, mantido por Henrike Braga. Forks são
bem-vindos, mas use outro nome para versões modificadas e deixe claro que não
são o Offtape oficial.
