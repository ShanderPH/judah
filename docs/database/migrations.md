# Migrations

## Resumo

O JUDAH usa o sistema de migrations do Django. Cada app mantém seus arquivos de migration na pasta `migrations/`.

## Convenções

- Cada migration deve ser reversível (`reverse_code` para RunPython).
- Migrations de dados devem ser idempotentes.
- Em produção, nunca rodar `DROP`/`TRUNCATE` sem aprovação explícita.
- Adicionar índices com `AddIndex` em migrations separadas para grandes tabelas.

## Comandos úteis

```bash
# Criar migration após alterar models
python manage.py makemigrations

# Aplicar migrations
python manage.py migrate

# Verificar status
python manage.py showmigrations

# Reverter até uma migration específica
python manage.py migrate support 0032

# Gerar SQL da migration
python manage.py sqlmigrate support 0033
```

## Estrutura

```text
apps/<app>/migrations/
  __init__.py
  0001_initial.py
  0002_...
```

## Migrations recentes conhecidas

> TODO: confirmar listagem exata com `python manage.py showmigrations`.

## Arquivos relacionados

- [`database/models.md`](./models.md)
- [`database/overview.md`](./overview.md)
