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
from pathlib import Path

from flask import Flask, render_template, request, jsonify

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


@app.route("/api/consultores", methods=["GET"])
def obter_consultores():
    """Retorna todos os consultores cadastrados no servidor."""
    conn = get_db()
    row = conn.execute(
        "SELECT valor FROM armazenamento WHERE chave = 'consultores'"
    ).fetchone()
    conn.close()
    consultores = json.loads(row["valor"]) if row else []
    return jsonify({"consultores": consultores})


@app.route("/api/consultores", methods=["POST"])
def salvar_consultores():
    """Recebe a lista completa de consultores e persiste no servidor."""
    payload = request.get_json(force=True, silent=True) or {}
    consultores = payload.get("consultores", [])

    conn = get_db()
    conn.execute(
        """INSERT INTO armazenamento (chave, valor) VALUES ('consultores', ?)
           ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor""",
        (json.dumps(consultores, ensure_ascii=False),),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "total_consultores": len(consultores)})


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=debug, host="0.0.0.0", port=port)
