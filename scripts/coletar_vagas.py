#!/usr/bin/env python3
"""
Coletor de vagas de Seguranca do Trabalho em Minas Gerais.
Roda automaticamente pelo GitHub Actions (1x por dia) ou localmente pelo Claude Code.
Gera o arquivo data/vagas.json que o site le.

Nao depende de nenhuma API paga. Usa feeds publicos e busca leve.
"""

import json
import re
import ssl
import html
import hashlib
import datetime
import unicodedata
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

# ----------------------------------------------------------------------
# CONFIGURACAO
# ----------------------------------------------------------------------

# Palavras que identificam uma vaga de Seguranca do Trabalho
PALAVRAS_SST = [
    "seguranca do trabalho", "seguranca do trabalho", "sesmt", "sst",
    "engenheiro de seguranca", "engenheira de seguranca",
    "tecnico de seguranca", "tecnico em seguranca",
    "coordenador de seguranca", "coordenadora de seguranca",
    "tecnico de seguranca do trabalho", "hse", "ssma", "sso",
    "saude e seguranca", "seguranca ocupacional", "higiene ocupacional",
    "normas regulamentadoras", "tst", "analista de seguranca do trabalho",
]

# Termos que indicam Minas Gerais
TERMOS_MG = [
    " mg", "/mg", "-mg", "minas gerais", "belo horizonte", "contagem",
    "betim", "uberlandia", "uberaba", "juiz de fora", "montes claros",
    "santa luzia", "nova lima", "ipatinga", "divinopolis", "sete lagoas",
    "ouro branco", "ouro preto", "mariana", "paracatu", "varginha",
    "pocos de caldas", "patos de minas", "governador valadares",
    "ribeirao das neves", "sabara", "lagoa santa", "vespasiano",
]

# Fontes de feeds publicos (RSS/Atom). Adicione mais conforme quiser.
# Cada item: (nome_da_fonte, url_do_feed)
#
# Google News foi REMOVIDO de proposito: retornava quase so concursos publicos
# e processos seletivos de prefeituras (lixo para um site de setor privado).
# A coleta real de vagas privadas vem da API da Gupy (ver coletar_gupy).
FONTES_RSS = [
    # EmpregJusto - vagas setor privado (filtradas por palavras SST no script).
    # So a categoria engenharia: o feed /all/ vive dando timeout.
    ("EmpregJusto - Engenharia",
     "https://www.empregojusto.com/rss/engenharia/"),
    # Huork - vagas Brasil (filtradas por palavras SST + MG no script)
    ("Huork - Todas as vagas",
     "https://www.huork.com/br/rss/all/"),
]

# Termos de busca usados na API publica da Gupy (vagas de empresas privadas).
TERMOS_GUPY = [
    "seguranca do trabalho",
    "tecnico de seguranca do trabalho",
    "engenheiro de seguranca do trabalho",
    "coordenador de seguranca do trabalho",
    "tecnico seguranca",
    "sesmt",
    "sso",
    "hse",
]

# Endpoint publico (sem autenticacao) da Gupy. Retorna JSON com vagas de
# career pages de empresas privadas. Filtramos por estado = Minas Gerais.
GUPY_API = "https://employability-portal.gupy.io/api/v1/jobs"
GUPY_PAGINA = 100         # tamanho de cada pagina da API
GUPY_MAX_PAGINAS = 6      # ate 600 vagas por termo (cobre paginas com vagas MG)

ARQUIVO_SAIDA = Path(__file__).resolve().parent.parent / "data" / "vagas.json"
DIAS_VALIDADE = 30  # vagas com mais de X dias somem da lista

# TRAVA ANTI-ESVAZIAMENTO: se a nova lista ficar com menos que esta fracao do
# que ja existia, NAO sobrescreve (protege contra fonte quebrada/feed vazio).
FRACAO_MINIMA_SEGURA = 0.5

# MODO "SEMPRE TER CONTEUDO": vagas marcadas com "fixa": true nunca expiram.
# As 20 vagas-semente vem assim, entao o site nunca fica vazio mesmo sem
# fontes novas configuradas.


