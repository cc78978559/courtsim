# Advanced cap mechanics v1

The cap ledger models Non-Bird, Early Bird, and Full Bird rights, the salary cap, first apron,
second apron, and expiring trade exceptions. Over-cap signings must use matching Bird rights and
remain inside the applicable governed limit.

Trade salary matching uses small, medium, and large outgoing-salary tiers. A legal salary-saving
trade can create an expiring exception; later transactions may consume it partially. Exceptions
cannot be aggregated with outgoing salary, expired exceptions are rejected, and all changes
return a new immutable ledger.

The complete cap ledger is stored in manager league schema 4. Advancing a real adapter season
automatically removes exceptions that have passed their governed expiry season.
