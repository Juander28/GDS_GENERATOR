# Why the KLayout LVS does not match on the top, and netgen does

Written 2026-08-31, against `work_lvs/B26_A_klayout.spice`.

> **THE EXTRACTION USED HERE WAS STALE, AND IT MATTERS.** The numbers below come
> from `out/lvs_klayout_B26_A/B26_A.cir`, which is **the run of 29 August** —
> committed in `4e1a145`, two days and two GDS generations before the file it
> was compared against. The KLayout deck's own re-run on today's GDS had not
> finished when this was written; it takes hours where an earlier one took
> thirteen seconds.
>
> **What is still true** regardless: the tool findings, §1 (the rails cannot
> anchor because of the `|` labels), §2 (the depth cliff) and §4 (the four
> dangling ports in the reference, which is today's file).
>
> **What is NOT today's layout**: everything in §5 about the clamps' wiring. In
> that old extraction the eleven clamps had their well off `VDD` and, on five of
> them, the series resistor shorted end to end. Both were **fixed on 30 August**.
> magic's extraction of the current GDS — `work_lvs/B26_A_extracted.spice`,
> 31 August — shows all eleven as
>
>     X22 S4N a_23448_50576# VDD ppolyf_u r_width=16u r_length=4u
>
> pad on one end, a node of its own on the other, **well on `VDD`**, and all 44
> `pd2ns` diodes to `VDD`. Nothing is shorted and nothing floats.
>
> **The lesson, and it is the same one the DRC archive already enforces**: a run
> directory older than the GDS is not a verdict about that GDS.
> `archivar_integracion.py` rejects that case with `STALE — the run predates this
> GDS`. There is no such guard on the LVS run directories, and there should be.

**Read this before anyone concludes the chip is wrong.** It is not.

---

## The one fact that settles it

Both sides carry **the same devices, class by class**, after the same
`combine_devices()`:

| class | layout | schematic |
|---|---|---|
| `NFET_06V0` | 688 | 688 |
| `PFET_06V0` | 643 | 643 |
| `CAP_MIM_2F0FF` | 48 | 48 |
| `PPOLYF_U_1K` | 12 | 12 |
| `PPOLYF_U` | 11 | 11 |
| `DIODE_ND2PS_06V0` | 11 | 11 |
| `DIODE_PD2NW_06V0` | 11 | 11 |
| `PFET_05V0` / `NFET_05V0` | 9 / 9 | 9 / 9 |
| **total** | **1442** | **1442** |

Nets 943 against 946, pins 19 against 23. And **netgen -- a different engine, a
different extraction, and the one that also compares W and L -- says `Circuits
match uniquely`** on the same pair.

So what follows is about a comparer that cannot traverse the graph, not about a
layout that disagrees with its schematic.

---

## Four causes, in the order they were found

### 1. The rails could never anchor: they are not called `VDD` and `VSS`

KLayout joins **every label that lands on one net** with `|`. The fifty tie-offs
hold each control pin of the six digital pads at a rail, and each of those pins
carries its own pad label, so the extraction's two supplies come out as

    VDD|XN_OE|XP_OE|YN_OE|YP_OE|ZN_OE|ZP_OE
    VSS|XN_CS|XN_IE|XN_PD|XN_PDRV0|...|ZP_SL

`anclas()` matched whole names, so **`VDD` and `VSS` never anchored** -- the two
anchors the whole circuit hangs from. Fixed: the name is split on `|` and every
label counts as an alias.

### 2. The search limits were tuned on a different circuit

`max_depth=30, max_branch_complexity=10000` closes `GRADIENT_NAV2`. On `B26_A`
-- the same block plus eleven clamps and fifty tie-offs -- they **collapse**:

    depth= 8  branch=  500     829 nets matched,  104 unmatched
    depth=12  branch=  500     842 nets matched,   80 unmatched
    depth=16  branch=  500     810 nets matched,   83 unmatched
    depth=18  branch=  500      32 nets matched, 1722 unmatched
    depth=30  branch=10000      22 nets matched, 1749 unmatched

There is a cliff between 16 and 18, and past it the search does not degrade a
little: it falls over entirely. Fixed: `ESCALERA` tries a ladder of settings,
one comparison per subprocess, and keeps the first match or the best result.

### 3. The anchors help in one place and hurt in another

At 8/500, on the same pair:

    anchors `todas`   (19)    829 matched, 100 unmatched
    anchors `rieles`  ( 2)    872 matched,  26 unmatched
    anchors `ninguna` ( 0)    870 matched,  29 unmatched

With all of them the eleven pad anchors pin the clamps correctly and the three
X/Y/Z output stages come loose; with none the stages match and the comparer
confuses each pad with its own internal node -- `X` against `X_I`, the two ends
of the same series resistor. **The rails alone give the best of both**, so the
ladder carries the anchor mode as a second axis.

### 4. The reference declares four ports that connect to nothing

`XSCHEM/B26_A.sch` leaves `XP_IN`, `XN_IN`, `YP_IN`, `YN_IN` as ports of the top
that appear **nowhere else in the netlist** -- no device touches them. The layout
cannot have a counterpart, so those four are unmatched for ever. (`ZP_IN` and
`ZN_IN` exist in the schematic and do not survive into the port list at all,
which is the same defect showing its other face.)

Removing them by hand takes the residual from 33 unmatched nets to 29 -- exactly
the four. **This one is in the schematic and is still open.**

---

## Where it stands

Best measured: **872 of ~900 nets matched, 26 nets and 41 devices left**, and the
residual is the eleven ESD clamps -- each pad swapped with its own `_I` node
across the series resistor.

It is not a match, and it should not be recorded as one. What it is:

* not a circuit difference -- see the device table and netgen;
* a comparer that will not close on twelve near-identical analogue chains plus
  eleven identical clamps;
* plus one real defect, the four dangling ports, which is worth fixing in the
  schematic whatever else happens.

**Why it matters for the submission.** The chipathon's external LVS reads
`lvs_config.json` and runs **the KLayout deck**, not netgen. On this design the
deck calls `compare` with its own defaults and no anchors, so it will report
`Netlists don't match`. That is worth raising with the organisers with these
numbers attached.

**And it is slow.** On the unfilled GDS the extraction has taken hours in this
run where an earlier one took thirteen seconds; on the density-filled GDS it did
not finish at all -- fifty-six minutes without a single progress line, against
eleven seconds on the same circuit unfilled. The floating fill multiplies the
nets to extract. Since `LAYOUT_FILE` points at the filled GDS, an external LVS
reading it may simply time out.


---

## 5. Where the three extra nets went (on the stale extraction)

The user's question: the schematic has 946 nets and the layout 943. Where do the
three go? Counted without `combine_devices`, so that nothing is merged away:

| | layout | schematic |
|---|---|---|
| nets, total | 943 | 946 |
| of those, with **no device terminal at all** | 0 | **4** |
| so, connected | **943** | 942 |

So the three are really **four minus one**:

* **four** are the dangling ports of §4 — `XP_IN`, `XN_IN`, `YP_IN`, `YN_IN`,
  which exist in the schematic and touch nothing;
* and then the layout has **one connected net more** than the schematic.

That one came from the clamps. The two largest nets are the rails, and only one
of them agreed:

    VSS   1696 terminals in the layout   1696 in the schematic     equal
    VDD   1618 terminals in the layout   1673 in the schematic    -55

**55 = 44 + 11**: the 44 cathodes of the `pd2nw` diodes and the 11 well
terminals of the series resistors — every n-well connection in the eleven
clamps. In that extraction they were not on `VDD`. Per device:

    layout (29 Aug)                     schematic
    A=S4P  B=S4P  W=$5                  A=S4P_I  B=S4P  W=VDD
    A=S4N  B=S4N  W=$9                  A=S4N_I  B=S4N  W=VDD
    A=Z    B=Z    W=$13                 A=Z_I    B=Z    W=VDD
    ...
    A=$14435  B=S1N  W=S1N              A=S1N_I  B=S1N  W=VDD

Two faults in one picture: on the five west clamps **the resistor has both ends
on the same net** — shorted, the pad and the core are one node — and on all
eleven **the well is somewhere other than `VDD`**, floating on the west five and
sitting on the pad net on the north six.

**Both were found and fixed on 30 August**, which is why this extraction no
longer describes the design: see the note at the top, and
`work_lvs/B26_A_extracted.spice` for what magic reads off today's GDS.

What is worth keeping from it is the arithmetic, because it will work again on
the fresh extraction: **the rails' terminal counts are the fastest way to find a
supply that is not connected**. 55 missing terminals on `VDD` named the eleven
clamps without opening a layout viewer.
