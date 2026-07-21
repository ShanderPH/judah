# INT-01 - ocorrência HubSpot ponta a ponta

O timestamp de NOVO é obtido do webhook ou da propriedade atual confirmada. Se
ambos faltarem ou forem inválidos, a fila falha fechada sem usar `timezone.now()`.
O identificador persistido do webhook segue como auditoria até o ciclo, sem
participar da identidade natural. O dispatch Celery ocorre em `on_commit()`.
