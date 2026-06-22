"""Testes do coletor de vagas SST.

Rodar:  pytest -q
Cobrem as funcoes puras de filtro, classificacao e limpeza (sem rede).
"""

import sys
from pathlib import Path

import pytest

# torna o pacote scripts/ importavel
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import coletar_vagas as c  # noqa: E402


# ----------------------------------------------------------------------
# sem_acento / limpar_texto
# ----------------------------------------------------------------------

@pytest.mark.unit
def test_sem_acento_remove_acentos_e_baixa_caixa():
    assert c.sem_acento("Segurança do Trabalho") == "seguranca do trabalho"


@pytest.mark.unit
def test_limpar_texto_decodifica_entidades_html():
    # Arrange
    bruto = "T&eacute;cnico de Seguran&ccedil;a&nbsp;&amp; Sa&uacute;de"
    # Act
    limpo = c.limpar_texto(bruto)
    # Assert
    assert limpo == "Técnico de Segurança & Saúde"


@pytest.mark.unit
def test_limpar_texto_normaliza_espacos():
    assert c.limpar_texto("  a   b\n c ") == "a b c"


# ----------------------------------------------------------------------
# eh_vaga_sst (whitelist SST + blacklist concurso)
# ----------------------------------------------------------------------

@pytest.mark.unit
def test_aceita_vaga_privada_de_tecnico():
    assert c.eh_vaga_sst("Técnico de Segurança do Trabalho", "vaga CLT", "Bauducco")


@pytest.mark.unit
@pytest.mark.parametrize("titulo", [
    "Concurso Prefeitura de Passos-MG 2016",
    "Processo Seletivo Prefeitura de Barbacena MG",
    "FHEMIG abre processo seletivo para Engenheiro de Segurança",
    "SEPLAG MG abre processo seletivo com CR de aprovados",
    "Prefeitura de Nova Lima abre edital",
])
def test_rejeita_concurso_publico(titulo):
    assert not c.eh_vaga_sst(titulo, "", "")


@pytest.mark.unit
def test_rejeita_empregador_publico_mesmo_com_palavra_sst():
    assert not c.eh_vaga_sst(
        "Técnico de Segurança do Trabalho", "", "Prefeitura de Contagem"
    )


@pytest.mark.unit
def test_rejeita_vaga_sem_palavra_sst():
    assert not c.eh_vaga_sst("Auxiliar de Limpeza", "servicos gerais", "Empresa X")


# ----------------------------------------------------------------------
# eh_minas_gerais
# ----------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("local", ["Belo Horizonte", "Betim - MG", "Minas Gerais"])
def test_reconhece_minas_gerais(local):
    assert c.eh_minas_gerais("Vaga", "", local)


@pytest.mark.unit
def test_rejeita_outro_estado():
    assert not c.eh_minas_gerais("Vaga", "", "São Paulo - SP")


# ----------------------------------------------------------------------
# classificar
# ----------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("titulo,categoria", [
    ("Técnico de Segurança do Trabalho", "Tecnico"),
    ("Engenheiro de Segurança", "Engenharia"),
    ("Coordenador de Segurança e Medicina", "Coordenacao/Gestao"),
    ("Analista de Segurança do Trabalho", "Analista"),
])
def test_classifica_categoria(titulo, categoria):
    assert c.classificar(titulo)[0] == categoria


@pytest.mark.unit
def test_classifica_nivel_senior():
    assert c.classificar("Técnico de Segurança Sênior")[1] == "Senior"


# ----------------------------------------------------------------------
# extrair_cidade
# ----------------------------------------------------------------------

@pytest.mark.unit
def test_extrair_cidade_prefere_cidade_conhecida():
    assert c.extrair_cidade("Vaga", "", "", cidade_conhecida="Extrema") == "Extrema"


@pytest.mark.unit
def test_extrair_cidade_ignora_conhecida_generica_e_usa_titulo():
    cidade = c.extrair_cidade("Vaga em Betim", "", "", cidade_conhecida="Minas Gerais")
    assert cidade == "Betim"


@pytest.mark.unit
def test_extrair_cidade_fallback_generico():
    assert c.extrair_cidade("Vaga", "", "") == "Minas Gerais"


# ----------------------------------------------------------------------
# empresa_de_url_gupy
# ----------------------------------------------------------------------

@pytest.mark.unit
def test_empresa_gupy_mapa_conhecido():
    url = "https://vagas-mrveco.gupy.io/job/abc"
    assert c.empresa_de_url_gupy(url, "") == "MRV&CO"


@pytest.mark.unit
def test_empresa_gupy_confidencial():
    url = "https://paginaconfidencialoficial.gupy.io/job/abc"
    assert c.empresa_de_url_gupy(url, "") == "Empresa confidencial"


@pytest.mark.unit
def test_empresa_gupy_remove_ruido_prefixo():
    url = "https://vagas-acmeltda.gupy.io/job/abc"
    assert c.empresa_de_url_gupy(url, "") == "Acmeltda"


# ----------------------------------------------------------------------
# resumir
# ----------------------------------------------------------------------

@pytest.mark.unit
def test_resumir_remove_tags_e_entidades():
    bruto = "<p>Vaga de <b>Seguran&ccedil;a</b></p>"
    assert c.resumir(bruto) == "Vaga de Segurança"


@pytest.mark.unit
def test_resumir_vazio_retorna_placeholder():
    assert "Abra a vaga" in c.resumir("")


# ----------------------------------------------------------------------
# id_vaga
# ----------------------------------------------------------------------

@pytest.mark.unit
def test_id_vaga_usa_link_como_chave():
    # mesmo link (com querystring/barra diferentes) => mesmo id
    a = c.id_vaga("https://x.gupy.io/job/123?src=portal")
    b = c.id_vaga("https://x.gupy.io/job/123/")
    assert a == b and len(a) == 12


@pytest.mark.unit
def test_id_vaga_fallback_sem_link_estavel_a_acentos():
    a = c.id_vaga("", "Técnico", "Empresa", "Betim")
    b = c.id_vaga("", "Tecnico", "Empresa", "Betim")
    assert a == b and len(a) == 12
