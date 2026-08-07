"""
Backend do Sistema de Prontuário Digital do CFC.

Serve a interface (templates/index.html) e expõe uma API simples que
persiste todos os prontuários em um banco SQLite local (dados.db),
substituindo o armazenamento no navegador por um armazenamento real
no servidor.
"""
import json
import os
import secrets
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).parent
DB_PATH = Path(os.environ.get("DB_PATH", BASE_DIR / "dados.db"))

app = Flask(__name__)
# Railway (e a maioria dos hosts) coloca a app atrás de um proxy — sem isso,
# request.remote_addr mostraria o IP interno do proxy, não o do visitante real.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
# Sem SECRET_KEY configurada (env var), gera uma aleatória a cada início do processo —
# funciona, mas derruba todas as sessões logadas a cada deploy/restart. Pra sessões
# estáveis entre deploys, defina a variável de ambiente SECRET_KEY no Railway.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)


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


def login_obrigatorio(f):
    """Bloqueia a rota se não houver usuário logado na sessão."""
    @wraps(f)
    def decorada(*args, **kwargs):
        if not session.get("usuario"):
            return jsonify({"erro": "Login necessário."}), 401
        return f(*args, **kwargs)
    return decorada


def admin_obrigatorio(f):
    """Bloqueia a rota se quem estiver logado não for o admin/dono do sistema."""
    @wraps(f)
    def decorada(*args, **kwargs):
        usuario = session.get("usuario")
        if not usuario or not usuario.get("admin"):
            return jsonify({"erro": "Acesso restrito ao administrador."}), 403
        return f(*args, **kwargs)
    return decorada


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


@app.route("/api/sessao", methods=["GET"])
def obter_sessao():
    """Diz ao frontend se já existe alguém logado (pra restaurar o estado ao recarregar)."""
    usuario = session.get("usuario")
    return jsonify({"logado": bool(usuario), "usuario": usuario})


def _garantir_admin(consultores, promovido_id):
    """Se ninguém no sistema for admin ainda, promove quem está logando agora.
    Isso garante que a primeira pessoa a acessar depois de um banco novo/limpo
    vire o dono do sistema, sem precisar de um passo manual de setup."""
    if not any(c.get("admin") for c in consultores):
        for c in consultores:
            if c["id"] == promovido_id:
                c["admin"] = True
                return True
    return False


@app.route("/api/login", methods=["POST"])
def login():
    """Autentica um usuário reaproveitando o cadastro de consultores (nome + senha)."""
    payload = request.get_json(force=True, silent=True) or {}
    nome = (payload.get("nome") or "").strip()
    senha = payload.get("senha") or ""
    if not nome or not senha:
        return jsonify({"ok": False, "erro": "Informe nome e senha."}), 400

    consultores = _carregar_consultores()
    for c in consultores:
        if c.get("nome", "").strip().lower() == nome.lower() and c.get("senha_hash") and check_password_hash(c["senha_hash"], senha):
            c["ultimo_login_em"] = datetime.now().isoformat(timespec="seconds")
            c["ultimo_login_ip"] = request.remote_addr
            _garantir_admin(consultores, c["id"])
            _persistir_consultores(consultores)
            session["usuario"] = {"id": c["id"], "nome": c["nome"], "admin": bool(c.get("admin"))}
            return jsonify({"ok": True, "usuario": session["usuario"]})

    return jsonify({"ok": False, "erro": "Nome ou senha inválidos."}), 401


