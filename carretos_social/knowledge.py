"""Base de conhecimento estruturada (dashboard → Conhecimento).

Cada marca ("geral" = David Carreto + Carretos Group; "auron"; "todas" = vale para todas) tem:
  - fichas por secção, cada uma com estado (publicável / interno / em desenvolvimento), função (contactos),
    validade e contas onde se aplica;
  - tom de comunicação e palavras proibidas.
A IA recebe SÓ as fichas publicáveis e válidas da marca da conta (+ as de "todas"). As fichas internas e
em desenvolvimento nunca são publicadas e as suas palavras bloqueiam a aprovação de uma legenda.
As fichas de partida vêm de config/conhecimento.yaml (só da 1.ª vez; as novas são propostas no dashboard).
"""
from __future__ import annotations

import json
from datetime import date, datetime

from .config import CONFIG_DIR
from .db import connect, now

SECTIONS = {
    "empresa": "Empresa e oficinas",
    "servicos": "Serviços e produtos",
    "condicoes": "Condições",
    "contactos": "Contactos e links",
    "pessoas": "Pessoas e história",
    "conquistas": "Conquistas e números",
    "faq": "Perguntas frequentes",
    "regras": "Regras de comunicação",
    "outros": "Por arrumar",
}
STATUS = {"publicavel": "Publicável", "interno": "Interno (nunca se publica)",
          "desenvolvimento": "Em desenvolvimento (ainda não se publica)"}
ROLES = {"cta": "Chamada à ação principal", "alternativa": "Alternativa", "duvidas": "Dúvidas", "info": "Informação"}
BRANDS_EXTRA = {"todas": "Todas as marcas"}
FIELDS = ("brand", "section", "text", "answer", "status", "role", "value", "keywords", "accounts", "valid_until")


# ------------------------------------------------------------------ fichas de partida (config)
def _seed() -> dict:
    import yaml
    p = CONFIG_DIR / "conhecimento.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _row_from_seed(f: dict) -> dict:
    return {"brand": f.get("marca", "geral"), "section": f.get("secao", "outros"), "text": f["texto"].strip(),
            "answer": f.get("resposta") or None, "status": f.get("estado", "publicavel"),
            "role": f.get("funcao") or None, "value": f.get("valor") or None,
            "keywords": json.dumps(f.get("palavras") or [], ensure_ascii=False),
            "accounts": json.dumps(f.get("contas") or [], ensure_ascii=False),
            "valid_until": f.get("validade") or None, "base_key": f.get("chave")}


def _setting(conn, key: str, default=None):
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def _set_setting(conn, key: str, value) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value, ensure_ascii=False)))


def ensure_seeded(conn) -> None:
    """Da 1.ª vez cria as fichas a partir de config/conhecimento.yaml, mais os factos que tenham sido editados
    na antiga página Factos (data/factos*.yaml), que ficam em "Por arrumar"."""
    if _setting(conn, "knowledge_seeded"):
        return
    seed = _seed()
    for i, f in enumerate(seed.get("fichas") or []):
        _insert(conn, _row_from_seed(f), position=i, action="importada")
    for brand_id, cfg in (seed.get("marcas") or {}).items():
        _set_setting(conn, f"tom:{brand_id}", (cfg.get("tom") or "").strip())
        _set_setting(conn, f"proibidas:{brand_id}", list(cfg.get("proibidas") or []))
    _import_old_facts(conn)
    # numa base nova o tom já vem completo: os ajustes ficam dados como aplicados
    _set_setting(conn, "tone_updates_done", [a["chave"] for a in (seed.get("ajustes_tom") or []) if a.get("chave")])
    _set_setting(conn, "knowledge_seeded", True)


def _import_old_facts(conn) -> None:
    import yaml
    from .config import DATA_DIR
    for path, brand_id in ((DATA_DIR / "factos.yaml", "geral"), (DATA_DIR / "factos_auron.yaml", "auron")):
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        have = {r["text"] for r in conn.execute("SELECT text FROM knowledge WHERE brand=?", (brand_id,))}
        for f in data.get("factos") or []:
            if str(f).strip() and str(f).strip() not in have:
                _insert(conn, {"brand": brand_id, "section": "outros", "text": str(f).strip()}, action="importada")
        if data.get("tom"):
            _set_setting(conn, f"tom:{brand_id}", str(data["tom"]).strip())


