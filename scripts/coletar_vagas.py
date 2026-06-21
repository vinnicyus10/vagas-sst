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
FONTES_RSS = [
    # EmpregJusto - vagas setor privado (filtradas por palavras SST no script)
    ("EmpregJusto - Engenharia",
     "https://www.empregojusto.com/rss/engenharia/"),
    ("EmpregJusto - Todas as categorias",
     "https://www.empregojusto.com/rss/all/"),
    # Huork - vagas Brasil (filtradas por palavras SST + MG no script)
    ("Huork - Todas as vagas",
     "https://www.huork.com/br/rss/all/"),
    # Google News - busca ampla sem filtro de concurso (o script ja filtra)
    ("Google News - Técnico Segurança MG",
     "https://news.google.com/rss/search?q=%22t%C3%A9cnico+de+seguran%C3%A7a+do+trabalho%22+%22Minas+Gerais%22&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
    ("Google News - Engenheiro Segurança MG",
     "https://news.google.com/rss/search?q=%22engenheiro+de+seguran%C3%A7a%22+%22Minas+Gerais%22&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
    ("Google News - SST SESMT MG",
     "https://news.google.com/rss/search?q=SESMT+SST+%22Minas+Gerais%22+vaga&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
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
    "concurso publico", "edital", "inscricoes abertas", "prova objetiva",
    "gabarito", "processo seletivo publico", "prefeitura abre",
    "governo abre", "secretaria de estado", "prefeitura municipal",
    "camara municipal", "tribunal de justica", "tribunal regional",
    "ministerio publico", "defensoria publica", "policia militar",
    "policia civil", "corpo de bombeiros", "exercito brasileiro",
    "marinha do brasil", "forca aerea", "autarquia", "fundacao publica",
    "empresa publica", "sociedade de economia mista", "regime juridico unico",
    "estatutario", "cargo publico", "nomeacao", "posse do cargo",
    "diario oficial", "agencia reguladora", "instituto federal",
    "universidade federal", "universidade estadual", "secretaria municipal",
    "secretaria de saude", "secretaria de educacao", "vestibular",
    "selecao publica", "lei organica", "vinculo estatutario",
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


def extrair_cidade(titulo: str, local: str, descricao: str) -> str:
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
    texto = re.sub(r"<[^>]+>", " ", descricao)       # remove HTML
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) <= limite:
        return texto
    return texto[:limite].rsplit(" ", 1)[0] + "..."


def id_vaga(titulo: str, empresa: str, cidade: str) -> str:
    base = sem_acento(f"{titulo}|{empresa}|{cidade}")
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


def empresa_de_url_gupy(job_url: str, fallback: str) -> str:
    """Extrai o nome da empresa do subdominio da career page Gupy.

    Ex.: https://vagas-mrveco.gupy.io/... -> "Mrveco".
    """
    m = re.search(r"https?://([^.]+)\.gupy\.io", job_url or "")
    if not m:
        return fallback or "Nao informada"
    slug = m.group(1)
    slug = re.sub(r"^vagas?-?", "", slug)        # tira prefixo "vagas-"
    slug = slug.replace("-", " ").strip()
    return slug.title() if slug else (fallback or "Nao informada")


def coletar_gupy() -> list[dict]:
    """Busca vagas na API publica da Gupy (empresas privadas) e devolve apenas
    as de Minas Gerais, no mesmo formato dos demais coletores."""
    vagas = []
    vistos_links = set()
    print("Coletando vagas da Gupy (empresas privadas)...")
    for termo in TERMOS_GUPY:
        url = f"{GUPY_API}?jobName={quote(termo)}&limit=100"
        dados = baixar_json(url)
        if not dados or "data" not in dados:
            continue
        achadas_mg = 0
        for j in dados["data"]:
            estado = (j.get("state") or "")
            if "minas" not in sem_acento(estado):
                continue
            link = j.get("jobUrl") or j.get("careerPageUrl") or ""
            if not link or link in vistos_links:
                continue
            vistos_links.add(link)
            empresa = empresa_de_url_gupy(link, j.get("careerPageName", ""))
            vagas.append({
                "titulo": (j.get("name") or "").strip(),
                "link": link,
                "descricao": j.get("description") or "",
                "data_origem": j.get("publishedDate") or "",
                "empresa": empresa,
                "local": f"{j.get('city','')} {estado}".strip(),
                "fonte": "Gupy",
            })
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

        empresa = empresa_bruta or "Nao informada"
        cidade = extrair_cidade(titulo, local, desc)
        vid = id_vaga(titulo, empresa, cidade)
        if vid in vistos:
            continue
        vistos.add(vid)

        categoria, nivel = classificar(titulo)
        finais.append({
            "id": vid,
            "titulo": titulo.strip(),
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
    por_id = {}

    # mantem existentes: as fixas nunca expiram; as demais, dentro da validade
    for v in existentes:
        if v.get("fixa"):
            por_id[v["id"]] = v
            continue
        try:
            dc = datetime.date.fromisoformat(v.get("data_coleta", hoje.isoformat()))
        except Exception:
            dc = hoje
        if (hoje - dc).days <= DIAS_VALIDADE:
            por_id[v["id"]] = v

    # adiciona novas (novas sobrescrevem para atualizar data)
    for v in novas:
        por_id[v["id"]] = v

    lista = list(por_id.values())
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
