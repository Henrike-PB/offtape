#!/usr/bin/env python3
"""Baixa as faixas de uma playlist como MP3 buscando o áudio oficial no YouTube.

Lê um ``tracks.json`` (lista de objetos ``{"n", "title", "artist", "duration"}``,
gerado pelo ``make_tracks.py``), busca cada faixa no YouTube com o yt-dlp,
pontua os candidatos para priorizar o áudio oficial (canais "Artista - Topic",
"official audio", duração compatível) e penaliza versões ao vivo, covers,
remixes e videoclipes. Se o melhor candidato estiver indisponível, tenta o
próximo. O áudio é baixado em ``bestaudio`` e convertido para MP3 pelo ffmpeg.

Fluxo::

    tracks.json -> busca no YouTube (yt-dlp) -> pontua e ordena candidatos
                -> baixa bestaudio -> converte para MP3 (ffmpeg)
                -> grava tags ID3 (opcional) -> relatório CSV

Execução em lotes (batches) com pausas entre eles, para reduzir o risco de
bloqueio pelo YouTube. É retomável: faixas cujo MP3 já existe são puladas.
Ao final, gera um relatório CSV com data e hora no nome.

Requisitos:
    - Python 3.9+ e ``pip install yt-dlp``
    - ffmpeg instalado e no PATH:
        - macOS: ``brew install ffmpeg``
        - Windows: ``winget install Gyan.FFmpeg`` (depois reabra o terminal)
        - Linux: ``sudo apt install ffmpeg`` (ou ``dnf``/``pacman``)
    - Opcional: ``pip install mutagen`` para gravar as tags ID3 (título/artista)

Compatibilidade:
    macOS, Linux e Windows. Os caminhos padrão são montados com
    ``os.path.join`` a partir da pasta do script, e ``--tracks``/``--out``/
    ``--reports-dir`` aceitam caminhos do sistema (inclusive ``C:\\...`` no
    Windows). Os arquivos são lidos/gravados em UTF-8 e a saída do console
    troca caracteres não suportados por ``?`` (consoles legados do Windows,
    como cp1252/cp850), em vez de falhar.

Uso:
    python3 download_playlist.py                        # baixa tudo
    python3 download_playlist.py --dry-run              # só mostra as escolhas
    python3 download_playlist.py --start 1 --end 20     # só as faixas 1 a 20
    python3 download_playlist.py --batch-size 10 --batch-pause 30
    python3 download_playlist.py --cookies-from-browser firefox

    Por padrão, lê ``tracks.json`` da pasta do script, salva os MP3 em
    ``exported-musics/`` e os relatórios em ``relatorios/``, ambos também na
    pasta do script.

Funções reutilizáveis (importáveis por outros programas, ex.: o app web):
    download_one(track, out_dir, ...): baixa uma faixa completa (busca,
        fallback de candidatos, conversão e tags) e devolve um dict de status.
    search_candidates(track, n_results, ...): busca e devolve os candidatos
        ordenados do melhor para o pior.
    score_entry(entry, track): pontua um candidato em relação a uma faixa.
    sanitize_filename(name): limpa um texto para uso como nome de arquivo.
    load_tracks(path): lê e valida um tracks.json (formato inesperado vira
        ``ValueError`` legível, não traceback no meio do download).
    ffmpeg_available(): indica se o ffmpeg foi encontrado no PATH.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import time
import random

_YTDLP_MISSING_MSG = "yt-dlp não instalado. Rode: pip install -r requirements.txt"

try:
    import yt_dlp
except ImportError as _e:
    # Rodando como script: mensagem amigável e código de saída 1.
    # Importado como módulo (ex.: pelo app web): levanta ImportError em vez de
    # SystemExit, que mataria threads silenciosamente.
    if __name__ == "__main__":
        sys.exit(_YTDLP_MISSING_MSG)
    raise ImportError(_YTDLP_MISSING_MSG) from _e


# --------------------------------------------------------------------------- #
# Utilitários
# --------------------------------------------------------------------------- #
def sanitize_filename(name: str) -> str:
    """Converte um texto em um nome de arquivo seguro.

    Remove caracteres de controle, troca caracteres inválidos em sistemas de
    arquivos por ``-``, colapsa espaços em branco e limita o tamanho a 180
    caracteres e a 200 bytes em UTF-8. O limite em bytes protege contra o máximo de 255 bytes por nome de
    arquivo (títulos não latinos ocupam até 4 bytes por caractere), deixando
    folga para ``.mp3`` e sufixos temporários do yt-dlp (``.part``,
    ``.webm``). O corte nunca divide um caractere multibyte ao meio. Nomes
    dentro dos dois limites saem exatamente como antes.

    Compatibilidade com Windows: o resultado é válido também no Windows
    desde que a extensão ``.mp3`` seja acrescentada (como sempre acontece).
    Os caracteres proibidos no Windows (``\\ / : * ? " < > |`` e controles
    ``\\x00``-``\\x1f``) já são removidos/trocados; ponto ou espaço no fim do
    nome (também proibidos lá) deixam de ser o fim quando ``.mp3`` é
    acrescentado; e os nomes reservados de dispositivo (``CON``, ``NUL``,
    ``COM1`` etc.) não ocorrem, porque os nomes sempre começam com
    ``"NNN - "``. Por isso a saída não muda em relação às versões
    anteriores (arquivos já baixados continuam sendo reconhecidos). Único
    ponto de atenção: com o limite clássico de 260 caracteres por caminho
    completo (``MAX_PATH``), uma pasta de saída muito profunda somada a um
    nome muito longo pode falhar; nesse caso, use uma pasta mais curta ou
    habilite caminhos longos no Windows.

    Args:
        name: Texto de origem (ex.: ``"001 - Artista - Título"``).

    Returns:
        O nome de arquivo sanitizado, sem extensão.
    """
    # Caracteres de controle (\x00-\x1f, \x7f) nunca são úteis em nomes de arquivo.
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r'[\\/:*?"<>|]', "-", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name[:180]
    encoded = name.encode("utf-8")
    if len(encoded) > 200:
        # errors="ignore" descarta o caractere multibyte incompleto no fim.
        name = encoded[:200].decode("utf-8", errors="ignore").rstrip()
    return name


def ffmpeg_available() -> bool:
    """Indica se o ffmpeg está instalado e acessível no PATH.

    O ffmpeg é necessário para converter o áudio baixado em MP3. Usa
    ``shutil.which``, que no Windows também considera as extensões do
    ``PATHEXT`` (ex.: ``ffmpeg.exe``).

    Returns:
        ``True`` se o executável ``ffmpeg`` foi encontrado, ``False`` caso
        contrário.
    """
    return shutil.which("ffmpeg") is not None


FFMPEG_MISSING_MSG = (
    "ffmpeg não encontrado no PATH. Ele é necessário para converter o áudio em MP3.\n"
    "Instale e rode de novo:\n"
    "  - macOS:   brew install ffmpeg\n"
    "  - Windows: winget install Gyan.FFmpeg   (depois feche e reabra o terminal)\n"
    "  - Linux:   sudo apt install ffmpeg   (Fedora: sudo dnf install ffmpeg; "
    "Arch: sudo pacman -S ffmpeg)\n"
    "Dica: use --dry-run para só ver as escolhas sem baixar (não precisa do ffmpeg)."
)


def _console_safe():
    """Evita ``UnicodeEncodeError`` ao imprimir em consoles legados.

    Em consoles antigos do Windows (cp1252/cp850), caracteres como ``↳``,
    emojis ou títulos não latinos não podem ser codificados e fariam o
    ``print`` falhar. Com ``errors="replace"``, eles viram ``?``.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass  # stream não reconfigurável (ex.: substituído por outro objeto)


