"""Ponto de entrada: python -m avaliacoes.main [--publicar] [--listar-locais]

Por omissão corre em MODO TESTE: mostra as respostas que daria, sem publicar nada.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .alertas import AlertasGitHub
from .google_api import GoogleBusinessClient, Location
from .respostas import Gerador, comentario_original, estrelas, normalizar

log = logging.getLogger("avaliacoes")
RAIZ = Path(__file__).resolve().parents[2]
SECRETS_GOOGLE = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")


@dataclass
class Resultado:
    respondidas: list[dict] = field(default_factory=list)
    baixas: list[dict] = field(default_factory=list)       # 1-3 estrelas (sem resposta automática)
    erros: list[str] = field(default_factory=list)
    oficinas_em_falta: list[str] = field(default_factory=list)


def carregar_config() -> tuple[list[dict], dict]:
    oficinas = yaml.safe_load((RAIZ / "config/oficinas.yaml").read_text())["oficinas"]
    respostas = yaml.safe_load((RAIZ / "config/respostas.yaml").read_text())
    return oficinas, respostas


def associar_oficinas(oficinas: list[dict], locais: list[Location]) -> dict[str, Location]:
    """Liga cada oficina do config à ficha Google correspondente."""
    mapa = {}
    for of in oficinas:
        chave = normalizar(of["procurar"])
        encontrados = [l for l in locais if chave in normalizar(l.title)]
        if len(encontrados) == 1:
            mapa[of["nome"]] = encontrados[0]
        elif len(encontrados) > 1:
            log.error("'%s' corresponde a várias fichas: %s", of["nome"], [l.title for l in encontrados])
    return mapa


def _data(review: dict) -> datetime:
    valor = review.get("updateTime") or review.get("createTime")
    return datetime.fromisoformat(valor.replace("Z", "+00:00"))


def processar(client, oficinas: list[dict], config: dict, publicar: bool,
              gerador: Gerador | None = None, agora: datetime | None = None) -> Resultado:
    res = Resultado()
    gerador = gerador or Gerador(config)
    agora = agora or datetime.now(timezone.utc)
    dias = config.get("dias_maximos")
    limite_data = agora - timedelta(days=dias) if dias else None
    minimo = config.get("estrelas_minimas", 4)
    restantes = config.get("max_respostas_por_execucao", 25)

    ativas = [o for o in oficinas if o.get("ativa", True)]
    mapa = associar_oficinas(ativas, client.listar_locais())
    res.oficinas_em_falta = [o["nome"] for o in ativas if o["nome"] not in mapa]

    for nome, local in mapa.items():
        try:
            for review in client.listar_avaliacoes(local):
                if limite_data and _data(review) < limite_data:
                    break  # ordenadas da mais recente para a mais antiga
                if review.get("reviewReply"):
                    continue
                n = estrelas(review)
                info = {
                    "id": review.get("reviewId") or review["name"].rsplit("/", 1)[-1],
                    "oficina": nome,
                    "estrelas": n,
                    "autor": (review.get("reviewer") or {}).get("displayName", "?"),
                    "comentario": comentario_original(review),
                    "data": _data(review).date().isoformat(),
                }
                if n < minimo:
                    res.baixas.append(info)
                    continue
                if restantes <= 0:
                    continue
                texto, origem = gerador.gerar(review, nome)
                if publicar:
                    client.responder(review["name"], texto)
                res.respondidas.append({**info, "resposta": texto, "origem": origem})
                restantes -= 1
        except Exception as e:  # noqa: BLE001 - uma oficina com erro não pára as outras
            log.exception("Erro na oficina %s", nome)
            res.erros.append(f"{nome}: {e}")
    return res


def relatorio(res: Resultado, publicar: bool) -> str:
    modo = "PUBLICADO" if publicar else "MODO TESTE (nada foi publicado)"
    linhas = [f"# Avaliações Google – {modo}", ""]
    linhas.append(f"**Respostas {'publicadas' if publicar else 'propostas'}:** {len(res.respondidas)}")
    for r in res.respondidas:
        linhas += ["", f"### {r['oficina']} – {'★' * r['estrelas']} – {r['autor']} ({r['data']}) [{r['origem']}]",
                   f"> {r['comentario'] or '(sem comentário)'}", "", r["resposta"].replace("\n", "  \n")]
    if res.baixas:
        linhas += ["", f"## ⚠️ Avaliações de 1–3 estrelas por responder: {len(res.baixas)}"]
        for b in res.baixas:
            linhas.append(f"- **{b['oficina']}** – {'★' * b['estrelas']} – {b['autor']} ({b['data']}): {b['comentario'] or '(sem comentário)'}")
    if res.oficinas_em_falta:
        linhas += ["", f"## ❌ Oficinas não encontradas no Google: {', '.join(res.oficinas_em_falta)}"]
    if res.erros:
        linhas += ["", "## ❌ Erros"] + [f"- {e}" for e in res.erros]
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--publicar", action="store_true", help="publica mesmo as respostas no Google")
    p.add_argument("--listar-locais", action="store_true", help="só lista as fichas acessíveis")
    args = p.parse_args(argv)

    em_falta = [s for s in SECRETS_GOOGLE if not os.environ.get(s)]
    if em_falta:
        log.warning("Credenciais Google ainda não configuradas (%s). Nada a fazer.", ", ".join(em_falta))
        return 0

    client = GoogleBusinessClient.from_env()
    if args.listar_locais:
        for l in client.listar_locais():
            print(f"{l.v4_path}\t{l.title}")
        return 0

    oficinas, config = carregar_config()
    res = processar(client, oficinas, config, publicar=args.publicar)
    texto = relatorio(res, args.publicar)
    if config.get("alertas", True) and AlertasGitHub.disponivel():
        try:
            criados, fechados = AlertasGitHub.from_env().sincronizar(
                res.baixas, pode_fechar=not (res.erros or res.oficinas_em_falta))
            texto += f"\n\n**Alertas:** {criados} novo(s), {fechados} fechado(s) (já respondidas)."
        except Exception as e:  # noqa: BLE001
            log.exception("Falha ao criar alertas")
            res.erros.append(f"Alertas: {e}")
    print(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    return 1 if (res.erros or res.oficinas_em_falta) else 0


if __name__ == "__main__":
    sys.exit(main())
