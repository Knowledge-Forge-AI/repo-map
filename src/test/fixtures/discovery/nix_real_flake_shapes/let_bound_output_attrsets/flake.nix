{
  inputs = {
    nixpkgs.url = "github:example/nixpkgs";
    repo-lib.follows = "nixpkgs";
  };

  outputs = inputs:
    let
      systems = [ "aarch64-darwin" "x86_64-linux" ];
      mkExampleOutputs = system: {
        packages.${system}.default = inputs.nixpkgs;
        apps.${system}.example-tool = { type = "app"; };
        devShells.${system}.default = inputs.nixpkgs;
        checks.${system}.unit = inputs.nixpkgs;
      };
    in
      mkExampleOutputs (builtins.head systems);
}