def csv_safe(row: list) -> list:
    """Neutraliza "injeção de fórmula" antes de gravar uma linha em CSV.

    Títulos vêm do Spotify/YouTube (texto de terceiros). Se um valor começar
    com ``= + - @`` (ou tab/CR), Excel/Sheets podem interpretá-lo como fórmula
    ao abrir o relatório. Prefixar com ``'`` faz a planilha tratá-lo como texto.

    Args:
        row: Valores de uma linha do relatório.

    Returns:
        A mesma linha, com os textos perigosos prefixados por ``'``.
    """
    out = []
    for v in row:
        if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
            v = "'" + v
        out.append(v)
    return out


def load_tracks(path: str) -> list:
    """Lê e valida um ``tracks.json``.

    O arquivo pode vir de terceiros (ou ser editado à mão); em vez de quebrar
    no meio do download com um traceback, recusa formatos inesperados logo na
    entrada. Aceita exatamente o que ``make_tracks.py`` e o app geram.

    Args:
        path: Caminho do arquivo.

    Returns:
        A lista de faixas ``{n, title, artist, duration}``.

    Raises:
        OSError: Se o arquivo não puder ser lido.
        ValueError: Se não for JSON válido ou não tiver o formato esperado
            (lista de objetos com ``n`` inteiro, ``title``/``artist`` texto e
            ``duration`` numérica ou ausente). JSON aninhado demais também
            vira ``ValueError``.
    """
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except RecursionError as e:          # JSON aninhado demais
            raise ValueError("tracks.json aninhado demais") from e
    if not isinstance(data, list):
        raise ValueError("tracks.json deve ser uma lista de faixas")
    for i, t in enumerate(data, 1):
        ok = (isinstance(t, dict)
              and isinstance(t.get("n"), int) and not isinstance(t.get("n"), bool)
              and isinstance(t.get("title"), str) and isinstance(t.get("artist"), str)
              and (t.get("duration") is None
                   or (isinstance(t.get("duration"), (int, float))
                       and not isinstance(t.get("duration"), bool))))
        if not ok:
            raise ValueError(f"faixa #{i} do tracks.json inválida "
                             "(esperado n inteiro, title/artist texto, duration número)")
    return data


