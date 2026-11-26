# Plano de Gerência de Configuração (GCS) do Offtape

Este documento diz o que fica sob controle de versão no Offtape, quem aprova as
mudanças e como uma mudança chega à `main` e a uma release. É curto de
propósito: o projeto é pequeno e o processo deve ser leve.

## 1. O que controlamos

| Versionado (itens de configuração) | Nunca versionado (fica só na sua máquina) |
|---|---|
| Código: `download_playlist.py`, `make_tracks.py`, `spotify_app/app.py` e os testes em `tests/` | Credenciais e estado do app: `config.json`, `.flask_secret`, `*.db`, `.env` |
| Dependências: `requirements.txt` (uso) e `requirements-dev.txt` (lint e testes) | Dados pessoais: `tracks.json`, `tracks_json/`, `relatorios/`, `exported-musics/`, `*.mp3`, `*.csv` |
| Exemplos sem dados pessoais: `tracks.example.json`, `spotify_app/config.example.json` | Ambiente: `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ipynb_checkpoints/`, `.DS_Store` |
| Documentação: `README.md`, `docs/`, `CONTRIBUTING.md`, `CHANGELOG.md`, `LICENSE` | |
| Processo e automação: `.github/` (CI, Dependabot, templates), `ruff.toml`, `.gitignore` | |
| Notebook de análise: `explore_report.ipynb` (sem saídas com dados pessoais) | |

A fonte da verdade para "nunca versionado" é o [`.gitignore`](../.gitignore).

## 2. Quem faz e quem aprova

- **Mantenedor:** Henrike Pajares Braga. Revisa todo PR, decide o que entra e
  quando sai uma versão.
- **Contribuidores:** qualquer pessoa, via fork e pull request, com commits
  assinados (DCO, `git commit -s`).

## 3. Como versionamos

- **GitHub Flow:** a `main` é a única branch permanente e está sempre estável.
  Todo trabalho acontece numa branch curta, criada a partir da `main`.
- **Nome da branch:** `tipo/descricao`, com `feat/`, `fix/`, `docs/` ou `chore/`.
  Exemplo: `fix/pen-drive-windows`.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/pt-br/)
  (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`), sempre com `-s`.
- **Versões:** [SemVer](https://semver.org/lang/pt-BR/) `MAJOR.MINOR.PATCH`.
  Cada release tem uma tag `vX.Y.Z` na `main` e uma seção no `CHANGELOG.md`.
  - PATCH: correção sem mudar o uso.
  - MINOR: funcionalidade nova compatível.
  - MAJOR: algo que quebra o uso atual (comando, formato do `tracks.json` etc.).
- **Como sai uma release** (o mantenedor decide a versão):
  1. PR `chore/release-X.Y.Z` que renomeia `[Não lançado]` para
     `[X.Y.Z] - data` no `CHANGELOG.md`; CI verde e merge.
  2. Na `main` atualizada: `git tag -a vX.Y.Z -m "Offtape vX.Y.Z"` e
     `git push origin vX.Y.Z`.
  3. O workflow [`release.yml`](../.github/workflows/release.yml) confere
     que a tag está na `main` e publica a release com as notas daquela
     seção do CHANGELOG. Para ver as notas antes:
     `python .github/scripts/notas_release.py vX.Y.Z`.

## 4. Como uma mudança entra

```
issue ──► branch tipo/descricao ──► PR com "Closes #N" ──► CI verde ──► revisão ──► merge na main ──► CHANGELOG
```

1. Abra uma **issue** (bug ou ideia) para registrar o porquê da mudança.
2. Crie a **branch** a partir da `main`.
3. Abra o **PR** para a `main` usando o template, com `Closes #N` e a
   descrição de como testou.
4. A **CI** precisa passar nos 3 sistemas.
5. O mantenedor **revisa** e faz o merge. A issue fecha sozinha.
6. A mudança entra em `[Não lançado]` no `CHANGELOG.md`. Na release, essa
   seção vira `[X.Y.Z]`, a tag é criada e a release é publicada sozinha
   (veja "Como sai uma release" na seção 3).

## 5. O que a CI verifica

O workflow [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) roda em
cada PR e em cada push na `main`, em **Ubuntu, macOS e Windows**, com
**Python 3.11** (mínimo) e **3.14** (mais novo):

1. **Lint** com `ruff check`, só com regras de erro real (`E9`, `F63`, `F7`, `F82`).
2. **Sintaxe** com `python -m py_compile` dos três scripts.
3. **Dependências:** instala o núcleo do `requirements.txt` e confere que o
   arquivo inteiro resolve (`pip install --dry-run`).
4. **Testes** com `pytest`: leitura de CSV/TXT, validação do `tracks.json`,
   nomes de arquivo e pontuação dos candidatos do YouTube.

A CI não substitui testar o app de verdade: login, download e cópia para o pen
drive dependem de contas e de hardware que a CI não tem.

## 6. Ferramentas

| Ferramenta | Uso |
|---|---|
| Git + GitHub | versionamento, issues, pull requests, tags e releases |
| GitHub Actions | CI e publicação da release a partir da tag |
| Dependabot | PRs semanais de atualização (pip e actions) |
| ruff | lint |
| pytest | testes automatizados |
| DCO (`git commit -s`) | origem e licença de cada contribuição |
| Keep a Changelog | histórico de mudanças por versão |

## 7. Revisão do plano

O plano é revisado **a cada release** ou quando o processo mudar (nova
ferramenta, novo sistema suportado, mudança na CI). Alterar o plano segue o
mesmo fluxo de qualquer mudança: branch `docs/`, PR e merge.
