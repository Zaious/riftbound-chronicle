# Contributing

There are two ways to help, and they ask different things of you.

## Reporting a rules error, a wrong locator, or a bug — nothing to sign

Open an issue. Say which card, which clause, or which procedure; quote the
official Core Rules paragraph you believe applies; if you can, give a state and
an expected result. That is a complete contribution. You will be credited in
the commit that fixes it (`Reported-by:`), and you do not sign anything.

The fastest way to be sure a report lands is to phrase it as a fixture: "with
this state and this program, the engine returns X; the rules say Y because of
paragraph Z." Every fix in this repo ships as a gate that would have caught
it, so a report shaped like a gate is already most of the work.

## Submitting code, data, or documentation — sign the CLA, pass the gates

1. **Sign the [Contributor License Agreement](CLA.md)** once. The CLA
   Assistant asks on your first pull request; comment the sentence it shows
   and it is recorded. You keep your copyright; you grant the Owner the right
   to sublicense, which is what lets the public engine and the proprietary
   service layer share your fix. A pull request from an unsigned author stays
   red.
2. **Every gate passes, in-repo and off-cwd.** The workflow in
   `.github/workflows/ci.yml` is the definition; run it locally with the
   commands in the README's Validation section. A change that needs a gate
   relaxed explains why in the pull request, and the relaxation is its own
   commit.
3. **A change to behaviour ships with a gate that would have failed before
   it.** "It works" is not a receipt; the failing-then-passing gate is.
4. **Rules claims cite the official locator**, and the locator must resolve in
   the rules index (`skill/scripts/rules_index.py`). A claim that cannot be
   located is not merged.
5. **Card program packs beyond the public seed are not accepted here.** The
   public repo carries the engine, the grammar contract and the Wave A seed
   corpus; compiled card corpora beyond that live in the private overlay. A
   pull request that adds a pack under `skill/data/card_program_packs/` will be
   closed with a pointer to this paragraph.

## What "done" means

A pull request is done when the gates are green on both CI legs, the commit
message says what changed and which rule it implements, and the reviewer can
reproduce the claim from the receipts in the description without reading the
diff. That is the standard the maintainer holds their own work to; it is the
same for yours.

## Licence

Code in this repository is licensed under the GNU Affero General Public
License v3.0 (see `LICENSE`). Versions released before the licence change
remain available under the MIT licence they were published with. Riot Games'
material is not licensed by this project at all; see `skill/data/README.md`.