def norm(s: str) -> str:
    """Normaliza um texto para comparação aproximada.

    Converte para minúsculas e substitui qualquer sequência de caracteres fora
    de ``[a-z0-9]`` por um único espaço.

    Args:
        s: Texto a normalizar (``None`` é tratado como string vazia).

    Returns:
        O texto normalizado.
    """
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# Termos que indicam que o candidato NÃO é a gravação de estúdio oficial.
BAD_TERMS = [
    "live", "ao vivo", "en vivo", "performance", "session", "sessions",
    "acoustic", "acústico", "unplugged", "remix", "sped up", "speed up",
    "slowed", "reverb", "8d audio", "nightcore", "karaoke", "instrumental",
    "reaction", "react", "review", "tutorial", "how to play", "lesson",
    "1 hour", "1hour", "loop", "extended loop", "mashup", "megamix",
]
# Termos de videoclipe: preferimos o áudio, mas o clipe é aceitável se não
# houver nada melhor.
VIDEO_TERMS = [
    "official video", "official music video", "music video", "official mv",
    "videoclipe", "video clipe", "clipe oficial", "vídeo oficial", "video oficial",
]


def score_entry(entry: dict, track: dict) -> float:
    """Pontua um candidato do YouTube em relação à faixa procurada.

    Quanto maior a pontuação, mais provável que o candidato seja o áudio
    oficial da faixa. Os pesos são heurísticos: sinais de áudio oficial e
    duração compatível somam; versões alternativas (ao vivo, cover, remix
    etc.) e videoclipes subtraem.

    Args:
        entry: Resultado de busca do yt-dlp (usa ``title``, ``uploader`` ou
            ``channel`` e ``duration``).
        track: Faixa do ``tracks.json`` (usa ``title``, ``artist`` e,
            opcionalmente, ``duration`` em segundos).

    Returns:
        A pontuação do candidato (pode ser negativa).
    """
    title = (entry.get("title") or "").lower()
    uploader = (entry.get("uploader") or entry.get("channel") or "").lower()
    dur = entry.get("duration") or 0
    track_title_l = track["title"].lower()
    # Em faixas com vários artistas ("A, B"), só o primeiro costuma aparecer
    # no nome do canal/título.
    first_artist = track["artist"].split(",")[0].strip().lower()

    s = 0.0

    # --- Sinais fortes de áudio oficial ---
    # Canais "Artista - Topic" são gerados automaticamente pelo YouTube a
    # partir do catálogo das gravadoras: é o sinal mais confiável, por isso
    # o maior peso.
    if uploader.endswith("- topic"):
        s += 60
    if "official audio" in title:
        s += 35
    if re.search(r"[\(\[]\s*audio\s*[\)\]]|full audio|hq audio", title):
        s += 18
    if first_artist and first_artist in uploader:
        s += 25          # canal oficial do próprio artista
    if "vevo" in uploader:
        s += 12

    # --- Correspondência de título/artista (pesos menores: desempate) ---
    if norm(track["title"]) in norm(title):
        s += 12
    if first_artist and first_artist in title:
        s += 6

    # --- Penalidades (ignoradas se o termo faz parte do título real da faixa,
    #     ex.: uma faixa que se chama "Live Forever") ---
    for w in BAD_TERMS:
        if w in title and w not in track_title_l:
            s -= 30
    for w in VIDEO_TERMS:
        if w in title and w not in track_title_l:
            s -= 14       # penalidade leve: clipe perde para o áudio, mas serve de fallback
    if "cover" in title and "cover" not in track_title_l:
        s -= 35           # cover de terceiros, a não ser que a faixa SEJA um cover

    # --- Proximidade da duração com a original (ex.: do Spotify) ---
    # Diferenças de poucos segundos são normais (silêncio no início/fim);
    # diferenças grandes indicam versão estendida, editada ou compilação.
    target = track.get("duration") or 0
    if dur and target:
        diff = abs(dur - target)
        if diff <= 3:
            s += 28
        elif diff <= 10:
            s += 16
        elif diff <= 20:
            s += 6
        elif diff <= 45:
            s -= 8
        else:
            s -= 35       # provável versão errada / estendida / compilação

    return s


