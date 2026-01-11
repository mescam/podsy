{
  description = "Podsy - TUI for managing iPod 5.5g on Linux";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs, ... }:
    let
      inherit (nixpkgs) lib;
      forAllSystems = lib.genAttrs [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
    in
    {
      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.python313
              pkgs.uv
              pkgs.ruff
              pkgs.pyright
            ];

            env = lib.optionalAttrs pkgs.stdenv.isLinux {
              LD_LIBRARY_PATH = lib.makeLibraryPath [
                pkgs.stdenv.cc.cc.lib
              ];
            };

            shellHook = ''
              unset PYTHONPATH
            '';
          };
        }
      );

      packages = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python313;
        in
        {
          default = pkgs.stdenv.mkDerivation {
            pname = "podsy";
            version = "0.1.0";
            src = ./.;

            nativeBuildInputs = [ pkgs.uv python ];

            buildPhase = ''
              export HOME=$(mktemp -d)
              export UV_CACHE_DIR=$(mktemp -d)
              uv sync --frozen --no-dev
              uv build
            '';

            installPhase = ''
              mkdir -p $out/bin
              # Install wheel into a venv
              python -m venv $out/venv
              $out/venv/bin/pip install dist/*.whl
              # Create wrapper script
              cat > $out/bin/podsy << EOF
              #!${pkgs.bash}/bin/bash
              exec $out/venv/bin/podsy "\$@"
              EOF
              chmod +x $out/bin/podsy
            '';
          };
        }
      );

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/podsy";
        };
      });
    };
}
