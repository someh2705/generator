{
  description = "capstone project";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    nixpkgs-unstable,
    flake-utils,
    ...
  }:
    flake-utils.lib.eachDefaultSystem (
      system: let
        pkgs = import nixpkgs {inherit system;};
        unstable = import nixpkgs-unstable {inherit system;};

        devTools = with unstable; [
          uv
          ty
          ruff
          pyright
          watchexec
        ];

        python = unstable.python3.withPackages (
          ps:
            with ps; [
              scipy
              numpy
              pyyaml
              addict
              networkx
              matplotlib
              icecream

              python-lsp-server
              python-lsp-ruff
            ]
        );
      in {
        devShells.default = pkgs.mkShell {
          nativeBuildInputs = devTools;
          buildInputs = [python];

          shellHook = ''
            export PYTHONPATH=$PYTHONPATH:${python}/${python.sitePackages}
          '';
        };
      }
    );
}
