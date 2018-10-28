with import <nixpkgs> {};
stdenv.mkDerivation rec {
  name = "zappa-end-to-end-tests";
  env = buildEnv { name = name; paths = buildInputs; };
  buildInputs = [
    bashInteractive
    python27Full
    python36Full
    python36Packages.virtualenv
    python36Packages.pip
    python36Packages.pytest
    pipenv
  ];
}