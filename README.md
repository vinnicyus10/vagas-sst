# Site de Vagas de Segurança do Trabalho — Minas Gerais

Site que mostra vagas de **Engenheiro, Coordenador e Técnico de Segurança do
Trabalho em MG**, atualizado automaticamente todos os dias. Tudo roda de graça,
sem servidor e sem você precisar mexer no dia a dia.

---

## Como funciona (em 1 parágrafo)

Um robô em Python (`scripts/coletar_vagas.py`) busca vagas em fontes públicas,
filtra só as de Segurança do Trabalho em Minas Gerais, remove repetidas e salva
tudo no arquivo `data/vagas.json`. O **GitHub Actions** roda esse robô sozinho
1x por dia. O **GitHub Pages** publica o site (pasta `site/`), que lê o JSON e
mostra as vagas com busca e filtros. Custo total: **R$ 0,00**.

```
Fontes públicas  ->  Robô Python  ->  vagas.json  ->  Site no ar
                     (GitHub Actions, todo dia)        (GitHub Pages)
```

---

## O QUE VOCÊ VAI FAZER (guia para quem não programa)

Você só precisa de uma conta no GitHub (grátis). O Claude Code faz o resto.
Siga na ordem. Se travar em algum passo, copie a mensagem de erro e cole no
Claude Code pedindo ajuda.

### Passo 1 — Criar conta no GitHub
1. Acesse https://github.com e clique em **Sign up**.
2. Crie usuário, e-mail e senha. Confirme o e-mail.

### Passo 2 — Criar o repositório
1. No GitHub, clique no **+** no canto superior direito > **New repository**.
2. Em *Repository name*, escreva: `vagas-sst`
3. Marque **Public** (precisa ser público para o site grátis funcionar).
4. Clique em **Create repository**. Deixe essa aba aberta.

### Passo 3 — Subir os arquivos com o Claude Code
Abra o Claude Code na pasta deste projeto e cole o pedido abaixo
(o roteiro completo está em `GUIA_CLAUDE_CODE.md`):

> "Suba todo o conteúdo desta pasta para o meu repositório
> github.com/SEU_USUARIO/vagas-sst. Configure o git, faça o primeiro commit e o
> push para a branch main."

Troque `SEU_USUARIO` pelo seu nome de usuário do GitHub.

### Passo 4 — Ligar o site (GitHub Pages)
1. No seu repositório, clique em **Settings** (engrenagem no topo).
2. No menu lateral, clique em **Pages**.
3. Em *Source*, escolha **Deploy from a branch**.
4. Em *Branch*, escolha **main** e a pasta **/docs**. Clique em **Save**.
5. Espere 1–2 minutos e atualize a página. Vai aparecer o link do seu site,
   algo como: `https://SEU_USUARIO.github.io/vagas-sst/`

Pronto, o site está no ar.

### Passo 5 — Ligar a atualização automática
1. No repositório, clique na aba **Actions**.
2. Se aparecer um aviso pedindo para habilitar os workflows, clique em
   **I understand my workflows, go ahead and enable them**.
3. Clique no workflow **Atualizar vagas SST** > botão **Run workflow** para
   testar agora. Daí em diante ele roda sozinho todo dia de manhã.

---

## Como adicionar mais fontes de vagas

Abra `scripts/coletar_vagas.py` e procure a lista `FONTES_RSS`. Cada fonte é
uma linha assim:

```python
FONTES_RSS = [
    ("NomeDaFonte", "https://endereco-do-feed.com/rss"),
]
```

Não sabe achar o feed de um site? Peça ao Claude Code:
> "Procure o feed RSS de vagas do site X e adicione na lista FONTES_RSS do
> coletar_vagas.py."

> Importante: o robô já vem pronto com 20 vagas reais de exemplo (coletadas
> manualmente) para o site nascer com conteúdo. Conforme você adiciona fontes
> de feed, ele passa a trazer vagas novas sozinho.

---

## Estrutura do projeto

```
vagas-sst/
├── scripts/
│   └── coletar_vagas.py        # o robô que coleta e filtra
├── data/
│   └── vagas.json              # banco de vagas (gerado pelo robô)
├── docs/
│   ├── index.html              # o site em si (servido pelo GitHub Pages)
│   └── data/vagas.json         # cópia que o site lê
├── .github/workflows/
│   └── atualizar-vagas.yml      # agendador (roda o robô todo dia)
├── GUIA_CLAUDE_CODE.md         # roteiro pronto para colar no Claude Code
└── README.md                   # este arquivo
```

---

## Dúvidas comuns

**O site some se eu não mexer?** Não. Fica no ar para sempre, de graça.

**As 20 vagas iniciais somem?** Não. Elas vêm marcadas como "fixas" e nunca
expiram, então o site nunca fica vazio — mesmo antes de você plugar fontes
novas. Vagas trazidas automaticamente por feeds, sim, expiram após 30 dias
(para não mostrar vaga velha).

**E se uma fonte quebrar e vier lixo?** O robô tem uma trava: se a coleta nova
ficar com menos da metade do que já existia, ele **não sobrescreve** e mantém o
arquivo bom anterior. Assim o site não esvazia por causa de um feed com defeito.

**Preciso deixar o computador ligado?** Não. O GitHub roda o robô na nuvem.

**Quanto custa?** Nada. GitHub Pages e Actions são gratuitos para projetos
públicos.

**As vagas têm salário?** Quando a fonte informa, sim. Quando não, o site mostra
"abra a vaga para ver detalhes" e leva ao link original.