# ----------------------------------------------------------------------
# FUNCOES AUXILIARES
# ----------------------------------------------------------------------

def sem_acento(texto: str) -> str:
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def limpar_texto(texto: str) -> str:
    """Decodifica entidades HTML (&amp;, &ccedil;, &nbsp;...) e normaliza
    espacos. Usado em titulos, resumos e nomes de empresa."""
    if not texto:
        return ""
    texto = html.unescape(texto)
    texto = texto.replace("\xa0", " ")            # nbsp residual
    return re.sub(r"\s+", " ", texto).strip()


def _contexto_ssl() -> ssl.SSLContext:
    """Contexto SSL tolerante.

    Em alguns ambientes Windows o repositorio de certificados nao esta
    disponivel para o Python e o handshake falha. Como so lemos dados
    publicos de vagas (nada sensivel, nenhuma credencial trafega), caimos
    para um contexto sem verificacao quando o padrao falhar. No GitHub
    Actions (Linux) a verificacao normal funciona.
    """
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()


_SSL_CTX = _contexto_ssl()
_SSL_CTX_INSEGURO = ssl._create_unverified_context()


def baixar(url: str, timeout: int = 20) -> str | None:
    for ctx in (_SSL_CTX, _SSL_CTX_INSEGURO):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (vagas-sst-bot)"})
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except ssl.SSLError:
            continue  # tenta de novo sem verificacao
        except (URLError, HTTPError, TimeoutError, Exception) as e:
            print(f"  [aviso] falha ao baixar {url[:60]}: {e}")
            return None
    return None


def baixar_json(url: str, timeout: int = 25) -> dict | None:
    texto = baixar_com_accept(url, "application/json", timeout)
    if not texto:
        return None
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return None


def baixar_com_accept(url: str, accept: str, timeout: int = 25) -> str | None:
    for ctx in (_SSL_CTX, _SSL_CTX_INSEGURO):
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (vagas-sst-bot)",
                "Accept": accept,
            })
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except ssl.SSLError:
            continue
        except (URLError, HTTPError, TimeoutError, Exception) as e:
            print(f"  [aviso] falha ao baixar {url[:60]}: {e}")
            return None
    return None


# Termos que indicam orgao publico / concurso (excluem a vaga mesmo se bater
# com palavra SST, pois o site e so para setor privado).
PALAVRAS_CONCURSO = [
    "concurso publico", "concurso ", "concursos abertos", "edital",
    "inscricoes abertas", "prova objetiva", "gabarito",
    "processo seletivo publico", "processo seletivo simplificado",
    "prefeitura abre", "prefeitura de", "prefeitura municipal",
    "governo abre", "secretaria de estado", "camara municipal",
    "tribunal de justica", "tribunal regional", "ministerio publico",
    "defensoria publica", "policia militar", "policia civil",
    "corpo de bombeiros", "exercito brasileiro", "marinha do brasil",
    "forca aerea", "autarquia", "fundacao publica", "empresa publica",
    "sociedade de economia mista", "regime juridico unico", "estatutario",
    "cargo publico", "nomeacao", "posse do cargo", "diario oficial",
    "agencia reguladora", "instituto federal", "universidade federal",
    "universidade estadual", "secretaria municipal", "secretaria de saude",
    "secretaria de educacao", "vestibular", "selecao publica",
    "lei organica", "vinculo estatutario", "retifica", "fhemig", "seplag",
    "fundacao hospitalar", "fundacao hospital", "spdm", "pci concursos",
    "ache concursos", "direcao concursos", "consulplan", "cr de aprovados",
]

# Nomes de empregador que indicam vaga publica (checados no campo empresa).
EMPRESAS_PUBLICAS = [
    "prefeitura", "camara municipal", "governo do estado", "governo federal",
    "secretaria de estado", "secretaria municipal", "tribunal", "ministerio",
    "defensoria", "policia", "bombeiros", "exercito", "marinha", "forca aerea",
    "inss", "incra", "ibama", "receita federal", "cras", "creas", "detran",
    "autarquia", "fundacao publica", "universidade federal", "instituto federal",
]