@app.route("/api/registrar", methods=["POST"])
def registrar():
    """Auto-cadastro: qualquer pessoa pode criar o próprio acesso de consultor.
    Guarda IP e data do cadastro pra fins de auditoria (visível só pro admin)."""
    payload = request.get_json(force=True, silent=True) or {}
    nome = (payload.get("nome") or "").strip()
    senha = payload.get("senha") or ""
    if not nome or not senha:
        return jsonify({"ok": False, "erro": "Informe nome e senha."}), 400
    if len(senha) < 4:
        return jsonify({"ok": False, "erro": "A senha precisa ter pelo menos 4 caracteres."}), 400

    consultores = _carregar_consultores()
    if any(c.get("nome", "").strip().lower() == nome.lower() for c in consultores):
        return jsonify({"ok": False, "erro": "Já existe um consultor cadastrado com esse nome."}), 409

    agora = datetime.now().isoformat(timespec="seconds")
    ip = request.remote_addr
    novo = {
        "id": "c_" + secrets.token_hex(6),
        "nome": nome,
        "senha_hash": generate_password_hash(senha),
        "criado_em": agora,
        "criado_ip": ip,
        "ultimo_login_em": agora,
        "ultimo_login_ip": ip,
        "admin": False,
    }
    consultores.append(novo)
    _garantir_admin(consultores, novo["id"])
    _persistir_consultores(consultores)

    session["usuario"] = {"id": novo["id"], "nome": novo["nome"], "admin": bool(novo.get("admin"))}
    return jsonify({"ok": True, "usuario": session["usuario"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/dados", methods=["GET"])
@login_obrigatorio
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
@login_obrigatorio
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
    """Lista pública/mínima — só nome e id. Usada pra tela de login saber se já
    existe algum consultor cadastrado (pra decidir entre 'entrar' e 'criar 1º acesso').
    Dados de auditoria (IP, datas, admin) só saem pelo /api/admin/consultores."""
    consultores = _carregar_consultores()
    publico = [{"id": c["id"], "nome": c["nome"]} for c in consultores]
    return jsonify({"consultores": publico})


@app.route("/api/admin/consultores", methods=["GET"])
@admin_obrigatorio
def obter_consultores_admin():
    """Lista completa com dados de auditoria — só o administrador/dono vê isso."""
    consultores = _carregar_consultores()
    completo = [{
        "id": c["id"],
        "nome": c["nome"],
        "admin": bool(c.get("admin")),
        "criado_em": c.get("criado_em"),
        "criado_ip": c.get("criado_ip"),
        "ultimo_login_em": c.get("ultimo_login_em"),
        "ultimo_login_ip": c.get("ultimo_login_ip"),
    } for c in consultores]
    return jsonify({"consultores": completo})


@app.route("/api/consultores", methods=["POST"])
@admin_obrigatorio
def salvar_consultores():
    """Recebe a lista de consultores (nome + senha opcional) e persiste com a senha
    sempre hasheada. Quando 'senha' vem vazia/ausente para um consultor que já existe,
    o hash atual é mantido — permite editar o nome sem precisar redigitar a senha.
    Só o admin pode chamar essa rota (gerencia todo mundo)."""
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

        if existente:
            criado_em = existente.get("criado_em")
            criado_ip = existente.get("criado_ip")
        else:
            criado_em = datetime.now().isoformat(timespec="seconds")
            criado_ip = request.remote_addr

        salvos.append({
            "id": cid,
            "nome": nome,
            "senha_hash": senha_hash,
            "admin": bool(existente.get("admin")) if existente else False,
            "criado_em": criado_em,
            "criado_ip": criado_ip,
            "ultimo_login_em": existente.get("ultimo_login_em") if existente else None,
            "ultimo_login_ip": existente.get("ultimo_login_ip") if existente else None,
        })

    _persistir_consultores(salvos)
    return jsonify({"ok": True, "total_consultores": len(salvos)})


@app.route("/api/admin/consultores/<consultor_id>/admin", methods=["POST"])
@admin_obrigatorio
def alternar_admin(consultor_id):
    """Promove ou rebaixa um consultor a administrador/dono do sistema."""
    payload = request.get_json(force=True, silent=True) or {}
    tornar_admin = bool(payload.get("admin"))

    consultores = _carregar_consultores()
    alvo = next((c for c in consultores if c["id"] == consultor_id), None)
    if not alvo:
        return jsonify({"ok": False, "erro": "Consultor não encontrado."}), 404

    if not tornar_admin and alvo["id"] == session["usuario"]["id"]:
        return jsonify({"ok": False, "erro": "Você não pode remover seu próprio acesso de administrador."}), 400

    alvo["admin"] = tornar_admin
    _persistir_consultores(consultores)
    return jsonify({"ok": True})


@app.route("/api/backup", methods=["GET"])
@login_obrigatorio
def baixar_backup():
    """Disponibiliza o banco SQLite atual como download, pra backup manual."""
    if not DB_PATH.exists():
        return jsonify({"erro": "Banco de dados ainda não existe."}), 404
    nome_arquivo = f"prontuario_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
    return send_file(DB_PATH, as_attachment=True, download_name=nome_arquivo)


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