def apply_tone_updates(conn) -> None:
    """Ajustes ao tom pedidos pelo David (config/conhecimento.yaml → ajustes_tom), aplicados uma só vez."""
    done = set(_setting(conn, "tone_updates_done", []))
    pending = [a for a in (_seed().get("ajustes_tom") or []) if a.get("chave") and a["chave"] not in done]
    for a in pending:
        brand_id, extra = a.get("marca", "geral"), (a.get("acrescentar") or "").strip()
        current = str(_setting(conn, f"tom:{brand_id}", "") or "").strip()
        if extra and extra not in current:
            new = f"{current} {extra}".strip()
            _set_setting(conn, f"tom:{brand_id}", new)
            _log(conn, None, brand_id, None, "tom", current, new)
        done.add(a["chave"])
    if pending:
        _set_setting(conn, "tone_updates_done", sorted(done))


def new_base_items(conn, brand_id: str) -> list[dict]:
    """Fichas de config/conhecimento.yaml que ainda não estão no dashboard (nem foram apagadas de propósito)."""
    have = {r["base_key"] for r in conn.execute("SELECT base_key FROM knowledge WHERE base_key IS NOT NULL")}
    deleted = set(_setting(conn, "knowledge_deleted_keys", []))
    return [f for f in (_seed().get("fichas") or []) if f.get("marca", "geral") == brand_id
            and f.get("chave") and f["chave"] not in have and f["chave"] not in deleted]


def add_base_items(conn, brand_id: str, user_id: int | None = None) -> int:
    items = new_base_items(conn, brand_id)
    for f in items:
        _insert(conn, _row_from_seed(f), user_id=user_id, action="criada")
    return len(items)


# ------------------------------------------------------------------ ler / escrever
def _insert(conn, row: dict, position: int | None = None, user_id: int | None = None, action: str = "criada") -> int:
    row = {k: row.get(k) for k in (*FIELDS, "base_key") if k in row}
    row.setdefault("status", "publicavel")
    row.setdefault("keywords", "[]")
    row.setdefault("accounts", "[]")
    if position is None:
        position = (conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM knowledge WHERE brand=? AND section=?",
                                 (row["brand"], row["section"])).fetchone()[0])
    row.update(position=position, updated_at=now(), updated_by=user_id)
    cols = ",".join(row)
    iid = conn.execute(f"INSERT INTO knowledge({cols}) VALUES ({','.join('?' * len(row))})", list(row.values())).lastrowid
    _log(conn, iid, row["brand"], user_id, action, None, row)
    return iid


def _log(conn, item_id, brand_id, user_id, action, old, new) -> None:
    conn.execute("INSERT INTO knowledge_history(item_id, brand, at, user_id, action, old, new) VALUES (?,?,?,?,?,?,?)",
                 (item_id, brand_id, now(), user_id, action,
                  json.dumps(old, ensure_ascii=False) if old is not None else None,
                  json.dumps(new, ensure_ascii=False) if new is not None else None))


def items(conn, brand_id: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM knowledge", []
    if brand_id:
        q, args = q + " WHERE brand=?", [brand_id]
    out = []
    for r in conn.execute(q + " ORDER BY section, position, id", args):
        d = dict(r)
        d["keywords"] = json.loads(d.get("keywords") or "[]")
        d["accounts"] = json.loads(d.get("accounts") or "[]")
        d["expired"] = bool(d.get("valid_until") and d["valid_until"] < date.today().isoformat())
        out.append(d)
    order = list(SECTIONS)
    out.sort(key=lambda d: (order.index(d["section"]) if d["section"] in order else 99, d["position"], d["id"]))
    return out


def get(conn, item_id: int) -> dict | None:
    return next((i for i in items(conn) if i["id"] == item_id), None)


def clean(form: dict) -> dict:
    """Valores de um formulário → ficha (valida secção, estado e função)."""
    row = {
        "brand": form.get("brand", "geral"),
        "section": form.get("section") if form.get("section") in SECTIONS else "outros",
        "text": (form.get("text") or "").strip(),
        "answer": (form.get("answer") or "").strip() or None,
        "status": form.get("status") if form.get("status") in STATUS else "publicavel",
        "role": form.get("role") if form.get("role") in ROLES else None,
        "value": (form.get("value") or "").strip() or None,
        "keywords": json.dumps([k.strip() for k in (form.get("keywords") or "").split(",") if k.strip()],
                               ensure_ascii=False),
        "accounts": json.dumps(form.get("accounts") or [], ensure_ascii=False),
        "valid_until": (form.get("valid_until") or "").strip() or None,
    }
    if row["valid_until"]:
        datetime.strptime(row["valid_until"], "%Y-%m-%d")          # erro se a data for inválida
    if row["section"] != "contactos":
        row["role"], row["value"] = None, None
    if row["section"] != "faq":
        row["answer"] = None
    return row


def create(conn, row: dict, user_id: int | None = None) -> int:
    if not row["text"]:
        raise ValueError("A ficha precisa de texto.")
    return _insert(conn, row, user_id=user_id)


def update(conn, item_id: int, row: dict, user_id: int | None = None) -> None:
    old = conn.execute("SELECT * FROM knowledge WHERE id=?", (item_id,)).fetchone()
    if not old:
        raise ValueError("Essa ficha já não existe.")
    if not row["text"]:
        raise ValueError("A ficha precisa de texto.")
    old = dict(old)
    sets = {k: row[k] for k in FIELDS if k in row}
    if old["section"] != sets.get("section"):
        sets["position"] = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM knowledge WHERE brand=? AND section=?",
                                        (sets["brand"], sets["section"])).fetchone()[0]
    sets.update(updated_at=now(), updated_by=user_id)
    conn.execute(f"UPDATE knowledge SET {','.join(f'{k}=?' for k in sets)} WHERE id=?", [*sets.values(), item_id])
    _log(conn, item_id, sets["brand"], user_id, "alterada",
         {k: old[k] for k in FIELDS}, {k: sets[k] for k in FIELDS if k in sets})