def search_candidates(track: dict, n_results: int, cookies_browser: str | None = None) -> list:
    """Busca a faixa no YouTube e devolve os candidatos ordenados.

    A busca usa ``"<artista> <título>"``. Cada candidato recebe a chave
    ``_score`` (pontuação arredondada, usada para exibição).

    Args:
        track: Faixa do ``tracks.json``.
        n_results: Quantidade de resultados da busca a avaliar.
        cookies_browser: Nome do navegador de onde ler cookies (ex.:
            ``"firefox"``), útil para vídeos com restrição de idade.
            ``None`` para não usar cookies.

    Returns:
        Lista de candidatos (dicts do yt-dlp), do melhor para o pior. Pode
        ser vazia.

    Raises:
        yt_dlp.utils.DownloadError: Em falhas de rede ou da própria busca.
    """
    query = f"{track['artist']} {track['title']}"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "default_search": "ytsearch",
        "noplaylist": True,
        # Sem isto, um único resultado indisponível/restrito aborta a busca
        # inteira. Com isto, o yt-dlp devolve None no lugar dele (filtrado
        # abaixo) e seguimos com os demais candidatos.
        "ignoreerrors": True,
    }
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n_results}:{query}", download=False)
    entries = [e for e in (info or {}).get("entries", []) if e]
    ranked = sorted(entries, key=lambda e: score_entry(e, track), reverse=True)
    for e in ranked:
        e["_score"] = round(score_entry(e, track), 1)
    return ranked


def tag_mp3(path: str, track: dict):
    """Grava as tags ID3 de título e artista no MP3.

    É opcional: se o mutagen não estiver instalado ou ocorrer qualquer erro,
    a função não faz nada (o MP3 continua válido, só sem tags).

    Args:
        path: Caminho do arquivo MP3.
        track: Faixa do ``tracks.json`` (usa ``title`` e ``artist``).
    """
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.mp3 import MP3
        try:
            audio = EasyID3(path)
        except Exception:
            # Arquivo ainda sem cabeçalho ID3: cria as tags antes de editar.
            m = MP3(path)
            m.add_tags()
            m.save()
            audio = EasyID3(path)
        audio["title"] = track["title"]
        audio["artist"] = track["artist"]
        audio.save()
    except Exception:
        pass  # mutagen ausente ou erro -> ignora


