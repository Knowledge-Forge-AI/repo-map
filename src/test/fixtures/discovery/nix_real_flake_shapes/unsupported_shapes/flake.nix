{
  self,
  nixpkgs,
}:
let
  outputsModule = import ./outputs.nix { inherit self nixpkgs; };
  systems = [ "aarch64-darwin" "x86_64-linux" ];
in
{
  outputs = inputs:
    outputsModule
    // {
      packages = nixpkgs.lib.genAttrs systems (system:
        import ./pkgs/example-package.nix { inherit system; });
      inherit (outputsModule) checks;
      templates.default = {
        description = "Example template";
      };
    };
}
