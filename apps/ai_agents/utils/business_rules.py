"""Motor de regras de negócio — horário comercial, janelas especiais e feriados.

Todas as decisões de tempo são tomadas em America/Sao_Paulo (UTC-3/UTC-2).
Usar `datetime.now(tz=...)` + `zoneinfo.ZoneInfo` em Python 3.14 é o caminho
canônico — nunca `datetime.utcnow()` (deprecated) nem `pytz` (descontinuado
para código novo).

As funções recebem `now` opcional para facilitar testes. Em produção, basta
chamá-las sem argumentos — elas consultam o relógio no fuso correto.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")

# Feriados hardcoded — mova para um banco/config quando a lista crescer.
# Chave é a data, valor é a descrição humana (usada em logs).
HOLIDAYS: dict[date, str] = {
    date(2026, 1, 1): "Confraternização Universal",
    date(2026, 2, 16): "Carnaval (segunda)",
    date(2026, 2, 17): "Carnaval (terça)",
    date(2026, 4, 3): "Sexta-feira Santa",
    date(2026, 4, 21): "Tiradentes",
    date(2026, 5, 1): "Dia do Trabalho",
    date(2026, 6, 4): "Corpus Christi",
    date(2026, 9, 7): "Independência do Brasil",
    date(2026, 10, 12): "Nossa Senhora Aparecida",
    date(2026, 11, 2): "Finados",
    date(2026, 11, 15): "Proclamação da República",
    date(2026, 12, 25): "Natal",
    # Feriados corporativos InChurch (exemplo — confirmar com RH).
    date(2026, 12, 24): "Véspera de Natal (InChurch)",
    date(2026, 12, 31): "Véspera de Ano Novo (InChurch)",
}


def now_sao_paulo() -> datetime:
    """Retorna o datetime atual no fuso America/Sao_Paulo."""
    return datetime.now(tz=SAO_PAULO_TZ)


def _resolve(now: datetime | None) -> datetime:
    """Normaliza o `now` recebido: se None usa agora; se naive, localiza em SP."""
    if now is None:
        return now_sao_paulo()
    if now.tzinfo is None:
        return now.replace(tzinfo=SAO_PAULO_TZ)
    return now.astimezone(SAO_PAULO_TZ)


def is_quinta_fire(now: datetime | None = None) -> bool:
    """True se for quinta-feira entre 12h00 e 13h00 (janela 'Quinta Fire').

    Usado pelo legado para bloquear atendimento durante reunião semanal.
    Intervalo fechado no início e aberto no fim: [12:00, 13:00).
    """
    local = _resolve(now)
    # weekday(): segunda=0 ... domingo=6 → quinta-feira == 3.
    if local.weekday() != 3:
        return False
    return time(12, 0) <= local.time() < time(13, 0)


def is_business_hours(now: datetime | None = None) -> bool:
    """True se estiver dentro do horário comercial InChurch.

    Grade oficial:
      - Segunda a Sexta: 09:00 - 18:00
      - Sábado:          09:00 - 13:00
      - Domingo:         08:00 - 12:00

    Retorna False em feriados (qualquer dia da semana) e na janela
    'Quinta Fire' (quinta 12h-13h), já que o time está indisponível nesses
    períodos.
    """
    local = _resolve(now)

    if is_holiday(local):
        return False
    if is_quinta_fire(local):
        return False

    weekday = local.weekday()  # 0=seg ... 6=dom
    current = local.time()

    if weekday <= 4:  # seg-sex
        return time(9, 0) <= current < time(18, 0)
    if weekday == 5:  # sábado
        return time(9, 0) <= current < time(13, 0)
    # domingo
    return time(8, 0) <= current < time(12, 0)


def is_holiday(now: datetime | None = None) -> bool:
    """True se a data atual (em SP) cair num feriado listado em HOLIDAYS."""
    local = _resolve(now)
    return local.date() in HOLIDAYS


def holiday_name(now: datetime | None = None) -> str | None:
    """Nome do feriado atual, ou None se hoje não for feriado."""
    local = _resolve(now)
    return HOLIDAYS.get(local.date())


def off_hours_reason(now: datetime | None = None) -> str | None:
    """Motivo legível para fora-de-horário, ou None se estiver dentro do horário.

    Usado para logging estruturado e para preencher o pipeline 'Fora de Horário'
    do HubSpot com uma justificativa clara.
    """
    local = _resolve(now)

    if is_holiday(local):
        return f"holiday:{holiday_name(local)}"
    if is_quinta_fire(local):
        return "quinta_fire"
    if is_business_hours(local):
        return None
    return "off_hours"


__all__ = [
    "HOLIDAYS",
    "SAO_PAULO_TZ",
    "holiday_name",
    "is_business_hours",
    "is_holiday",
    "is_quinta_fire",
    "now_sao_paulo",
    "off_hours_reason",
]
