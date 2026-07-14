# Testing

This document explains how Phoropter is tested, and — just as important — how we
learned that "all tests pass" was giving us false confidence. It's written to be
readable without a testing background; the jargon is defined as it appears.

## Why this document exists

Phoropter's whole value rests on a few claims being **exactly** true: that a
larger slice provably *contains* a smaller one, that swapping a small slice for
its parent never loses relevant text, that the same query always produces the
same result. If any of those is subtly wrong, the system quietly returns wrong
context and nobody notices.

We had a full, green test suite — hundreds of passing tests — and a real
correctness bug still shipped and had to be caught by hand. That prompted an
audit of the tests themselves, using a technique called **mutation testing**
(explained below). The audit found that several of our tests were *green for the
wrong reasons*: they would have kept passing even if the code were broken. This
document records what we found, in plain terms, and how we're fixing it.

## The one idea to take away

**A passing test does not mean the code is correct. It means the code is correct
for the specific cases the test tries, checked in the specific way the test
checks them.** Bugs live in the gap between "what the test checks" and "what the
code actually promises." Two traps create that gap:

### Trap 1 — checking a stand-in instead of the real thing

Suppose the promise is *"the slice we keep must contain the slice we threw away."*
Containment implies the kept slice is *larger*. So a lazy test checks the easy
consequence — "is it larger?" — instead of the real promise — "does it actually
contain the other one?"

Those are not the same. A slice can be larger than another and still be a
completely different piece of text. Our original bug was exactly this: the code
merged two passages that had nothing to do with each other, the kept one *was*
larger, and the test — which only checked "larger" — happily passed while
relevant text was silently dropped. We call the "larger" check a **proxy**: a
weaker stand-in for the real claim.

### Trap 2 — the test and the code agreeing because they share a blind spot

Two common versions of this:

- **Repeated text.** Many tests slice a document that is just the letter `x`
  repeated a thousand times. Every 64-character chunk of that is byte-for-byte
  identical, so every chunk has the *same* fingerprint. A test that checks "are
  these fingerprints equal?" or "are these in the right order?" is meaningless
  when they're all the same anyway — the assertion can't fail. The bug hides
  because the test material can't expose it.
- **The test copying the code's formula.** If the code computes something with a
  particular arithmetic expression, and the test computes its "expected answer"
  with the *same* expression, then a mistake in that expression appears in
  *both* — they agree, and the test passes. The test isn't an independent check;
  it's an echo.

## Mutation testing, explained

How do you find these gaps on purpose? You **break the code deliberately and see
if any test notices.**

A **mutant** is a copy of the program with one tiny change — an `and` flipped to
an `or`, a `<=` changed to `<`, a line deleted, a number nudged. Each mutant is a
small, plausible "what if the author had made this mistake?" You then run the
whole test suite against the mutant:

- If some test **fails**, the mutant is **killed** — the tests noticed the bug.
  Good.
- If **all tests still pass**, the mutant **survives** — this is a version of the
  program that is *wrong* but that your tests would happily ship. A surviving
  mutant is a concrete, undeniable hole in your tests.

It's the software equivalent of testing a smoke detector by actually lighting a
match instead of just noting that the green light is on. A green light tells you
nothing until something proves the alarm goes off.

When we ran mutation testing on Phoropter's core, **several mutants survived** —
including one that is literally the bug we already fixed once, re-introduced in a
nearby spot. Those survivors are the highest-priority items below, because
they're not hypothetical: they are wrong programs, proven to pass every test.

## The bug that started all this

Some background in plain terms:

- Phoropter chops each document into slices at several sizes and gives each slice
  a **marker** — a short fingerprint (a SHA-256 hash) of that slice's exact
  bytes. Identical text always produces the identical fingerprint.
- To decide "is slice A contained inside slice B?", the *correct* method is:
  first check the **positions** — B's character range must actually cover A's
  range — and *then* use the fingerprint as a tamper-check. Position is the
  decision; the fingerprint only confirms it.
- The bug: in one place the code skipped the position check and decided
  containment from the **fingerprint alone**. In a document with repeated or
  boilerplate text (extremely common — headers, legal footers, whitespace, code),
  two *unrelated* passages in different places have the *same* fingerprint. So
  the code concluded a passage "contained" another passage that was actually
  somewhere else entirely, merged them, and dropped the second one's content.

The test that should have caught it only checked that the surviving slice was
*larger* (Trap 1), using a single repeated-text document (Trap 2). Both traps at
once. It shipped green and was caught later by manual review.

## What we found (the mutants and gaps)

Each item below is written as: what the flaw is, the concrete failure it allows,
and the test we're adding to close it. "Confirmed live" means mutation testing
*proved* the gap by producing a wrong program that passed every test.

### Confirmed-live mutants (proven gaps)

- **The public "contains" check can be reduced to fingerprint-only and no test
  notices.** Flipping the `and` between the position check and the fingerprint
  check to an `or` — i.e. "contained if positions match *or* fingerprints
  match" — survives. That is the original bug, now sitting in a function other
  code calls. *Failure it allows:* two unrelated passages with matching
  boilerplate are declared one-inside-the-other. *New test:* feed it two slices
  that are disjoint in position but share a fingerprint (repeated text at
  different offsets) and require the answer to be **False**; also a slice that
  runs past the parent's end.

