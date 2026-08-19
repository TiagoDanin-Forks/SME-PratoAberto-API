# coding: utf-8
"""Testes de regressão da impressão do cardápio (recreio nas férias).

Cenário do bug (produção, julho/2024):
- A última semana de julho/2024 (29/07 a 04/08) cruza a data_fim da unidade
  especial do recreio nas férias (31/07/2024).
- Antes da correção, a busca da unidade especial exigia que o período da semana
  estivesse totalmente contido no da unidade, então a unidade não era encontrada,
  o tipo_unidade voltava ao do request e nenhum cardápio era achado, resultando em
  IndexError na linha 416 (list index out of range).

Correção:
1. find_menu_json passou a buscar a unidade especial por INTERSEÇÃO de períodos.
2. ReportPdf.get ganhou guard que retorna 404 quando não há cardápios publicados.

Os testes usam o banco local (API_MONGO_URI) e criam/limpam os próprios dados.
"""

import datetime
import json

import pytest

ESCOLA_NOME = 'EMEF RECREIO TESTE'
ESCOLA_ID = 900001
UE_NOME = 'RECREIO_FERIAS'


@pytest.fixture
def db():
    import api
    return api.db


@pytest.fixture
def dados_recreio_ferias(db):
    """Cria escola, UEs e cardápios de recreio nas férias (jul/2024 e jul/2025)."""
    # Limpa dados de teste anteriores
    db.unidades_especiais.delete_many({'nome': UE_NOME})
    db.cardapios.delete_many({'tipo_unidade': UE_NOME})
    db.cardapios.delete_many({'tipo_unidade': 'EMEF', 'data': {'$regex': '^2024'}})

    # Escola normal que participa do recreio nas férias
    db.escolas.update_one(
        {'_id': ESCOLA_ID},
        {'$set': {
            'nome': ESCOLA_NOME,
            'tipo_unidade': 'EMEF',
            'tipo_atendimento': 'TERCEIRIZADA',
            'agrupamento': 'EDITAL 78/2016',
            'status': 'ativo',
            'idades': ['G - 4 A 6 ANOS', 'F - 1 A 3 ANOS', 'Z - UNIDADES SEM FAIXA'],
            'refeicoes': ['A - ALMOCO', 'L - LANCHE'],
        }},
        upsert=True)
    db.escolas_editais.update_one(
        {'escola': ESCOLA_ID},
        {'$set': {'escola': ESCOLA_ID, 'edital': 'EDITAL 78/2016', 'data_inicio': '20171218',
                  'data_fim': None, 'tipo_atendimento': 'TERCEIRIZADA'}},
        upsert=True)

    # UE do recreio jul/2024 com data_fim = 31/07 (cenário do bug)
    db.unidades_especiais.insert_one({
        'nome': UE_NOME, 'data_criacao': '20240601',
        'data_inicio': '20240701', 'data_fim': '20240731',
        'escolas': [str(ESCOLA_ID)],
    })
    # UE do recreio jul/2025 com data_fim = 01/08 (cobrindo a última semana)
    db.unidades_especiais.insert_one({
        'nome': UE_NOME, 'data_criacao': '20250601',
        'data_inicio': '20250701', 'data_fim': '20250801',
        'escolas': [str(ESCOLA_ID)],
    })

    # Cardápios publicados de recreio (dias úteis) para jul/2024 e jul/2025
    for ano in (2024, 2025):
        d = datetime.date(ano, 7, 1)
        while d <= datetime.date(ano, 7, 31):
            if d.weekday() < 5:
                db.cardapios.insert_one({
                    'agrupamento': 'UE', 'tipo_unidade': UE_NOME,
                    'tipo_atendimento': 'UE', 'status': 'PUBLICADO',
                    'idade': 'Z - UNIDADES SEM FAIXA', 'data': d.strftime('%Y%m%d'),
                    'data_publicacao': d.strftime('%Y%m%d') + 'T10:00:00.000Z',
                    'cardapio': {'A - ALMOCO': ['ARROZ'], 'L - LANCHE': ['PÃO']},
                })
            d += datetime.timedelta(days=1)

    yield db

    # Limpeza
    db.unidades_especiais.delete_many({'nome': UE_NOME})
    db.cardapios.delete_many({'tipo_unidade': UE_NOME})
    db.cardapios.delete_many({'tipo_unidade': 'EMEF', 'data': {'$regex': '^2024'}})


def url_cardapio_pdf(data_inicial, data_final):
    return (
        '/cardapio-pdf?nome={nome}&tipo_unidade=EMEF&tipo_atendimento=TERCEIRIZADA'
        '&agrupamento=EDITAL 78/2016&data_inicial={inicio}&data_final={fim}'
    ).format(nome=ESCOLA_NOME, inicio=data_inicial, fim=data_final)


class TestCardapioPdfRecreioFerias:

    def test_impressao_semana_dentro_da_unidade(self, client, dados_recreio_ferias):
        """Semana totalmente dentro do período da UE deve gerar PDF."""
        res = client.get(url_cardapio_pdf('20240701', '20240707'))
        assert res.status_code == 200
        assert res.mimetype == 'application/pdf'

    def test_impressao_semana_cruzando_o_fim_da_unidade(self, client, dados_recreio_ferias):
        """REGRESSÃO: semana 29/07-04/08 cruza a data_fim da UE (31/07).

        Antes da correção, isso estourava IndexError (500). Agora deve gerar PDF.
        """
        res = client.get(url_cardapio_pdf('20240729', '20240804'))
        assert res.status_code == 200
        assert res.mimetype == 'application/pdf'

    def test_impressao_dia_29_07_2024(self, client, dados_recreio_ferias):
        """Impressão do último dia do recreio (dia específico) deve gerar PDF."""
        res = client.get(url_cardapio_pdf('20240729', '20240729'))
        assert res.status_code == 200

    def test_impressao_julho_2025_ultima_semana(self, client, dados_recreio_ferias):
        """Julho/2025 (que funcionava) continua funcionando na última semana."""
        res = client.get(url_cardapio_pdf('20250728', '20250803'))
        assert res.status_code == 200

    def test_impressao_semana_sem_cardapios_retorna_404(self, client, dados_recreio_ferias):
        """REGRESSÃO: semana sem cardápios publicados deve retornar 404 amigável,
        não 500 (IndexError)."""
        res = client.get(url_cardapio_pdf('20240805', '20240809'))
        assert res.status_code == 404
        assert json.loads(res.data.decode('utf-8')) == {
            'erro': 'Nenhum cardápio publicado para o período solicitado.'}
