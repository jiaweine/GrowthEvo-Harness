# Python Support Policy

GrowthEvo separates the **core/runtime support matrix** from the **frozen research environments** used to reproduce accepted real-world evidence.

## Core and package support

The dependency-light core is continuously tested on the current supported stable matrix:

- Python 3.11
- Python 3.12
- Python 3.13
- Python 3.14

The project metadata therefore declares `requires-python = ">=3.11"` and classifiers for Python 3.11–3.14. CI runs the full dependency-light pytest suite and runtime/training demos on all four versions.

The distribution job builds the sdist and universal wheel on Python 3.14, validates both with `twine check`, installs the wheel into a clean environment outside the repository, imports `growthevo`, and executes the installed locked-OPE and locked-targeting command-line entry points.

Passing the core matrix means the GrowthEvo Python package/runtime is tested on those stable interpreters. It does **not** retroactively change the interpreter or dependency versions used by accepted benchmark evidence.

## Frozen real-world research environments

Promoted full-data evidence is tied to its exact evidence commit and captured environment. Reproduction should use the environment stored beside that artifact rather than silently upgrading Python or scientific dependencies.

### Full Criteo Uplift v2.1 evidence

The accepted locked evidence under
`benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/`
was produced on Python 3.12 with the frozen LightGBM/NumPy/pandas/scikit-learn versions recorded in `environment.txt` and the preregistered candidate configuration.

The `criteo` optional dependency group remains an evidence-reproduction stack. Core support for Python 3.13/3.14 is **not** a claim that this historical frozen scientific stack should be upgraded in place. A different dependency recipe is a new research environment and must not be used to reinterpret the already accepted locked evidence.

### Open Bandit Dataset evidence

The maintained `sb-obp==0.5.10` bridge is explicitly marked for `python_version < '3.13'`. Small-OBD integration and accepted full OBD evidence therefore remain on the compatible research interpreter line rather than being forced onto the newest core Python.

This distinction is deliberate: package/runtime modernization and scientific evidence reproduction have different stability requirements.

## New Python releases

A new stable Python minor version is added to the supported matrix only after:

1. `actions/setup-python` can provision the stable release;
2. the full core test and demo suite passes;
3. a built wheel installs and both public CLI entry points execute in a clean environment;
4. project metadata and the CI contract test are updated together.

Pre-release interpreters may be evaluated separately, but an alpha/beta/RC is not listed as formally supported merely because it is newer.

## Research dependency upgrades

Upgrading a research-only dependency is not a routine compatibility edit when it changes a promoted benchmark's model/Q-generation environment. For accepted locked evidence, the old environment stays archived and reproducible. A new dependency stack should be preregistered and evaluated as a **new experiment identity** if it is intended to produce a new promoted result.
