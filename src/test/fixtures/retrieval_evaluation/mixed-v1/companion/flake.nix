{
  description = "Mixed-v1 companion flake for cross-source Nix/script retrieval evaluation";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";
  };

  outputs = { self, nixpkgs }: {
    nixosModules.repomapCompanion = import ./module.nix;
  };
}
