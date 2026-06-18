# Roteiro para o Claude Code

Você não precisa entender os comandos. É só abrir o Claude Code dentro da pasta
`vagas-sst` e colar os pedidos abaixo, **um de cada vez**, na ordem. Troque
`SEU_USUARIO` pelo seu nome de usuário do GitHub.

---

## 1) Subir o projeto para o GitHub

Cole no Claude Code:

> Estou na pasta do meu projeto de site de vagas. Quero subir tudo para o
> repositório público https://github.com/SEU_USUARIO/vagas-sst que acabei de
> criar (ele está vazio). Por favor:
> 1. Inicialize o git nesta pasta (se ainda não estiver).
> 2. Adicione todos os arquivos e faça o primeiro commit.
> 3. Configure a branch main e o remote para o meu repositório.
> 4. Faça o push.
> Se pedir login, me explique exatamente onde clicar para autenticar.

---

## 2) Testar o robô localmente (opcional)

> Rode o arquivo `scripts/coletar_vagas.py` e me mostre quantas vagas ele gerou.
> Depois copie o `data/vagas.json` para `site/data/vagas.json`.

---

## 3) Ver o site no meu próprio computador antes de publicar (opcional)

> Suba um servidor local simples na pasta `site` e me passe o endereço para eu
> abrir no navegador e ver o site funcionando.

---

## 4) Adicionar uma nova fonte de vagas

> Quero adicionar uma nova fonte de vagas no robô. A fonte é: [cole aqui o site
> ou o link do feed]. Encontre o feed RSS/JSON dela, adicione na lista
> FONTES_RSS do `scripts/coletar_vagas.py`, rode o robô para testar e me diga se
> trouxe vagas novas. Se funcionar, faça commit e push.

---

## 5) Quando algo der errado

> Recebi este erro: [cole o erro aqui]. Explique em linguagem simples o que
> aconteceu e corrija para mim.

---

## Dica

Sempre que quiser uma mudança no site (cores, textos, novo filtro), descreva em
português para o Claude Code, por exemplo:

> No site, mude a cor do cabeçalho para verde e adicione um filtro por tipo de
> contrato (CLT, PJ). Depois faça commit e push.
