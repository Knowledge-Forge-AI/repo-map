{
  self,
  nixpkgs,
  flake-utils,
}:
{
  inputs = {
    nixpkgs.url = "https://example.invalid/nixpkgs";
    flake-utils.url = "https://example.invalid/flake-utils";
    repo-lib.follows = "nixpkgs";
    local-lib.url = "path:example-module";
  };

  outputs = { self, nixpkgs, flake-utils, repo-lib, ... }@inputs: {
    nixosModules.default = import ./modules/example-module.nix;
    darwinModules.default = import ./modules/darwin-module.nix;
    homeManagerModules.default = import ./modules/home-manager-module.nix;
    overlays.default = final: prev: import ./overlays/example-overlay.nix final prev;
  };
}