def eh_vaga_sst(titulo: str, descricao: str, empresa: str = "") -> bool:
    texto = sem_acento(f"{titulo} {descricao}")
    if any(p in texto for p in PALAVRAS_CONCURSO):
        return False
    emp = sem_acento(empresa)
    if any(p in emp for p in EMPRESAS_PUBLICAS):
        return False
    return any(p in texto for p in PALAVRAS_SST)


def eh_minas_gerais(titulo: str, descricao: str, local: str) -> bool:
    texto = sem_acento(f"{titulo} {descricao} {local}")
    return any(t in texto for t in TERMOS_MG)


def classificar(titulo: str) -> tuple[str, str]:
    """Retorna (categoria, nivel)."""
    t = sem_acento(titulo)
    if "coordenador" in t or "coordenadora" in t or "gerente" in t or "gestor" in t:
        categoria = "Coordenacao/Gestao"
    elif "engenheiro" in t or "engenheira" in t:
        categoria = "Engenharia"
    elif "tecnico" in t or "tecnica" in t:
        categoria = "Tecnico"
    elif "analista" in t:
        categoria = "Analista"
    else:
        categoria = "Outros"

    # compara palavras inteiras (evita casar "pl" dentro de "exemplo" etc.)
    palavras = set(re.findall(r"[a-z]+", t))
    if "senior" in t or "sr" in palavras:
        nivel = "Senior"
    elif "pleno" in t or "pl" in palavras:
        nivel = "Pleno"
    elif "junior" in t or "jr" in palavras:
        nivel = "Junior"
    elif "coordenador" in t or "gerente" in t or "gestor" in t:
        nivel = "Coordenacao"
    elif "estagi" in t or "trainee" in t:
        nivel = "Estagio/Trainee"
    else:
        nivel = "Nao informado"
    return categoria, nivel


def extrair_cidade(titulo: str, local: str, descricao: str,
                   cidade_conhecida: str = "") -> str:
    # Se a fonte ja informou a cidade exata (ex.: API da Gupy), usa ela.
    if cidade_conhecida and sem_acento(cidade_conhecida) != "minas gerais":
        return cidade_conhecida
    texto = sem_acento(f"{local} {titulo} {descricao}")
    cidades = {
        "belo horizonte": "Belo Horizonte", "contagem": "Contagem",
        "betim": "Betim", "uberlandia": "Uberlandia", "uberaba": "Uberaba",
        "juiz de fora": "Juiz de Fora", "montes claros": "Montes Claros",
        "santa luzia": "Santa Luzia", "nova lima": "Nova Lima",
        "ipatinga": "Ipatinga", "divinopolis": "Divinopolis",
        "sete lagoas": "Sete Lagoas", "ouro branco": "Ouro Branco",
        "ouro preto": "Ouro Preto", "mariana": "Mariana",
        "paracatu": "Paracatu", "varginha": "Varginha",
        "pocos de caldas": "Pocos de Caldas", "patos de minas": "Patos de Minas",
        "governador valadares": "Governador Valadares",
    }
    for chave, nome in cidades.items():
        if chave in texto:
            return nome
    return "Minas Gerais"


def resumir(descricao: str, limite: int = 240) -> str:
    if not descricao:
        return "Abra a vaga para ver os detalhes e requisitos."
    texto = re.sub(r"<[^>]+>", " ", descricao)       # remove tags HTML
    texto = limpar_texto(texto)                       # decodifica entidades
    if len(texto) <= limite:
        return texto
    return texto[:limite].rsplit(" ", 1)[0] + "..."


def normalizar_link(link: str) -> str:
    """Remove querystring/fragmento para o link virar chave estavel da vaga."""
    if not link:
        return ""
    link = link.split("#", 1)[0].split("?", 1)[0]
    return link.rstrip("/").lower()


