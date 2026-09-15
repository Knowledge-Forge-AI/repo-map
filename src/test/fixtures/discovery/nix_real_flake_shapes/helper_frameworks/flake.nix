{
  self,
  nixpkgs,
  flake-utils,
}:
let
  systems = [ "aarch64-darwin" "x86_64-linux" ];
  forAllSystems = nixpkgs.lib.genAttrs systems;
in
{
  outputs = { self, nixpkgs, flake-utils, ... }: {
    packages = flake-utils.lib.eachDefaultSystem (system: {
      default = import ./pkgs/example-package.nix { inherit system; };
    });

    devShells = builtins.genAttrs systems (system: {
      default = import ./shells/dev.nix { inherit system; };
    });

    apps = forAllSystems (system: {
      example-tool = {
        type = "app";
        program = "${self}/bin/example-tool";
      };
    });
  };
}
