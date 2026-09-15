{
  self,
  nixpkgs,
}:
{
  outputs = { self, nixpkgs, ... }: {
    packages = {
      aarch64-darwin = {
        example-package = import ./pkgs/example-package.nix { };
      };
    };

    devShells = {
      aarch64-darwin = {
        default = import ./shells/dev.nix { };
      };
    };

    checks = {
      aarch64-darwin = {
        unit = ./checks/unit.nix;
      };
    };
  };
}
