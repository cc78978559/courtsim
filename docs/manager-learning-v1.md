# Opponent-aware manager learning v1

Manager learning stores immutable opponent memories across completed seasons. Observations are
weighted by games played and track offense, defense, pace, three-point rate, and rim rate.
Seasons must advance monotonically, preventing future information from entering prior decisions.

An opponent memory compiles into bounded rotation emphasis for offense, defense, perimeter
coverage, interior coverage, and pace. The existing white-box rotation selector records these
effects as `opponent-model` contributions, so matchup-driven lineup changes remain explainable.

Manager league schema 3 persists one learning state per team. At the end of each simulated
season, the adapter derives games-weighted opponent offense, defense, and pace observations from
the canonical game ledger and advances every manager memory monotonically.

Before every regular-season game and playoff series game, the adapter resolves a separate
rotation for the scheduled opponent. The season engine verifies that this resolver changes only
lineups and substitution policy—not team identity or roster ownership. Unseen opponents reuse
the historical base rotation exactly.
