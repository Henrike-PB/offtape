# Changelog

Todas as mudanças relevantes do Offtape ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/).
Como uma mudança chega até aqui está no [plano de GCS](docs/PLANO_GCS.md).

## [Não lançado]

## [1.0.3] - 2026-11-26

Política de segurança, relatório CSV mais limpo e documentação revisada. O uso
do app não muda.

### Adicionado

- Política de segurança (`SECURITY.md`): como reportar uma vulnerabilidade
  em particular, o que esperar e o que está no escopo.

### Alterado

- README e guia de uso: o que fazer quando o pen drive não aparece nem no
  Finder/Explorer (o sistema não o montou).
- README: badges de última release, Python 3.11+ e licença; a lista de ideias
  deixa de citar o suporte a pen drive no Windows/Linux, que já existe.

### Corrigido

- As mensagens de erro do relatório CSV não trazem mais códigos de cor do
  terminal (ex.: `\x1b[0;31mERROR:`), que o yt-dlp acrescenta e que sujavam
  a planilha.

## [1.0.2] - 2026-11-26

Correções de segurança no app web, apontadas pelo CodeQL. O uso do app não
muda.

### Segurança

- O app web não usa mais caminhos vindos do navegador. O `tracks.json` e o pen
  drive são escolhidos pelo nome entre os que o próprio servidor lista
  (`tracks_json/` e drives detectados). Isso fecha os alertas de *path
  injection* do CodeQL.
- As mensagens de erro enviadas à página agora são textos fixos. O detalhe
  técnico (inclusive o traceback) fica só no terminal, para não vazar
  caminhos ou dados internos (*information exposure*).
- Ao gerar o `tracks.json`, o nome e o dono da playlist são buscados no
  Spotify. O que a página envia nesses campos é ignorado.

## [1.0.1] - 2026-11-26

Correção do requisito de Python e um processo de desenvolvimento com CI,
testes e releases. Nada muda no uso do app.

### Adicionado

- CI no GitHub Actions (`.github/workflows/ci.yml`) em cada pull request e em
  cada push na `main`. Roda em Ubuntu, macOS e Windows, com Python 3.11 e 3.14,
  e faz lint com `ruff` (só erros reais), verificação de sintaxe com
  `py_compile`, instalação das dependências e testes.
- Testes automatizados com `pytest` (`tests/`) para `make_tracks.py` e para as
  funções puras do `download_playlist.py`, sem internet, Spotify nem ffmpeg.
- Configuração do ruff (`ruff.toml`) e `requirements-dev.txt` com as versões
  fixas do ruff e do pytest.
- Dependabot com atualizações semanais de `pip` e de `github-actions`. No
  `pip`, ele só propõe versões que ficam fora das faixas do `requirements.txt`.
- Templates de pull request e de issue (bug e ideia/melhoria).
- Plano de gerência de configuração (`docs/PLANO_GCS.md`).
- Este CHANGELOG.
- Badge de status da CI no README.
- Publicação automática da release no GitHub a partir da tag `vX.Y.Z`, com as
  notas da seção correspondente deste CHANGELOG.

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

[Não lançado]: https://github.com/Henrike-PB/offtape/compare/v1.0.3...HEAD
[1.0.3]: https://github.com/Henrike-PB/offtape/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/Henrike-PB/offtape/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/Henrike-PB/offtape/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Henrike-PB/offtape/releases/tag/v1.0.0
