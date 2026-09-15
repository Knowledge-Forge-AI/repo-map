# Zsh Static Extraction Examples

These examples are public-safe design inputs for ZSH0. They are static source
examples only and must not be executed, sourced, or loaded by RepoMap.

The examples illustrate future zsh extraction boundaries for:

- zsh shebangs, startup/profile files, functions, options, exports, and
  sources;
- fpath, autoload, zstyle, zmodload, bindkey, completion functions, plugins,
  and themes;
- glob qualifiers, extended globs, parameter expansion flags, eval, and dynamic
  source paths;
- comments, strings, arrays, and heredocs that should not become false command
  or plugin evidence.

Implementation fixtures should begin under `src/test/fixtures/shell/zsh/` in
ZSH1 or later. These docs examples are not production fixtures.
