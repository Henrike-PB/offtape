# Changelog

Todas as mudanças relevantes do Offtape ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/).
Como uma mudança chega até aqui está no [plano de GCS](docs/PLANO_GCS.md).

## [Não lançado]

### Adicionado

- CI no GitHub Actions (`.github/workflows/ci.yml`) em cada pull request e em
  cada push na `main`. Roda em Ubuntu, macOS e Windows, com Python 3.11 e 3.14,
  e faz lint com `ruff` (só erros reais), verificação de sintaxe com
  `py_compile` e instalação das dependências.
- Configuração do ruff (`ruff.toml`) e `requirements-dev.txt` com a versão fixa
  do ruff.
- Dependabot com atualizações semanais de `pip` e de `github-actions`.
- Templates de pull request e de issue (bug e ideia/melhoria).
- Plano de gerência de configuração (`docs/PLANO_GCS.md`).
- Este CHANGELOG.
- Badge de status da CI no README.

### Alterado

- O requisito mínimo passa a ser **Python 3.11**. O yt-dlp atual exige essa
  versão, e com Python 3.9 ou 3.10 o pip instala uma versão antiga que não
  funciona mais com o YouTube.
- O `CONTRIBUTING.md` agora usa branches `tipo/descricao` (`feat/`, `fix/`,
  `docs/`, `chore/`) e Conventional Commits, e explica o que a CI verifica.

## [1.0.0] - 2026-09-29

Primeira versão do Offtape: sua playlist do Spotify, offline.

### Adicionado

- App web local (`spotify_app/app.py`) com login no Spotify (OAuth + PKCE, sem
  *client secret*). Lista as playlists, gera o `tracks.json`, baixa os MP3 em
  segundo plano e copia para o pen drive, com histórico em SQLite.
- Proteções do app web: só escuta em `127.0.0.1` e protege contra CSRF, DNS
  rebinding, XSS e *path traversal*.
- Downloader (`download_playlist.py`): busca cada faixa no YouTube com yt-dlp e
  dá preferência ao *official audio*. Tenta o próximo candidato quando um vídeo
  está indisponível, converte para MP3 com ffmpeg, roda em lotes, retoma de onde
  parou e gera um relatório CSV por execução.
- Conversor de CSV/TXT para `tracks.json` (`make_tracks.py`).
- Notebook de análise dos relatórios (`explore_report.ipynb`).
- README, guia de uso (`docs/GUIA_DE_USO.md`) e guia de contribuição com DCO.
- Suporte a macOS, Linux e Windows, inclusive a detecção de pen drive.

[Não lançado]: https://github.com/Henrike-PB/offtape/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Henrike-PB/offtape/releases/tag/v1.0.0
