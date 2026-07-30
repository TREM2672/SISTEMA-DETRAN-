# Prontuário Digital do CFC — com backend real (Flask + SQLite)

Esta versão substitui o armazenamento no navegador por um **backend de
verdade**: um servidor Flask que salva todos os prontuários num banco
SQLite (`dados.db`), no próprio servidor. Assim, os dados:

- Não dependem mais do navegador/dispositivo de quem está usando.
- Continuam existindo mesmo se o navegador for trocado, o cache for
  limpo, ou o arquivo HTML for aberto de outro computador (desde que
  aponte para o mesmo servidor).
- Podem ser acessados por múltiplos computadores da mesma autoescola,
  todos apontando para o mesmo servidor.

## Estrutura

```
prontuario_backend/
├── app.py              # servidor Flask + API
├── requirements.txt
├── dados.db             # banco SQLite (criado automaticamente no 1º uso)
└── templates/
    └── index.html        # a interface (mesma que você já usava, agora
                           # conectada à API em vez do armazenamento local)
```

## Como rodar

```bash
pip install -r requirements.txt
python app.py
```

Acesse **http://localhost:5000** no navegador — é a mesma interface de
sempre, só que agora salvando no servidor.

Se quiser acessar de outros computadores da rede local, use o IP da
máquina que está rodando o servidor, por exemplo `http://192.168.0.10:5000`
(o servidor já sobe com `host="0.0.0.0"`, então aceita conexões de fora).

## Como funciona por baixo dos panos

- `GET /api/dados` → retorna todos os prontuários salvos, em JSON.
- `POST /api/dados` → recebe a lista completa de prontuários e salva no
  banco (substitui o conteúdo anterior).
- O JavaScript da página (`carregarDados()` / `salvarDados()`) chama
  essas duas rotas automaticamente, sempre que você abre a página ou
  faz qualquer alteração (matricula aluno, marca documento, gera taxa,
  etc.) — não precisa clicar em nenhum botão de "salvar" extra.

## Backup

Os dados ficam todos no arquivo `dados.db`. Pra fazer backup, basta
copiar esse arquivo pra outro lugar periodicamente. Pra restaurar,
é só colocar o arquivo de volta na pasta antes de iniciar o servidor.

## Próximos passos possíveis

- Autenticação (login da secretaria do CFC) antes de liberar acesso à API.
- Hospedar o servidor em um serviço na nuvem (Render, Railway, PythonAnywhere
  etc.) pra acessar de qualquer lugar, não só da rede local.
- Migrar de "salvar a lista inteira a cada alteração" para endpoints
  específicos por aluno (`/api/alunos/<id>`), o que fica mais eficiente
  conforme o número de alunos crescer bastante.
