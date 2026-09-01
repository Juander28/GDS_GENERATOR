# How to run the sign-off DRC so that it actually runs

Written 2026-08-31, after finding out that one rule in this deck had **never
been checked** on the integrated die and that nothing in the flow could tell.

---

## The short version

```bash
cd /foss/designs/a_zonetic2026/openroad

# the fast screen -- 63 tables in parallel. `mslot` CRASHES here.
make drc T=B26_A TOP_OUT=out_integration ARGS=B26_A_FILLED

# THE VERDICT -- one `main` table, deep mode, one thread. `mslot` survives here.
DRC_MODE=deep DRC_THR=1 DRC_MP=1 \
    make drc T=B26_A TOP_OUT=out_integration ARGS=B26_A_FILLED
```

Only the second one is allowed to be called a pass.

---

## Why there are two modes

The GF180MCU KLayout deck can be driven two ways, and the flow uses the fast one
by default: split the rules into 63 tables, run them in parallel, collect the
`.lyrdb` files. On the 1110 x 1110 um die that is the only way it fits in memory
at all.

In that mode the PDK's own `mslot` table dies:

    undefined method 'sized' for nil:NilClass
    -- rule_decks/mslot.drc:470

That is a **bug in the deck**, not in the design: the rule builds an empty layer
and then sizes it. It happens on every design, every time.

Now the part that matters. **A table that dies produces no usable `.lyrdb`.** A
check that counts result files and finds no violations therefore reads a crashed
table as a clean one. That is how every "63 tables, 0 violations" in this
project's history came to be true about what it said and silent about `MSLOT.1`.

> **Corrected 2026-09-01, measured.** The original wording here said a crashed
> table writes *no* `.lyrdb` at all. On KLayout 0.30.8 it does write one — and
> that is worse, because a file that exists satisfies a file count. What it
> writes is an **empty shell**: 464 bytes, the cell name, and **zero
> `<category>` elements**, i.e. not one rule declared.
>
>     split run, mslot crashed   B26_A_filled_mslot.lyrdb   0 categories
>     deep run, mslot ran        B26_A_filled_main.lyrdb    MSLOT.0 … MSLOT.9
>
> So **the count that means anything is categories, not files.** Note that a
> zero-category `.lyrdb` is *not* proof of a crash on its own — in split mode
> 25 of the 63 tables legitimately declare none, and the same 25 did so in the
> older `GRADIENT_NAV2` run. What identifies the crash is the pairing: a
> zero-category file **and** an `| ERROR |` line naming that table in the log.

Run the deck as a **single `main` table in `deep` mode**, single-threaded, and
`mslot` does not crash. It is far slower and it needs the memory, but it is the
only run whose "clean" means clean.

| | split tables | `main`, deep, 1 thread |
|---|---|---|
| invocation | default | `DRC_MODE=deep DRC_THR=1 DRC_MP=1` |
| `mslot` | crashes, writes an empty shell | **runs** |
| speed | fast, parallel | hours on the full die |
| what it is for | the screen while iterating | **the verdict** |

`DRC_MODE`, `DRC_THR` and `DRC_MP` are read straight from the environment in
`drc_klayout.py`; there is no Makefile variable to remember.

---

## The two guards that were added because of this

* **`completo()` no longer trusts "only `mslot` died".** It used to accept a run
  where the single failed table was `mslot`. A run that was *killed at table 48
  of 63* read as clean, because the `mslot` message arrived before the kill did.
  It now also demands the table count, and only forgives `mslot` when everything
  else was written.
* **`mslot1_local()`** is our own implementation of `MSLOT.1` — maximum metal
  width without slotting, 30 um — so a crashed table still produces an answer.
  It subtracts vias sized by 0.2 um first, because a via array inside a plate
  does not make the plate narrower.

  It shipped with a unit bug worth knowing about: it treated database units as
  nanometres and so measured **15 um where the rule says 30**. The fix is to
  take the scale from `ly.dbu` and never assume it.

---

## exit 137

`137 = 128 + 9 = SIGKILL`. The kernel's OOM killer, not a tool failure.

* **Docker on native Linux has no memory or CPU cap of its own.** The container's
  cgroup limit reads `max` unless `--memory`/`--cpus` were passed. On a 64 GB
  Linux box the container can use all 64 GB.
* **On WSL2 the cap is the VM's**, set in `%UserProfile%\.wslconfig`, and it
  defaults to a fraction of the host's RAM. That is the limit that bites here.

So a DRC that dies at 137 is a machine problem. Give it more memory, or run
fewer threads — `DRC_THR=1 DRC_MP=1` exists for exactly that.

---

## What the deck cannot see, and what covers it instead

| blind spot | what covers it |
|---|---|
| density minimums | `make drc-density` — a **separate pass**; the deck does not run them unless asked |
| poly **fill** rules (`DPF.*`) | `make drc-magic`. With 0.4 um squares magic once reported 134,488 violations on a file KLayout called clean; hence the 5.6 um poly squares |
| **electromigration** | `scripts/check_current_density.py`. Not a design rule at all — DRC will never mention it |
| **two `PR_bndry` shapes** | `def_to_gds.py::una_sola_frontera()`. Legal geometry; rejected by the organisers' flow |
| whether the pins **conduct** | `check_connectivity.py`, `check_integration.py` |

And the question to ask before believing any clean: *would this tool notice if
the chip were wrong?* `make probar` and `make probar-drc` answer it by breaking
a cell on purpose and checking that the check fails.

---

## The open item as of 2026-08-31

The `main`/deep run on `B26_A_filled.gds` returns:

    B26_A_FILLED 11 violations: MSLOT.1 x11
    Violated rules are : {'MSLOT.1'}

Everything else in the deck is clean. The eleven are the **pin escape channels**
drawn by `integrate_top.tcl`, not the fill and not the ESD — `mslot1_local`
finds them identically on the filled and the unfilled GDS. See
`HANDOFF.md` §5, *THE ONE THING TO DO NEXT*.
