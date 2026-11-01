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

## Owner-provided origin statement — 2026-11-02

The project owner confirmed that the original controller scripts and historical
tests were written by them or generated for them, rather than knowingly copied
from another person or project. This statement supplies the owner confirmation
that was missing from the initial local-installation snapshot. It does not
identify which individual files were handwritten versus generated, and no
independent authorship or generated-output similarity audit has been performed.
No specific third-party copied source was identified by the owner.

The project-level GPL-3.0-or-later selection remains in place for project-authored
work. This statement is not a claim that all generated output is copyrightable,
and does not override any third-party rights or dependency license requirements.
Original baseline hashes and historical test fixtures are preserved as records
of the snapshot, not as proof of authorship.

firefox.js references KDE KWin's scripting.cpp for its QTimer API, and
cec-kde-settings.py references KDE PowerDevil's defaults implementation. Those
references alone do not establish that code was copied. They remain intact;
any subsequently identified copied material must retain its applicable notices
and be reviewed under its actual license.

## Privacy cleanup scope

Published main was replaced with a single clean root commit and other published
branches and tags were removed. That operation does not redact GitHub-managed
pull-request refs, cached views, or old local clones and worktrees. GitHub-side
purging requires separate verification; do not infer completion from this file.

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