def id_vaga(link: str, titulo: str = "", empresa: str = "", cidade: str = "") -> str:
    """ID estavel baseado no LINK (chave natural unica da vaga).

    Se nao houver link, cai para titulo|empresa|cidade (compatibilidade com
    vagas-semente antigas).
    """
    base = normalizar_link(link) or sem_acento(f"{titulo}|{empresa}|{cidade}")
    return hashlib.md5(base.encode()).hexdigest()[:12]


# ----------------------------------------------------------------------
# PARSERS DE FONTE
# ----------------------------------------------------------------------

def parse_rss(xml_texto: str, fonte: str) -> list[dict]:
    vagas = []
    try:
        raiz = ET.fromstring(xml_texto)
    except ET.ParseError:
        return vagas
    # RSS 2.0 (item) ou Atom (entry)
    itens = raiz.iter("item")
    for item in itens:
        titulo = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        data = (item.findtext("pubDate") or "").strip()
        # tenta achar empresa/local em tags comuns
        empresa = (item.findtext("author") or item.findtext("{http://purl.org/dc/elements/1.1/}creator") or "").strip()
        vagas.append({
            "titulo": titulo, "link": link, "descricao": desc,
            "data_origem": data, "empresa": empresa, "local": "", "fonte": fonte,
        })
    return vagas


# Mapa de subdominios Gupy conhecidos -> nome amigavel da empresa.
EMPRESAS_GUPY = {
    "mrveco": "MRV&CO", "santacasabh": "Santa Casa BH",
    "cocacolafemsabr": "Coca-Cola FEMSA", "fornodeminas": "Forno de Minas",
    "vinci-energies": "Vinci Energies", "densosa": "Denso",
    "bat": "BAT", "hmdcc": "Hospital Metropolitano Dr. Celio de Castro",
    "valgroup": "Valgroup", "britvic": "Britvic", "bauducco": "Bauducco",
    "piracanjuba": "Piracanjuba", "selpe": "Selpe", "tambasa": "Tambasa",
    "cocacolafemsabr": "Coca-Cola FEMSA", "vero": "Vero",
    "prumoengenharia": "Prumo Engenharia", "medmais": "Medmais",
    "direcionalengenharia": "Direcional Engenharia", "allonda": "Allonda",
}

# Fontes que foram aposentadas: entradas antigas com essa origem sao expurgadas
# do arquivo no proximo merge (nao serao recoletadas).
FONTES_APOSENTADAS = ("Google News",)

# Termos que aparecem em career pages "confidenciais" da Gupy.
_CONFIDENCIAL = ("confidencial", "confidential", "confidencialidade")
# Ruido que vem grudado no subdominio e nao faz parte do nome da empresa.
_RUIDO_SLUG = (
    "vagas", "vaga", "carreiras", "carreira", "trabalheconosco",
    "venha", "oportunidades", "oportunidade", "temporarias", "temporaria",
    "pagina", "oficial", "grupo", "br", "sa", "vempra", "vempro", "acele",
    "sua", "talentos", "trabalhe", "conosco",
)


def empresa_de_url_gupy(job_url: str, fallback: str) -> str:
    """Deriva um nome de empresa legivel do subdominio da career page Gupy.

    Ex.: vagas-mrveco.gupy.io -> "MRV&CO"; xptoconfidencial.gupy.io ->
    "Empresa confidencial".
    """
    m = re.search(r"https?://([^.]+)\.gupy\.io", job_url or "")
    if not m:
        return limpar_texto(fallback) or "Nao informada"
    slug = m.group(1).lower()
    # chave do mapa: ignora prefixo "vagas-"/"vaga-" (ex.: vagas-mrveco -> mrveco)
    slug_base = re.sub(r"^vagas?-", "", slug)

    if slug in EMPRESAS_GUPY:
        return EMPRESAS_GUPY[slug]
    if slug_base in EMPRESAS_GUPY:
        return EMPRESAS_GUPY[slug_base]
    if any(c in slug for c in _CONFIDENCIAL):
        return "Empresa confidencial"

    # quebra em palavras e remove ruido conhecido
    bruto = slug.replace("_", "-")
    palavras = [p for p in re.split(r"[-]", bruto) if p]
    palavras = [p for p in palavras if p not in _RUIDO_SLUG]
    # se nao tinha hifen, tenta tirar prefixo "vagas" colado
    if len(palavras) == 1:
        palavras[0] = re.sub(r"^(vagas?|venha|trabalhe)", "", palavras[0]) or palavras[0]
    nome = " ".join(palavras).strip()
    if not nome:
        return limpar_texto(fallback) or "Nao informada"
    # acronimo curto vira maiusculo; senao Title Case
    return nome.upper() if len(nome) <= 4 else nome.title()


