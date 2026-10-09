# Manutenção do perfil

O README apresenta os projetos e contatos. As imagens em `assets/` são geradas por scripts Python, sem dependências externas, com dados da API oficial do GitHub.

## Backup da versão anterior

Antes da publicação deste visual, a versão que estava no GitHub foi preservada na branch [codex/backup-profile-2026-10-09](https://github.com/fabiolrocha/fabiolrocha/tree/codex/backup-profile-2026-10-09), no commit `5da1f3395dead6f57122386cc51f240249a89343`. Esse backup mantém o README anterior e seu histórico, separado da atualização automática da branch principal.

## Personalizar

- **Apresentação, projetos, tecnologias e contatos:** edite `README.md`.
- **Nome, usuário, localização e frase do painel de identidade:** edite `profile.json` e gere as imagens novamente. Atualize também os textos correspondentes no README.
- **Cores, tipografia e composição:** edite `scripts/render_profile.py`. Os SVGs gerados são sobrescritos na próxima atualização.
- **Arte FL:** `assets/fl-logo.jpeg` contém a imagem original enviada. Os limites do losango e a máscara das letras são definidos no renderizador.

Os projetos em destaque são escolhidos manualmente. As tecnologias indicam ferramentas presentes nesses projetos e nos estudos, sem atribuir níveis de domínio.

## Direção visual

A composição usa o perfil [AVIVASHISHTA29](https://github.com/AVIVASHISHTA29/AVIVASHISHTA29) como referência: calendário no topo, identidade e atividade lado a lado, comandos centralizados e links compactos. O código dos SVGs é próprio.

A paleta combina fundo `#0d1117`, painéis `#161b22`, bordas `#30363d`, texto `#e6edf3`, texto secundário `#9da7b3` e verde `#7ee787`. A tipografia é monoespaçada, com fontes locais e sem downloads. O logo FL usa a imagem original enviada, incorporada aos SVGs. Um recorte SVG acompanha o losango para integrá-lo ao painel; o JPEG original permanece intacto.

Os projetos ficam em uma seção recolhível. Quando o portfólio estiver pronto, esse bloco deve ser substituído por um único destaque com imagem, descrição curta e link. O local está marcado com um comentário no README; não há botão apontando para um site inexistente.

## Executar localmente

Requer Python 3.10 ou superior. Para coletar dados, use o GitHub CLI já autenticado (`gh auth login`) ou disponibilize `GH_TOKEN` / `GITHUB_TOKEN` no ambiente. Não coloque tokens nos arquivos do repositório.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/fetch_github_data.py
python3 scripts/render_profile.py
```

Para ajustar somente o visual, execute apenas o último comando: ele usa o snapshot salvo em `data/github.json` e não acessa a rede.

## Atualização automática

O workflow `.github/workflows/update-profile.yml` roda diariamente às **06:17 de Brasília (09:17 UTC)**, manualmente pela aba **Actions → Update profile artwork → Run workflow**, ou quando scripts e configuração mudam na branch padrão.

Para ativá-lo, publique os arquivos na branch padrão do repositório e mantenha GitHub Actions habilitado. Ele usa o `GITHUB_TOKEN` fornecido pelo Actions para consultar a API e gravar as imagens, sem exigir um token pessoal. Políticas da conta ou regras de proteção de branch podem restringir o push do bot; nesse caso a execução informa a falha.

O workflow só cria um commit quando há alterações. Uma falha de coleta ou validação interrompe a execução antes da publicação; as imagens já versionadas continuam disponíveis. O renderizador funciona sem rede e os arquivos SVG não usam fontes, scripts ou imagens externos.

Agendamentos podem atrasar, e o GitHub pode desativá-los após 60 dias sem atividade em um repositório público. Confira o status na aba Actions se a data dos cartões parar de avançar.

## Como os números são calculados

- **Período:** 365 datas consecutivas, incluindo o dia da coleta, com limites em UTC.
- **Contribuições:** soma dos valores retornados pelo calendário do GitHub. Inclui os tipos de contribuição reconhecidos pelo GitHub, não apenas commits.
- **Repositórios públicos:** quantidade retornada pela API pública do perfil; pode incluir forks.
- **Dias ativos:** datas do período com pelo menos uma contribuição.
- **Maior sequência:** maior intervalo de datas consecutivas com contribuições dentro desses 365 dias.
- **Sequência atual:** sequência terminando hoje, ou ontem quando hoje ainda está sem contribuições. Se ontem também não teve atividade, é zero.
- **Melhor dia:** maior quantidade de contribuições em uma data do período. Em caso de empate, mostra a primeira data.
- **Média por dia ativo:** contribuições divididas pelo número de dias ativos; zero quando não há atividade.
- **Contribuições por mês:** soma das contribuições por mês do snapshot. Os meses nas pontas podem ser parciais; seus valores não representam necessariamente o mês inteiro.
- **Cores do gráfico:** níveis de atividade fornecidos pelo GitHub, do verde escuro ao verde claro.

A coleta rejeita calendários incompletos, datas repetidas e totais inconsistentes. O snapshot contém somente datas, contagens e quantidade de repositórios públicos; não armazena nomes ou conteúdo de repositórios privados. O calendário reflete os dados visíveis ao token e as preferências de contribuições privadas do perfil; contagens agregadas podem variar entre uma execução local autenticada e o token do Actions.

As animações se repetem continuamente: uma faixa verde sobe pelas letras brancas do logo FL, os dias com contribuições pulsam em sequência, os terminais têm cursor piscante e as barras mensais repetem uma revelação de baixo para cima. O logo fica parado, sem verde fixo ou pulsação de opacidade; a faixa passa em um ciclo de 7 segundos e fica restrita às letras por uma máscara SVG. As barras usam a mesma escala durante a animação, preservando a proporção entre os meses; os números não mudam. Dias sem contribuições permanecem estáticos. Os ciclos duram entre 2 e 10 segundos e usam apenas CSS interno dos SVGs, sem JavaScript.

Todos os movimentos respeitam `prefers-reduced-motion`: com essa preferência ativa, o desenho aparece completo e estático. As informações também permanecem disponíveis quando a animação não é reproduzida.

O README usa `<picture>` para escolher versões específicas para telas de até 600 pixels. No celular, o calendário anual é dividido em duas faixas, preservando os 365 dias, e o painel de estatísticas fica abaixo do monograma. As versões `*-mobile.svg` são geradas junto com as imagens de desktop.

`identity.svg` combina monograma e estatísticas em uma única imagem para evitar tabelas com rolagem horizontal. `monogram.svg` e `stats.svg` também ficam disponíveis separadamente para reutilização.

Referências: [calendário de contribuições](https://docs.github.com/en/account-and-profile/concepts/contributions-on-your-profile), [eventos do Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) e [permissões do workflow](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions).
