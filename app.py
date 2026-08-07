"""
Backend do Sistema de Prontuário Digital do CFC.

Serve a interface (templates/index.html) e expõe uma API simples que
persiste todos os prontuários em um banco SQLite local (dados.db),
substituindo o armazenamento no navegador por um armazenamento real
no servidor.
"""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).parent
DB_PATH = Path(os.environ.get("DB_PATH", BASE_DIR / "dados.db"))

app = Flask(__name__)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS armazenamento (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


init_db()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/dados", methods=["GET"])
def obter_dados():
    """Retorna todos os prontuários salvos no servidor."""
    conn = get_db()
    row = conn.execute(
        "SELECT valor FROM armazenamento WHERE chave = 'alunos'"
    ).fetchone()
    conn.close()
    alunos = json.loads(row["valor"]) if row else []
    return jsonify({"alunos": alunos})


@app.route("/api/dados", methods=["POST"])
def salvar_dados():
    """Recebe a lista completa de prontuários e persiste no servidor."""
    payload = request.get_json(force=True, silent=True) or {}
    alunos = payload.get("alunos", [])

    conn = get_db()
    conn.execute(
        """INSERT INTO armazenamento (chave, valor) VALUES ('alunos', ?)
           ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor""",
        (json.dumps(alunos, ensure_ascii=False),),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "total_alunos": len(alunos)})


def _carregar_consultores():
    conn = get_db()
    row = conn.execute(
        "SELECT valor FROM armazenamento WHERE chave = 'consultores'"
    ).fetchone()
    conn.close()
    return json.loads(row["valor"]) if row else []


def _persistir_consultores(consultores):
    conn = get_db()
    conn.execute(
        """INSERT INTO armazenamento (chave, valor) VALUES ('consultores', ?)
           ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor""",
        (json.dumps(consultores, ensure_ascii=False),),
    )
    conn.commit()
    conn.close()


@app.route("/api/consultores", methods=["GET"])
def obter_consultores():
    """Retorna os consultores cadastrados, sem expor a senha (hash) ao navegador."""
    consultores = _carregar_consultores()
    publico = [{"id": c["id"], "nome": c["nome"]} for c in consultores]
    return jsonify({"consultores": publico})


@app.route("/api/consultores", methods=["POST"])
def salvar_consultores():
    """Recebe a lista de consultores (nome + senha opcional) e persiste com a senha
    sempre hasheada. Quando 'senha' vem vazia/ausente para um consultor que já existe,
    o hash atual é mantido — permite editar o nome sem precisar redigitar a senha."""
    payload = request.get_json(force=True, silent=True) or {}
    recebidos = payload.get("consultores", [])
    atuais = {c["id"]: c for c in _carregar_consultores()}

    salvos = []
    for c in recebidos:
        cid = c.get("id")
        nome = (c.get("nome") or "").strip()
        senha_nova = c.get("senha") or ""
        existente = atuais.get(cid)
        if senha_nova:
            senha_hash = generate_password_hash(senha_nova)
        elif existente:
            senha_hash = existente.get("senha_hash", "")
        else:
            senha_hash = ""
        salvos.append({"id": cid, "nome": nome, "senha_hash": senha_hash})

    _persistir_consultores(salvos)
    return jsonify({"ok": True, "total_consultores": len(salvos)})


@app.route("/api/backup", methods=["GET"])
def baixar_backup():
    """Disponibiliza o banco SQLite atual como download, pra backup manual."""
    if not DB_PATH.exists():
        return jsonify({"erro": "Banco de dados ainda não existe."}), 404
    nome_arquivo = f"prontuario_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
    return send_file(DB_PATH, as_attachment=True, download_name=nome_arquivo)


@app.route("/api/status", methods=["GET"])
def status_armazenamento():
    """Informações pra conferir se o banco está num caminho persistente
    (ex.: um Volume do Railway) e não vai ser apagado a cada deploy."""
    return jsonify({
        "db_path": str(DB_PATH),
        "db_path_configurado": "DB_PATH" in os.environ,
        "db_existe": DB_PATH.exists(),
    })


@app.route("/api/consultores/verificar", methods=["POST"])
def verificar_senha_consultor():
    """Verifica uma senha de consultor no servidor. As senhas nunca saem do backend
    em texto puro nem como hash — só o resultado da verificação."""
    payload = request.get_json(force=True, silent=True) or {}
    senha = payload.get("senha") or ""
    if not senha:
        return jsonify({"ok": False}), 400

    for c in _carregar_consultores():
        if c.get("senha_hash") and check_password_hash(c["senha_hash"], senha):
            return jsonify({"ok": True, "consultor": {"id": c["id"], "nome": c["nome"]}})
    return jsonify({"ok": False}), 401


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=debug, host="0.0.0.0", port=port)
