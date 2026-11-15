import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from avaliacoes.alertas import AlertasGitHub  # noqa: E402
from avaliacoes.google_api import Location  # noqa: E402
from avaliacoes.main import associar_oficinas, carregar_config, processar, relatorio  # noqa: E402
from avaliacoes.respostas import (  # noqa: E402
    comentario_original, primeiro_nome, resposta_modelo, validar_texto_ia,
)

AGORA = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
TITULOS = [
    "Carretos Almada | Mercedes Especialista",
    "Carretos Cacém ∣ Mercedes Especialista",
    "Carretos Lisboa ∣ Mercedes Especialista",
    "Carretos Mafra ∣ Mercedes Especialista",
    "Carretos Santarém | Mercedes Especialista",
]


def review(rid, stars, nome="João Silva", comentario="Excelente serviço!", data="2026-11-14T10:00:00Z", reply=None):
    r = {"name": f"accounts/1/locations/1/reviews/{rid}", "reviewId": rid, "starRating": stars,
         "reviewer": {"displayName": nome}, "createTime": data, "updateTime": data}
    if comentario:
        r["comment"] = comentario
    if reply:
        r["reviewReply"] = {"comment": reply}
    return r


class FakeClient:
    def __init__(self, reviews_por_titulo):
        self.locais = [Location("accounts/1", f"locations/{i}", t) for i, t in enumerate(TITULOS)]
        self.reviews = reviews_por_titulo
        self.publicadas = []

    def listar_locais(self):
        return self.locais

    def listar_avaliacoes(self, local):
        return iter(self.reviews.get(local.title, []))

    def responder(self, name, texto):
        self.publicadas.append((name, texto))


