## 🔗 Wszystkie modele i repozytoria
Pełna lista projektów znajduje się na stronie:
https://jbackk-lang.github.io
---

# probabilistic‑timdr
Model łączący rachunek prawdopodobieństwa, warunki brzegowe i topologię TIMDR.

Repozytorium pokazuje:

- skąd biorą się progi probabilistyczne (np. 50% w paradoksie urodzin),
- dlaczego liczymy relacje (pary), a nie indywidua (osoby),
- jak próg prawdopodobieństwa staje się warunkiem kolapsu,
- jak to mapuje się na TIMDR (szum → stan krytyczny → obiekt),
- oraz jak tę samą logikę stosuje się w kosmologii (powstawanie galaktyk).

Struktura repo:

1. 01_probability_basics.md  
   Kombinacje, liczba par, paradoks urodzin, tabela prawdopodobieństw.
   *(poprawiono błędne wartości P dla N=13, 20, 22)*

2. 02_boundary_constant.md  
   Stała brzegowa 0.5 jako warunek kolapsu (urodziny → TIMDR → kosmologia).
   *(dodano zastrzeżenie: 0.5 nie jest uniwersalne — kontrprzykład z teorii perkolacji)*

3. 03_timdr_mapping.md  
   Mapowanie T–I–M–D–R na proces probabilistyczny.
   *(dodano rozdział 6: ten akronim różni się od TIMDR w innych repo — patrz TIMDR_POROWNANIE.md)*

4. 04_cosmic_application.md  
   Jak fluktuacje gęstości przekraczają próg i tworzą galaktyki.
   *(doprecyzowano: δ_crit≈1.686 to inna liczba niż 0.5, analogia strukturalna, nie tożsamość)*

5. TIMDR_POROWNANIE.md  
   Zestawienie pięciu różnych definicji "TIMDR" w repozytoriach autora
   (Synoptyk-v2.0, EasySound, Senscore, KHIPU, ten projekt) — żadna z nich
   nie liczy tej samej rzeczy. *(2026-08-26: dodano Synoptyk-v2.0 jako
   piąty wpis — to w istocie źródłowa definicja, od której wzięły się
   cztery sygnały anomalia/defekt/rezonans/skręt.)*

6. `probabilistic_timdr/` (kod, dodano 2026-08-26)  
   Do tego momentu repo było czystym markdown bez jednego wzoru
   obliczeniowego (punkt 1 w `TIMDR_POROWNANIE.md` mówił to wprost). Ten
   pakiet dodaje działający, przetestowany kod dla trzech twierdzeń z
   dokumentów — patrz sekcja niżej.

## Kod obliczeniowy (`probabilistic_timdr/`)

Cztery moduły, każdy odpowiadający konkretnemu twierdzeniu z dokumentów
01–04, plus 27 testów (`pytest`, wszystkie przechodzą):

| Moduł | Co robi | Weryfikuje |
|---|---|---|
| `birthday.py` | dokładna kombinatoryka: `C(N,2)`, `P(≥1 wspólnych urodzin)` bez przybliżeń | tabelę z `01_probability_basics.md` co do 0.01 punktu procentowego; `first_n_crossing_threshold(0.5) == 23` |
| `percolation.py` | symulacja Monte Carlo (union-find) perkolacji wiązaniowej na siatce kwadratowej L×L | próg ≈0.5 z `02_boundary_constant.md` — odtwarza sigmoidalne przejście wyśrodkowane blisko 0.5; pozostałe 5 wartości z tabeli są jawnie oznaczone `CITED` (cytowane z literatury, NIE symulowane tutaj) |
| `spherical_collapse.py` | **niezależne wyprowadzenie** δ_crit z parametrycznego (cykloidalnego) rozwiązania kolapsu top-hat (rozwinięcie Taylora + dopasowanie do wzrostu liniowego EdS), nie tylko zacytowana stała | zgodność wyprowadzenia z zamkniętym wzorem `(3/20)(12π)^(2/3)` i z wartością z `04_cosmic_application.md` (≈1.686) do 1e-9 |
| `threshold_schema.py` | działająca wersja schematu `R_total ≥ R* ⇒ OBIEKT` z `03_timdr_mapping.md` — ale z TRZEMA niezależnymi progami (0.5 z kombinatoryki, 0.5 z symulacji perkolacji, ≈1.686 z kolapsu sferycznego), nie jedną uniwersalną stałą | `compare_thresholds()` pokazuje wprost, że progi się różnią mimo wspólnego interfejsu |

Instalacja i testy:

```bash
pip install -r requirements.txt
pytest -v
```

To domyka lukę, którą sam `TIMDR_POROWNANIE.md` już wskazywał: teraz
`probabilistic-timdr` ma — obok trzech pozostałych repo TIMDR — realny,
sprawdzalny kod, a nie tylko etykiety pojęciowe. Nie zmienia to jednak
głównego wniosku z sekcji "Status poprawek" niżej: trzy zaimplementowane
progi (0.5 kombinatoryczne, 0.5 perkolacyjne, 1.686 kosmologiczne) to
nadal trzy osobne wyprowadzenia, nie jedna uniwersalna stała — kod to
teraz egzekwuje (`ThresholdSystem.threshold_source` różni się dla
każdego), zamiast tylko o tym wspominać w tekście.

## Status poprawek

Ten model łączy trzy rodzaje twierdzeń o różnej mocy dowodowej:
- **policzalne i sprawdzone** — kombinatoryka, paradoks urodzin (po poprawce tabeli),
- **realne i poprawnie zacytowane, ale osobne** — δ_crit≈1.686 z teorii sferycznego kolapsu,
- **analogia pojęciowa, nie dowód** — twierdzenie, że różne systemy progowe
  są "tym samym mechanizmem" (TIMDR). Wzorzec "próg krytyczny" jest realny
  i częsty, ale konkretna wartość progu i wzór, którym się go liczy, są
  różne w każdej dziedzinie — tak jak różne jest pięć definicji TIMDR
  w repozytoriach autora (patrz `TIMDR_POROWNANIE.md`).