def _gupy_vaga_mg(j: dict, vistos_links: set) -> dict | None:
    """Converte um job da Gupy em vaga MG no formato padrao, ou None."""
    estado = j.get("state") or ""
    if "minas" not in sem_acento(estado):
        return None
    link = j.get("jobUrl") or j.get("careerPageUrl") or ""
    if not link or link in vistos_links:
        return None
    vistos_links.add(link)
    empresa = empresa_de_url_gupy(link, j.get("careerPageName", ""))
    cidade = limpar_texto(j.get("city") or "")
    return {
        "titulo": limpar_texto(j.get("name") or ""),
        "link": link,
        "descricao": j.get("description") or "",
        "data_origem": j.get("publishedDate") or "",
        "empresa": empresa,
        "local": f"{cidade} {estado}".strip(),
        "cidade_origem": cidade,           # cidade exata vinda da API
        "fonte": "Gupy",
    }


def coletar_gupy() -> list[dict]:
    """Busca vagas na API publica da Gupy (empresas privadas), paginando cada
    termo, e devolve apenas as de Minas Gerais no formato padrao."""
    vagas = []
    vistos_links = set()
    print("Coletando vagas da Gupy (empresas privadas)...")
    for termo in TERMOS_GUPY:
        achadas_mg = 0
        for pagina in range(GUPY_MAX_PAGINAS):
            offset = pagina * GUPY_PAGINA
            url = (f"{GUPY_API}?jobName={quote(termo)}"
                   f"&limit={GUPY_PAGINA}&offset={offset}")
            dados = baixar_json(url)
            if not dados or not dados.get("data"):
                break  # acabaram as paginas para esse termo
            for j in dados["data"]:
                vaga = _gupy_vaga_mg(j, vistos_links)
                if vaga:
                    vagas.append(vaga)
                    achadas_mg += 1
        print(f"- Gupy '{termo}': {achadas_mg} em MG")
    print(f"Total Gupy (MG): {len(vagas)}")
    return vagas


# ----------------------------------------------------------------------
# PIPELINE
# ----------------------------------------------------------------------

def coletar() -> list[dict]:
    brutas = []
    print("Coletando feeds RSS configurados...")
    for nome, url in FONTES_RSS:
        print(f"- {nome}")
        conteudo = baixar(url)
        if conteudo:
            brutas.extend(parse_rss(conteudo, nome))
    brutas.extend(coletar_gupy())
    print(f"Total bruto coletado: {len(brutas)}")
    return brutas


def processar(brutas: list[dict]) -> list[dict]:
    vistos = set()
    finais = []
    for v in brutas:
        titulo = v.get("titulo", "")
        desc = v.get("descricao", "")
        local = v.get("local", "")
        if not titulo or not v.get("link"):
            continue
        empresa_bruta = v.get("empresa") or ""
        if not eh_vaga_sst(titulo, desc, empresa_bruta):
            continue
        if not eh_minas_gerais(titulo, desc, local):
            continue

        empresa = limpar_texto(empresa_bruta) or "Nao informada"
        titulo = limpar_texto(titulo)
        cidade = extrair_cidade(titulo, local, desc, v.get("cidade_origem", ""))
        vid = id_vaga(v.get("link", ""), titulo, empresa, cidade)
        if vid in vistos:
            continue
        vistos.add(vid)

        categoria, nivel = classificar(titulo)
        finais.append({
            "id": vid,
            "titulo": titulo,
            "empresa": empresa,
            "cidade": cidade,
            "categoria": categoria,
            "nivel": nivel,
            "resumo": resumir(desc),
            "link": v.get("link"),
            "fonte": v.get("fonte", ""),
            "data_coleta": datetime.date.today().isoformat(),
        })
    return finais


