{ inputs, ... }:
{
  imports = [
    ./modules/default.nix
    inputs.composition.nixosModules.default
    inputs.shared.nixosModules.default
    (if builtins.currentSystem == "x86_64-linux" then inputs.security else inputs.developer)
  ];
}
