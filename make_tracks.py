#!/usr/bin/env python3
"""Gera o tracks.json consumido pelo download_playlist.py.

Aceita dois formatos de entrada:

    - CSV exportado pelo Exportify (https://exportify.net): traz título,
      artista e duração de cada faixa da playlist do Spotify.
    - TXT simples, uma faixa por linha no formato ``Artista - Título``.
      Linhas vazias e linhas iniciadas por ``#`` são ignoradas.

A saída é uma lista JSON de objetos ``{"n", "title", "artist", "duration"}``,
em que ``n`` é a numeração sequencial (a partir de 1) e ``duration`` está em
segundos (0 quando desconhecida). A duração é opcional, mas melhora a escolha
do candidato no YouTube.

Requisitos:
    - Python 3.9+ (apenas biblioteca padrão)
    - Para o passo seguinte (download_playlist.py), o ffmpeg no PATH:
      macOS ``brew install ffmpeg`` · Windows ``winget install Gyan.FFmpeg``
      (depois reabra o terminal) · Linux ``sudo apt install ffmpeg`` (ou
      ``dnf``/``pacman``)

Compatibilidade:
    macOS, Linux e Windows. Entrada e saída usam UTF-8 (o BOM do CSV do
    Exportify é descartado), os caminhos aceitam o formato de cada sistema
    (inclusive ``C:\\...`` no Windows) e a saída do console troca caracteres
    não suportados por ``?`` em consoles legados (cp1252/cp850), em vez de
    falhar. Sem ``--out``, o JSON é gravado como ``tracks.json`` na pasta do
    script, que é onde o download_playlist.py o procura por padrão.

Uso:
    python3 make_tracks.py minha_playlist.csv
    python3 make_tracks.py lista.txt --out tracks.json

Depois, rode:
    python3 download_playlist.py
"""

from __future__ import annotations
import argparse
import csv
import json
import os
import sys


def find_col(fieldnames, *needles, exclude=()):
    """Encontra a primeira coluna cujo nome contém algum dos termos.

    A comparação não diferencia maiúsculas de minúsculas. As colunas são
    percorridas na ordem do CSV, e vence a primeira que casar com qualquer
    termo. Colunas que contenham algum termo de ``exclude`` são ignoradas.

    Args:
        fieldnames: Nomes das colunas do CSV.
        *needles: Termos a procurar, em minúsculas.
        exclude: Termos (em minúsculas) que desqualificam uma coluna, ex.:
            ``("uri",)`` para pular ``"Artist URI(s)"``.

    Returns:
        O nome original da coluna encontrada, ou ``None``.
    """
    for f in fieldnames:
        low = f.lower()
        if any(x in low for x in exclude):
            continue
        if any(n in low for n in needles):
            return f
    return None


def find_title_col(fieldnames):
    """Encontra a coluna de título da faixa.

    Ordem de preferência: ``"track name"`` (Exportify), depois ``"title"``/
    ``"música"``, e por fim qualquer ``"name"`` que não seja de artista ou
    álbum. Colunas de URI/ID nunca são escolhidas.

    Args:
        fieldnames: Nomes das colunas do CSV.

    Returns:
        O nome original da coluna encontrada, ou ``None``.
    """
    ids = ("uri", " id", "id)")
    return (find_col(fieldnames, "track name", exclude=ids)
            or find_col(fieldnames, "title", "música", "musica", exclude=ids)
            or find_col(fieldnames, "name", exclude=ids + ("artist", "album", "álbum")))


def find_artist_col(fieldnames):
    """Encontra a coluna de artista.

    Prefere ``"artist name"`` (ex.: ``"Artist Name(s)"`` do Exportify); na
    falta dela, aceita qualquer coluna com ``"artist"``. Colunas de URI/ID
    (``"Artist URI(s)"``, ``"Artist IDs"``) nunca são escolhidas, pois
    trariam valores como ``spotify:artist:...``.

    Args:
        fieldnames: Nomes das colunas do CSV.

    Returns:
        O nome original da coluna encontrada, ou ``None``.
    """
    ids = ("uri", " id", "id)", "ids")
    return (find_col(fieldnames, "artist name", exclude=ids)
            or find_col(fieldnames, "artist", exclude=ids))


