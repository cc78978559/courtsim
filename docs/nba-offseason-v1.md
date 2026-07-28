# CourtSim NBA offseason v1

`nba-offseason-v1` is the complete 30-team offseason transaction. It advances player
development, decline, injury burden and retirement; removes retirees; expires contracts;
builds independent scouting boards; executes the white-box manager draft; runs white-box free
agency; and replenishes the future-pick horizon.

Planning uses an exact preview of career and contract transitions, so the draft and market
plans are evaluated against the state they will actually execute on. The canonical offseason
engine then replays the same inputs from the initial state. The wrapper rejects any difference
between manager plans and executed ledgers.

The result advances the management year once and returns the complete career/management
offseason ledger plus a future draft-asset ledger containing no expired picks. The default
horizon seeds one first-round asset per team for the next three drafts.
