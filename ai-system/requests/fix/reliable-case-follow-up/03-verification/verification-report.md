# Verificação

- ruff: aprovado nos arquivos alterados.
- mypy: aprovado nos arquivos de produção alterados.
- Testes direcionados finais: 44 passed.
- Testes direcionados de comercial, lote, contexto e regressão: 172 passed.
- Suíte completa: 722 passed, cobertura total 91.89%.
- Política comercial validada com pedidos diretos, mensagens fragmentadas e
  confirmação contextual; “plano de contas” e “valor do ingresso” não acionam
  o formulário.
- Fila validada com silêncio de 4s, teto de 12s, descarte atômico de tarefa
  superada e degradação sem perda quando o Redis está indisponível.
- Link Markdown do Typeform renderizado como âncora HTTPS segura no HubSpot.
- Consulta real, somente leitura:
  - frase ambígua solicita protocolo ou ID da igreja;
  - protocolo 46667856488 encontrado pelo fallback do Supabase;
  - igreja 35120 retornou 9 casos em acompanhamento;
  - nenhum dos status excluídos apareceu no resultado.
- Nenhuma mensagem foi enviada ao HubSpot durante a verificação.
- Nenhum ticket ou registro remoto foi alterado.
