{
  inputs = {
    nixpkgs.url = "github:example/nixpkgs";
    flake-utils.url = "github:example/flake-utils";
  };

  outputs = inputs:
    let
      exampleSystems = [ "aarch64-darwin" "x86_64-linux" ];
      mkExampleOutputs = system: { packages = { default = inputs.nixpkgs; }; apps = { example-tool = { type = "app"; program = "example-tool"; }; }; };
    in
      builtins.listToAttrs (map (system: { name = system; value = mkExampleOutputs system; }) exampleSystems);
}
