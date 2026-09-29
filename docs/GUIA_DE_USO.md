# Guia de uso do Offtape

Passo a passo completo, da primeira instalação até o pen drive tocando no
carro. Se você só quer a visão geral, veja o [README](../README.md).

- [1. Antes de começar](#1-antes-de-começar)
- [2. Primeira instalação](#2-primeira-instalação)
- [3. Criando o app no Spotify](#3-criando-o-app-no-spotify)
- [4. Abrindo o Offtape](#4-abrindo-o-offtape)
- [5. Escolhendo e gerando uma playlist](#5-escolhendo-e-gerando-uma-playlist)
- [6. Baixando os MP3](#6-baixando-os-mp3)
- [7. Copiando para o pen drive](#7-copiando-para-o-pen-drive)
- [8. Deixando o pen drive pronto para o carro](#8-deixando-o-pen-drive-pronto-para-o-carro)
- [9. Conferindo os resultados (relatórios)](#9-conferindo-os-resultados-relatórios)
- [10. Usando pelo terminal](#10-usando-pelo-terminal)
- [11. Manutenção](#11-manutenção)
- [Perguntas frequentes](#perguntas-frequentes)

---

## 1. Antes de começar

Você vai precisar de:

- Um computador com **macOS, Linux ou Windows**.
- **Python 3.9 ou mais novo.** Para conferir: `python3 --version` (macOS/Linux)
  ou `py --version` (Windows). No Windows, instale pelo site python.org e marque
  **"Add python.exe to PATH"** na instalação.
- Uma conta no **Spotify**.
- Uns 10 minutos para a configuração inicial. Depois disso, é só clicar.

> **Onde está o terminal?**
> - macOS: `Cmd + Espaço`, digite **Terminal**, Enter.
> - Windows: menu Iniciar → **PowerShell** (ou **Terminal**).
> - Linux: `Ctrl + Alt + T` na maioria das distribuições.
> - VS Code (qualquer sistema): **Terminal → New Terminal**, já dentro da pasta.

Nos comandos abaixo, o que muda entre sistemas aparece em blocos separados.
O restante é igual para todos.

## 2. Primeira instalação

**Instale o ffmpeg** (converte o áudio em MP3):

| Sistema | Comando |
|---|---|
| macOS | `brew install ffmpeg` (instale antes o Homebrew: https://brew.sh) |
| Windows | `winget install Gyan.FFmpeg`, depois **feche e abra o terminal** |
| Linux | `sudo apt install ffmpeg` (Fedora: `sudo dnf install ffmpeg` · Arch: `sudo pacman -S ffmpeg`) |

**Crie o ambiente do projeto**, dentro da pasta do projeto:

macOS / Linux:

```bash
python3 -m venv .venv            # cria um ambiente isolado só para o projeto
source .venv/bin/activate        # ativa o ambiente
pip install -r requirements.txt  # instala as dependências
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> Se o PowerShell recusar o `Activate.ps1` ("execução de scripts desabilitada"),
> rode uma vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e tente de
> novo. Outra saída é usar o Prompt de Comando com `.venv\Scripts\activate.bat`.

Com o ambiente ativo, o início da linha mostra `(.venv)`. **Sempre que abrir um
terminal novo** para usar o Offtape, ative de novo: `source .venv/bin/activate`
no macOS/Linux, ou `.venv\Scripts\Activate.ps1` no Windows. Com ele ativo, o
comando `python` funciona igual nos três sistemas.

## 3. Criando o app no Spotify

O Spotify exige que cada programa que lê suas playlists tenha um "app"
cadastrado. É grátis e só se faz uma vez.

1. Entre em https://developer.spotify.com/dashboard com sua conta do Spotify.
2. Clique em **Create app** e preencha nome e descrição (pode ser "Offtape").
3. Em **Redirect URIs**, cole **exatamente**:
   ```
   http://127.0.0.1:8888/callback
   ```
   Não use `localhost`, porque o Spotify não aceita. Tem que ser `127.0.0.1`.
4. Em *Which API/SDKs are you planning to use?*, marque **Web API**. Salve.
5. Abra o app criado → **Settings** → copie o **Client ID**.
   Você **não** precisa do *Client Secret*: o Offtape usa PKCE.
6. **Quem pode usar:** enquanto o app estiver em *Development mode*, só as contas
   cadastradas em **User Management** conseguem fazer login. Adicione o e-mail
   da sua conta do Spotify e o de quem mais for usar o seu app.

Agora informe o Client ID ao Offtape:

```bash
cp spotify_app/config.example.json spotify_app/config.json      # macOS / Linux
copy spotify_app\config.example.json spotify_app\config.json    # Windows
```

Abra `spotify_app/config.json` e troque o texto de exemplo pelo seu Client ID:

```json
{ "client_id": "cole_aqui_o_seu_client_id" }
```

Esse arquivo é ignorado pelo git, então não vai parar num repositório por acidente.

## 4. Abrindo o Offtape

Com o ambiente ativo (passo 2):

```bash
cd spotify_app
python app.py
```

O terminal mostra `Abra: http://127.0.0.1:8888`. Abra esse endereço no navegador
e clique em **Conectar com Spotify**. Autorize o acesso **somente leitura** às
suas playlists.

- **Deixe o terminal aberto.** O app funciona enquanto ele estiver rodando.
- Para desligar, clique no terminal e aperte `Ctrl + C`.
- O login dura alguns dias: reiniciar o app não pede login de novo.

## 5. Escolhendo e gerando uma playlist

Na tela principal:

- Use a **busca** para filtrar pelo nome ou pelo dono da playlist.
- **Minhas** mostra só as playlists criadas por você, marcadas com o selo *minha*.
- **Ver faixas** abre as músicas em páginas de 50, com **Anterior/Próxima**.
  Serve para conferir antes de gerar.
- **Gerar** salva a lista de faixas em `tracks_json/AAAA-MM-DD_nome-da-playlist.json`
  e registra no **Histórico de gerações**, no fim da página.

> Algumas playlists aparecem, mas o Spotify não deixa lê-las pela API
> (geralmente as editoriais e algorítmicas, ou de outros usuários). Nesses casos,
> o Offtape mostra um aviso em vez de gerar.

## 6. Baixando os MP3

Abra **Histórico de gerações** e clique em **Baixar MP3** na playlist.

- O botão mostra o progresso (`Baixando 12/100`). No fim, aparece um aviso como
  *"Concluído: 97 baixadas · 0 já existiam · 3 falhas"*.
- São **3 músicas por vez**: mais rápido, sem sobrecarregar o YouTube.
  Cada música leva alguns segundos (busca + download + conversão). Para mudar,
  inicie o app com `DOWNLOAD_WORKERS=5 python app.py`. Não exagere: valores
  altos aumentam a chance de o YouTube limitar você.
- Os arquivos vão para `exported-musics/<playlist>/`, com o nome
  `NNN - Artista - Título.mp3`. O número garante a ordem da playlist.
- **Pode clicar de novo sem medo:** o que já foi baixado é pulado. Se houve
  falhas, um novo clique tenta só as que faltam.
- Clicar duas vezes seguidas não duplica nada: o app reaproveita o download em
  andamento.

## 7. Copiando para o pen drive

1. Plugue o pen drive.
2. Em **Histórico de gerações**, escolha o pen drive no seletor **Pen drive**.
   Se ele não aparecer, clique em **atualizar**.
3. Clique em **→ Pen drive** na playlist.

A playlist é copiada para uma pasta com o nome dela, sem acentos, que é o
formato mais compatível com som de carro (ex.: `Minha Playlist/`). Rodar de novo
só copia o que falta. Dá para repetir com várias playlists: cada uma fica na sua
pasta.

> Só aparecem unidades externas, e o disco do sistema nunca é listado.
> Onde o Offtape procura em cada sistema:
> - **macOS:** volumes em `/Volumes`.
> - **Linux:** pontos de montagem em `/media`, `/run/media` ou `/mnt`. Se o pen
>   drive não montar sozinho, abra-o uma vez no gerenciador de arquivos.
> - **Windows:** unidades removíveis (ex.: `E:\`). HDs externos que o Windows
>   classifica como disco fixo não aparecem.

## 8. Deixando o pen drive pronto para o carro

- **Formato:** a maioria dos sons de carro lê **FAT32** ou **exFAT**. Se o carro
  não reconhecer o pen drive, formate em **FAT32** (no Mac aparece como
  "MS-DOS (FAT)") ou **exFAT**. Onde formatar:
  - macOS: *Utilitário de Disco*;
  - Windows: Explorador de Arquivos → botão direito no pen drive → **Formatar**;
  - Linux: aplicativo *Discos* (GNOME Disks).

  Atenção: formatar apaga tudo o que está no pen drive.
- **Organização:** uma pasta por playlist. A maioria dos sons navega por pasta.
  Se você tinha músicas soltas, vale juntá-las numa pasta como `Diversos/`.
- **Arquivos ocultos (só no macOS):** o macOS cria itens como `.Spotlight-V100`,
  `.fseventsd` e arquivos `._nome.mp3`. Quase todo som ignora itens ocultos, mas
  alguns mostram os `._` como faixas quebradas. Para evitar:
  ```bash
  dot_clean "/Volumes/NOME_DO_PENDRIVE/Nome da pasta"   # remove os ._ de uma pasta
  sudo mdutil -i off /Volumes/NOME_DO_PENDRIVE          # para o Spotlight de indexar o pen drive
  ```
  Rode o `dot_clean` em cada pasta de música, e não na raiz do pen drive: na raiz
  ele esbarra nas pastas protegidas do sistema e para com erro.
  O Windows e o Linux não criam esses arquivos.
- **Ejete antes de tirar.** Tirar sem ejetar pode corromper arquivos.
  - macOS: botão de ejetar no Finder.
  - Windows: ícone "Remover hardware com segurança" na barra de tarefas.
  - Linux: "Ejetar" no gerenciador de arquivos.

## 9. Conferindo os resultados (relatórios)

Cada download gera `relatorios/download_report_AAAAMMDD_HHMMSS.csv`, com uma
linha por faixa: status (`ok`, `skipped` ou `failed`), vídeo escolhido e motivo
da falha.

Para explorar com gráficos e filtros, abra o notebook:

Com o ambiente ativo:

```bash
jupyter notebook explore_report.ipynb
```

No VS Code, basta abrir o `explore_report.ipynb` e escolher a `.venv` como
*kernel* (canto superior direito). O notebook abre o relatório mais recente
sozinho e mostra: resumo por status, lista de falhas com o motivo, os vídeos
escolhidos (útil para achar um match errado), busca por faixa e comparação
entre execuções.

## 10. Usando pelo terminal

Tudo também funciona sem o app web.

**Montar a lista de faixas.** Escolha **uma** das opções (cada uma cria o
`tracks.json`, substituindo o anterior):

```bash
# Opção A: começar do exemplo e editar à mão
cp tracks.example.json tracks.json       # Windows: copy tracks.example.json tracks.json

# Opção B: a partir de um CSV exportado do https://exportify.net
python make_tracks.py minha_playlist.csv

# Opção C: a partir de um TXT com uma faixa por linha ("Artista - Título")
python make_tracks.py lista.txt
```

> Dica: o botão **copiar comando** do histórico no app já monta o comando da
> CLI completo, com a pasta de saída certa para aquela playlist.

**Baixar:**

```bash
python download_playlist.py --dry-run          # confere os vídeos escolhidos, sem baixar
python download_playlist.py                    # baixa o tracks.json
python download_playlist.py --start 1 --end 3  # só as 3 primeiras, para testar
python download_playlist.py --tracks tracks_json/2026-01-01_minha-playlist.json
```

Veja todas as opções com `python download_playlist.py --help`.

## 11. Manutenção

- **Atualize o yt-dlp de vez em quando.** O YouTube muda com frequência e
  versões antigas param de funcionar:
  Com o ambiente ativo:
  ```bash
  pip install -U yt-dlp
  ```
- **Seus dados ficam só com você:** listas em `tracks_json/`, músicas em
  `exported-musics/`, relatórios em `relatorios/` e histórico em
  `spotify_app/history.db`. Para recomeçar do zero, basta apagar essas pastas e
  arquivos.

---

## Perguntas frequentes

**O Offtape funciona sem Spotify Premium?**
Sim. Ele só lê as suas playlists, e o áudio vem do YouTube.

**Por que alguma música saiu errada (versão ao vivo, cover…)?**
A escolha é automática. Confira no notebook (seção *matches escolhidos*).
Baixar de novo escolheria o mesmo vídeo, então o jeito é substituir o arquivo à
mão: coloque a versão certa em `exported-musics/<playlist>/` com o **mesmo nome**,
e o Offtape passa a usá-la, inclusive na cópia para o pen drive.

**Posso fechar o navegador durante o download?**
Pode. O download roda no app (terminal). Só não feche o terminal. Ao reabrir a
página, o progresso não aparece mais, mas clicar em **Baixar MP3** de novo
continua de onde parou.

**Aparece "403" ao abrir a página.**
Por segurança, o app só responde em `http://127.0.0.1:8888` ou
`http://localhost:8888`. Acessar pelo IP da rede ou por outro nome é bloqueado
de propósito.

**Aparece "O Spotify não permite ler esta playlist pela API".**
É uma limitação do Spotify para algumas playlists (editoriais, algorítmicas ou
de outros usuários). Uma saída é duplicar a playlist na sua conta, pelo app do
Spotify, e gerar a cópia.

**Uma faixa falhou com "Sign in to confirm your age".**
O Offtape já tenta outros vídeos automaticamente. Se todos forem restritos,
use a CLI com `--cookies-from-browser chrome` (usa o seu login do navegador)
para aquela faixa.

**Outra pessoa pode usar o meu Offtape?**
Pode, rodando o projeto na máquina dela. Ou ela cria o próprio app no Spotify,
ou você adiciona a conta dela em **User Management** no seu app do Dashboard.