def from_csv(path: str) -> list:
    """Lê as faixas de um CSV (formato Exportify ou similar).

    Detecta as colunas de título, artista e duração pelo nome. A duração é
    lida em milissegundos (coluna com "ms", padrão do Exportify) ou, na falta
    dela, em segundos ou no formato ``m:ss`` (valores inválidos viram 0).
    Colunas de URI/ID (ex.: ``"Artist URI(s)"``) nunca são usadas como título
    ou artista. Linhas sem título são ignoradas.

    Args:
        path: Caminho do arquivo CSV.

    Returns:
        Lista de faixas ``{"title", "artist", "duration"}`` (ainda sem ``n``).

    Raises:
        SystemExit: Se não houver colunas reconhecíveis de título e artista.
    """
    # utf-8-sig descarta o BOM que alguns exportadores colocam no início.
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        c_title = find_title_col(cols)
        c_artist = find_artist_col(cols)
        c_dur_ms = find_col(cols, "duration (ms)", "duration ms", "ms")
        c_dur_s = find_col(cols, "duration") if not c_dur_ms else None
        if not c_title or not c_artist:
            sys.exit(f"CSV sem colunas de título/artista reconhecíveis. Colunas: {cols}")

        tracks = []
        for row in reader:
            title = (row.get(c_title) or "").strip()
            artist = (row.get(c_artist) or "").strip()
            if not title:
                continue
            dur = 0
            if c_dur_ms and row.get(c_dur_ms):
                try:
                    dur = round(float(row[c_dur_ms]) / 1000)
                except ValueError:
                    dur = 0
            elif c_dur_s and row.get(c_dur_s):
                v = row[c_dur_s].strip()
                if ":" in v:                       # formato m:ss (ou h:mm:ss; usa os dois últimos campos)
                    try:
                        m, s = v.split(":")[-2:]
                        dur = int(m) * 60 + int(float(s))
                    except ValueError:             # ex.: "abc:1", "1:xx"
                        dur = 0
                else:
                    try:
                        dur = round(float(v))
                    except ValueError:
                        dur = 0
            tracks.append({"title": title, "artist": artist, "duration": dur})
        return tracks


def from_txt(path: str) -> list:
    """Lê as faixas de um TXT com uma faixa por linha (``Artista - Título``).

    Linhas vazias ou iniciadas por ``#`` são ignoradas. A linha é dividida no
    primeiro ``" - "``; se não houver separador, a linha inteira vira o
    título e o artista fica vazio. A duração é sempre 0 (desconhecida).

    Args:
        path: Caminho do arquivo de texto (UTF-8).

    Returns:
        Lista de faixas ``{"title", "artist", "duration"}`` (ainda sem ``n``).
    """
    tracks = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if " - " in line:
                artist, title = line.split(" - ", 1)
            else:                                   # sem separador: linha inteira é o título
                artist, title = "", line
            tracks.append({"title": title.strip(), "artist": artist.strip(), "duration": 0})
    return tracks


def main():
    """Ponto de entrada da linha de comando.

    Escolhe o leitor pela extensão do arquivo de entrada (``.csv`` ou
    ``.txt``/``.text``/sem extensão), numera as faixas e grava o JSON.

    Raises:
        SystemExit: Se a extensão não for suportada ou nenhuma faixa for
            encontrada.
    """
    # Consoles legados do Windows (cp1252/cp850) não codificam "—", emojis ou
    # títulos não latinos: com errors="replace" eles viram "?" em vez de
    # levantar UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass
    here = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(here, "tracks.json")

    ap = argparse.ArgumentParser(description="Gera tracks.json a partir de CSV (Exportify) ou TXT.")
    ap.add_argument("input", help="Arquivo .csv (Exportify) ou .txt (Artista - Título por linha)")
    ap.add_argument("--out", default=default_out, help="Saída (padrão: tracks.json na pasta do script)")
    args = ap.parse_args()

    ext = os.path.splitext(args.input)[1].lower()
    if ext not in (".csv", ".txt", ".text", ""):
        sys.exit(f"Extensão não suportada: {ext}. Use .csv ou .txt")
    # Arquivo de entrada pode vir de terceiros: campo gigante (csv.Error),
    # encoding errado ou arquivo ilegível viram mensagem curta, sem traceback.
    try:
        tracks = from_csv(args.input) if ext == ".csv" else from_txt(args.input)
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        sys.exit(f"Não foi possível ler {args.input}: {e}")

    if not tracks:
        sys.exit("Nenhuma faixa encontrada no arquivo de entrada.")

    # Numera as faixas a partir de 1. O campo 'n' vem primeiro no JSON e é
    # usado como prefixo do nome do MP3 (ex.: "001 - Artista - Título.mp3").
    tracks = [{"n": i, **t} for i, t in enumerate(tracks, 1)]

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(tracks, f, ensure_ascii=False, indent=2)

    com_dur = sum(1 for t in tracks if t.get("duration"))
    print(f"OK: {len(tracks)} faixas gravadas em {args.out}")
    print(f"    (com duração: {com_dur}/{len(tracks)} — duração ajuda o match, mas é opcional)")
    print("\nAgora rode:  python download_playlist.py")


if __name__ == "__main__":
    main()
