# The second reading

Part of ela's watch skill (`SKILL.md` beside this file), read by the session the runner starts after the decider (`ela watch review prompt`).

## The second reading

A second session, after the decider, reads again what the decider could not settle: a ruling ask whose option A is
only the watch's own writes (assign, a non-terminal status, a raised priority, a due date, a link), and a low act.
Those wait as review-pending, off the owner's page, until this reading. Asks that are never ela's (a close, release
scope, a person, Slack, a lowered priority, Fixed In, labels) never come here; they went straight to him.

`ela watch review prompt` lists the cases. You have the decider's tools: read first-hand what the decider did not (the
ticket's comments, `ela release`, `ela mail`, `ela slack`, `ela configserver`, `ela team`, `ela asks fact get`). A case
is settled only by a first-hand source you read yourself, named as `{"kind", "ref"}`, kind one of: reporter-comment,
qa-report, build-record, config-value, roster, owner-fact. Agreeing with the decider is not a source; a precedent
strengthens a leaning but does not settle a case. Write `<reports>/ela/watch/<date>-review.json` (the prompt names it):

```json
{"cases": [
  {"topic": "watch:MH-1", "settles": true, "letter": "A",
   "source": {"kind": "build-record", "ref": "mh-web build 2.2.170 carries the merge"}, "why": "one line"},
  {"topic": "watch:MH-6", "settles": false, "why": "what you read, and why it does not settle it"}
]}
```

Then `ela watch review settle --from <that file>` (a dry run) checks it. A settled ruling ask is closed with its letter
and its writes go out at the next pass; a settled low act stays with the owner, your source shown beside it, until his
amendment of the low-act rule is recorded. A case you leave unsettled reaches him with your `why`, so he sees what was
tried. A case you leave out of the file stays pending; if the reading fails or times out, the runner releases every
pending case to him marked "not read twice".
