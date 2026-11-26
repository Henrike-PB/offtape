"""Testes do make_tracks.py: leitura de CSV (Exportify) e TXT."""

import pytest

from make_tracks import find_artist_col, find_title_col, from_csv, from_txt


def _escreve(tmp_path, nome, conteudo, encoding="utf-8"):
    """Grava um arquivo temporário e devolve o caminho como texto."""
    caminho = tmp_path / nome
    caminho.write_text(conteudo, encoding=encoding)
    return str(caminho)


# --------------------------------------------------------------------------- #
# Detecção de colunas
# --------------------------------------------------------------------------- #
COLUNAS_EXPORTIFY = [
    "Track URI", "Track Name", "Artist URI(s)", "Artist Name(s)",
    "Album Name", "Duration (ms)",
]


def test_coluna_de_titulo_do_exportify():
    assert find_title_col(COLUNAS_EXPORTIFY) == "Track Name"


def test_coluna_de_artista_ignora_uri():
    # "Artist URI(s)" vem antes, mas traria "spotify:artist:..." como artista.
    assert find_artist_col(COLUNAS_EXPORTIFY) == "Artist Name(s)"


def test_coluna_de_titulo_nao_usa_artista_nem_album():
    assert find_title_col(["Artist Name", "Album Name", "Name"]) == "Name"


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
def test_csv_exportify_com_bom_e_duracao_em_ms(tmp_path):
    csv = (
        "﻿Track URI,Track Name,Artist URI(s),Artist Name(s),Duration (ms)\n"
        "spotify:track:1,Blue Monday,spotify:artist:1,New Order,449000\n"
        "spotify:track:2,Ceremony,spotify:artist:1,New Order,264600\n"
    )
    faixas = from_csv(_escreve(tmp_path, "playlist.csv", csv))
    assert faixas == [
        {"title": "Blue Monday", "artist": "New Order", "duration": 449},
        {"title": "Ceremony", "artist": "New Order", "duration": 265},
    ]


@pytest.mark.parametrize("valor, esperado", [
    ("3:45", 225),
    ("1:02:03", 123),   # h:mm:ss usa só os dois últimos campos
    ("200", 200),
    ("abc", 0),
    ("1:xx", 0),
])
def test_csv_duracao_em_segundos_ou_m_ss(tmp_path, valor, esperado):
    csv = f"Title,Artist,Duration\nMúsica,Artista,{valor}\n"
    faixas = from_csv(_escreve(tmp_path, "lista.csv", csv))
    assert faixas[0]["duration"] == esperado


def test_csv_ignora_linhas_sem_titulo(tmp_path):
    csv = "Title,Artist\n,Ninguém\nFaixa,Alguém\n"
    faixas = from_csv(_escreve(tmp_path, "lista.csv", csv))
    assert [f["title"] for f in faixas] == ["Faixa"]


def test_csv_sem_colunas_reconheciveis_encerra(tmp_path):
    with pytest.raises(SystemExit):
        from_csv(_escreve(tmp_path, "ruim.csv", "foo,bar\n1,2\n"))


# --------------------------------------------------------------------------- #
# TXT
# --------------------------------------------------------------------------- #
def test_txt_artista_titulo_comentarios_e_linhas_vazias(tmp_path):
    txt = (
        "# minha lista\n"
        "\n"
        "New Order - Blue Monday\n"
        "Daft Punk - Harder, Better, Faster, Stronger\n"
        "Artista - Título - Remaster\n"
        "Só o título\n"
    )
    faixas = from_txt(_escreve(tmp_path, "lista.txt", txt))
    assert faixas == [
        {"title": "Blue Monday", "artist": "New Order", "duration": 0},
        {"title": "Harder, Better, Faster, Stronger", "artist": "Daft Punk", "duration": 0},
        # Divide só no primeiro " - ".
        {"title": "Título - Remaster", "artist": "Artista", "duration": 0},
        {"title": "Só o título", "artist": "", "duration": 0},
    ]
