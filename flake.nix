{
  description = "blog-agent: automated Telegram pipeline with local LLM";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config = { allowUnfree = true; };
      };
      pythonEnv = pkgs.python313.withPackages (ps: with ps; [
        ruamel-yaml
        httpx
        aiogram
        pytest
        pytest-asyncio
      ]);

      appSource = pkgs.runCommand "blog-agent-app" { } ''
        mkdir -p $out/app
        cp -r ${./src} $out/app/src
        cp -r ${./prompts} $out/app/prompts
        cp -r ${./templates} $out/app/templates
        cp -r ${./docs} $out/app/docs
        cp ${./SYSTEM.MD} $out/app/SYSTEM.MD
        cp ${./persona.md} $out/app/persona.md
        cp ${./content-plan.yaml} $out/app/content-plan.yaml
        mkdir -p $out/app/out/drafts $out/app/out/images $out/app/logs
      '';

      container = pkgs.dockerTools.buildLayeredImage {
        name = "blog-agent";
        tag = "latest";
        contents = [
          pythonEnv
          pkgs.resvg
          pkgs.liberation_ttf
          pkgs.cacert
          pkgs.coreutils
          pkgs.bashInteractive
          appSource
        ];
        config = {
          WorkingDir = "/app";
          Cmd = [ "python3" "src/bot.py" ];
          Env = [
            "PYTHONPATH=/app"
            "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            "PATH=${pythonEnv}/bin:${pkgs.resvg}/bin:${pkgs.coreutils}/bin:${pkgs.bashInteractive}/bin"
          ];
        };
      };
    in
    {
      packages.${system} = {
        inherit container;
        default = container;
      };

      devShells.${system}.default = pkgs.mkShell {
        name = "blog-agent-dev";
        packages = [
          pythonEnv
          pkgs.resvg
        ];

        shellHook = ''
          export PYTHONPATH="$PWD:$PYTHONPATH"
          export MODEL_PATH="/home/BadRabbit/.eva/models/gemma-4-12b-it-uncensored-GGUF/gemma-4-12b-it-uncensored-Q4_K_M.gguf"
          alias blog="python3 $PWD/src/cli.py"
          alias bot="python3 $PWD/src/bot.py"

          start_llama() {
            if curl -s http://127.0.0.1:8080/health > /dev/null 2>&1 || curl -s http://127.0.0.1:8080/v1/models > /dev/null 2>&1; then
              echo "[+] llama-server already running on http://127.0.0.1:8080"
            else
              echo "[*] Launching llama-server on http://127.0.0.1:8080 with 256k/131k context + flash attention..."
              llama-server -m "$MODEL_PATH" -ngl 28 -c 262144 -ctk q4_0 -ctv q4_0 -fa on --host 127.0.0.1 --port 8080 > logs/llama-server.log 2>&1 &
              echo "[+] llama-server started in background (PID: $!)."
            fi
          }
        '';
      };
    };
}
