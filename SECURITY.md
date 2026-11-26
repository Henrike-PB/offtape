# Política de segurança

## Versões com suporte

Correções de segurança entram sempre na **versão mais recente** do Offtape
(veja as [releases](https://github.com/Henrike-PB/offtape/releases)). Versões
antigas não recebem correção: atualize para a última.

| Versão | Suporte |
|---|---|
| última release | ✅ |
| anteriores | ❌ |

## Como reportar uma vulnerabilidade

**Não abra uma issue pública** para falhas de segurança: ela fica visível para
todo mundo antes da correção.

Use o reporte privado do GitHub:

1. Abra a aba **[Security](https://github.com/Henrike-PB/offtape/security)** do
   repositório.
2. Clique em **Report a vulnerability**.
3. Descreva o problema, os passos para reproduzir, o sistema operacional e a
   versão do Offtape (tag ou `git rev-parse --short HEAD`).

Só o mantenedor vê o reporte. Antes de enviar, **apague dados pessoais** de logs
e prints: Client ID, tokens, caminhos como `/Users/seu-nome` e nomes das suas
playlists.

## O que esperar

O Offtape é um projeto pessoal, mantido por Henrike Pajares Braga no tempo livre:

- **Primeira resposta:** em até 7 dias.
- **Correção:** depende da gravidade. Falhas graves têm prioridade e saem numa
  versão PATCH (ex.: `1.0.2` → `1.0.3`), registrada na seção *Segurança* do
  [CHANGELOG](CHANGELOG.md).
- **Crédito:** se quiser, seu nome entra nas notas da release que corrigir o
  problema.

## Escopo

O Offtape roda **só no seu computador**. O modelo de segurança está descrito na
seção [Segurança e privacidade do README](README.md#segurança-e-privacidade).

**Interessa reportar**, por exemplo:

- outro site aberto no navegador conseguir acionar o app local (CSRF, *DNS
  rebinding*);
- o app ler ou gravar arquivos fora de `tracks_json/`, `exported-musics/`,
  `relatorios/` ou do pen drive escolhido;
- vazamento de tokens do Spotify ou da chave de sessão;
- injeção de comandos ou de fórmulas (no relatório CSV).

**Fora do escopo:**

- falhas no **yt-dlp**, no **ffmpeg** ou no **Flask**: reporte direto nesses
  projetos (e, se afetar o Offtape, abra uma issue pedindo a atualização);
- expor o app de propósito na rede (ele foi feito para `127.0.0.1`);
- uso que viole os termos do YouTube ou do Spotify.

## Verificação automática

Todo pull request passa pelo **CodeQL** (análise de código do GitHub) e pela CI.
O Dependabot propõe atualizações das dependências toda semana. Veja o
[plano de gerência de configuração](docs/PLANO_GCS.md).
