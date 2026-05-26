"""Стартовые вселенные тикеров MOEX (только акции TQBR, без БПИФ)."""

# Core: ликвидные голубые фишки (~80%)
DEFAULT_CORE_UNIVERSE: list[str] = [
    "SBER",
    "LKOH",
    "GAZP",
    "NVTK",
    "YDEX",
    "PLZL",
    "TATN",
    "GMKN",
    "ROSN",
    "MGNT",
]

# Satellite: более волатильные (~20%)
DEFAULT_SATELLITE_UNIVERSE: list[str] = [
    "VTBR",
    "AFKS",
    "MTSS",
    "AFLT",
    "MAGN",
    "CHMF",
    "ALRS",
]
