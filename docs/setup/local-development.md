# Desenvolvimento local

Pré-requisitos: Python 3.14, PostgreSQL e Redis. Crie o ambiente, instale
`requirements/dev.txt`, configure um `.env` local e execute:

```powershell
.\run.ps1 run
```

Validação segura e oficial:

```powershell
.venv\Scripts\python.exe run_tests_local.py
.venv\Scripts\python.exe run_checks.py
.venv\Scripts\ruff.exe check .
.venv\Scripts\mypy.exe apps core common
```

`run_tests_local.py` força banco SQLite local. Não execute a suíte contra banco
compartilhado: o isolamento de testes pode apagar dados.