def download_track(entry: dict, out_dir: str, base_name: str, bitrate: str,
                   cookies_browser: str | None = None) -> str:
    """Baixa um candidato e converte o áudio para MP3.

    Args:
        entry: Candidato escolhido (precisa de ``webpage_url``).
        out_dir: Pasta de saída.
        base_name: Nome do arquivo, sem extensão.
        bitrate: Qualidade do MP3 em kbps (ex.: ``"320"``).
        cookies_browser: Navegador de onde ler cookies, ou ``None``.

    Returns:
        O caminho do MP3 gerado (``<out_dir>/<base_name>.mp3``).

    Raises:
        yt_dlp.utils.DownloadError: Se o vídeo estiver indisponível ou o
            download falhar por outro motivo que não seja formato.
    """
    # Segurança: o nome vem de títulos de terceiros (Spotify/YouTube) e NÃO
    # entra no template do yt-dlp. Além de "%(...)s", o yt-dlp aplica
    # expandvars/expanduser à parte literal do outtmpl: um título "$HOME" ou
    # "${VAR}" viraria o valor da variável de ambiente (com "/"), criando
    # subpastas e vazando o ambiente no nome do arquivo. Por isso baixamos
    # com um nome temporário fixo e só ASCII (hash do nome, então o .part é
    # retomável) e renomeamos para o nome final com os.replace, que não
    # interpreta nada. out_dir é do próprio usuário/app; seu "%" é escapado.
    tmp_base = ".offtape-" + hashlib.sha1(base_name.encode("utf-8")).hexdigest()[:16]
    outtmpl = os.path.join(out_dir.replace("%", "%%"), tmp_base + ".%(ext)s")
    base_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio",
             "preferredcodec": "mp3",
             "preferredquality": bitrate},
        ],
    }
    if cookies_browser:
        base_opts["cookiesfrombrowser"] = (cookies_browser,)

    # Cadeia de fallback de formato: alguns vídeos não oferecem um stream só de
    # áudio ("bestaudio"), então tentamos "best" (áudio+vídeo, o ffmpeg extrai
    # o áudio) e, por fim, None = sem restrição, deixando o yt-dlp escolher.
    # Só avançamos na cadeia em erro de formato; outros erros sobem na hora.
    format_attempts = ["bestaudio/best", "best", None]
    last_err = None
    for fmt in format_attempts:
        opts = dict(base_opts)
        if fmt is not None:
            opts["format"] = fmt
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([entry["webpage_url"]])
            final_mp3 = os.path.join(out_dir, base_name + ".mp3")
            os.replace(os.path.join(out_dir, tmp_base + ".mp3"), final_mp3)
            return final_mp3
        except yt_dlp.utils.DownloadError as e:
            last_err = e
            if "Requested format is not available" in str(e):
                continue   # tenta o próximo seletor
            raise
    raise last_err


