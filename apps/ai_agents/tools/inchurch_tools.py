from __future__ import annotations

import os

import httpx
import structlog
from agno.tools import Toolkit

logger = structlog.get_logger(__name__)


class InChurchDiagnosticsTool(Toolkit):
    """Ferramenta para diagnóstico de dados internos da InChurch (Eventos, etc)."""

    def __init__(self) -> None:
        super().__init__(name="inchurch_diagnostics")
        self.register(self.diagnose_event_visibility)

    def diagnose_event_visibility(self, event_id: int) -> str:
        """Diagnostica o porquê de um evento não estar visível no portal/app.

        Faz uma requisição à API interna da InChurch para verificar o status
        de um evento em tempo real e sugerir correções ao usuário.

        Args:
            event_id: O ID do evento a ser verificado.

        Returns:
            Relatório formatado em Markdown com o status, problemas encontrados,
            e as soluções sugeridas.
        """
        token = os.getenv("INRADAR_AUTH_TOKEN", "")
        if not token:
            return "Erro Interno: O Token de autenticação para o diagnóstico InRadar não está configurado. Transfira a solicitação para um humano."

        url = "https://www.inradar.com.br/api/v1/webhook/operations/read_event/"

        try:
            with httpx.Client() as client:
                response = client.post(
                    url, headers={"Authorization": f"Bearer {token}"}, json={"event_id": event_id}, timeout=10.0
                )

                if response.status_code == 404:
                    return f"❌ Evento com ID {event_id} não foi encontrado na base de dados."

                if response.status_code != 200:
                    logger.error("diagnose_event_failed", event_id=event_id, status_code=response.status_code)
                    return f"⚠️ Não foi possível verificar o evento no momento. A API retornou status {response.status_code}."

                data = response.json()

                # Extrai chaves da resposta da API de webhooks velha
                is_active = data.get("is_active", False)
                is_enabled = data.get("is_enabled", False)
                published_for = data.get("published_for", "nenhum")
                has_active_tickets = data.get("has_active_tickets", False)

                issues = []
                solutions = []

                if not is_enabled:
                    issues.append("- O evento está desabilitado (`is_enabled: false`).")
                    solutions.append("- Habilite o evento no painel administrativo principal.")

                if not is_active:
                    issues.append("- O evento está inativo (`is_active: false`).")
                    solutions.append("- Ative o evento nas abas de configuração do sistema.")

                if str(published_for).lower() not in ["todos", "all", "public", "público"]:
                    issues.append(f"- O evento não é público (Publicado para: `{published_for}`).")
                    solutions.append(
                        "- Certifique-se de publicar o evento para 'Todos' se quiser listá-lo publicamente, ou indique ao membro que ele precisa fazer login correspondente."
                    )

                if not has_active_tickets:
                    issues.append("- O evento não possui ingressos ou lotes ativos configurados.")
                    solutions.append("- Crie e publique pelo menos um lote de ingresso para liberar o evento no app.")

                if not issues:
                    status_text = "✅ **Evento OK**"
                    diagnosis = "Nenhuma restrição encontrada neste diagnóstico rápido! O evento deve estar visível (exceto em casos de cache não-vencido no aplicativo)."
                else:
                    status_text = "❌ **Problemas Encontrados:**\n" + "\n".join(issues)
                    diagnosis = (
                        "💡 **Soluções:** O usuário deverá tomar as seguintes ações no painel da InChurch:\n"
                        + "\n".join(solutions)
                    )

                return f"### Diagnóstico do Evento {event_id}\n\n{status_text}\n\n{diagnosis}"

        except Exception as e:
            logger.error("diagnose_event_exception", event_id=event_id, error=str(e))
            return "⚠️ Ocorreu um erro de comunicação na leitura da API InRadar. O diagnóstico não pôde ser completado autonomamente."
