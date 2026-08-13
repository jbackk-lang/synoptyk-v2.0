# synoptyk/__init__.py
"""
Pakiet synoptyk_v2: porównanie modeli (ECMWF/ICON) z danymi rzeczywistymi
oraz wyliczanie trendu 14-dniowego.

Uwaga: ten pakiet (katalog synoptyk/) jest czymś innym niż plik synoptyk.py
w katalogu głównym repo. Ten __init__.py jest wymagany, żeby Python
jednoznacznie traktował synoptyk/ jako pakiet nadrzędny nad synoptyk.py
przy imporcie `import synoptyk.compare` / `import synoptyk.trend`.
"""

__all__ = ["compare", "trend"]
