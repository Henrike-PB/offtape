"""Testes das funções puras do download_playlist.py.

Nada aqui acessa a internet nem precisa do ffmpeg: são testados a limpeza de
nomes de arquivo, a proteção do relatório CSV, a validação do tracks.json e a
pontuação dos candidatos do YouTube. O módulo importa o yt-dlp, então ele
precisa estar instalado (``pip install -r requirements.txt``).
"""

import json

import pytest

from download_playlist import csv_safe, load_tracks, norm, sanitize_filename, score_entry


# --------------------------------------------------------------------------- #
# sanitize_filename
# --------------------------------------------------------------------------- #
def test_nome_troca_caracteres_invalidos_e_espacos():
    # Espaços repetidos viram um só. (Tab é caractere de controle: é removido.)
    assert sanitize_filename('001 - AC/DC: "Back"   in  Black?') == "001 - AC-DC- -Back- in Black-"


def test_nome_remove_caracteres_de_controle():
    assert sanitize_filename("001 - A\x00B\x1fC\x7f") == "001 - ABC"


def test_nome_respeita_limite_de_bytes_sem_cortar_caractere():
    nome = sanitize_filename("001 - " + "語" * 100)   # 3 bytes por caractere
    assert len(nome.encode("utf-8")) <= 200
    nome.encode("utf-8").decode("utf-8")           # não pode ter sobrado meio caractere


def test_nome_curto_nao_muda():
    assert sanitize_filename("001 - New Order - Blue Monday") == "001 - New Order - Blue Monday"


# --------------------------------------------------------------------------- #
# csv_safe
# --------------------------------------------------------------------------- #
def test_csv_safe_neutraliza_formulas():
    assert csv_safe(["=1+1", "+x", "-y", "@z", "normal", 3]) == ["'=1+1", "'+x", "'-y", "'@z", "normal", 3]


# --------------------------------------------------------------------------- #
# load_tracks
# --------------------------------------------------------------------------- #
def _grava_json(tmp_path, dados):
    caminho = tmp_path / "tracks.json"
    caminho.write_text(json.dumps(dados), encoding="utf-8")
    return str(caminho)


def test_load_tracks_aceita_formato_valido(tmp_path):
    dados = [
        {"n": 1, "title": "Blue Monday", "artist": "New Order", "duration": 449},
        {"n": 2, "title": "Ceremony", "artist": "New Order"},   # duration é opcional
    ]
    assert load_tracks(_grava_json(tmp_path, dados)) == dados


@pytest.mark.parametrize("dados", [
    {"n": 1},                                                    # não é lista
    [{"n": "1", "title": "a", "artist": "b"}],                   # n em texto
    [{"n": True, "title": "a", "artist": "b"}],                  # bool não vale como int
    [{"n": 1, "title": None, "artist": "b"}],                    # título ausente
    [{"n": 1, "title": "a", "artist": "b", "duration": "3:00"}],  # duração em texto
])
def test_load_tracks_recusa_formato_invalido(tmp_path, dados):
    with pytest.raises(ValueError):
        load_tracks(_grava_json(tmp_path, dados))


# --------------------------------------------------------------------------- #
# norm e score_entry
# --------------------------------------------------------------------------- #
def test_norm():
    assert norm("  Harder, Better... FASTER!! ") == "harder better faster"
    assert norm(None) == ""


FAIXA = {"title": "Blue Monday", "artist": "New Order", "duration": 449}


def _pontua(title, uploader="", duration=0, faixa=FAIXA):
    return score_entry({"title": title, "uploader": uploader, "duration": duration}, faixa)


def test_canal_topic_vence_videoclipe():
    topic = _pontua("Blue Monday", "New Order - Topic", 449)
    clipe = _pontua("New Order - Blue Monday (Official Music Video)", "Some Channel", 449)
    assert topic > clipe


def test_audio_oficial_vence_ao_vivo_e_cover():
    oficial = _pontua("New Order - Blue Monday (Official Audio)", "New Order", 449)
    ao_vivo = _pontua("New Order - Blue Monday (Live)", "New Order", 449)
    cover = _pontua("Blue Monday cover", "Fulano", 449)
    assert oficial > ao_vivo
    assert oficial > cover


def test_termo_que_faz_parte_do_titulo_real_nao_penaliza():
    faixa = {"title": "Live Forever", "artist": "Oasis", "duration": 276}
    com_termo = _pontua("Oasis - Live Forever", "Oasis", 276, faixa)
    sem_termo = _pontua("Oasis - Forever", "Oasis", 276, faixa)
    # "live" está no título real: não pode ser tratado como versão ao vivo.
    assert com_termo >= sem_termo


def test_duracao_proxima_pontua_mais_que_distante():
    perto = _pontua("Blue Monday", "New Order - Topic", 450)
    longe = _pontua("Blue Monday", "New Order - Topic", 449 + 600)
    assert perto > longe
