{ self }:
{
  imports = [ ./modules/base.nix ];

  apps.aarch64-darwin.tool = {
    type = "app";
    program = "${self}/bin/tool";
  };

  packages.aarch64-darwin.default = ./pkgs/default.nix;
  devShells.aarch64-darwin.default = { };
  checks.aarch64-darwin.unit = { };
  scripts = [ ./config/settings.json ];
}
