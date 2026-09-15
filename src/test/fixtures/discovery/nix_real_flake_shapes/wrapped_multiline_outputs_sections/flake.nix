{
  inputs = {
    nixpkgs.url = "github:example/nixpkgs";
    repo-lib.follows = "nixpkgs";
  };

  outputs =
    inputs:
    let
      examplePackages = { aarch64-darwin = { default = inputs.nixpkgs; }; };
      exampleShells = { aarch64-darwin = { default = inputs.nixpkgs; }; };
      exampleChecks = { aarch64-darwin = { unit = inputs.nixpkgs; }; };
    in { packages = examplePackages; devShells = exampleShells; checks = exampleChecks; };
}
