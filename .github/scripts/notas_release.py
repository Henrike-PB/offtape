"""Extrai do CHANGELOG.md as notas de uma versão, para a release do GitHub.

Usado pelo workflow .github/workflows/release.yml quando uma tag ``vX.Y.Z`` é
enviada. Também dá para rodar na mão, para conferir as notas antes da tag:

    python .github/scripts/notas_release.py v1.0.1
"""

from __future__ import annotations

import re
import sys


def extrair_notas(changelog: str, versao: str) -> str:
    """Devolve o texto da seção ``## [versao]`` do CHANGELOG, sem o título.

    Args:
        changelog: Conteúdo do CHANGELOG.md (formato Keep a Changelog).
        versao: Versão sem o ``v`` (ex.: ``"1.0.1"``).

    Returns:
        As linhas entre o título da versão e a próxima seção ``## [``.

    Raises:
        ValueError: Se a versão não tiver seção no CHANGELOG, ou se a seção
            estiver vazia.
    """
    titulo = re.compile(r"^## \[" + re.escape(versao) + r"\]")
    linhas = changelog.splitlines()
    for i, linha in enumerate(linhas):
        if titulo.match(linha):
            corpo = []
            for seguinte in linhas[i + 1:]:
                # Próxima versão ou bloco de links do rodapé ("[x]: https://...").
                if seguinte.startswith("## [") or re.match(r"^\[[^\]]+\]: ", seguinte):
                    break
                corpo.append(seguinte)
            notas = "\n".join(corpo).strip()
            if not notas:
                raise ValueError(f"a seção [{versao}] do CHANGELOG está vazia")
            return notas
    raise ValueError(f"o CHANGELOG não tem a seção [{versao}]")


def main() -> None:
    """Lê a tag do argumento e imprime as notas da versão correspondente."""
    if len(sys.argv) != 2 or not re.fullmatch(r"v\d+\.\d+\.\d+", sys.argv[1]):
        sys.exit("Uso: python .github/scripts/notas_release.py vX.Y.Z")
    with open("CHANGELOG.md", encoding="utf-8") as f:
        changelog = f.read()
    try:
        print(extrair_notas(changelog, sys.argv[1][1:]))
    except ValueError as e:
        sys.exit(f"Erro: {e}. Atualize o CHANGELOG antes de criar a tag.")


if __name__ == "__main__":
    main()
