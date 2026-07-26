# Thirty-team NBA league v1

The league layer requires thirty ordered teams and generates an 82-date schedule with fifteen
games per date. Every team appears exactly once per date and plays exactly 82 games, producing
1,230 regular-season games.

Each conference play-in accepts seeds 7–10 and validates the 7/8, 9/10, and final derived
matchups. The resulting eight-team conference fields feed a fixed 16-team bracket. A complete
postseason ledger contains fifteen best-of-seven series and is rejected if any matchup, address,
winner, or advancement path does not derive from earlier results.

An optional ordered 15-team East/15-team West alignment is part of manager league schema 3, so a
thirty-team save restores the same conference membership exactly.