def delete(conn, item_id: int, user_id: int | None = None) -> None:
    old = conn.execute("SELECT * FROM knowledge WHERE id=?", (item_id,)).fetchone()
    if not old:
        return
    conn.execute("DELETE FROM knowledge WHERE id=?", (item_id,))
    if old["base_key"]:                                   # não voltar a propor esta ficha da base
        keys = _setting(conn, "knowledge_deleted_keys", [])
        _set_setting(conn, "knowledge_deleted_keys", sorted(set(keys) | {old["base_key"]}))
    _log(conn, item_id, old["brand"], user_id, "apagada", {k: old[k] for k in FIELDS}, None)


def tone(conn, brand_id: str) -> str:
    return str(_setting(conn, f"tom:{brand_id}", "") or "").strip()


def forbidden_words(conn, brand_id: str) -> list[str]:
    return list(_setting(conn, f"proibidas:{brand_id}", []) or [])


def save_brand_rules(conn, brand_id: str, tom: str, proibidas: list[str], user_id: int | None = None) -> None:
    old_t, old_p = tone(conn, brand_id), forbidden_words(conn, brand_id)
    if tom.strip() != old_t:
        _set_setting(conn, f"tom:{brand_id}", tom.strip())
        _log(conn, None, brand_id, user_id, "tom", old_t, tom.strip())
    words = [w.strip() for w in proibidas if w.strip()]
    if words != old_p:
        _set_setting(conn, f"proibidas:{brand_id}", words)
        _log(conn, None, brand_id, user_id, "proibidas", old_p, words)


