#!/usr/bin/env python3
"""Offtape — app web local para exportar playlists do Spotify para MP3 e pen drive.

O que é
    Um BFF (Backend For Frontend) em Flask que roda APENAS na máquina de quem
    baixou o projeto, em http://127.0.0.1:8888. O navegador nunca fala com o
    Spotify diretamente: conversa só com este backend, que faz o login OAuth,
    lê as playlists, gera o tracks.json (consumido por download_playlist.py),
    guarda o histórico em SQLite, baixa os MP3 e copia para um pen drive.

Modelo de segurança
    - Servidor escuta só em 127.0.0.1; requisições com cabeçalho Host diferente
      de 127.0.0.1:<PORT> / localhost:<PORT> são recusadas (anti DNS rebinding).
    - Todo POST exige Content-Type application/json e, se houver Origin, que ele
      seja a própria origem local (anti-CSRF); cookie de sessão SameSite=Lax.
    - OAuth Authorization Code + PKCE: não existe client secret no projeto.
    - Os tokens ficam num cookie de sessão assinado e HttpOnly, que nunca sai da
      máquina; caminhos, ids e drives recebidos do navegador são validados.
    - ``Sec-Fetch-Site`` cross-site/same-site é recusado em POST e em
      /login e /logout (anti login/logout CSRF); respostas levam
      ``Cache-Control: no-store`` e CORP/COOP ``same-origin`` (anti XS-Leak).

Riscos residuais (conhecidos e aceitos)
    - O cookie de sessão do Flask é *assinado*, não *cifrado*: quem lê o cookie
      (outro processo do mesmo usuário, extensões do navegador, ou outro
      servidor web em 127.0.0.1 numa porta diferente, pois cookies não são
      isolados por porta) consegue decodificar o access/refresh token do
      Spotify (escopos só de leitura). Rode apenas servidores locais em que
      você confia e use "sair" para descartar os tokens.
    - Se outro processo ocupar a porta 8888 antes do app, ele pode se passar
      pelo Offtape e iniciar o próprio OAuth com o Client ID público (PKCE não
      impede isso). O app não sobe se a porta estiver em uso; desconfie se a
      página não for a do Offtape.

Endpoints
    ======  ===========================  ==========================================
    Método  Caminho                      Descrição
    ======  ===========================  ==========================================
    GET     /                            Página única (HTML/JS embutido)
    GET     /login                       Inicia o OAuth (redireciona ao Spotify)
    GET     /callback                    Retorno do OAuth; troca code por token
    GET     /logout                      Limpa a sessão (também aceita POST)
    GET     /api/me                      Perfil (nome + avatar)
    GET     /api/playlists               Playlists do usuário (contagem, "minha")
    GET     /api/playlist/<id>/preview   Uma página de faixas (offset/limit)
    GET     /api/history                 Gerações anteriores (SQLite)
    POST    /api/generate                Gera tracks_json/AAAA-MM-DD_slug.json
    POST    /api/download                Job em background que baixa os MP3
    GET     /api/drives                  Pen drives/volumes externos montados
    POST    /api/export                  Job que copia os MP3 para o pen drive
    GET     /api/job/<id>                Status de um job (download ou export)
    GET     /api/download/<id>           Alias de /api/job/<id>
    ======  ===========================  ==========================================

Como rodar
    1) Crie um app em https://developer.spotify.com/dashboard e cadastre em
       "Redirect URIs" exatamente: http://127.0.0.1:8888/callback
    2) Informe o Client ID via variável de ambiente SPOTIFY_CLIENT_ID ou num
       config.json nesta pasta (veja config.example.json).
    3) pip install flask requests   (e yt-dlp/ffmpeg para baixar os MP3)
    4) python app.py  e abra http://127.0.0.1:8888

    Guia detalhado: README → Instalação e docs/GUIA_DE_USO.md.

Compatibilidade
    macOS, Linux e Windows. Muda por sistema só o que é inevitável: a detecção
    de pen drives (``/Volumes`` no macOS, ``/proc/mounts`` em /media, /run/media
    ou /mnt no Linux, letras de unidade removíveis via ctypes no Windows), a
    forma de escapar o comando de terminal (``shlex.quote`` no POSIX,
    ``subprocess.list2cmdline`` no Windows) e a instrução para instalar o
    ffmpeg. Comparações de caminho usam ``normcase``/``realpath``/``commonpath``.

Configuração (variáveis de ambiente)
    SPOTIFY_CLIENT_ID  Client ID do app Spotify (alternativa ao config.json).
    FLASK_SECRET       Chave que assina o cookie de sessão (padrão: gerada e
                       persistida em spotify_app/.flask_secret).
    DOWNLOAD_WORKERS   Nº de downloads simultâneos no botão "Baixar MP3"
                       (padrão 3, mínimo 1). Valores altos podem disparar o
                       rate limit do YouTube e saturar o CPU com o ffmpeg.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import requests
from flask import (Flask, g, redirect, request, session,
                   render_template_string, jsonify, url_for)
from markupsafe import escape

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
TRACKS_DIR = os.path.join(PROJECT_ROOT, "tracks_json")
OUT_DIR = os.path.join(PROJECT_ROOT, "exported-musics")   # MP3 (mesmo destino do CLI)
DB_PATH = os.path.join(HERE, "history.db")
sys.path.insert(0, PROJECT_ROOT)   # para importar download_playlist.py

HOST = "127.0.0.1"
PORT = 8888
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"
SCOPES = "playlist-read-private playlist-read-collaborative"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
HTTP_TIMEOUT = 20                     # segundos por chamada ao Spotify

PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9]{1,64}$")
MAX_TEXT = 200                        # limite para nome/dono vindos do navegador
MAX_OFFSET = 100_000


def load_client_id() -> str:
    """Obtém o Client ID do app Spotify.

    Procura primeiro na variável de ambiente ``SPOTIFY_CLIENT_ID`` e depois na
    chave ``client_id`` de ``config.json`` (mesma pasta deste arquivo).

    Returns:
        O Client ID sem espaços nas pontas, ou string vazia se não configurado.
    """
    cid = os.environ.get("SPOTIFY_CLIENT_ID")
    if cid:
        return cid.strip()
    cfg = os.path.join(HERE, "config.json")
    if os.path.exists(cfg):
        with open(cfg, encoding="utf-8") as f:
            return (json.load(f).get("client_id") or "").strip()
    return ""


CLIENT_ID = load_client_id()


def read_or_create_secret(path: str) -> str:
    """Lê a chave secreta de ``path`` ou a cria com permissão 0o600.

    A criação usa ``O_CREAT | O_EXCL`` para ser atômica: se dois processos
    tentarem criar ao mesmo tempo, só um escreve e o outro lê o resultado.
    No Windows o modo 0o600 é praticamente ignorado (só o bit de somente
    leitura tem efeito; o acesso real é controlado pelas ACLs do perfil do
    usuário), então falhas de ``chmod`` são toleradas.

    Args:
        path: Caminho do arquivo da chave.

    Returns:
        A chave (hex) persistida no arquivo.
    """
    for _ in range(50):
        try:
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        except FileExistsError:
            with open(path, encoding="utf-8") as f:
                s = f.read().strip()
            if s:
                # Corrige arquivos antigos permissivos no POSIX. No Windows o
                # chmod só mexe no bit somente-leitura (ACLs protegem o arquivo);
                # qualquer OSError é ignorado para nunca impedir a subida do app.
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
                return s
            time.sleep(0.02)            # outro processo ainda está escrevendo
            continue
        s = secrets.token_hex(32)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(s)
        return s
    raise RuntimeError(f"não foi possível ler a chave em {path}")


def load_secret() -> str:
    """Retorna a chave que assina o cookie de sessão.

    Usa a variável de ambiente ``FLASK_SECRET`` se existir; senão, persiste a
    chave em ``.flask_secret`` para a sessão sobreviver a reinícios.

    Returns:
        A chave secreta do Flask.
    """
    env = os.environ.get("FLASK_SECRET")
    if env:
        return env
    return read_or_create_secret(os.path.join(HERE, ".flask_secret"))


app = Flask(__name__)
app.secret_key = load_secret()
app.permanent_session_lifetime = timedelta(days=7)   # sessão dura até 7 dias
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    # Nome próprio: cookies não são isolados por porta, então o nome padrão
    # "session" colidiria com outros apps Flask em 127.0.0.1:<outra porta>.
    SESSION_COOKIE_NAME="offtape_session",
    MAX_CONTENT_LENGTH=1024 * 1024,   # corpos JSON pequenos bastam
)


# --------------------------------------------------------------------------- #
# Segurança (Host, CSRF, validação de entrada)
# --------------------------------------------------------------------------- #
@app.before_request
def guard_request():
    """Aplica as verificações de Host e anti-CSRF antes de qualquer rota.

    Returns:
        ``None`` para seguir com a requisição, ou uma resposta 403 se o Host
        não for local, se um POST vier de outra origem / sem JSON, ou se um
        POST, /login ou /logout vier de outro site (``Sec-Fetch-Site``).
    """
    # Anti DNS rebinding: um site malicioso que aponte seu domínio para
    # 127.0.0.1 chega aqui com Host "evil.com:8888" e é recusado.
    if request.headers.get("Host", "") not in ALLOWED_HOSTS:
        return jsonify({"error": "host não permitido"}), 403
    # Defesa em profundidade (navegadores modernos enviam Sec-Fetch-Site):
    # recusa requisições disparadas por outro site ("cross-site") ou por
    # outra porta de 127.0.0.1/localhost ("same-site"). Vale para POST e para
    # os GET com efeito colateral /login e /logout (login/logout CSRF). O
    # /callback fica de fora de propósito: ele chega via redirect do Spotify.
    fetch_site = request.headers.get("Sec-Fetch-Site")
    if fetch_site in ("cross-site", "same-site") and (
            request.method not in ("GET", "HEAD", "OPTIONS")
            or request.path in ("/login", "/logout")):
        return jsonify({"error": "requisição de outro site recusada"}), 403
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            return jsonify({"error": "origem não permitida"}), 403
        # Formulários cross-site não conseguem enviar application/json sem
        # preflight CORS (que este app não responde), então exigir JSON barra CSRF.
        if not request.is_json:
            return jsonify({"error": "Content-Type deve ser application/json"}), 403
    return None


@app.after_request
def security_headers(resp):
    """Adiciona cabeçalhos de segurança a toda resposta.

    A CSP libera só o ``<script>`` inline que carrega o nonce desta requisição
    (gerado em ``index``), estilos inline, imagens https (CDN do Spotify) e
    ``fetch`` para a própria origem; o formulário só pode ir ao Spotify.

    Args:
        resp: Resposta do Flask prestes a ser enviada.

    Returns:
        A mesma resposta, com os cabeçalhos adicionados.
    """
    nonce = g.get("csp_nonce")
    script_src = "'self'" + (f" 'nonce-{nonce}'" if nonce else "")
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src {script_src}; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'; "
        "form-action 'self' https://accounts.spotify.com"
    )
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    # Tudo aqui é dinâmico e pessoal (playlists, caminhos, jobs): não guardar
    # em cache de disco do navegador nem de proxies.
    resp.headers["Cache-Control"] = "no-store"
    # Anti XS-Leak: outras origens (inclusive outras portas de 127.0.0.1) não
    # podem embutir estas respostas via <script>/<img>, nem manter referência
    # à nossa janela (window.opener) para sondar estado.
    resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return resp


def json_body() -> dict | None:
    """Lê o corpo JSON da requisição atual.

    Returns:
        O objeto JSON se for um dicionário válido; ``None`` caso contrário.
    """
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def _norm(path: str) -> str:
    """Normaliza ``path`` para comparação: ``normcase(realpath(path))``.

    ``realpath`` resolve symlinks e ``..``; ``normcase`` deixa em minúsculas e
    troca ``/`` por ``\\`` no Windows (onde o sistema de arquivos ignora caixa)
    e não faz nada no POSIX.
    """
    return os.path.normcase(os.path.realpath(path))


def _is_within(child: str, parent: str) -> bool:
    """Indica se ``child`` está dentro de ``parent`` (ou é o próprio ``parent``).

    Ambos são resolvidos com ``realpath`` (um symlink que aponte para fora de
    ``parent`` não passa) e comparados com ``commonpath``, que respeita a
    fronteira de componentes (``/a/bc`` não está dentro de ``/a/b``, ao
    contrário de um ``startswith`` ingênuo).

    Args:
        child: Caminho a verificar.
        parent: Diretório que deve contê-lo.

    Returns:
        ``True`` se ``child`` estiver contido em ``parent``; ``False`` caso
        contrário, inclusive quando estão em unidades diferentes no Windows
        (``commonpath`` levanta ``ValueError``) ou o caminho é inválido.
    """
    try:
        c, p = _norm(child), _norm(parent)
        return os.path.commonpath([c, p]) == p
    except (ValueError, TypeError, OSError):
        return False


def resolve_tracks_json(value) -> str | None:
    """Valida um caminho de tracks.json recebido do navegador.

    Args:
        value: Valor bruto de ``json_path`` no corpo da requisição.

    Returns:
        O caminho real (``realpath``) se for um arquivo ``.json`` existente
        dentro de ``TRACKS_DIR``; ``None`` caso contrário.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        real = os.path.realpath(value)
    except (ValueError, OSError):          # ex.: byte nulo no caminho
        return None
    if (real.lower().endswith(".json") and os.path.isfile(real)
            and _is_within(real, TRACKS_DIR) and _norm(real) != _norm(TRACKS_DIR)):
        return real
    return None


