{
  outputs = inputs: { apps = { aarch64-darwin = { example-tool = { type = "app"; }; }; }; packages = { x86_64-linux = { default = inputs.nixpkgs; }; }; };
}
