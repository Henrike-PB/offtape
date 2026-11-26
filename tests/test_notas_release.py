"""Testes do extrator de notas da release (.github/scripts/notas_release.py)."""

import importlib.util
import os

import pytest

_CAMINHO = os.path.join(os.path.dirname(__file__), os.pardir, ".github", "scripts", "notas_release.py")
_spec = importlib.util.spec_from_file_location("notas_release", _CAMINHO)
notas_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(notas_release)

CHANGELOG = """# Changelog

## [Não lançado]

## [1.1.0] - 2026-12-01

### Adicionado

- Coisa nova.

## [1.0.0] - 2026-09-29

### Adicionado

- Primeira versão.

[Não lançado]: https://exemplo/compare/v1.1.0...HEAD
[1.1.0]: https://exemplo/compare/v1.0.0...v1.1.0
[1.0.0]: https://exemplo/releases/tag/v1.0.0
"""


def test_extrai_secao_do_meio():
    assert notas_release.extrair_notas(CHANGELOG, "1.1.0") == "### Adicionado\n\n- Coisa nova."


def test_ultima_secao_para_antes_dos_links():
    assert notas_release.extrair_notas(CHANGELOG, "1.0.0") == "### Adicionado\n\n- Primeira versão."


def test_versao_sem_secao_da_erro():
    with pytest.raises(ValueError, match="não tem a seção"):
        notas_release.extrair_notas(CHANGELOG, "9.9.9")


def test_secao_vazia_da_erro():
    with pytest.raises(ValueError, match="vazia"):
        notas_release.extrair_notas(CHANGELOG.replace("- Coisa nova.", "").replace("### Adicionado\n\n\n", ""), "1.1.0")


def test_ponto_na_versao_nao_e_curinga():
    # "1.0.0" não pode casar com "1x0x0" (o ponto é escapado na regex).
    assert notas_release.extrair_notas(CHANGELOG.replace("[1.0.0] - ", "[1x0x0] - ", 1), "1.1.0")
    with pytest.raises(ValueError):
        notas_release.extrair_notas(CHANGELOG.replace("## [1.0.0]", "## [1x0x0]"), "1.0.0")
