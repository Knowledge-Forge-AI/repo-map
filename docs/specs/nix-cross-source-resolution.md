# Static Nix Cross-Source Resolution

## Scope

RepoMap resolves a deliberately small static subset of Nix relations across
explicit source bindings. It never evaluates Nix, instantiates derivations,
loads repository code, runs scripts, or acquires a remote source.

## Inputs

Resolution operates on the complete immutable snapshot vector and extracted
observations for one graph candidate. Each configured binding supplies a stable
alias, role, optional `input_name`, and selected-file manifest. A physical root
is capture-only locator state and is not resolver evidence or identity.

## Exact forms

The following forms can resolve as `exact`:

- a literal relative import such as `./modules/default.nix` when its normalized
  target exists inside the same binding;
- `inputs.<name>.nixosModules.<module>` when exactly one binding maps `<name>`,
  the target `flake.nix` contains exactly one direct literal export for that
  module, and the export resolves to a selected source-relative file. Admitted
  exports are `nixosModules.<module> = import ./path.nix`,
  `nixosModules.<module> = ./path.nix`, and the equivalent direct literal member
  of `nixosModules = { ... };`.

An exact observation records `static-literal` evidence, source and target
binding aliases, same/cross-binding state, candidate identity, and one resolved
binding-qualified file target.

## Non-exact outcomes

- `ambiguous`: several bindings map the same input name.
- `conflicting`: one binding statically exports more than one admitted literal
  target for the same module reference.
- `evaluation-dependent`: interpolation or conditional evaluation is present.
- `unsupported`: no mapped binding/selected target exists or the syntax is
  outside this phase's admitted forms.

Non-exact observations use bounded-unknown evidence and deterministic opaque
unknown/dynamic targets. The identity is per observation and contains no path
or content, so unrelated scalar binding metadata cannot conflate during edge
merge. They never create a speculative exact target or use configuration order
as precedence.

## Deliberate unsupported surface

Bare `inputs.<name>` references, file existence or naming convention, attribute
indirection, arbitrary output traversal, `darwinModules`, overlays,
functions requiring argument evaluation, generated paths, platform-dependent
outputs, inherited or merged attrsets, helper-generated exports, string
interpolation, conditional branches, and nonliteral import expressions are not
exact in this slice. Later support requires a separately accepted static rule
and exact evidence; it does not authorize Nix evaluation.