def valid_playlist_id(pid) -> bool:
    """Indica se ``pid`` tem o formato de um id de playlist do Spotify (base62)."""
    return isinstance(pid, str) and bool(PLAYLIST_ID_RE.match(pid))


def clip_text(value, limit: int = MAX_TEXT) -> str:
    """Converte ``value`` em string (``None`` vira vazio) e corta em ``limit``."""
    return ("" if value is None else str(value))[:limit]


# --------------------------------------------------------------------------- #
# SQLite
# --------------------------------------------------------------------------- #
def db() -> sqlite3.Connection:
    """Abre uma conexão com o banco de histórico.

    Returns:
        Conexão SQLite com ``row_factory`` de acesso por nome de coluna.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Cria as tabelas ``snapshots`` e ``tracks`` se ainda não existirem."""
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id   TEXT    NOT NULL,
                playlist_name TEXT    NOT NULL,
                owner         TEXT,
                fetched_at    TEXT    NOT NULL,
                track_count   INTEGER NOT NULL,
                json_path     TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tracks (
                snapshot_id  INTEGER NOT NULL,
                n            INTEGER NOT NULL,
                title        TEXT    NOT NULL,
                artist       TEXT,
                duration     INTEGER,
                FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
            );
            """
        )
    # O histórico revela suas playlists: só o dono lê/escreve (POSIX). No
    # Windows o chmod é praticamente inócuo (ACLs do perfil protegem).
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def save_snapshot(playlist: dict, tracks: list, json_path: str) -> int:
    """Grava um snapshot da playlist e suas faixas no histórico.

    Args:
        playlist: Dicionário com ``id``, ``name`` e ``owner``.
        tracks: Lista de faixas ``{n, title, artist, duration}``.
        json_path: Caminho do tracks.json gerado.

    Returns:
        O id do snapshot inserido.
    """
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO snapshots (playlist_id, playlist_name, owner, fetched_at, track_count, json_path)"
            " VALUES (?,?,?,?,?,?)",
            (playlist["id"], playlist["name"], playlist.get("owner", ""),
             datetime.now().isoformat(timespec="seconds"), len(tracks), json_path),
        )
        sid = cur.lastrowid
        conn.executemany(
            "INSERT INTO tracks (snapshot_id, n, title, artist, duration) VALUES (?,?,?,?,?)",
            [(sid, t["n"], t["title"], t["artist"], t["duration"]) for t in tracks],
        )
        return sid


# --------------------------------------------------------------------------- #
# OAuth (Authorization Code + PKCE — sem client secret)
# --------------------------------------------------------------------------- #
def pkce_pair() -> tuple[str, str]:
    """Gera o par PKCE (``code_verifier``, ``code_challenge``).

    O verifier aleatório fica só na sessão; ao Spotify vai apenas o hash
    SHA-256 (S256). Na troca do code o verifier é enviado e o Spotify confere,
    o que substitui o client secret num app que roda na máquina do usuário.

    Returns:
        Tupla ``(verifier, challenge)`` em base64url sem padding.
    """
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def token_valid() -> bool:
    """Indica se há access token na sessão e se ele ainda não expirou."""
    return bool(session.get("access_token")) and time.time() < session.get("expires_at", 0)


def refresh_token() -> bool:
    """Renova o access token usando o refresh token da sessão.

    Returns:
        ``True`` se a renovação funcionou e a sessão foi atualizada.
    """
    rt = session.get("refresh_token")
    if not rt:
        return False
    try:
        r = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": CLIENT_ID,
        }, timeout=HTTP_TIMEOUT)
    except requests.RequestException:
        return False
    if r.status_code != 200:
        return False
    tok = r.json()
    session["access_token"] = tok["access_token"]
    # Margem de 60 s para não usar um token que expira no meio da chamada.
    session["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    # Com PKCE o Spotify pode rotacionar o refresh token; guarda o novo se vier.
    if tok.get("refresh_token"):
        session["refresh_token"] = tok["refresh_token"]
    return True


def ensure_token() -> bool:
    """Garante um access token válido, renovando se necessário."""
    return token_valid() or refresh_token()


def api_get(path_or_url: str, params: dict | None = None) -> dict:
    """Faz GET na Web API do Spotify com o token da sessão.

    Args:
        path_or_url: Caminho relativo a ``API`` (ex.: ``/me``) ou URL absoluta
            do Spotify (usada para seguir o campo ``next`` da paginação).
        params: Parâmetros de query opcionais.

    Returns:
        O JSON da resposta.

    Raises:
        PermissionError: Se não há sessão válida nem refresh possível.
        ValueError: Se a URL absoluta não for da API do Spotify.
        requests.HTTPError: Se o Spotify responder com erro.
    """
    if not ensure_token():
        raise PermissionError("sessão expirada — faça login de novo")
    if path_or_url.startswith("http"):
        if not path_or_url.startswith(API + "/"):
            raise ValueError("URL fora da API do Spotify")
        url = path_or_url
    else:
        url = API + path_or_url

    def _do():
        """Executa o GET com o access token atual da sessão."""
        return requests.get(url, params=params or {}, timeout=HTTP_TIMEOUT,
                            headers={"Authorization": f"Bearer {session['access_token']}"})
    r = _do()
    # Token pode ter sido revogado/expirado antes do previsto: 1 retry após refresh.
    if r.status_code == 401 and refresh_token():
        r = _do()
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- #
# Helpers de domínio
# --------------------------------------------------------------------------- #
def slugify(name: str) -> str:
    """Converte o nome da playlist num slug seguro para nome de arquivo.

    Args:
        name: Nome original da playlist.

    Returns:
        Slug em minúsculas com hífens (até 60 caracteres), ou ``"playlist"``.
    """
    s = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:60] or "playlist"


def current_user() -> dict:
    """Retorna o perfil do usuário logado, com cache na sessão.

    Returns:
        Dicionário ``{id, name, image}``.

    Raises:
        PermissionError: Se não houver sessão válida.
        requests.HTTPError: Se o Spotify responder com erro.
    """
    if "me" not in session:
        me = api_get("/me")
        imgs = me.get("images") or []
        session["me"] = {
            "id": me.get("id", ""),
            "name": me.get("display_name") or me.get("id", ""),
            "image": imgs[0]["url"] if imgs else "",
        }
    return session["me"]


def err_info(e: Exception) -> tuple[str, int]:
    """Traduz uma exceção em mensagem curta e amigável + status HTTP.

    Nunca devolve traceback: erros do Spotify viram mensagens fixas e demais
    exceções têm a mensagem truncada.

    Args:
        e: Exceção capturada na rota.

    Returns:
        Tupla ``(mensagem, status_http)``.
    """
    resp = getattr(e, "response", None)
    if resp is not None:
        sc = resp.status_code
        if sc in (403, 404):
            return ("O Spotify não permite ler esta playlist pela API "
                    "(geralmente editorial/algorítmica, de outro usuário, ou indisponível na sua região).", sc)
        if sc == 429:
            return ("Limite de requisições do Spotify atingido. Aguarde alguns segundos e tente de novo.", 429)
        return (f"Erro do Spotify (HTTP {sc}).", 502)
    if isinstance(e, requests.RequestException):
        return ("Falha de rede ao falar com o Spotify.", 502)
    return (clip_text(e) or e.__class__.__name__, 400)


def parse_track_item(item: dict) -> dict | None:
    """Extrai título, artistas e duração de um item de playlist.

    Args:
        item: Elemento de ``items`` retornado pelo Spotify.

    Returns:
        ``{title, artist, duration}`` (duração em segundos), ou ``None`` para
        itens vazios, indisponíveis ou episódios de podcast.
    """
    # O endpoint novo /playlists/{id}/items usa a chave 'item'; o antigo
    # /tracks usava 'track'. Aceita as duas por compatibilidade.
    tr = item.get("item") or item.get("track")
    if not tr or not tr.get("name") or tr.get("type") == "episode":
        return None
    artists = ", ".join(a["name"] for a in tr.get("artists", []) if a.get("name"))
    return {"title": tr["name"], "artist": artists,
            "duration": round((tr.get("duration_ms") or 0) / 1000)}


def fetch_all_tracks(playlist_id: str) -> list:
    """Busca todas as faixas de uma playlist, página a página.

    Args:
        playlist_id: Id (já validado) da playlist no Spotify.

    Returns:
        Lista ``[{n, title, artist, duration}]`` numerada a partir de 1.

    Raises:
        requests.HTTPError: Se o Spotify recusar a leitura.
    """
    tracks, n = [], 0
    params = {"limit": 50,
              "fields": "items(item(name,duration_ms,artists(name),type)),next"}
    data = api_get(f"/playlists/{playlist_id}/items", params)
    while True:
        for item in data.get("items", []):
            t = parse_track_item(item)
            if t:
                n += 1
                tracks.append({"n": n, **t})
        # O Spotify devolve em 'next' a URL completa da próxima página (já com
        # offset/fields); quando é null, acabou.
        nxt = data.get("next")
        if not nxt:
            break
        data = api_get(nxt)
    return tracks


# --------------------------------------------------------------------------- #
# Jobs de download (background) — 2ª etapa direto pela UI
# --------------------------------------------------------------------------- #
JOBS: dict = {}
JOBS_LOCK = threading.Lock()
# Nº de downloads simultâneos. Baixo de propósito: acelera sem disparar o
# rate limit do YouTube nem saturar o CPU com a conversão do ffmpeg.
# Ajustável via env DOWNLOAD_WORKERS.
DOWNLOAD_WORKERS = max(1, int(os.environ.get("DOWNLOAD_WORKERS", "3")))


def slug_from_json(json_path: str) -> str:
    """Deriva o slug da playlist do nome do tracks.json (sem a data AAAA-MM-DD_).

    O resultado vira um componente de caminho (``OUT_DIR/<slug>``), então é
    garantido como um único nome de pasta seguro: vazio, ``"."``, ``".."``
    ou só pontos/espaços (ex.: arquivo ``2026-01-01_...json`` criado à mão em
    ``tracks_json/``) viram ``"playlist"``, e nomes de dispositivo do Windows
    (``con``, ``aux``...) ganham ``"_"``. Slugs gerados pelo app (só letras,
    dígitos e hífens) não mudam.
    """
    base_name = os.path.splitext(os.path.basename(json_path))[0]
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", base_name) or base_name
    # Defesa em profundidade contra travessia: "..", separadores, ":" (ADS no
    # Windows) e NUL nunca podem sair daqui.
    if not slug.strip(" .") or re.search(r"[\\/:\x00]", slug):
        return "playlist"
    stem, dot, rest = slug.partition(".")
    if _WIN_RESERVED_RE.match(stem.rstrip(" ")):
        return stem.rstrip(" ") + "_" + dot + rest
    return slug


def playlist_out_dir(json_path: str) -> str:
    """Retorna a pasta de MP3 de um tracks.json: ``OUT_DIR/<slug>``.

    Fonte única usada pelo download, pela exportação e pelo comando copiado,
    para que os três apontem sempre para a mesma pasta.

    Args:
        json_path: Caminho do tracks.json.

    Returns:
        Caminho absoluto da pasta de saída da playlist.
    """
    return os.path.join(OUT_DIR, slug_from_json(json_path))


def download_command(json_path: str) -> str:
    """Monta o comando de terminal equivalente ao botão "Baixar MP3".

    Usa o interpretador atual (``sys.executable``, para cair na mesma venv;
    ``"python"`` se indisponível), o caminho absoluto do
    ``download_playlist.py`` (funciona de qualquer pasta) e ``--out`` para a
    mesma subpasta usada pela UI. No Windows os argumentos são unidos com
    ``subprocess.list2cmdline`` (aspas duplas, regras do CRT/cmd); no POSIX,
    escapados com ``shlex.quote``.

    Args:
        json_path: Caminho do tracks.json.

    Returns:
        Linha de comando pronta para colar no terminal.
    """
    script = os.path.join(PROJECT_ROOT, "download_playlist.py")
    argv = [sys.executable or "python", script, "--tracks", json_path,
            "--out", playlist_out_dir(json_path)]
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return " ".join(shlex.quote(a) for a in argv)


# Nomes de dispositivo que o Windows não permite como nome de arquivo/pasta.
_WIN_RESERVED_RE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)


def fat_dirname(name: str) -> str:
    """Gera um nome de pasta compatível com pen drive FAT32 e som de carro.

    Muitos rádios automotivos só leem FAT32 e exibem mal acentos; por isso o
    nome vira ASCII, sem caracteres proibidos no FAT/Windows (inclusive
    caracteres de controle) e sem ponto ou espaço nas pontas. Nomes de
    dispositivo reservados do Windows (``CON``, ``PRN``, ``AUX``, ``NUL``,
    ``COM1``–``COM9``, ``LPT1``–``LPT9``, em qualquer caixa e também com
    extensão, como ``con.txt``) ganham um ``"_"`` após o radical
    (``CON`` → ``CON_``, ``con.txt`` → ``con_.txt``).
    Se nada sobrar após a conversão (ex.: nomes só em japonês/chinês), usa o
    slug da playlist se ele for ASCII; senão, ``"playlist-"`` + os 8 primeiros
    hex do SHA-1 do nome original, para duas playlists diferentes nunca caírem
    na mesma pasta.

    Args:
        name: Nome original da playlist.

    Returns:
        Nome de pasta seguro, não vazio (até 101 caracteres).
    """
    def fold(s: str) -> str:
        """Converte ``s`` para ASCII seguro no FAT32 (pode resultar vazio)."""
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
        s = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', "-", s)
        s = re.sub(r"\s+", " ", s).strip(" .")[:100]
        return s.rstrip(" .")          # o corte em 100 pode expor ponto/espaço

    def unreserve(s: str) -> str:
        """Acrescenta ``"_"`` ao radical se ``s`` for nome de dispositivo do Windows.

        O ``"_"`` vai logo após o radical (``aux.txt`` → ``aux_.txt``): o
        Windows considera reservado qualquer ``AUX.<ext>``, então pôr o
        ``"_"`` só no fim (``aux.txt_``) não bastaria.
        """
        stem, dot, rest = s.partition(".")
        if _WIN_RESERVED_RE.match(stem.rstrip(" ")):
            return stem.rstrip(" ") + "_" + dot + rest
        return s

    n = fold(name)
    if re.search(r"[A-Za-z0-9]", n):
        return unreserve(n)
    slug = slugify(name)
    if slug != "playlist" and slug.isascii() and fold(slug):
        return unreserve(fold(slug))
    return "playlist-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


# Fontes de volumes por sistema (constantes de módulo para facilitar testes).
MAC_VOLUMES_DIR = "/Volumes"
LINUX_MOUNTS_FILE = "/proc/mounts"
LINUX_REMOVABLE_PREFIXES = ("/media/", "/run/media/", "/mnt/")
WIN_DRIVE_REMOVABLE = 2   # valor de DRIVE_REMOVABLE em GetDriveTypeW


def _drive_entry(name: str, path: str) -> dict | None:
    """Monta o item ``{name, path, free_gb, total_gb}`` de um volume.

    Args:
        name: Nome exibido na UI.
        path: Raiz do volume.

    Returns:
        O dicionário do volume, ou ``None`` se não der para ler o espaço
        (ex.: leitor de cartão sem cartão, volume desmontado no meio).
    """
    try:
        du = shutil.disk_usage(path)
    except (OSError, ValueError):
        return None
    return {"name": name, "path": path,
            "free_gb": round(du.free / 1e9, 1),
            "total_gb": round(du.total / 1e9, 1)}


def _parse_linux_mounts(text: str) -> list[str]:
    """Extrai de um conteúdo de ``/proc/mounts`` os pontos de montagem removíveis.

    Considera removível o que estiver montado sob ``/media/``, ``/run/media/``
    ou ``/mnt/`` (onde udisks/desktops e usuários montam pen drives). O kernel
    escapa espaço, tab, quebra de linha e barra invertida em octal (``\\040``
    etc.); esses escapes são decodificados. Função pura, sem acesso a disco.

    Args:
        text: Conteúdo completo de ``/proc/mounts``.

    Returns:
        Pontos de montagem (sem duplicatas, na ordem em que aparecem).
    """
    out: list[str] = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        mnt = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), fields[1])
        if mnt.startswith(LINUX_REMOVABLE_PREFIXES) and mnt not in out:
            out.append(mnt)
    return out


def _win_logical_drives() -> list[tuple[str, int, str]]:
    """Consulta as unidades do Windows via ctypes (``kernel32``).

    Isolado aqui para poder ser substituído em testes; ``ctypes`` é
    importado só dentro da função, então o módulo importa em qualquer SO.

    Returns:
        Lista ``[(raiz, tipo, rótulo)]``, ex. ``[("E:\\\\", 2, "MEU_PENDRIVE")]``;
        ``tipo`` é o retorno de ``GetDriveTypeW`` e ``rótulo`` pode ser vazio.
    """
    import ctypes   # noqa: PLC0415 — só existe/necessário no Windows

    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    out = []
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(ord('A') + i)}:\\"
        try:
            dtype = int(k32.GetDriveTypeW(ctypes.c_wchar_p(root)))
            buf = ctypes.create_unicode_buffer(261)
            ok = k32.GetVolumeInformationW(ctypes.c_wchar_p(root), buf, len(buf),
                                           None, None, None, None, 0)
            out.append((root, dtype, buf.value if ok else ""))
        except Exception:   # uma unidade problemática não derruba a lista
            continue
    return out


def _list_drives_macos() -> list:
    """Volumes em ``/Volumes`` que são diretórios, exceto o disco de boot.

    No macOS o disco de boot aparece como ``/Volumes/<disco>``, um symlink
    para ``/``; ele é descartado.
    """
    out = []
    try:
        names = sorted(os.listdir(MAC_VOLUMES_DIR))
    except OSError:
        return out
    for name in names:
        try:
            p = os.path.join(MAC_VOLUMES_DIR, name)
            if not os.path.isdir(p) or os.path.realpath(p) == "/":
                continue
            item = _drive_entry(name, p)
            if item:
                out.append(item)
        except Exception:
            continue
    return out


def _list_drives_linux() -> list:
    """Pontos de montagem removíveis de ``/proc/mounts`` que são diretórios."""
    out = []
    try:
        # surrogateescape preserva bytes não UTF-8 do nome do ponto de montagem.
        with open(LINUX_MOUNTS_FILE, encoding="utf-8", errors="surrogateescape") as f:
            mounts = _parse_linux_mounts(f.read())
    except OSError:
        return out
    for p in mounts:
        try:
            if not os.path.isdir(p):
                continue
            item = _drive_entry(os.path.basename(p.rstrip("/")) or p, p)
            if item:
                out.append(item)
        except Exception:
            continue
    return out


def _list_drives_windows() -> list:
    """Unidades removíveis (``DRIVE_REMOVABLE``) do Windows, exceto a do sistema.

    O nome exibido é a raiz seguida do rótulo, ex. ``E:\\ (MEU_PENDRIVE)``.
    """
    system = os.environ.get("SystemDrive", "C:").rstrip("\\/").upper()
    out = []
    try:
        drives = _win_logical_drives()
    except Exception:
        return out
    for root, dtype, label in drives:
        try:
            if dtype != WIN_DRIVE_REMOVABLE or root.rstrip("\\/").upper() == system:
                continue
            item = _drive_entry(f"{root} ({label})" if label else root, root)
            if item:
                out.append(item)
        except Exception:
            continue
    return out


def list_drives() -> list:
    """Lista os pen drives/volumes externos disponíveis para exportação.

    O critério depende do sistema:

    - macOS: entradas de ``/Volumes`` que são diretórios, sem o disco de boot.
    - Linux: pontos de montagem de ``/proc/mounts`` sob ``/media/``,
      ``/run/media/`` ou ``/mnt/``.
    - Windows: letras de unidade do tipo removível, nunca a do sistema.
    - Outros sistemas: lista vazia.

    Erros num volume isolado são ignorados (ele só some da lista).

    Returns:
        Lista ``[{name, path, free_gb, total_gb}]``.
    """
    if sys.platform == "darwin":
        return _list_drives_macos()
    if sys.platform.startswith("linux"):
        return _list_drives_linux()
    if os.name == "nt":
        return _list_drives_windows()
    return []


def _safe_copy_into(sp: str, dp: str, dst: str) -> None:
    """Copia ``sp`` para ``dp`` sem seguir links plantados no pen drive.

    Um pen drive malicioso (formatado em ext4/APFS/NTFS) pode trazer
    ``<pasta>/001 - X.mp3`` como symlink/junction para um arquivo seu
    (ex.: ``~/.zshrc``); ``shutil.copy2`` seguiria o link e sobrescreveria o
    alvo. Aqui o destino é recusado se for link ou se resolver para fora de
    ``dst``, e a cópia vai para um temporário novo (``O_EXCL``, e
    ``O_NOFOLLOW`` onde existe) trocado atomicamente por ``os.replace`` —
    que substitui a *entrada* do diretório, nunca o alvo de um link.

    Args:
        sp: Arquivo de origem (MP3 local).
        dp: Caminho final dentro de ``dst``.
        dst: Pasta de destino no pen drive (já validada).

    Raises:
        OSError: Se o destino for um link ou a cópia falhar.
    """
    if os.path.islink(dp) or (os.path.lexists(dp) and not _is_within(dp, dst)):
        raise OSError(f"{os.path.basename(dp)}: é um link no pen drive — ignorado por segurança")
    tmp = os.path.join(dst, f".offtape-{secrets.token_hex(6)}.tmp")
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    fd = os.open(tmp, flags, 0o644)
    try:
        with os.fdopen(fd, "wb") as out, open(sp, "rb") as inp:
            shutil.copyfileobj(inp, out, 1024 * 1024)
        try:
            shutil.copystat(sp, tmp)      # datas (FAT32 pode recusar parte disso)
        except OSError:
            pass
        os.replace(tmp, dp)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run_export_job(job: dict) -> None:
    """Copia os MP3 de ``job["src"]`` para ``job["dst"]`` (roda em thread).

    É idempotente: arquivos que já existem no destino com o mesmo tamanho são
    pulados, então repetir a exportação só copia o que falta. Atualiza os
    contadores ``done/ok/skipped/failed`` e o ``status`` do próprio job.
    Links (symlink/junction) no pen drive nunca são seguidos: a pasta de
    destino é revalidada aqui e cada arquivo passa por ``_safe_copy_into``.
    Arquivos ocultos (``.*``, ex.: temporários ``.offtape-*``) não são copiados.

    Args:
        job: Dicionário do job (compartilhado com ``/api/job/<id>``).
    """
    try:
        src, dst = job["src"], job["dst"]
        os.makedirs(dst, exist_ok=True)
        # Revalida depois do makedirs (a pasta pode ter surgido/trocado desde a
        # checagem em api_export): tem de continuar dentro da raiz do drive.
        drive = job.get("drive") or os.path.dirname(dst)
        if not _is_within(dst, drive) or _norm(dst) == _norm(drive):
            raise OSError("pasta de destino aponta para fora do pen drive — cancelado")
        files = [f for f in sorted(os.listdir(src))
                 if f.endswith(".mp3") and not f.startswith(".")]
        job["total"] = len(files)
        for f in files:
            if job.get("cancel"):
                break
            sp, dp = os.path.join(src, f), os.path.join(dst, f)
            try:
                if (not os.path.islink(dp) and os.path.isfile(dp)
                        and os.path.getsize(dp) == os.path.getsize(sp)):
                    job["skipped"] += 1          # já está lá, igual -> pula
                else:
                    _safe_copy_into(sp, dp, dst)
                    job["ok"] += 1
            except Exception as e:
                job["failed"] += 1
                job["error"] = clip_text(e)
            job["done"] += 1
            job["current"] = f
        job["current"] = ""
        job["status"] = "done"
    except Exception as e:
        job["status"] = "error"
        job["error"] = clip_text(e)


FFMPEG_MISSING_MSG = (
    "ffmpeg não encontrado — ele é necessário para converter os MP3. Instale e "
    "reinicie o app: macOS: brew install ffmpeg · Windows: winget install Gyan.FFmpeg"
    " · Linux: sudo apt install ffmpeg"
)


def ffmpeg_ok() -> bool:
    """Indica se o ffmpeg está disponível, segundo ``download_playlist``.

    Usa ``download_playlist.ffmpeg_available()`` se ela existir. Se o módulo
    não importar (ex.: sem yt-dlp) ou não tiver a função, devolve ``True``
    para não bloquear aqui: o job reporta o erro real depois.

    Returns:
        ``False`` apenas quando ``ffmpeg_available()`` responde ``False``.
    """
    try:
        import download_playlist as dl
    except (Exception, SystemExit):
        return True
    check = getattr(dl, "ffmpeg_available", None)
    if not callable(check):
        return True
    try:
        return bool(check())
    except Exception:
        return True


def run_download_job(job: dict) -> None:
    """Baixa os MP3 de um tracks.json via ``download_playlist.download_one``.

    Roda em thread; usa ``DOWNLOAD_WORKERS`` downloads paralelos, salva em
    ``OUT_DIR/<slug>/`` e grava um relatório CSV em ``relatorios/``. Atualiza
    contadores e ``status`` do próprio job.

    Args:
        job: Dicionário do job (compartilhado com ``/api/job/<id>``).
    """
    try:
        # Importa só na hora (precisa de yt-dlp/ffmpeg). Sem yt-dlp o módulo pode
        # chamar sys.exit() -> SystemExit, que não herda de Exception.
        import download_playlist as dl
    except (Exception, SystemExit):
        job["status"] = "error"
        job["error"] = "yt-dlp não instalado na venv (pip install -r requirements.txt)."
        return
    try:
        # load_tracks valida o formato (lista de {n:int, title:str, artist:str});
        # arquivo malformado vira erro legível no job em vez de exceção no meio.
        tracks = dl.load_tracks(job["json_path"])
        job["total"] = len(tracks)
        out_dir = playlist_out_dir(job["json_path"])
        os.makedirs(out_dir, exist_ok=True)
        job["out_dir"] = out_dir
        lock = threading.Lock()
        results = []   # linhas do relatório CSV

        def work(t):
            """Baixa uma faixa e atualiza contadores/relatório sob ``lock``.

            Args:
                t: Faixa ``{n, title, artist, duration}`` do tracks.json.
            """
            if job.get("cancel"):
                return
            try:
                r = dl.download_one(t, out_dir)    # idempotente: pula MP3 já existente
            except (Exception, SystemExit) as e:
                r = {"status": "failed", "url": "", "chosen_title": "", "msg": clip_text(e)}
            if r.get("status") not in ("ok", "skipped", "failed"):
                r["status"] = "failed"          # nunca cria chave nova no job
            with lock:
                job[r["status"]] += 1           # ok | skipped | failed
                job["done"] += 1
                job["current"] = f'{t.get("artist","")} - {t.get("title","")}'.strip(" -")
                results.append([t.get("n"), t.get("title"), t.get("artist"),
                                r["status"], r.get("url", ""), r.get("chosen_title", ""), r.get("msg", "")])

        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as ex:
            list(ex.map(work, tracks))

        # Relatório no mesmo formato do CLI (lido pelo explore_report.ipynb).
        reports_dir = os.path.join(PROJECT_ROOT, "relatorios")
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(reports_dir, f"download_report_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        results.sort(key=lambda row: row[0] if row[0] is not None else 0)
        with open(report_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["n", "title", "artist", "status", "chosen_url", "chosen_title", "message"])
            w.writerows(dl.csv_safe(r) for r in results)   # evita "injeção de fórmula"

        job["report"] = report_path
        job["current"] = ""
        job["status"] = "done"
    except (Exception, SystemExit) as e:
        job["status"] = "error"
        job["error"] = clip_text(e) or e.__class__.__name__
    finally:
        # Garantia: o job nunca fica preso em "running" (ex.: BaseException rara).
        if job.get("status") == "running":
            job["status"] = "error"
            job["error"] = job.get("error") or "download interrompido inesperadamente"


# --------------------------------------------------------------------------- #
# Página (servida pelo BFF; o front só consome /api/*)
# --------------------------------------------------------------------------- #
PAGE = r"""
<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Offtape</title>
<style>
  :root{--bg:#0f0f10;--card:#181818;--card2:#202020;--line:#2a2a2a;--green:#1db954;
        --txt:#eaeaea;--mut:#9aa0a6;color-scheme:dark;}
  *{box-sizing:border-box}
  body{font-family:-apple-system,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);
       color:var(--txt);margin:0;padding:0;}
  .wrap{max-width:920px;margin:0 auto;padding:20px 18px 60px;}
  header{display:flex;align-items:center;gap:12px;padding:14px 0;position:sticky;top:0;
         background:linear-gradient(var(--bg),var(--bg) 70%,transparent);z-index:5;}
  header h1{font-size:1.15rem;margin:0;flex:1;}
  .me{display:flex;align-items:center;gap:8px;font-size:.9rem;color:var(--mut);}
  .me img{width:30px;height:30px;border-radius:50%;object-fit:cover;background:#333;}
  a{color:var(--green);text-decoration:none;} a:hover{text-decoration:underline;}
  .btn{background:var(--green);color:#06210f;border:0;border-radius:999px;padding:9px 16px;
       font-weight:700;cursor:pointer;font-size:.9rem;white-space:nowrap;}
  .btn:disabled{opacity:.5;cursor:default;}
  .btn.ghost{background:transparent;color:var(--txt);border:1px solid var(--line);}
  .btn.ghost.active{border-color:var(--green);color:var(--green);}
  .toolbar{display:flex;gap:8px;align-items:center;margin:6px 0 14px;flex-wrap:wrap;}
  input[type=search]{flex:1;min-width:180px;background:var(--card2);border:1px solid var(--line);
       color:var(--txt);border-radius:10px;padding:10px 12px;font-size:.95rem;}
  .count{color:var(--mut);font-size:.82rem;}
  .card{display:flex;align-items:center;gap:12px;padding:10px 12px;border:1px solid var(--line);
        border-radius:12px;margin:8px 0;background:var(--card);transition:border-color .15s;}
  .card:hover{border-color:#3a3a3a;}
  .card img{width:52px;height:52px;border-radius:8px;object-fit:cover;background:#2a2a2a;flex:none;}
  .meta{flex:1;min-width:0;} .meta b{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .meta small{color:var(--mut);} .badge{font-size:.68rem;background:#0c2a16;color:var(--green);
        border:1px solid #20492f;border-radius:6px;padding:1px 6px;margin-left:6px;}
  .acts{display:flex;gap:6px;flex:none;}
  .muted{color:var(--mut);} .center{text-align:center;padding:30px 0;}
  .spin{width:18px;height:18px;border:3px solid #444;border-top-color:var(--green);
        border-radius:50%;display:inline-block;animation:r .7s linear infinite;vertical-align:-3px;}
  @keyframes r{to{transform:rotate(360deg)}}
  details.hist{margin-top:26px;border-top:1px solid var(--line);padding-top:14px;}
  details.hist summary{cursor:pointer;font-weight:600;}
  .hrow{display:flex;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid #1e1e1e;font-size:.88rem;}
  .hrow code{font-size:.78rem;}
  code{background:#222;padding:2px 6px;border-radius:5px;word-break:break-all;}
  /* modal */
  .modal{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;align-items:center;
         justify-content:center;padding:18px;z-index:10;}
  .modal.open{display:flex;}
  .sheet{background:#161616;border:1px solid var(--line);border-radius:14px;max-width:520px;width:100%;
         max-height:80vh;overflow:auto;padding:18px;}
  .sheet h3{margin:.2rem 0 .2rem;overflow-wrap:anywhere;}
  .sheet, #m-body{overflow-wrap:anywhere;word-break:break-word;}
  .mhead{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px;}
  .trow{display:flex;justify-content:space-between;gap:10px;
         padding:7px 0;border-bottom:1px solid #202020;font-size:.9rem;line-height:1.35;}
  .trow .d{color:var(--mut);flex:none;}
  .errbox{background:#2a1414;border:1px solid #5a2a2a;color:#ffd9d9;border-radius:10px;
          padding:12px;font-size:.9rem;}
  .pager{position:sticky;bottom:-18px;background:#161616;display:flex;align-items:center;
         justify-content:space-between;gap:10px;padding:12px 0 2px;margin-top:10px;
         border-top:1px solid var(--line);}
  .pager .muted{font-size:.85rem;text-align:center;flex:1;}
  /* toast */
  #toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%) translateY(20px);
         background:#0c2a16;border:1px solid var(--green);color:#eafff1;padding:14px 20px;
         border-radius:12px;font-size:.98rem;font-weight:600;display:none;z-index:30;max-width:90%;
         box-shadow:0 10px 30px rgba(0,0,0,.5);opacity:0;transition:opacity .25s,transform .25s;}
  #toast.show{display:block;opacity:1;transform:translateX(-50%) translateY(0);}
  #toast.err{background:#2a1414;border-color:#c0504d;color:#ffe1e1;}
  .hrow .acts{display:flex;gap:6px;flex:none;align-items:center;flex-wrap:wrap;justify-content:flex-end;}
  .hrow .prog{font-size:.82rem;color:var(--green);}
  .drivebar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0 4px;font-size:.88rem;}
  select{background:var(--card2);border:1px solid var(--line);color:var(--txt);
         border-radius:8px;padding:7px 10px;font-size:.88rem;}
</style></head><body><div class="wrap">

<header>
  <h1>📼 Offtape <span class="muted" style="font-size:.8rem;font-weight:400">sua playlist, offline</span></h1>
  <div id="who" class="me"></div>
</header>

{% if not logged_in %}
  {% if not has_client_id %}
    <p class="muted">⚠️ Falta o <b>Client ID</b> do Spotify: crie o <code>spotify_app/config.json</code>
       com seu Client ID (ou defina <code>SPOTIFY_CLIENT_ID</code>) — veja
       <code>README.md</code> → Instalação ou <code>docs/GUIA_DE_USO.md</code>.</p>
  {% else %}
    <p class="muted">Conecte sua conta do Spotify para listar suas playlists.</p>
    <a class="btn" href="{{ url_for('login') }}">Conectar com Spotify</a>
  {% endif %}
{% else %}
  <div class="toolbar">
    <input id="q" type="search" placeholder="Buscar playlist…" autocomplete="off">
    <button class="btn ghost active" id="f-all" data-f="all">Todas</button>
    <button class="btn ghost" id="f-mine" data-f="mine">Minhas</button>
  </div>
  <div id="count" class="count"></div>
  <div id="list"><div class="center muted"><span class="spin"></span> carregando playlists…</div></div>

  <details class="hist" id="histbox">
    <summary>Histórico de gerações</summary>
    <div class="drivebar">
      <span class="muted">Pen drive / volume externo:</span>
      <select id="drive"><option value="">—</option></select>
      <button class="btn ghost" id="reloadDrives">atualizar</button>
    </div>
    <div id="hist" class="muted" style="padding-top:8px">…</div>
  </details>
{% endif %}

</div>

<div class="modal" id="modal"><div class="sheet">
  <div class="mhead">
    <h3 id="m-title">Faixas</h3>
    <button class="btn ghost" id="m-close">fechar</button>
  </div>
  <div id="m-body" class="muted">…</div>
</div></div>
<div id="toast"></div>

<script nonce="{{ nonce }}">
// ---- Utilitários: seletor, escape de HTML, imagem segura, duração, toast ----
// Todo texto dinâmico que entra em innerHTML passa por esc().
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeImg = u => (typeof u === 'string' && u.startsWith('https://')) ? esc(u) : '';
let ALL = [], filter = 'all', me = null;

function fmt(sec){ if(!sec) return ''; const m=Math.floor(sec/60), s=sec%60; return m+':'+String(s).padStart(2,'0'); }
let toastTimer=null;
function toast(msg, type){ const t=$('#toast'); t.textContent=msg; t.classList.toggle('err', type==='err');
  t.classList.add('show'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>t.classList.remove('show'), 6000); }

// ---- Inicialização: perfil, playlists, histórico e filtros ----
async function boot(){
  try { me = await (await fetch('/api/me')).json(); }
  catch(e){ me = {}; }
  if(me && me.name){
    const img = safeImg(me.image);
    $('#who').innerHTML = `${img?`<img src="${img}" alt="">`:''}<span>${esc(me.name)}</span> · <a href="/logout">sair</a>`;
  }
  await loadPlaylists();
  loadHistory();
  $('#q').addEventListener('input', render);
  document.querySelectorAll('[data-f]').forEach(b=>b.onclick=()=>{
    filter=b.dataset.f; $('#f-all').classList.toggle('active',filter==='all');
    $('#f-mine').classList.toggle('active',filter==='mine'); render();
  });
}

// ---- Lista de playlists (busca + filtro "Minhas") ----
async function loadPlaylists(){
  const r = await fetch('/api/playlists'); const d = await r.json();
  if(d.error){ $('#list').innerHTML = `<p class="muted">Erro: ${esc(d.error)}. Tente <a href="/login">reconectar</a>.</p>`; return; }
  ALL = d.items; render();
}

function render(){
  const q = ($('#q').value||'').toLowerCase();
  let rows = ALL.filter(p => p.name.toLowerCase().includes(q) || (p.owner||'').toLowerCase().includes(q));
  if(filter==='mine') rows = rows.filter(p => p.mine);
  $('#count').textContent = `${rows.length} playlist(s)`;
  const list = $('#list');
  if(!rows.length){ list.innerHTML = '<p class="muted center">Nenhuma playlist encontrada.</p>'; return; }
  list.innerHTML = '';
  rows.forEach(p=>{
    const div = document.createElement('div'); div.className='card';
    div.innerHTML = `<img src="${safeImg(p.image)}" alt="">
      <div class="meta"><b>${esc(p.name)}${p.mine?'<span class="badge">minha</span>':''}</b>
      <small>${esc(p.tracks)} faixas · ${esc(p.owner)||'—'}</small></div>`;
    // Botões criados via DOM (sem onclick inline com dados interpolados).
    const acts = document.createElement('div'); acts.className='acts';
    const prev = document.createElement('button'); prev.className='btn ghost'; prev.textContent='Ver faixas';
    prev.onclick = ()=>preview(p);
    const gen = document.createElement('button'); gen.className='btn'; gen.textContent='Gerar';
    gen.onclick = ()=>generate(p, gen);
    acts.append(prev, gen); div.appendChild(acts); list.appendChild(div);
  });
}

// ---- Modal de pré-visualização (paginação offset/limit) ----
let pv = {pid:null, limit:50, offset:0, total:0};

async function preview(p){
  pv = {pid:p.id, limit:50, offset:0, total:0};
  $('#m-title').textContent = p.name;
  $('#modal').classList.add('open');
  loadPage(0);
}
async function loadPage(offset){
  $('#m-body').innerHTML = '<div class="center"><span class="spin"></span></div>';
  let d;
  try { d = await (await fetch(`/api/playlist/${encodeURIComponent(pv.pid)}/preview?offset=${offset}&limit=${pv.limit}`)).json(); }
  catch(e){ $('#m-body').innerHTML = `<div class="errbox">Falha de rede: ${esc(e)}</div>`; return; }
  if(d.error){ $('#m-body').innerHTML = `<div class="errbox">${esc(d.error)}</div>`; return; }
  pv.offset = d.offset; pv.total = d.total;
  const rows = d.tracks.map((t,i)=>
    `<div class="trow"><span>${esc(d.offset+i+1)}. <b>${esc(t.title)}</b> — ${esc(t.artist)}</span>`
    + `<span class="d">${esc(fmt(t.duration))}</span></div>`).join('');
  const from = d.total ? d.offset+1 : 0, to = d.offset + d.tracks.length;
  const nav = `<div class="pager">
      <button class="btn ghost" id="prev" ${d.offset<=0?'disabled':''}>← Anterior</button>
      <span class="muted">${esc(from)}–${esc(to)} de ${esc(d.total)}</span>
      <button class="btn ghost" id="next" ${!d.has_more?'disabled':''}>Próxima →</button>
    </div>`;
  $('#m-body').innerHTML = (rows || '<p class="muted">Sem faixas nesta página.</p>') + nav;
  const pb=$('#prev'), nb=$('#next');
  if(pb && !pb.disabled) pb.onclick = ()=>loadPage(Math.max(0, d.offset - pv.limit));
  if(nb && !nb.disabled) nb.onclick = ()=>loadPage(d.offset + pv.limit);
  $('#m-body').scrollTop = 0;
}
function closeModal(){ $('#modal').classList.remove('open'); }
$('#m-close').addEventListener('click', closeModal);
$('#modal').addEventListener('click', e=>{ if(e.target.id==='modal') closeModal(); });

// ---- Geração do tracks.json (POST JSON) ----
async function generate(p, btn){
  btn.disabled = true; const old = btn.textContent; btn.innerHTML = '<span class="spin"></span>';
  try{
    const d = await (await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},
      body: JSON.stringify({id:p.id, name:p.name, owner:p.owner})})).json();
    if(d.error){ toast('Erro: '+d.error); }
    else { toast(`✅ ${d.count} faixas salvas`); loadHistory(); }
  }catch(e){ toast('Erro: '+e); }
  btn.disabled = false; btn.textContent = old;
}

// ---- Histórico e seletor de pen drive ----
let drivesLoaded = false;
async function loadDrives(){
  const sel = $('#drive'); if(!sel) return;
  const cur = sel.value;
  let d; try { d = await (await fetch('/api/drives')).json(); } catch(e){ return; }
  sel.innerHTML = '<option value="">—</option>' +
    (d.items||[]).map(x=>`<option value="${esc(x.path)}">${esc(x.name)} (${esc(x.free_gb)} GB livres)</option>`).join('');
  if(cur) sel.value = cur;
}

async function loadHistory(){
  const box = $('#hist'); const d = await (await fetch('/api/history')).json();
  if(!drivesLoaded){ drivesLoaded = true; loadDrives(); const rb=$('#reloadDrives'); if(rb) rb.onclick = loadDrives; }
  if(!d.items || !d.items.length){ box.innerHTML = '<span class="muted">Nenhuma geração ainda.</span>'; return; }
  box.innerHTML = '';
  d.items.forEach(h=>{
    // O backend monta o comando (caminhos absolutos, --out da playlist; aspas no
    // formato do shell do SO: shlex.quote no macOS/Linux, list2cmdline no Windows).
    const cmd = h.cmd || `python download_playlist.py --tracks "${h.json_path}"`;
    const row = document.createElement('div'); row.className='hrow';
    row.innerHTML = `<div style="flex:1;min-width:0">
      <b>${esc(h.playlist_name)}</b><br>
      <span class="muted">${esc(h.track_count)} faixas · ${esc(h.fetched_at).replace('T',' ')}</span></div>`;
    const acts = document.createElement('div'); acts.className='acts';
    const prog = document.createElement('span'); prog.className='prog';
    const dl = document.createElement('button'); dl.className='btn'; dl.dataset.label='Baixar MP3'; dl.textContent='Baixar MP3';
    dl.onclick = ()=>startDownload(h.json_path, dl, prog);
    const ex = document.createElement('button'); ex.className='btn ghost'; ex.dataset.label='→ Pen drive'; ex.textContent='→ Pen drive';
    ex.title = 'Copia esta playlist (já baixada) para o pen drive/volume externo selecionado';
    ex.onclick = ()=>startExport(h.json_path, ex, prog);
    const cp = document.createElement('button'); cp.className='btn ghost'; cp.textContent='copiar comando';
    cp.title = 'Copia o comando para rodar no terminal, se preferir';
    cp.onclick = ()=>copy(cmd);
    acts.append(prog, dl, ex, cp); row.appendChild(acts); box.appendChild(row);
  });
}
function copy(text){ navigator.clipboard.writeText(text).then(()=>toast('Comando copiado!')); }

// ---- Jobs em background: download, exportação e polling de status ----
async function startDownload(jsonPath, btn, prog){
  btn.disabled = true; btn.textContent = 'Iniciando…';   // anti-duplo-clique
  let r;
  try { r = await (await fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({json_path: jsonPath})})).json(); }
  catch(e){ toast('Erro ao iniciar: '+e,'err'); btn.disabled=false; btn.textContent=btn.dataset.label; return; }
  if(r.error){ toast('Erro: '+r.error,'err'); btn.disabled=false; btn.textContent=btn.dataset.label; return; }
  toast(r.reused ? 'Download já em andamento.' : 'Download iniciado…');
  pollJob(r.job_id, btn, prog, 'Baixando', 'baixadas');
}

async function startExport(jsonPath, btn, prog){
  const drive = $('#drive').value;
  if(!drive){ toast('Escolha o pen drive no seletor acima (clique "atualizar" se não aparecer).','err'); return; }
  btn.disabled = true; btn.textContent = 'Iniciando…';
  let r;
  try { r = await (await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({json_path: jsonPath, drive})})).json(); }
  catch(e){ toast('Erro ao iniciar: '+e,'err'); btn.disabled=false; btn.textContent=btn.dataset.label; return; }
  if(r.error){ toast('Erro: '+r.error,'err'); btn.disabled=false; btn.textContent=btn.dataset.label; return; }
  toast(r.reused ? 'Cópia já em andamento.' : 'Copiando para o pen drive…');
  pollJob(r.job_id, btn, prog, 'Copiando', 'copiadas');
}

