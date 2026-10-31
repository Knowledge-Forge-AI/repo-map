{ config, lib, pkgs, ... }:

{
  options.services.repomap-companion = {
    enableStrictSandbox = lib.mkEnableOption "strict sandbox mode for repomap-companion";
    deployScriptPath = lib.mkOption {
      type = lib.types.str;
      default = "./deploy.sh";
      description = "Companion deploy script invoking core/scripts/bootstrap.sh";
    };
  };

  config = {
    services.repomap-companion.enableStrictSandbox = true;
    services.repomap-companion.deployScriptPath = "./deploy.sh";
  };
}
