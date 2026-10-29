# Serve the local Nemotron 3.5 Lightning GGUF on http://127.0.0.1:8080/v1 (OpenAI-compatible).
# Same model Nebius Token Factory serves as nvidia/Nemotron-3.5-Lightning, so switching is one env var.
$ErrorActionPreference = "Stop"

# Unsloth's llama.cpp build needs its bundled CUDA runtime on PATH.
$cudaLib = "$HOME\.unsloth\studio\unsloth_studio\Lib\site-packages\torch\lib"
$env:PATH = "$cudaLib;$env:PATH"

$server = "$HOME\.unsloth\llama.cpp\build\bin\Release\llama-server.exe"
$model = "D:\Unsloth\New Models\hub\models--unsloth--NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF\snapshots\f2d3fe3694501008786e81e5f20360cbf715496a\NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ3_XXS.gguf"

foreach ($path in @($server, $model)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file not found: $path" }
}
if (Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue) {
    throw "Port 8080 is already in use. Stop the other server first."
}

& $server `
    -m $model `
    --alias "nvidia/Nemotron-3.5-Lightning" `
    --host 127.0.0.1 --port 8080 `
    -c 32768 --parallel 1 `
    --device CUDA0 --n-gpu-layers 999 --flash-attn on `
    --jinja `
    --temp 1.0 --top-p 0.95
if ($LASTEXITCODE -ne 0) { throw "llama-server exited with code $LASTEXITCODE" }
