# CourtSim NBA franchise v2

`nba-franchise-v2` carries every manager's opponent memory as part of the composable
30-team franchise state. The first completed season creates 29 event-ledger opponent
models per manager. Later seasons turn those memories into up to 870 directed matchup
teams with white-box rotation, offense, defense, and tempo adjustments.

The canonical 30-team executor resolves the appropriate directed team for every
regular-season, play-in, and playoff game while requiring the matchup variant to
preserve the base team's identity and complete roster. The execution result publishes
the number of matchup variants used, so application is auditable rather than inferred.

At season end, observations from the 1,230-game regular-season possession ledger are
games-weighted into persistent memory. Manager replacement resets that team's memory.
Postseason tactics use the current memory, but postseason events are not yet added to
the learning sample. Franchise disk checkpoints remain deferred.