- **The "keep-the-leaf" merge step can decide containment by fingerprint alone,
  survives all 22 selection tests.** Deleting the fingerprint tamper-check on the
  merge, and separately loosening its boundary comparison (`<=` to `<`), both
  survive. *Failure it allows:* during budget trade-up, a parent absorbs and
  discards a passage it doesn't actually contain — the original bug's twin.
  *New tests:* place a distinct passage exactly at a parent's edge and require it
  to be absorbed correctly; place a stale passage (fingerprint doesn't match the
  parent's record) inside the parent's range and require it *not* to be absorbed.

- **Merging across two different documents is never tested.** The property test
  that's supposed to stress the merge logic only ever builds *one* document.
  *Failure it allows:* with two documents full of the same boilerplate, a passage
  from document A "absorbs" and drops a passage from document B. *New test:* two
  documents with identical text; require that nothing a slice replaces ever comes
  from a different document.

- **Skipping a size in the retrieval results makes a passage look like it has no
  parent.** The forest-building loop's "if this size is missing, keep looking
  upward" can be changed to "stop looking" and no test fails, because every test
  supplies a complete, unbroken ladder of sizes. *Failure it allows:* when
  retrieval returns, say, the 64- and 256-size matches but not the 128 in
  between, the code wrongly treats the small slice as a top-level result. *New
  test:* retrieve with a deliberate gap in the size ladder and require the small
  slice's parent to be found above the gap.

- **A budget round can quit early and starve a passage that could still fit.**
  When one candidate is too expensive to grow this round, the code should skip it
  and keep considering the others; changing "skip" to "stop" survives, because
  the relevant test only has one candidate. *Failure it allows:* a cheap,
  lower-priority passage that could have been upgraded within budget is silently
  left un-upgraded because a pricier one was considered first. *New test:* two
  candidates in one round where the first is unaffordable and the second is
  affordable; require the second to still be upgraded.

- **The result-merging step breaks on the normal case of uneven result counts.**
  When different sizes return different numbers of matches (the usual situation),
  the guard that stops reading past the end of the shorter list can be loosened
  and it survives — because every test happens to give each size the *same*
  number of matches. *Failure it allows:* a real query where, say, the 64-size
  returns 10 matches and the 1024-size returns 2 crashes or produces garbage.
  *New test:* feed the merger uneven-length lists and require correct output.

- **A storage adapter could corrupt slice metadata and a conformance test still
  passes.** The test meant to verify "search results carry complete metadata"
  contains an escape hatch (`... or size == 64`) that is always true for the size
  it probes, so the real check never runs. *Failure it allows:* a store that
  drops or mangles the descendant fingerprints on retrieval passes the suite.
  *New test:* remove the escape hatch and probe a size where the check actually
  has to hold.

### Gaps with no independent check

These aren't "wrong program survives" findings; they're places where a claim is
simply never verified independently:

- **Fingerprints are never re-derived from scratch.** Every test trusts the
  slicer's own fingerprints against each other. If the slicer hashed the wrong
  byte range, or silently "normalized" Unicode (changed the text before
  hashing), or used the wrong text encoding, it would stay self-consistent and
  pass. *New test:* independently recompute `SHA-256(slice text as UTF-8)` and
  require it to equal the slicer's fingerprint, for every slice — including text
  with combining characters, byte-order marks, and different newline styles.

- **The list of "what's inside this slice" is checked against a copy of the
  slicer's own formula.** If that formula is subtly wrong, the "expected answer"
  is wrong the same way and they agree (Trap 2). *New test:* compute the expected
  contents a *different* way — by directly checking every other slice's position
  — and compare.

- **Nothing verifies that no relevant text is dropped.** The system promises that
  every retrieved passage ends up either in the final answer, or explicitly
  recorded as "didn't fit," or absorbed into a slice that genuinely contains it.
  That accounting is never checked, so a bookkeeping slip that makes a passage
  vanish from *all three* places would go unnoticed. *New test (Tier 2):* an
  independent audit that every retrieved passage lands in exactly one of those
  buckets.

## How we're hardening the tests

The fixes are grouped into three tiers by cost and leverage.

**Tier 1 — turn the proxies into the real checks (in progress).** Small, targeted
tests that assert the *actual* promise instead of a stand-in, plus one test for
each confirmed-live mutant that makes it fail. A recurring theme: replace
repeated-text (`"x"*n`) material with text that is *distinct at every position*,
so that a wrong offset or a wrong merge changes a fingerprint *value* — something
a test can see — rather than just a count that looks fine. Tier 1 closes every
confirmed-live mutant above.

**Tier 2 — independent second opinions.** Where a test currently checks the code
against itself, add a genuinely independent oracle: a slow-but-obviously-correct
reference implementation of the selection logic to cross-check *which* slices get
chosen; metamorphic checks (e.g. giving more budget must never return *less*
text); a stateful model that drives long random sequences of operations and
checks the invariants after each step; and an end-to-end check that the server's
JSON response mirrors the engine's decision exactly, in order.

**Tier 3 — keep the alarm wired up.** Run mutation testing continuously (in CI)
on the correctness-critical code so that any *future* change that reintroduces a
proxy-shaped gap is caught automatically, and add a coverage floor so
untested code paths can't quietly grow.

## Principles going forward

1. **Assert the whole promise, not a consequence of it.** "Contains," not
   "larger." "Same bytes," not "same length."
2. **Make test material able to expose the bug.** Distinct text beats repeated
   text; a bug should change a *value*, not just a count.
3. **Check the code against something independent** — a hand-computed answer, a
   naive reference implementation, a different formula — not against itself.
4. **Trust the alarm only after you've heard it ring.** Mutation testing is how
   we hear it.

## Running the tests

```bash
pytest -m gate --exitfirst   # the correctness gates (slicing + cross-language parity) — run first
pytest                       # the full unit suite (integration excluded by default)
pytest -m integration        # integration tier (needs Docker: a real Qdrant container)
```

Mutation testing (the ongoing signal, Tier 3) runs the suite against thousands of
deliberately-broken copies of the core modules; it is slow and runs in CI rather
than on every local change. See `CONTRIBUTING.md` for the tooling once it's
wired up.