async function pollJob(jid, btn, prog, verb, doneWord){
  btn.textContent = verb+'…';
  const tick = async ()=>{
    let j;
    try { j = await (await fetch(`/api/job/${encodeURIComponent(jid)}`)).json(); }
    catch(e){ setTimeout(tick, 2000); return; }
    if(j.error){ toast('Erro: '+j.error,'err'); btn.disabled=false; btn.textContent=btn.dataset.label; return; }
    prog.textContent = j.total ? `${j.done}/${j.total}` : '';
    if(j.status === 'running'){ btn.textContent = `${verb} ${j.done}/${j.total||'…'}`; setTimeout(tick, 1200); return; }
    if(j.status === 'error'){ toast('Falhou: '+(j.error||'erro'),'err'); }
    else { toast(`✅ Concluído: ${j.ok} ${doneWord} · ${j.skipped} já existiam · ${j.failed} falhas`); }
    prog.textContent = '';
    btn.disabled = false; btn.textContent = btn.dataset.label;
  };
  tick();
}

// Só há lista/histórico quando logado; sem isso não há o que iniciar.
if($('#list')) boot();
</script>
</body></html>
"""


# --------------------------------------------------------------------------- #
# Rotas de página / auth
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    """Serve a página única da aplicação.

    Gera um nonce por requisição para o ``<script>`` inline; o mesmo valor vai
    no cabeçalho CSP (ver ``security_headers``).
    """
    g.csp_nonce = secrets.token_urlsafe(16)
    return render_template_string(PAGE, logged_in=token_valid(),
                                  has_client_id=bool(CLIENT_ID), nonce=g.csp_nonce)


@app.route("/login")
def login():
    """Inicia o OAuth: gera PKCE + state e redireciona ao Spotify.

    Returns:
        Redirecionamento para a tela de autorização do Spotify, ou 400 se o
        Client ID não estiver configurado.
    """
    if not CLIENT_ID:
        return "Falta SPOTIFY_CLIENT_ID. Veja o README.", 400
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)          # amarra o callback a esta sessão
    session["pkce_verifier"] = verifier
    session["oauth_state"] = state
    params = {
        "client_id": CLIENT_ID, "response_type": "code", "redirect_uri": REDIRECT_URI,
        "scope": SCOPES, "code_challenge_method": "S256",
        "code_challenge": challenge, "state": state,
    }
    return redirect(f"{AUTH_URL}?{urlencode(params)}")


@app.route("/callback")
def callback():
    """Recebe o retorno do OAuth e troca o ``code`` pelos tokens.

    Returns:
        Redirecionamento para ``/`` com a sessão preenchida, ou 400 com uma
        mensagem curta se o usuário negou, o state não confere ou a troca falhou.
    """
    if request.args.get("error"):
        return f"Spotify negou: {escape(clip_text(request.args['error'], 100))}", 400
    # state e verifier são de uso único: saem da sessão já na 1ª tentativa
    # (mesmo que falhe), então um callback repetido/forjado não os reaproveita.
    # A comparação é em tempo constante (compare_digest sobre bytes, pois com
    # str ele recusa caracteres não ASCII).
    expected = session.pop("oauth_state", None) or ""
    verifier = session.pop("pkce_verifier", None) or ""
    got = request.args.get("state") or ""
    if not expected or not verifier or not secrets.compare_digest(
            got.encode("utf-8"), expected.encode("utf-8")):
        return "state inválido (possível CSRF). Tente de novo.", 400
    try:
        r = requests.post(TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": request.args.get("code"),
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
        }, timeout=HTTP_TIMEOUT)
    except requests.RequestException:
        return "Falha de rede ao trocar o token. Tente de novo.", 502
    if r.status_code != 200:
        return f"Falha ao trocar o token (HTTP {r.status_code}). Tente de novo.", 400
    tok = r.json()
    session.permanent = True
    session["access_token"] = tok["access_token"]
    session["refresh_token"] = tok.get("refresh_token")
    session["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    session.pop("me", None)
    return redirect(url_for("index"))


@app.route("/logout", methods=["GET", "POST"])
def logout():
    """Limpa a sessão (tokens e perfil) e volta para a página inicial.

    Aceita GET (link "sair" da página) e POST (JSON, sujeito ao anti-CSRF).
    """
    session.clear()
    return redirect(url_for("index"))


# --------------------------------------------------------------------------- #
# API (BFF) — o front só consome estes endpoints
# --------------------------------------------------------------------------- #
@app.route("/api/me")
def api_me():
    """Retorna o perfil do usuário logado.

    Returns:
        JSON ``{id, name, image}`` ou ``{error}``.
    """
    try:
        return jsonify(current_user())
    except Exception as e:
        msg, code = err_info(e)
        return jsonify({"error": msg}), code


@app.route("/api/playlists")
def api_playlists():
    """Lista todas as playlists do usuário (seguindo a paginação).

    Returns:
        JSON ``{items: [{id, name, owner, mine, tracks, image}]}`` ou ``{error}``.
    """
    try:
        my_id = current_user().get("id", "")
        items, offset = [], 0
        while True:
            data = api_get("/me/playlists", {"limit": 50, "offset": offset})
            for p in data.get("items", []):
                if not p:
                    continue
                imgs = p.get("images") or []
                # 'tracks' está obsoleto na API; o total agora vem em 'items'.
                count_obj = p.get("items") or p.get("tracks") or {}
                owner = p.get("owner") or {}
                items.append({
                    "id": p["id"],
                    "name": p["name"],
                    "owner": owner.get("display_name", ""),
                    "mine": owner.get("id") == my_id,
                    "tracks": count_obj.get("total", 0),
                    "image": imgs[0]["url"] if imgs else "",
                })
            if not data.get("next"):
                break
            offset += 50
        return jsonify({"items": items})
    except Exception as e:
        msg, code = err_info(e)
        return jsonify({"error": msg}), code


@app.route("/api/playlist/<pid>/preview")
def api_preview(pid):
    """Retorna uma página de faixas de uma playlist.

    Args:
        pid: Id da playlist (base62, validado antes de chegar ao Spotify).

    Query:
        offset: Início da página (0..MAX_OFFSET, padrão 0).
        limit: Tamanho da página (1..50, padrão 50).

    Returns:
        JSON ``{total, offset, limit, has_more, tracks}`` ou ``{error}``.
    """
    if not valid_playlist_id(pid):
        return jsonify({"error": "id de playlist inválido"}), 400
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 50))
        offset = max(0, min(int(request.args.get("offset", 0)), MAX_OFFSET))
    except (TypeError, ValueError):
        return jsonify({"error": "offset/limit inválidos"}), 400
    try:
        data = api_get(f"/playlists/{pid}/items", {
            "limit": limit, "offset": offset,
            "fields": "total,items(item(name,duration_ms,artists(name),type))",
        })
        tracks = [t for t in (parse_track_item(it) for it in data.get("items", [])) if t]
        total = data.get("total", offset + len(tracks))
        return jsonify({
            "total": total, "offset": offset, "limit": limit,
            "has_more": offset + limit < total, "tracks": tracks,
        })
    except Exception as e:
        msg, code = err_info(e)
        return jsonify({"error": msg}), code


@app.route("/api/history")
def api_history():
    """Lista as 50 gerações mais recentes do histórico.

    Returns:
        JSON ``{items: [{playlist_name, owner, fetched_at, track_count,
        json_path, cmd}]}``, onde ``cmd`` é o comando de terminal equivalente
        ao botão "Baixar MP3" (mesma pasta ``OUT_DIR/<slug>``).
    """
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT playlist_name, owner, fetched_at, track_count, json_path"
                " FROM snapshots ORDER BY id DESC LIMIT 50"
            ).fetchall()
        items = []
        for r in rows:
            item = dict(r)
            item["cmd"] = download_command(item["json_path"])
            items.append(item)
        return jsonify({"items": items})
    except Exception as e:
        msg, code = err_info(e)
        return jsonify({"error": msg}), code


@app.route("/api/download", methods=["POST"])
def api_download():
    """Inicia (ou reaproveita) um job de download para um tracks.json.

    Body JSON:
        json_path: Caminho de um ``.json`` dentro de ``TRACKS_DIR``.

    Returns:
        JSON ``{job_id, reused}`` ou ``{error}`` com 400 (inclusive quando o
        ffmpeg não está instalado; a mensagem diz como instalar em cada SO).
    """
    body = json_body()
    if body is None:
        return jsonify({"error": "corpo JSON inválido"}), 400
    json_path = resolve_tracks_json(body.get("json_path"))
    if not json_path:
        return jsonify({"error": "arquivo tracks.json não encontrado"}), 400
    if not ffmpeg_ok():
        return jsonify({"error": FFMPEG_MISSING_MSG}), 400
    try:
        with JOBS_LOCK:
            # Dedup / anti-duplo-clique: se já há job rodando p/ esse arquivo,
            # devolve o mesmo id em vez de baixar tudo em dobro.
            for jid, j in JOBS.items():
                if j.get("json_path") == json_path and j["status"] == "running":
                    return jsonify({"job_id": jid, "reused": True})
            jid = uuid.uuid4().hex[:8]
            # Todas as chaves já existem: os workers só alteram valores, nunca
            # o tamanho do dict (seguro para a cópia em api_job_status).
            job = {"id": jid, "kind": "download", "json_path": json_path, "status": "running",
                   "total": 0, "done": 0, "ok": 0, "skipped": 0, "failed": 0, "current": "",
                   "error": "", "out_dir": "", "report": "", "cancel": False}
            JOBS[jid] = job
        threading.Thread(target=run_download_job, args=(job,), daemon=True).start()
        return jsonify({"job_id": jid, "reused": False})
    except Exception as e:
        msg, code = err_info(e)
        return jsonify({"error": msg}), code


@app.route("/api/download/<jid>")
@app.route("/api/job/<jid>")
def api_job_status(jid):
    """Retorna o estado atual de um job de download ou exportação.

    Args:
        jid: Id do job devolvido por ``/api/download`` ou ``/api/export``.

    Returns:
        JSON com os campos do job, ou ``{error}`` com 404.
    """
    # Cópia rasa tirada sob o lock: o jsonify não itera um dict em mutação.
    with JOBS_LOCK:
        j = JOBS.get(jid)
        snap = dict(j) if j else None
    if not snap:
        return jsonify({"error": "job não encontrado"}), 404
    return jsonify(snap)


@app.route("/api/drives")
def api_drives():
    """Lista os pen drives/volumes externos disponíveis para exportação.

    A detecção depende do sistema (ver ``list_drives``):

    - macOS: diretórios em ``/Volumes``, exceto o disco de boot.
    - Linux: pontos de montagem de ``/proc/mounts`` sob ``/media/``,
      ``/run/media/`` ou ``/mnt/``.
    - Windows: unidades removíveis (``DRIVE_REMOVABLE``), nunca a do sistema;
      o nome inclui o rótulo, ex. ``E:\\ (MEU_PENDRIVE)``.

    Returns:
        JSON ``{items: [{name, path, free_gb, total_gb}]}`` (vazio em outros
        sistemas ou sem volumes plugados).
    """
    return jsonify({"items": list_drives()})


@app.route("/api/export", methods=["POST"])
def api_export():
    """Copia a playlist já baixada para um pen drive, em subpasta própria.

    Body JSON:
        json_path: Caminho de um ``.json`` dentro de ``TRACKS_DIR``.
        drive: Um dos ``path`` retornados por ``/api/drives``.

    Returns:
        JSON ``{job_id, reused, dest}`` ou ``{error}`` com 400.
    """
    body = json_body()
    if body is None:
        return jsonify({"error": "corpo JSON inválido"}), 400
    raw_json_path = body.get("json_path")
    json_path = resolve_tracks_json(raw_json_path)
    if not json_path:
        return jsonify({"error": "tracks.json não encontrado"}), 400
    drive_in = body.get("drive")
    # Compara normcase(realpath()) dos dois lados: no Windows "e:\" == "E:\".
    drives = set()
    for d in list_drives():
        try:
            drives.add(_norm(d["path"]))
        except (ValueError, OSError):
            continue
    try:
        drive_ok = isinstance(drive_in, str) and bool(drive_in) and _norm(drive_in) in drives
    except (ValueError, OSError):
        drive_ok = False
    if not drive_ok:
        return jsonify({"error": "destino inválido — plugue o pen drive e atualize"}), 400
    drive = os.path.realpath(drive_in)
    try:
        slug = slug_from_json(json_path)
        src = playlist_out_dir(json_path)
        if (not _is_within(src, OUT_DIR) or _norm(src) == _norm(OUT_DIR)
                or not os.path.isdir(src)
                or not any(f.endswith(".mp3") for f in os.listdir(src))):
            return jsonify({"error": "baixe a playlist primeiro (sem MP3 para copiar)"}), 400

        # Nome da pasta vem do nome real da playlist (snapshot), no formato FAT32.
        pname = slug
        try:
            with db() as conn:
                row = conn.execute("SELECT playlist_name FROM snapshots WHERE json_path IN (?, ?)"
                                   " ORDER BY id DESC LIMIT 1",
                                   (raw_json_path, json_path)).fetchone()
                if row:
                    pname = row["playlist_name"]
        except sqlite3.Error:
            pass
        dst = os.path.join(drive, fat_dirname(pname))
        if not _is_within(dst, drive) or _norm(dst) == _norm(drive):
            return jsonify({"error": "destino inválido"}), 400

        with JOBS_LOCK:
            # Dedup: um único job de cópia por pasta de destino por vez.
            for jid, j in JOBS.items():
                if j.get("kind") == "export" and j.get("dst") == dst and j["status"] == "running":
                    return jsonify({"job_id": jid, "reused": True, "dest": dst})
            jid = uuid.uuid4().hex[:8]
            job = {"id": jid, "kind": "export", "src": src, "dst": dst, "drive": drive,
                   "status": "running",
                   "total": 0, "done": 0, "ok": 0, "skipped": 0, "failed": 0, "current": "",
                   "error": "", "cancel": False}
            JOBS[jid] = job
        threading.Thread(target=run_export_job, args=(job,), daemon=True).start()
        return jsonify({"job_id": jid, "reused": False, "dest": dst})
    except Exception as e:
        msg, code = err_info(e)
        return jsonify({"error": msg}), code


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Gera o tracks.json de uma playlist e registra o snapshot no histórico.

    Body JSON:
        id: Id da playlist (base62).
        name: Nome da playlist (usado no slug do arquivo; até 200 caracteres).
        owner: Nome do dono (opcional; até 200 caracteres).

    Returns:
        JSON ``{count, json_path}`` ou ``{error}``.
    """
    body = json_body()
    if body is None:
        return jsonify({"error": "corpo JSON inválido"}), 400
    pid = body.get("id")
    if not valid_playlist_id(pid):
        return jsonify({"error": "id de playlist inválido"}), 400
    name = clip_text(body.get("name")).strip()
    if not name:
        return jsonify({"error": "nome da playlist ausente"}), 400
    playlist = {"id": pid, "name": name, "owner": clip_text(body.get("owner"))}
    try:
        tracks = fetch_all_tracks(playlist["id"])
        if not tracks:
            return jsonify({"error": "playlist sem faixas legíveis"}), 400

        os.makedirs(TRACKS_DIR, exist_ok=True)
        fname = f"{date.today().isoformat()}_{slugify(playlist['name'])}.json"
        json_path = os.path.join(TRACKS_DIR, fname)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(tracks, f, ensure_ascii=False, indent=2)

        save_snapshot(playlist, tracks, json_path)
        return jsonify({"count": len(tracks), "json_path": json_path})
    except Exception as e:
        msg, code = err_info(e)
        return jsonify({"error": msg}), code


if __name__ == "__main__":
    # Consoles legados do Windows (cp1252/cp850) não codificam emoji/acentos e
    # o print levantaria UnicodeEncodeError; com "replace" vira "?" e segue.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass
    init_db()
    print(f"\n  Abra:  http://{HOST}:{PORT}\n")
    if not CLIENT_ID:
        print("  ⚠️  Client ID não configurado: crie o spotify_app/config.json com seu Client ID\n"
              "      (veja README → Instalação ou docs/GUIA_DE_USO.md).\n")
    app.run(host=HOST, port=PORT, debug=False)
