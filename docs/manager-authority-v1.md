# CourtSim manager authority v1

`manager-authority-v1` gives every white-box manager stage one explicit authority mode and one
canonical execution receipt.

The canonical stages are draft, free agency, trade, rotation, and tactics. Draft, free agency,
and trade default to `shadow`; their recommendations may execute only inside the isolated
Shadow experiment arm. Rotation and tactics default to `active` because they are canonical
game-runtime policies used by both experiment arms.

`assist` recommendations require an explicit human approval flag. `active` recommendations
are authorized directly. A receipt that reports executed recommendations without authority is
invalid and is rejected.

Every receipt records whether the policy was evaluated, recommendation and execution counts,
the authority decision, human approval, isolated-Shadow status, and a stable reason. The
manager league audit emits all five receipts in canonical stage order.

This contract does not automatically promote a Shadow policy. Evidence promotion and production
activation remain separate governed actions.
