#!/usr/bin/env bash
set -Eeuo pipefail

# Ubuntu bootstrap for COPE Chess, its web/runner/worker processes, and
# common native chess engine build stacks.
#
# Usage:
#   bash scripts/bootstrap-ubuntu-everything.sh
#   bash scripts/bootstrap-ubuntu-everything.sh /path/to/cope-chess
#
# Environment switches:
#   SKIP_PROJECT_INSTALL=1    Install system and language deps only.
#   INSTALL_RUSTUP=0          Skip rustup installation.
#   INSTALL_CHOOSENIM=0       Skip choosenim installation.
#   COPE_VENV=.venv           Override the project virtualenv path.

if [ "$(id -u)" -eq 0 ]; then
  SUDO=()
else
  SUDO=(sudo)
fi

run_root() {
  "${SUDO[@]}" "$@"
}

apt_get() {
  run_root env DEBIAN_FRONTEND=noninteractive apt-get "$@"
}

apt_install_required() {
  apt_get install -y "$@"
}

apt_install_available() {
  local packages=()
  local package

  for package in "$@"; do
    if apt-cache show "$package" >/dev/null 2>&1; then
      packages+=("$package")
    else
      printf 'Skipping unavailable apt package: %s\n' "$package"
    fi
  done

  if [ "${#packages[@]}" -gt 0 ]; then
    apt_get install -y "${packages[@]}"
  fi
}

repo_dir_from_args() {
  if [ "${1:-}" ]; then
    cd "$1"
    pwd
    return
  fi

  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  if [ -f "$script_dir/../pyproject.toml" ]; then
    cd "$script_dir/.."
    pwd
    return
  fi

  if [ -f "$PWD/pyproject.toml" ]; then
    pwd
    return
  fi

  printf ''
}

install_apt_dependencies() {
  apt_get update
  apt_install_required \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    software-properties-common

  if command -v add-apt-repository >/dev/null 2>&1; then
    run_root add-apt-repository -y universe || true
  fi

  apt_get update

  apt_install_required \
    autoconf \
    automake \
    bison \
    build-essential \
    bzip2 \
    ca-certificates \
    ccache \
    clang \
    cmake \
    curl \
    file \
    flex \
    g++ \
    gcc \
    gdb \
    git \
    git-lfs \
    gzip \
    libbz2-dev \
    libffi-dev \
    libgmp-dev \
    libjemalloc-dev \
    liblz4-dev \
    liblzma-dev \
    libncursesw5-dev \
    libnuma-dev \
    libomp-dev \
    libreadline-dev \
    libsqlite3-dev \
    libssl-dev \
    libtool \
    libzstd-dev \
    lld \
    llvm \
    m4 \
    make \
    meson \
    ninja-build \
    nodejs \
    npm \
    openssh-client \
    pipx \
    pkg-config \
    procps \
    psmisc \
    python3 \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-venv \
    python3-wheel \
    rsync \
    sqlite3 \
    tar \
    time \
    tk-dev \
    unzip \
    uuid-dev \
    valgrind \
    wget \
    xz-utils \
    zip \
    zlib1g-dev \
    zstd

  apt_install_available \
    cabal-install \
    clinfo \
    cutechess-cli \
    default-jdk \
    doxygen \
    dub \
    fpc \
    ghc \
    golang-go \
    gradle \
    graphviz \
    libboost-all-dev \
    libcurl4-openssl-dev \
    libeigen3-dev \
    libopenblas-dev \
    libprotobuf-dev \
    libvulkan-dev \
    ldc \
    maven \
    mold \
    mono-complete \
    nasm \
    nim \
    ocl-icd-opencl-dev \
    opencl-headers \
    protobuf-compiler \
    ruby-full \
    scons \
    stockfish \
    swig \
    vulkan-tools \
    yasm \
    zig
}

install_rustup() {
  if [ "${INSTALL_RUSTUP:-1}" != "1" ]; then
    return
  fi

  if ! command -v rustup >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --profile default
  fi

  export PATH="$HOME/.cargo/bin:$PATH"
  rustup toolchain install stable
  rustup default stable
  rustup component add clippy rustfmt
}

install_choosenim() {
  if [ "${INSTALL_CHOOSENIM:-1}" != "1" ]; then
    return
  fi

  export CHOOSENIM_NO_ANALYTICS=1
  export PATH="$HOME/.nimble/bin:$PATH"

  if ! command -v choosenim >/dev/null 2>&1; then
    curl -fsSL https://nim-lang.org/choosenim/init.sh | sh -s -- -y
  fi

  export PATH="$HOME/.nimble/bin:$PATH"
  if command -v choosenim >/dev/null 2>&1; then
    choosenim stable
  fi
  if command -v nimble >/dev/null 2>&1; then
    nimble refresh -y || nimble refresh
  fi
}

install_python_project() {
  local repo_dir="$1"
  if [ "${SKIP_PROJECT_INSTALL:-0}" = "1" ]; then
    return
  fi
  if [ -z "$repo_dir" ]; then
    printf 'No pyproject.toml found. Skipping COPE Python virtualenv setup.\n'
    return
  fi

  local venv_path="${COPE_VENV:-.venv}"
  cd "$repo_dir"
  python3 -m venv "$venv_path"
  "$venv_path/bin/python" -m pip install --upgrade pip setuptools wheel
  "$venv_path/bin/python" -m pip install -e ".[web,runner,worker,dev]"
}

print_summary() {
  local repo_dir="$1"

  printf '\nBootstrap complete.\n'
  printf 'Installed broad Ubuntu build dependencies for Python, web, runner, worker, Rust, Nim, C/C++, Java, Go, and common engine tooling.\n'

  if [ -n "$repo_dir" ] && [ "${SKIP_PROJECT_INSTALL:-0}" != "1" ]; then
    printf '\nProject virtualenv:\n'
    printf '  %s/%s\n' "$repo_dir" "${COPE_VENV:-.venv}"
    printf '\nCommon commands:\n'
    printf '  source "%s/%s/bin/activate"\n' "$repo_dir" "${COPE_VENV:-.venv}"
    printf '  cope init-db\n'
    printf '  cope web --host 0.0.0.0\n'
    printf '  cope runner\n'
    printf '  cope worker --server-url ws://HOST:8765\n'
  fi

  printf '\nYou may need to open a new shell for rustup or choosenim PATH changes.\n'
}

main() {
  local repo_dir
  repo_dir="$(repo_dir_from_args "${1:-}")"

  install_apt_dependencies
  install_rustup
  install_choosenim
  install_python_project "$repo_dir"
  print_summary "$repo_dir"
}

main "$@"
