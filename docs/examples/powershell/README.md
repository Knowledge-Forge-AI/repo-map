# PowerShell Static Extraction Examples

These files are public-safe examples for the PowerShell extraction design in
`docs/extraction/powershell-extraction-design.md`.

They are static extraction examples only:

- do not execute them;
- do not import them into a real profile or module path;
- do not treat fake command targets as operational advice;
- do not add real secrets, private paths, or machine-local scripts here.

The examples intentionally include command shapes that a future extractor should
recognize, including aliases, splatting, dynamic invocation, host mutation,
network, remoting, and secret-like values. Mutating or network-looking commands
are placed inside uncalled functions so the files do not perform work merely by
being inspected.