def mesclar_com_existente(novas: list[dict]) -> list[dict]:
    """Mantem vagas anteriores ainda validas e adiciona as novas, sem duplicar."""
    existentes = []
    if ARQUIVO_SAIDA.exists():
        try:
            dados = json.loads(ARQUIVO_SAIDA.read_text(encoding="utf-8"))
            existentes = dados.get("vagas", [])
        except Exception:
            existentes = []

    hoje = datetime.date.today()
    por_chave = {}

    def chave(v: dict) -> str:
        # link normalizado e a chave natural; cai para id quando nao houver link
        return normalizar_link(v.get("link", "")) or v.get("id", "")

    # mantem existentes: as fixas nunca expiram; as demais, dentro da validade.
    # Reaplica o filtro de concurso para EXPURGAR vagas publicas que entraram
    # antes do filtro ser reforcado.
    for v in existentes:
        if not v.get("fixa"):
            fonte = v.get("fonte", "")
            if any(fonte.startswith(f) for f in FONTES_APOSENTADAS):
                continue  # origem aposentada (so trazia ruido): descarta
            texto = f"{v.get('titulo','')} {v.get('resumo','')}"
            if not eh_vaga_sst(texto, "", v.get("empresa", "")):
                continue  # era concurso/publico ou nao-SST: descarta
            try:
                dc = datetime.date.fromisoformat(v.get("data_coleta", hoje.isoformat()))
            except Exception:
                dc = hoje
            if (hoje - dc).days > DIAS_VALIDADE:
                continue  # vaga vencida
        por_chave[chave(v)] = v

    # adiciona novas (novas sobrescrevem a versao antiga da mesma vaga,
    # trazendo nome de empresa/cidade ja limpos e data atualizada)
    for v in novas:
        por_chave[chave(v)] = v

    lista = list(por_chave.values())
    lista.sort(key=lambda x: x.get("data_coleta", ""), reverse=True)
    return lista


def salvar(vagas: list[dict]) -> None:
    ARQUIVO_SAIDA.parent.mkdir(parents=True, exist_ok=True)
    saida = {
        "atualizado_em": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total": len(vagas),
        "vagas": vagas,
    }
    ARQUIVO_SAIDA.write_text(
        json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Arquivo gerado: {ARQUIVO_SAIDA} ({len(vagas)} vagas)")


def contar_existentes() -> int:
    if not ARQUIVO_SAIDA.exists():
        return 0
    try:
        return len(json.loads(ARQUIVO_SAIDA.read_text(encoding="utf-8")).get("vagas", []))
    except Exception:
        return 0


def main():
    print("=" * 50)
    print("COLETOR DE VAGAS SST - MINAS GERAIS")
    print("=" * 50)
    antes = contar_existentes()
    brutas = coletar()
    novas = processar(brutas)
    print(f"Vagas SST/MG apos filtro: {len(novas)}")
    todas = mesclar_com_existente(novas)

    # TRAVA ANTI-ESVAZIAMENTO: nao deixa o site encolher demais de uma vez.
    if antes > 0 and len(todas) < antes * FRACAO_MINIMA_SEGURA:
        print(f"[PROTECAO] Resultado ({len(todas)}) ficou abaixo de "
              f"{int(antes * FRACAO_MINIMA_SEGURA)} (metade do anterior: {antes}).")
        print("[PROTECAO] Mantendo o arquivo anterior intacto. Verifique as fontes.")
        return

    salvar(todas)
    print("Concluido.")


if __name__ == "__main__":
    main()
