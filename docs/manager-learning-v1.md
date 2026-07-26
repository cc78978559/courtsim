# Opponent-aware manager learning v1

Manager learning stores immutable opponent memories across completed seasons. Observations are
weighted by games played and track offense, defense, pace, three-point rate, and rim rate.
Seasons must advance monotonically, preventing future information from entering prior decisions.

An opponent memory compiles into bounded rotation emphasis for offense, defense, perimeter
coverage, interior coverage, and pace. The existing white-box rotation selector records these
effects as `opponent-model` contributions, so matchup-driven lineup changes remain explainable.
