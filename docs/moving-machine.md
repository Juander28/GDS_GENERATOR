# Moving this work to another machine

Written 2026-09-01, from the machine the chip was built on: 7.5 GB of RAM, which
is enough for everything except two checks. If the point of the move is more
memory, jump to [What more memory buys](#what-more-memory-buys) — it is a short
list, and shorter than it looks.

**Run `python3 openroad/scripts/check_environment.py` first on the new machine.**
It checks every one of the things below and says which are missing. Everything
here exists because the flow reaches outside its own directory: a PDK, a
virtualenv with a pinned gdsfactory, five binaries and a sibling tree that is
not in the design repository. All by absolute path.

---

## 1. The container: this is the environment, and it is not yours

Everything here runs inside **IIC-OSIC-TOOLS**, the image the chipathon
standardises on. The tools, the PDK and their versions come with it; you do not
install xschem, magic, netgen, klayout, OpenROAD or GF180 by hand, and you should
not want to.

    image     hpretl/iic-osic-tools:chipathon26
    version   IIC_OSIC_TOOLS_VERSION=2026.04   (echo it inside, to check)
    size      about 20 GB once unpacked

### Install Docker

The organisers' own instructions are in their repository, with screenshots:

    sscs-ose/sscs-chipathon-2026
      docs/install_instructions/Linux/install_docker_desktop.md
      docs/install_instructions/Windows/install_docker_desktop.md

The short version for Ubuntu, and their words on the choice: *Docker Desktop is
the easy way… if you are familiar with Docker, we recommend the classic Docker CE
without a GUI, since it has better performance.* **On a big Linux box, take Docker
CE.** It is the one that gives the container the whole machine (§4).

```bash
# 1. KVM, only needed by Docker Desktop
sudo apt install cpu-checker && kvm-ok          # "KVM acceleration can be used"
sudo usermod -aG kvm $USER

# 2. Docker's repository
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
     -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

# 3a. Docker CE, headless, the fast one
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
     docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER      # log out and back in for this to take

# 3b. or Docker Desktop: download the .deb from docker.com and install it,
#     then launch it once from the menu and accept the agreement.

# 4. only for the X11/Wayland mode under Docker Desktop
sudo apt install -y socat
```

### Start the container

Do not write a `docker run` by hand. The organisers ship start scripts that get
the mounts, the ports, the user id and the image tag right:

    sscs-ose/sscs-chipathon-2026/resources/IIC-OSIC-TOOLS/
      start_chipathon_x.sh        X11/Wayland — fastest, no desktop
      start_chipathon_vnc.sh      full desktop in the browser
      start_chipathon_jupyter.sh  Jupyter only

```bash
git clone https://github.com/sscs-ose/sscs-chipathon-2026.git
cd sscs-chipathon-2026/resources/IIC-OSIC-TOOLS
./start_chipathon_vnc.sh
```

* VNC: <http://localhost:80>, password **abc123** (port 5901 for a native client)
* Jupyter: <http://localhost:8888>
* The scripts are pinned to the tag `chipathon26` and work on x86_64 and arm64.

To update the container: stop it, delete it, pull the image again, run the start
script again.

### The one thing that will lose your work

The scripts mount **one** directory:

    host   $HOME/eda/designs        (override with $DESIGNS)
    inside /foss/designs

**That is the only path that survives deleting or updating the container.**
Everything else in the container is thrown away. And the virtualenv this flow
depends on lives at `/headless/.venvs/zotnetic`, which is **not** in there —
see §3.

---

## 2. What to copy

Everything the design needs is under the persistent mount, so the move is one
directory:

    $HOME/eda/designs/          ->  /foss/designs/
      a_zonetic2026/       353 MB   the design
      zotnetic_layout/     4.2 MB   THE GENERATOR — a sibling tree, and NOT part
                                    of the design repository. Three scripts add
                                    it to sys.path by absolute path.

Do not copy `/foss/pdks` (2.4 GB) or the tools: they come with the image.

`rsync -a` rather than a zip, so the symlinks in `a_zonetic2026/spice_blocks/`
survive. `check_environment.py` verifies they resolve.

**This already went wrong once, on the move of 2026-09-01.** The nine links in
`spice_blocks/` arrived as **regular files of zero bytes**. In the working tree
their targets are absolute (`/foss/designs/a_zonetic2026/XSCHEM/...`); that path
does not exist on a host that has not started the container yet, so a copy that
dereferences links wrote nothing at all.

And the check named in `HANDOFF.md` §9 **cannot see this case**: `find -xtype l`
reports zero broken links, because there are no links left to be broken. The
check that catches it is a size check:

    find spice_blocks -type f -empty        # must be empty
    find spice_blocks -type l -lname '/*'   # must be empty

They were restored as **relative** links (`../XSCHEM/<sub>/simulation/<cell>.sch/<cell>.spice`),
which is the form the repository stores and the only one that survives the next
copy. `build_block.py` resolves the link, and `spice_blocks/` is the source of
truth for every netlist the generator reads — so nine empty files would have
been nine silently empty builds.

If you would rather clone than copy:

```bash
git clone git@github.com:AnBuiUCI/sscs-2026-zotnetic.git
mv sscs-2026-zotnetic/FINAL /foss/designs/a_zonetic2026
git clone git@github.com:Juander28/GDS_GENERATOR.git
cp -a GDS_GENERATOR/zotnetic_layout /foss/designs/
```

Two things a clone does not carry, both by design: the `*.md` documentation
(gitignored in the design repository — it lives here, in `GDS_GENERATOR/docs/`)
and the virtualenv.

---

## 3. Rebuild the virtualenv. It is not persistent.

```bash
python3 -m venv /headless/.venvs/zotnetic
env -u PYTHONPATH /headless/.venvs/zotnetic/bin/pip install \
    -r /foss/designs/zotnetic_layout/requirements-frozen.txt
```

`requirements-frozen.txt` is all 105 packages as they actually ran, not the ten
of `requirements.txt`.

**`env -u PYTHONPATH` is mandatory, here and every time.** The container carries
its own gdsfactory 9.44 on `PYTHONPATH`; it shadows the pinned **9.2.2** and the
generator draws different geometry from the same netlist, without a word.
`openroad/Makefile` bakes it into `KPYTHON` for that reason.

And the other interpreter: **`lvs_klayout.py` runs under the system `python3`,
not the venv** — the venv has no `docopt`, which the PDK's `run_lvs.py` imports.
Called with the wrong one it dies on import, and this flow once reported that as
"the top does not match".

If the container is recreated, come back to this section. It is the step that is
easiest to forget and the one whose absence looks like a broken design.

---

## 4. What more memory buys

Docker on native Linux sets **no memory or CPU cap of its own**: the cgroup reads
`max` and the container gets the whole machine. On **WSL2** the cap is the VM's,
from `%UserProfile%\.wslconfig`, and defaults to a fraction of the host's RAM.
`check_environment.py` prints which of the two you are in.

Measured on 7.5 GB, so this is not a wishlist:

| | on 7.5 GB |
|---|---|
| every block, and the whole top | fits |
| full sign-off DRC, `DRC_MODE=deep DRC_THR=1 DRC_MP=1`, on the filled GDS | three minutes, clean |
| split-table DRC on the filled GDS | **loses five tables** — `ldnmos`, `nwell`, `ldpmos`, `lvpwell`, `mslot` |
| density fill on the 1110 x 1110 die | about six minutes |
| KLayout LVS on the filled GDS | **does not finish** |

So there are exactly two things to try again with more memory:

1. **The split-table DRC on the filled GDS.** Raise `DRC_MP` and `DRC_THR` to 4
   and the five tables should stop dying. Worth having as a fast screen — but
   `mslot` crashes in that mode for a reason that is not memory (a bug in the
   PDK deck), so **the verdict stays the `main`/deep run**. See
   [`drc-full-deck.md`](drc-full-deck.md).

   **MEASURED 2026-09-01 on 31 GB: this is confirmed.** `DRC_THR=4 DRC_MP=4`,
   18m41s wall (63 min CPU), peak ~13 GB of 31.

       63 tables launched, 63 .lyrdb written, 0 violations
       ldnmos, nwell, ldpmos, lvpwell   all four now run and are clean
       mslot                            still crashes -- the deck bug, not memory

   The four that used to die of memory are recovered. `mslot` behaves exactly as
   predicted, so the fast screen is now genuinely 62 of 63 tables. **The verdict
   is still the `main`/deep run**, which on this machine took 3m51s and was
   clean with `MSLOT.0`…`MSLOT.9` actually declared.
2. **The KLayout LVS on the filled GDS**, which is what the chipathon's external
   LVS runs. On the unfilled GDS it took thirteen seconds; on the filled one it
   ran fifty-six minutes without a progress line. That is net count from the
   floating fill, not only memory, **so measure it, do not assume it**. If it
   still will not finish, that is worth telling the organisers, because
   `lvs_config.json` points `LAYOUT_FILE` at the filled GDS.

Everything else already passes here and will not get better.

---

## 5. First commands on the new machine

```bash
cd /foss/designs/a_zonetic2026/openroad

python3 scripts/check_environment.py         # the ground, before anything else

# nothing has to be rebuilt: the deliverable is already clean and archived.
# These only re-confirm it, and they are cheap:
env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python scripts/check_integration.py
env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python scripts/check_current_density.py
make lvs T=B26_A TOP_OUT=out_integration ARGS=B26_A     # netgen

# the verdict run, three minutes here
DRC_MODE=deep DRC_THR=1 DRC_MP=1 \
    make drc T=B26_A TOP_OUT=out_integration ARGS=B26_A_FILLED

# and the two that are worth the new machine
DRC_THR=4 DRC_MP=4 make drc T=B26_A TOP_OUT=out_integration ARGS=B26_A_FILLED
make lvs-klayout T=B26_A TOP_OUT=out_integration ARGS=B26_A_FILLED
```

The deliverable is `openroad/out_integration/B26_A_filled3.gds`, archived as
`integration/gds/2026-08-31_02`. `HANDOFF.md` §5 has the state of everything and
what is left to do.

---

## 6. Absolute paths, if the tree ever moves off `/foss/designs`

The scripts find their own root from `__file__`, but five things are written out
in full. They are correct inside the container and will not be anywhere else:

| path | who writes it |
|---|---|
| `/foss/designs/zotnetic_layout` | `decap_fill.py`, `lvs_klayout.py`, `esd_layout.py` (`sys.path`), `lvs_netgen.py` (`SETUP_POLYRES`) |
| `/foss/designs/a_zonetic2026` | `spice_to_verilog.py`, `esd_layout.py`, `build_block.py`, `run_lvs.sh` |
| `/headless/.venvs/zotnetic/bin/python` | `openroad/Makefile` (`KPYTHON`), `probar_verificacion.py` |
| `/foss/pdks/gf180mcuD/...` | the DRC and LVS runners, the magicrc, the netgen setup |
| `/foss/tools/bin/magic`, `/foss/tools/bin/netgen` | `drc_magic.py`, `lvs_netgen.py` |

Keeping the tree at `/foss/designs/a_zonetic2026` with the generator beside it at
`/foss/designs/zotnetic_layout` costs nothing and avoids all of it.
