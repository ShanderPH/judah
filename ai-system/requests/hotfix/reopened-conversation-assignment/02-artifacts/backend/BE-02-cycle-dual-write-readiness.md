# BE-02 - dual-write e readiness de ciclos

O ingresso Matchmaker abre/anexa ciclo somente para ocorrência comprovável. Com
enforcement desligado, falhas de identidade preservam o fluxo legado; com ele
ligado, falham antes de criar fila. O `cycle_id` é propagado aditivamente pelos
writers atuais sem alterar a decisão de reserva. Readiness expõe apenas flags e
contagens agregadas de cobertura e divergência, sem portal, ticket ou PII.