class Testes(unittest.TestCase):
    def setUp(self):
        self.oficinas, self.config = carregar_config()
        self.config = {**self.config, "modo": "modelos"}

    def test_associa_as_5_oficinas(self):
        mapa = associar_oficinas(self.oficinas, FakeClient({}).locais)
        self.assertEqual(len(mapa), 5)
        self.assertEqual(mapa["Carretos Cacém"].title, TITULOS[1])

    def test_comentario_traduzido(self):
        r = {"comment": "(Translated by Google) Great\n\n(Original)\nÓtimo atendimento"}
        self.assertEqual(comentario_original(r), "Ótimo atendimento")

    def test_nomes(self):
        self.assertEqual(primeiro_nome(review("a", "FIVE", nome="MARIA COSTA")), "Maria")
        self.assertIsNone(primeiro_nome(review("a", "FIVE", nome="A Google User")))
        self.assertIsNone(primeiro_nome(review("a", "FIVE", nome="J.")))

    def test_modelo(self):
        txt = resposta_modelo(review("x", "FIVE"), "Carretos Lisboa", self.config)
        self.assertTrue(txt.startswith("Olá João,"))
        self.assertTrue(txt.endswith("Equipa Carretos Lisboa"))
        sem = resposta_modelo(review("y", "FOUR", nome="", comentario=None), "Carretos Mafra", self.config)
        self.assertTrue(sem.startswith("Olá,"))

    def test_validacao_ia(self):
        validar_texto_ia("Obrigado pela visita!")
        for mau in ["", "Veja www.site.pt", "Ligue 912 345 678", "x" * 2000]:
            with self.assertRaises(ValueError):
                validar_texto_ia(mau)

    def test_fluxo_completo(self):
        client = FakeClient({
            TITULOS[0]: [
                review("r1", "FIVE"),
                review("r2", "FOUR", comentario=None),
                review("r3", "TWO", comentario="Demorou muito"),
                review("r4", "FIVE", reply="Já respondida"),
                review("r5", "FIVE", data="2025-01-01T00:00:00Z"),  # antiga
            ],
            TITULOS[4]: [review("r6", "FIVE", nome="Ana")],
        })
        cfg = {**self.config, "dias_maximos": 30}  # valida também o filtro de data opcional
        teste = processar(client, self.oficinas, cfg, publicar=False, agora=AGORA)
        self.assertEqual([r["oficina"] for r in teste.respondidas],
                         ["Carretos Almada", "Carretos Almada", "Carretos Santarém"])
        self.assertEqual(client.publicadas, [])  # modo teste não publica
        self.assertEqual(len(teste.baixas), 1)
        self.assertIn("MODO TESTE", relatorio(teste, False))

        real = processar(client, self.oficinas, cfg, publicar=True, agora=AGORA)
        self.assertEqual(len(client.publicadas), 3)
        self.assertFalse(real.erros)

    def test_limite_por_execucao(self):
        client = FakeClient({TITULOS[2]: [review(f"r{i}", "FIVE") for i in range(10)]})
        cfg = {**self.config, "max_respostas_por_execucao": 3}
        res = processar(client, self.oficinas, cfg, publicar=True, agora=AGORA)
        self.assertEqual(len(client.publicadas), 3)
        self.assertEqual(len(res.respondidas), 3)

    def test_oficina_inativa(self):
        oficinas = [{**o, "ativa": o["nome"] != "Carretos Mafra"} for o in self.oficinas]
        client = FakeClient({TITULOS[3]: [review("m1", "FIVE")]})
        res = processar(client, oficinas, self.config, publicar=True, agora=AGORA)
        self.assertEqual(res.respondidas, [])


    def test_sem_limite_de_data_responde_antigas(self):
        client = FakeClient({TITULOS[0]: [review("velha", "FIVE", data="2019-03-01T00:00:00Z")]})
        res = processar(client, self.oficinas, self.config, publicar=False, agora=AGORA)
        self.assertIsNone(self.config["dias_maximos"])
        self.assertEqual(len(res.respondidas), 1)

    def test_ia_recebe_respostas_recentes(self):
        vistos = []

        class GeradorFalso:
            def gerar(self, review, oficina, recentes):
                vistos.append(list(recentes))
                return f"resposta {review['reviewId']}", "ia"

        client = FakeClient({TITULOS[1]: [
            review("a", "FIVE"), review("b", "FIVE", reply="Obrigado, até breve!"), review("c", "FOUR")]})
        processar(client, self.oficinas, self.config, publicar=False, gerador=GeradorFalso(), agora=AGORA)
        self.assertEqual(vistos, [[], ["resposta a", "Obrigado, até breve!"]])


class FakeGitHub(AlertasGitHub):
    def __init__(self, issues):
        self.dono = "dono"
        self.issues = issues
        self.chamadas = []

    def _req(self, method, path, **kw):
        self.chamadas.append((method, path, kw.get("json")))
        if method == "GET":
            return self.issues if kw["params"]["page"] == 1 else []
        return {}


class TestesAlertas(unittest.TestCase):
    BAIXA = {"id": "r3", "oficina": "Carretos Almada", "estrelas": 2, "autor": "Rui",
             "comentario": "Demorou muito", "data": "2026-11-10"}

    def test_cria_alerta_uma_vez(self):
        gh = FakeGitHub([])
        self.assertEqual(gh.sincronizar([self.BAIXA]), (1, 0))
        method, path, body = gh.chamadas[-1]
        self.assertEqual((method, path), ("POST", "/issues"))
        self.assertIn("<!-- review:r3 -->", body["body"])
        self.assertEqual(body["assignees"], ["dono"])

        gh2 = FakeGitHub([{"number": 7, "state": "open", "body": body["body"]}])
        self.assertEqual(gh2.sincronizar([self.BAIXA]), (0, 0))

    def test_fecha_quando_respondida(self):
        issue = {"number": 7, "state": "open", "body": "x <!-- review:r3 -->"}
        self.assertEqual(FakeGitHub([issue]).sincronizar([]), (0, 1))
        # com erros de leitura não fecha nada
        self.assertEqual(FakeGitHub([issue]).sincronizar([], pode_fechar=False), (0, 0))


if __name__ == "__main__":
    unittest.main()
