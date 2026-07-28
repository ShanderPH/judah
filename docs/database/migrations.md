# Migrations

## Resumo

O JUDAH usa o sistema de migrations do Django. Cada app mantém seus arquivos de migration na pasta `migrations/`.

## Convenções

- Cada migration deve ser reversível (`reverse_code` para RunPython).
- Migrations de dados devem ser idempotentes.
- Em produção, nunca rodar `DROP`/`TRUNCATE` sem aprovação explícita.
- Adicionar índices com `AddIndex` em migrations separadas para grandes tabelas.

## Autoridade do schema

- O histórico de migrations Supabase descreve o bootstrap e o estado legado da
  plataforma; o grafo Django é a autoridade evolutiva do schema usado pelo JUDAH.
- Constraints criadas originalmente via Supabase devem ganhar uma migration
  Django explícita, idempotente e reversível antes de o código depender do novo
  contrato. Marcar uma `AlterField` como aplicada não substitui DDL externo.
- `support.0024_repair_queue_status_constraint` passa a administrar
  `new_conversations_queue_status_check` e valida sua definição no catálogo.

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
