# Origin and licensing

The primary source is the existing local installation on magne-desktop, not an
upstream repository. SNAPSHOT.json records the exact local origin and hash of each
copied file. Tests originate from local Codex work directories dated 2026-10-26.
Earlier local installation documentation corroborates the component layout and
superseded units. Available material suggests local iterative development, but
this is not a complete authorship or chain-of-title audit.

No LICENSE, SPDX identifier, copyright notice or explicit redistribution grant
was found in the 17 selected original files or the installed cec-tv root.
Individual authorship and any earlier copied-code provenance remain unverified.
No new license has been assigned. Private archival storage must not be interpreted
as permission to publish or redistribute under an open-source license.

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
solely for this archival task. All installed controller and original test bytes
remain unchanged.
