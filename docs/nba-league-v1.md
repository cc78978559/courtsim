# Thirty-team NBA league v1

The league layer requires thirty ordered teams and generates 1,230 regular-season games, with
exactly 82 games and a 41/41 home-away split for every team. Each conference contains three
ordered five-team divisions. Teams play division opponents four times, six other conference
opponents four times, four other conference opponents three times, and every opposite-conference
opponent twice. The deterministic scheduler prevents a team from appearing twice on one date.

Each conference play-in accepts seeds 7–10 and validates the 7/8, 9/10, and final derived
matchups. The resulting eight-team conference fields feed a fixed 16-team bracket. A complete
postseason ledger contains fifteen best-of-seven series and is rejected if any matchup, address,
winner, or advancement path does not derive from earlier results.

An optional ordered conference/division alignment is part of manager league schema 4, so a
thirty-team save restores the same membership exactly. Schema 1-3 saves remain readable, and a
legacy conference-only alignment deterministically derives three five-team divisions.