def download_one(track: dict, out_dir: str, bitrate: str = "320",
                 search_results: int = 6, cookies_browser: str | None = None) -> dict:
    """Baixa uma faixa completa: busca, fallback de candidatos, conversão e tags.

    Pensada para reuso por outros programas (ex.: o app web). É idempotente:
    se o MP3 já existe, não baixa de novo. Não levanta exceções; erros são
    reportados no dict de retorno.

    Args:
        track: Faixa do ``tracks.json`` (``n``, ``title``, ``artist`` e,
            opcionalmente, ``duration``).
        out_dir: Pasta de saída (precisa existir).
        bitrate: Qualidade do MP3 em kbps.
        search_results: Quantidade de candidatos a avaliar.
        cookies_browser: Navegador de onde ler cookies, ou ``None``.

    Returns:
        Um dict com as chaves:
            - ``status``: ``"ok"``, ``"skipped"`` ou ``"failed"``.
            - ``mp3``: caminho do MP3, ou ``None`` em caso de falha.
            - ``url``: URL do candidato baixado (vazia se não houve download).
            - ``chosen_title``: título do candidato baixado.
            - ``msg``: descrição do resultado ou do erro.
    """
    base = sanitize_filename(f"{track['n']:03d} - {track['artist']} - {track['title']}")
    final_mp3 = os.path.join(out_dir, base + ".mp3")
    # Idempotência/retomada: o nome do arquivo é determinístico, então a
    # existência do MP3 basta para saber que a faixa já foi baixada.
    if os.path.exists(final_mp3):
        return {"status": "skipped", "mp3": final_mp3, "url": "", "chosen_title": "", "msg": "já existe"}

    try:
        candidates = search_candidates(track, search_results, cookies_browser)
    except Exception as e:
        return {"status": "failed", "mp3": None, "url": "", "chosen_title": "", "msg": f"busca: {e}"}
    if not candidates:
        return {"status": "failed", "mp3": None, "url": "", "chosen_title": "", "msg": "nenhum resultado no YouTube"}

    # Tenta cada candidato em ordem de pontuação; se um estiver indisponível
    # (removido, bloqueado, restrição de idade etc.), passa para o próximo.
    last = ""
    for rank, cand in enumerate(candidates, 1):
        try:
            download_track(cand, out_dir, base, bitrate, cookies_browser)
            tag_mp3(final_mp3, track)
            return {"status": "ok", "mp3": final_mp3, "url": cand.get("webpage_url", ""),
                    "chosen_title": cand.get("title", ""),
                    "msg": "baixado" if rank == 1 else f"baixado (fallback #{rank})"}
        except Exception as e:
            last = str(e)
    return {"status": "failed", "mp3": None, "url": "", "chosen_title": "", "msg": last or "falha no download"}


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    """Ponto de entrada da linha de comando.

    Lê os argumentos, carrega o ``tracks.json``, processa as faixas do
    intervalo ``--start``..``--end`` em lotes com pausas, grava o relatório
    CSV e imprime um resumo com as faixas que falharam.

    O ``--retries`` repete apenas a busca no YouTube (ex.: erros de rede).
    Falhas no download não são repetidas com o mesmo candidato: passa-se ao
    próximo candidato da lista.

    Sem ``--dry-run``, encerra com código 1 se o ffmpeg não estiver no PATH.
    """
    _console_safe()
    here = os.path.dirname(os.path.abspath(__file__))
    default_tracks = os.path.join(here, "tracks.json")
    default_out = os.path.join(here, "exported-musics")     # MP3s
    default_reports = os.path.join(here, "relatorios")      # CSVs de relatório

    ap = argparse.ArgumentParser(description="Baixa playlist do YouTube como MP3.")
    ap.add_argument("--tracks", default=default_tracks, help="Caminho do tracks.json")
    ap.add_argument("--out", default=default_out, help="Pasta de saída dos MP3")
    ap.add_argument("--reports-dir", default=default_reports, help="Pasta dos relatórios CSV")
    ap.add_argument("--bitrate", default="320", help="Qualidade MP3 em kbps (ex: 192, 320)")
    ap.add_argument("--search-results", type=int, default=6, help="Nº de resultados p/ avaliar por faixa")
    ap.add_argument("--batch-size", type=int, default=10, help="Faixas por batch")
    ap.add_argument("--batch-pause", type=float, default=20, help="Pausa (s) entre batches")
    ap.add_argument("--track-pause", type=float, default=2, help="Pausa base (s) entre faixas")
    ap.add_argument("--retries", type=int, default=2, help="Tentativas da busca no YouTube por faixa em caso de erro "
                         "(não se aplica ao download; este já tenta os candidatos seguintes)")
    ap.add_argument("--start", type=int, default=1, help="Faixa inicial (nº)")
    ap.add_argument("--end", type=int, default=10**9, help="Faixa final (nº)")
    ap.add_argument("--dry-run", action="store_true", help="Só mostra escolhas, não baixa")
    ap.add_argument("--cookies-from-browser", default=None,
                    help="Usa cookies do navegador p/ vídeos com restrição de idade "
                         "(ex: chrome, brave, firefox, safari, edge)")
    args = ap.parse_args()

    if not args.dry_run and not ffmpeg_available():
        print(FFMPEG_MISSING_MSG, file=sys.stderr)
        sys.exit(1)

    try:
        tracks = load_tracks(args.tracks)
    except (OSError, ValueError) as e:
        sys.exit(f"Não foi possível ler {args.tracks}: {e}")
    tracks = [t for t in tracks if args.start <= t["n"] <= args.end]

    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.reports_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(args.reports_dir, f"download_report_{stamp}.csv")

    total = len(tracks)
    print(f"== {total} faixas | saída: {args.out} | dry-run: {args.dry_run} ==\n")

    results = []
    ok = skipped = failed = 0

    for i, track in enumerate(tracks, 1):
        base = sanitize_filename(f"{track['n']:03d} - {track['artist']} - {track['title']}")
        final_mp3 = os.path.join(args.out, base + ".mp3")
        tag = f"[{i}/{total}] #{track['n']} {track['artist']} - {track['title']}"

        # Retomada: o nome do MP3 é determinístico, então se ele já existe a
        # faixa foi baixada numa execução anterior. No dry-run não pulamos,
        # para mostrar a escolha de todas as faixas.
        if os.path.exists(final_mp3) and not args.dry_run:
            print(f"{tag}\n   ↳ já existe, pulando.\n")
            skipped += 1
            results.append([track["n"], track["title"], track["artist"], "skipped", "", "", "já existe"])
            continue

        status, url, chosen_title, msg = "failed", "", "", ""

        # 1) Busca os candidatos. O --retries vale só para a busca (erros de
        #    rede), com espera crescente entre as tentativas.
        candidates = []
        for attempt in range(1, args.retries + 1):
            try:
                candidates = search_candidates(track, args.search_results, args.cookies_from_browser)
                break
            except Exception as e:
                msg = f"busca: {type(e).__name__}: {e}"
                print(f"{tag}\n   ↳ erro na busca (tentativa {attempt}/{args.retries}): {e}")
                time.sleep(3 * attempt)

        if not candidates:
            msg = msg or "nenhum resultado no YouTube"
        else:
            # 2) Tenta cada candidato em ordem; se um estiver indisponível ou
            #    bloqueado, passa para o próximo melhor (resolve restrição de
            #    idade, vídeo removido etc.).
            for rank, cand in enumerate(candidates, 1):
                url = cand.get("webpage_url", "")
                chosen_title = cand.get("title", "")
                uploader = cand.get("uploader") or cand.get("channel") or "?"
                dur = cand.get("duration") or 0
                label = "candidato" if rank == 1 else f"candidato {rank} (fallback)"
                print(f"{tag}\n   ↳ {label}: \"{chosen_title}\" — {uploader} "
                      f"({dur//60}:{dur%60:02d}, score {cand.get('_score')})\n   ↳ {url}")

                if args.dry_run:
                    status, msg = "dry-run", "ok (não baixado)"
                    break
                try:
                    download_track(cand, args.out, base, args.bitrate, args.cookies_from_browser)
                    tag_mp3(final_mp3, track)
                    status, msg = "ok", ("baixado" if rank == 1 else f"baixado (fallback #{rank})")
                    print("   ↳ MP3 salvo.\n")
                    break
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    print(f"   ↳ indisponível ({e}); tentando próximo...\n")
                    time.sleep(1)

        if status in ("ok", "dry-run"):
            ok += 1
        elif status == "failed":
            failed += 1
            print(f"   ↳ FALHOU: {msg}\n")
        results.append([track["n"], track["title"], track["artist"], status, url, chosen_title, msg])

        # Pausas para não parecer tráfego automatizado: curta (com variação
        # aleatória) entre faixas e mais longa a cada --batch-size faixas.
        # Faixas puladas pelo resume não entram aqui (o `continue` acima).
        if i < total:
            if i % args.batch_size == 0:
                print(f"--- batch concluído, pausando {args.batch_pause}s ---\n")
                time.sleep(args.batch_pause)
            else:
                time.sleep(args.track_pause + random.uniform(0, 1.5))

    # Relatório CSV (um por execução, com data e hora no nome)
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["n", "title", "artist", "status", "chosen_url", "chosen_title", "message"])
        w.writerows(csv_safe(r) for r in results)

    print("\n===== RESUMO =====")
    print(f"  OK/baixados : {ok}")
    print(f"  pulados     : {skipped}")
    print(f"  falhas      : {failed}")
    print(f"  relatório   : {report_path}")
    if failed:
        print("\nFaixas com falha (rode de novo p/ tentar só elas, o resume pula as prontas):")
        for r in results:
            if r[3] == "failed":
                print(f"  #{r[0]} {r[2]} - {r[1]}  ({r[6]})")


if __name__ == "__main__":
    main()
