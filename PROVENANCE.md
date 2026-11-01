# Origin and licensing

The primary source is the existing local installation on magne-desktop, not an
upstream repository. SNAPSHOT.json records the exact local origin and hash of each
copied file. Tests originate from local Codex work directories dated 2026-10-26.
Earlier local installation documentation corroborates the component layout and
superseded units. Available material suggests local iterative development, but
this is not a complete authorship or chain-of-title audit.

The project owner explicitly selected GPL-3.0-or-later for TopCEC-authored
project files; `LICENSE` contains the standard license text. This applies to
TopCEC-authored work in this repository and does not change licenses for
third-party dependencies or separately identified external material.

The original 17-file snapshot was copied from a local installation. Its
individual authorship and any earlier copied-code provenance remain
unverified; the project-level license does not claim copyright in separately
identified third-party material. The KWin and PowerDevil references below are
references only and do not establish that code from those projects was copied.

firefox.js contains a reference to KDE KWin's scripting.cpp for its QTimer API.
cec-kde-settings.py refers to KDE PowerDevil's defaults implementation. References
alone do not establish whether code was copied or which license applies to these
local files. Resolve this with the original author/history before redistribution.

External runtime dependencies include KDE KWin/PowerDevil utilities, libCEC's
cec-client, Python, dbus-python, PyGObject, evdev and pyatspi; legacy helpers also
use swayidle and systemd. Their code is not included. Their respective upstream
licenses remain applicable to those dependencies; this snapshot does not assert
that their licenses automatically cover the local controller. External projects
from prior comparison research were deliberately excluded.

README, manifest, validation notes, .gitignore and the safe test runner were added
solely for this archival task. The baseline hashes remain recorded in
SNAPSHOT.json; subsequent TopCEC-authored modifications are covered by the
project license.
