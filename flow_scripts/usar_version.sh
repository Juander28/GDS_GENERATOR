#!/bin/bash
# Points the `gds/` links at whichever version of the blocks you want, and
# records which one is in place.
#
#   ./scripts/usar_version.sh v1     blocks from Layouts/
#   ./scripts/usar_version.sh v2     blocks from layouts_v2/
#
# The top flow reads the block layouts ONLY through these links
# (`build_collateral.py` opens them as `gds/<BLOCK>.gds`), so switching them is
# all it takes to build the top out of different cells. What is NOT optional is
# regenerating the collateral afterwards: the v2 blocks are a different size,
# and a stale LEF would describe a macro with the wrong dimensions -- the
# floorplan would close and the GDS would come out with overlapping macros.
#
# Hence `lef/.version`: the Makefile compares it against the requested version
# and refuses to go on if they disagree.

set -euo pipefail
AQUI=$(cd "$(dirname "$0")/.." && pwd)
V=${1:-v1}
case "$V" in
    v1) DIR=Layouts ;;
    v2) DIR=layouts_v2 ;;
    *)  echo "usage: $0 v1|v2" >&2; exit 2 ;;
esac

#  OPAM_LIN_flat is the linear amplifier, the one GRADIENT2 uses. It is on the
#  list even though the GRADIENT top does not instantiate it: a spare LEF
#  bothers nobody, and a missing one breaks the top that does use it.
#  DECODER_MAX, OPAM_SUMA and ESD_CDM only exist in v2 (the first two belong
#  to the GRADIENT_NAV3
#  top), so v1 does not link them and nothing is missed.
BLOQUES="COMP DECODER OPAM OPAM_LIN_flat WEIGHT_COMP"
#  io_secondary_5p0 is the organisers' cell, vendored (see
#  layouts_v2/io_secondary_5p0/README_ORIGEN.txt). It is not instantiated by
#  GRADIENT_NAV2 any more -- it goes one level up, next to the pads -- but
#  def_to_gds.py demands a resolvable gds/<stem>.gds for EVERY lef/*.lef,
#  used or not, so the link has to exist all the same.
[ "$V" = v2 ] && BLOQUES="$BLOQUES DECODER_MAX OPAM_SUMA ESD_CDM io_secondary_5p0"
#  BLOCKS PINNED TO v1, WHATEVER VERSION IS ASKED FOR. Empty, and here is the
#  story of why it once was not, because the trap is easy to fall into again.
#
#  On 2026-08-29 the v2 OPAM_LIN_flat came out LVS-clean and DRC-DIRTY: 44
#  violations, `PL.5a_MV` x6, `PL.5b_MV` x6, `CO.4` x26 and `M1.2a` x6, all at
#  two places, x = 22.4 and x = 30.1 of the P row. v2's extra abutment had put
#  two devices of DIFFERENT W into one shared block: the diffusion of the wider
#  one runs past the narrower one's, and the narrower one's gate end cap -- 0.58
#  um of poly beyond its own diffusion -- ends up as field poly 0.22 um from the
#  wider one's COMP edge, where `PL.5*_MV` asks 0.30. LVS said nothing: it is
#  geometry, not connectivity.
#
#  Pinning the block to v1 was tried first and DOES NOT WORK: `detailed_route`
#  aborts with `DRT-0073 No access point for x1_x1/INN`. The Metal3 port pad is
#  0.4 um tall against a 0.56 um track pitch, so whether a track crosses it
#  depends on where the macro lands, and the two versions put that pad at
#  different heights (20.69 in v1, 16.38 in v2).
#
#  The fix went where the problem was: `placement._can_join` now refuses to
#  share a block between two devices of unequal W. v2 came back 95.88 x 48.05
#  with 18 abutments instead of 24, 0 DRC violations and both LVS tools matching.
PIN_V1=""

for B in $BLOQUES; do
    D=$DIR
    case " $PIN_V1 " in *" $B "*) D=Layouts ;; esac
    DST=../../$D/$B/${B}_flat_gf180.gds
    REAL=$AQUI/../$D/$B/${B}_flat_gf180.gds
    if [ ! -s "$REAL" ]; then
        echo "  ERROR: $REAL does not exist" >&2; exit 1
    fi
    ln -sfn "$DST" "$AQUI/gds/$B.gds"
    aviso=""
    [ "$D" != "$DIR" ] && aviso="   (pinned to v1, see PIN_V1)"
    printf "  %-18s -> %s%s\n" "$B.gds" "$DST" "$aviso"
done
echo "$V" > "$AQUI/gds/.version"