def history(conn, brand_id: str, limit: int = 40) -> list[dict]:
    rows = conn.execute("SELECT h.*, u.name AS user_name FROM knowledge_history h LEFT JOIN users u ON u.id=h.user_id "
                        "WHERE h.brand=? ORDER BY h.id DESC LIMIT ?", (brand_id, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        new = json.loads(d["new"]) if d["new"] else None
        old = json.loads(d["old"]) if d["old"] else None
        text = (new or {}).get("text") if isinstance(new, dict) else None
        text = text or ((old or {}).get("text") if isinstance(old, dict) else None)
        d["summary"] = {"criada": f"Criada: {text}", "importada": f"Importada: {text}",
                        "alterada": f"Alterada: {text}", "apagada": f"Apagada: {text}",
                        "tom": "Tom de comunicação alterado",
                        "proibidas": f"Palavras proibidas: {', '.join(new or []) or '(nenhuma)'}"}.get(d["action"], d["action"])
        out.append(d)
    return out


# ------------------------------------------------------------------ para a IA e para a verificação das legendas
def _applies(item: dict, account_id: str | None) -> bool:
    return not item["accounts"] or not account_id or account_id in item["accounts"]


def for_brand(brand_id: str, account_id: str | None = None, conn=None) -> list[dict]:
    """Fichas desta marca + as de "todas", só as válidas e que se aplicam à conta."""
    def run(c):
        return [i for i in items(c) if i["brand"] in (brand_id, "todas") and not i["expired"] and _applies(i, account_id)]
    if conn is not None:
        return run(conn)
    with connect() as c:
        return run(c)


def publishable_lines(brand_id: str, account_id: str | None = None) -> list[str]:
    """Factos publicáveis, já organizados por secção (para as instruções da IA e para a verificação)."""
    lines = []
    for i in for_brand(brand_id, account_id):
        if i["status"] != "publicavel" or i["section"] == "regras":
            continue
        label = SECTIONS.get(i["section"], i["section"])
        if i["section"] == "faq":
            lines.append(f"[{label}] P: {i['text']} — R: {i['answer'] or ''}")
        elif i["section"] == "contactos":
            role = ROLES.get(i["role"] or "info", "")
            lines.append(f"[{label} · {role}] {i['text']}" + (f" ({i['value']})" if i["value"] and i["value"] not in i["text"] else ""))
        else:
            lines.append(f"[{label}] {i['text']}")
    return lines


def prompt_block(brand_id: str, account_id: str | None = None) -> dict:
    """Partes das instruções da IA: factos, regras publicáveis, o que nunca se publica, contactos por função."""
    its = for_brand(brand_id, account_id)
    rules = [i["text"] for i in its if i["status"] == "publicavel" and i["section"] == "regras"]
    never = [i["text"] for i in its if i["status"] in ("interno", "desenvolvimento")]
    cta = [i for i in its if i["status"] == "publicavel" and i["section"] == "contactos" and i["role"] == "cta"]
    alt = [i for i in its if i["status"] == "publicavel" and i["section"] == "contactos" and i["role"] == "alternativa"]
    with connect() as c:
        t, words = tone(c, brand_id), forbidden_words(c, brand_id)
    return {"facts": publishable_lines(brand_id, account_id), "rules": rules, "never": never, "tone": t,
            "forbidden": words,
            "cta": "; ".join(f"{i['text']}" for i in cta), "alt": "; ".join(f"{i['text']}" for i in alt)}


def blocked_terms(brand_id: str, account_id: str | None = None) -> list[tuple[str, str]]:
    """[(palavra, aviso)]: palavras proibidas da marca + palavras das fichas internas/em desenvolvimento."""
    out: list[tuple[str, str]] = []
    with connect() as c:
        for w in forbidden_words(c, brand_id):
            msg = (f"Nas contas da Carretos não se usa o nome {w}." if w.upper() == "AURON" and brand_id == "geral"
                   else f"Nestas contas não se usa \"{w}\".")
            out.append((w, msg))
        for i in for_brand(brand_id, account_id, conn=c):
            if i["status"] in ("interno", "desenvolvimento"):
                kind = "Informação interna que não se publica" if i["status"] == "interno" else \
                    "Ainda em desenvolvimento, não se publica"
                out += [(k, f"{kind}: \"{k}\".") for k in i["keywords"]]
    return out


# ------------------------------------------------------------------ Excel
COLUMNS = [("id", "ID (não mudar)"), ("brand", "Marca"), ("section", "Secção"), ("text", "Texto / pergunta"),
           ("answer", "Resposta (perguntas frequentes)"), ("status", "Estado"), ("role", "Função (contactos)"),
           ("value", "Link / número"), ("keywords", "Palavras que bloqueiam (separadas por vírgula)"),
           ("accounts", "Contas (vazio = todas)"), ("valid_until", "Válida até (AAAA-MM-DD)")]


def export_xlsx(conn, path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Conhecimento"
    ws.append([label for _, label in COLUMNS])
    for c in ws[1]:
        c.font = Font(bold=True)
    for i in items(conn):
        ws.append([i["id"], i["brand"], i["section"], i["text"], i["answer"] or "", i["status"], i["role"] or "",
                   i["value"] or "", ", ".join(i["keywords"]), ", ".join(i["accounts"]), i["valid_until"] or ""])
    for col, width in zip("ABCDEFGHIJK", (8, 10, 12, 70, 50, 16, 14, 30, 30, 24, 14)):
        ws.column_dimensions[col].width = width
    help_ws = wb.create_sheet("Valores possíveis")
    help_ws.append(["Campo", "Valores"])
    help_ws.append(["Marca", "geral (David + Carretos Group), auron, todas"])
    help_ws.append(["Secção", ", ".join(SECTIONS)])
    help_ws.append(["Estado", ", ".join(STATUS)])
    help_ws.append(["Função", ", ".join(ROLES)])
    help_ws.append(["ID", "Linhas sem ID são fichas novas; com ID atualizam a ficha. Para apagar, use o dashboard."])
    wb.save(path)


def import_xlsx(conn, path, user_id: int | None = None) -> tuple[int, int, list[str]]:
    """Importa a folha "Conhecimento": cria as linhas sem ID e atualiza as que têm ID. Não apaga nada."""
    from openpyxl import load_workbook
    ws = load_workbook(path, read_only=True, data_only=True).worksheets[0]
    created = updated = 0
    errors: list[str] = []
    for n, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not any(row):
            continue
        vals = {k: ("" if v is None else str(v).strip()) for (k, _), v in zip(COLUMNS, row)}
        form = {**vals, "accounts": [a.strip() for a in vals.get("accounts", "").split(",") if a.strip()]}
        try:
            if form["brand"] not in ("geral", "auron", "todas"):
                raise ValueError(f"marca desconhecida '{form['brand']}'")
            data = clean(form)
            if vals.get("id"):
                update(conn, int(float(vals["id"])), data, user_id)
                updated += 1
            else:
                create(conn, data, user_id)
                created += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"linha {n}: {exc}")
    return created, updated, errors
