# Origin and licensing

The primary source is an existing local KDE Plasma installation, not an
upstream repository. SNAPSHOT.json records generalized local origins and original
hashes of each copied file. Tests originate from local development work directories
dated 2026-10-26. Hostnames and personal absolute paths have been removed from
the current tree; the hashes still describe the original, unsanitized baseline,
not the current files. Historical fixtures retain their assertions, with a
personal import path replaced by a repository-relative path. Legacy scripts now
use home-relative paths.
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

This publication cleanup does not resolve that uncertainty. Confirmation from
the original author or supporting source history is still needed to establish
rights for the imported material. Current-tree sanitization does not redact
personal metadata, commit identities or generated files in earlier commits,
tags, other checkout branches or local checkpoint references.

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
