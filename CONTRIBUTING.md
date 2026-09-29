# Contribuindo com o Offtape

Que bom que você quer ajudar! Este guia explica como preparar o ambiente, o
padrão do código e como enviar sua contribuição.

## Como funciona

- O Offtape é mantido por **Henrike Braga**, que revisa e decide o que entra
  no projeto.
- O projeto usa a licença [MIT](LICENSE). Ao enviar uma contribuição, você
  concorda em disponibilizá-la sob essa mesma licença. Você continua autor(a)
  do que escreveu, e seu nome fica registrado no histórico do git.
- Não é preciso assinar contrato. Usamos o **DCO** (explicado abaixo).

## Preparando o ambiente

Siga a [Instalação do README](README.md#instalação-uma-vez-só), que tem os
comandos para macOS, Linux e Windows. Em resumo: instale o ffmpeg, crie a
`.venv`, ative-a e rode `pip install -r requirements.txt`.

O projeto precisa funcionar nos **três sistemas**. Ao mexer em caminhos, use
`os.path`, sempre passe `encoding="utf-8"` ao abrir arquivos de texto e não
assuma comandos exclusivos de um sistema. Se a mudança afetar a detecção de pen
drive, diga no PR em quais sistemas você testou.

Para testar o app web, você vai precisar do seu próprio app no Spotify
Developer Dashboard. Veja o [guia de uso](docs/GUIA_DE_USO.md#3-criando-o-app-no-spotify).

## Fluxo de contribuição

1. Abra uma **issue** descrevendo o bug ou a ideia antes de começar algo grande.
2. Faça um fork e crie um branch: `git checkout -b minha-melhoria`.
3. Faça as mudanças seguindo o padrão abaixo.
4. Faça commits **com assinatura DCO**: `git commit -s -m "Descreve a mudança"`.
5. Abra um **pull request** explicando o que mudou e como você testou.

## DCO (Developer Certificate of Origin)

Todo commit precisa terminar com uma linha assim:

```
Signed-off-by: Seu Nome <seu@email.com>
```

O `git commit -s` adiciona essa linha automaticamente, usando o nome e o e-mail
configurados no seu git. Com ela, você declara que escreveu a contribuição (ou
tem o direito de enviá-la) e que ela pode ser distribuída sob a licença do
projeto, conforme o texto do [Developer Certificate of Origin 1.1](https://developercertificate.org/).

Esqueceu de assinar? Para corrigir o último commit: `git commit --amend -s`.

## Padrão do código

- **Idioma:** docstrings, comentários e mensagens para o usuário em **português**.
- **Docstrings:** toda função tem uma, no estilo Google (`Args:`, `Returns:`,
  `Raises:`), igual às que já existem.
- **Comentários:** explique o *porquê* das partes não óbvias. Não comente o óbvio.
- **Comportamento:** mantenha a idempotência (rodar de novo não duplica nem
  rebaixa nada) e o tratamento de erros por faixa (uma falha não derruba o lote).
- **Segurança:** o app web é **só local**. Não remova as proteções de Host,
  CSRF, validação de caminhos e escape de HTML. Todo novo endpoint `POST` deve
  passar pelas mesmas verificações.

## Antes de abrir o PR

- [ ] `python -m py_compile download_playlist.py make_tracks.py spotify_app/app.py` passa.
- [ ] Testei a mudança de verdade (descreva como no PR).
- [ ] **Nenhum dado pessoal** no commit: nada de `config.json`, `history.db`,
      `.flask_secret`, `tracks.json`, `tracks_json/`, `relatorios/`, MP3, Client
      ID, tokens, caminhos como `/Users/seu-nome` ou nomes das suas playlists.
      Confira com `git status` e `git diff --cached`.
- [ ] Se mudou o uso, atualizei o README e/ou o `docs/GUIA_DE_USO.md`.
- [ ] Commits assinados com `-s`.

## Ideias para contribuir

Veja a seção [Contribuindo do README](README.md#contribuindo). A mais esperada
é o **caminho inverso**: identificar as músicas de um pen drive e criar uma
playlist no Spotify com elas.

## Dúvidas

Abra uma issue. Toda pergunta é bem-vinda.
