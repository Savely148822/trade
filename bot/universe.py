"""Стартовые вселенные тикеров MOEX (этап 1 — фиксированный список)."""

# Core: БПИФ + ликвидные голубые фишки (долг, ~80%)
DEFAULT_CORE_UNIVERSE: list[str] = [
    "SBMX",  # российские акции
    "TMOS",  # индекс МосБиржи
    "TRUR",  # вечный портфель
    "SBGB",  # гос. облигации
    "LQDT",  # ликвидность / денежный рынок
    "SBER",
    "LKOH",
    "GAZP",
    "NVTK",
    "YDEX",
    "PLZL",
    "TATN",
]

# Satellite: ликвидные, более волатильные (~20%)
DEFAULT_SATELLITE_UNIVERSE: list[str] = [
    "VTBR",
    "AFKS",
    "MTSS",
    "AFLT",
    "MAGN",
    "CHMF",
    "ALRS",
]
