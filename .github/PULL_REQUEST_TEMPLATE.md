## O que mudou

<!-- Descreva a mudança em poucas linhas. -->

## Como testei

<!-- Conte como você testou de verdade: o que rodou, em qual sistema (macOS,
Linux, Windows) e o resultado. Se mexeu na detecção de pen drive, diga em quais
sistemas testou. -->

Closes #

## Antes de abrir o PR

- [ ] Testei a mudança de verdade (descrito acima).
- [ ] `python -m py_compile download_playlist.py make_tracks.py spotify_app/app.py` passa
      (a CI também roda isso sozinha nos 3 sistemas).
- [ ] **Nenhum dado pessoal** no commit: nada de `config.json`, `history.db`,
      `.flask_secret`, `tracks.json`, `tracks_json/`, `relatorios/`, MP3, Client
      ID, tokens, caminhos como `/Users/seu-nome` ou nomes das suas playlists.
      Conferi com `git status` e `git diff --cached`.
- [ ] Se mudou o uso, atualizei o README e/ou o `docs/GUIA_DE_USO.md`.
- [ ] Commits assinados com `-s` (DCO) e no padrão Conventional Commits.
