@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion

set "MODEL_PATH=D:\models\Qwen3-0.6B"
set "MAX_GEN_TOKS=300"
set "BATCH_SIZE=1"
set "USE_ACCELERATE=False"
set "DEFAULT_TASK_LIST=mapfin_AS mapfin_SA mapfin_TC mapfin_TS mapfin_QA"
set "MODEL_BACKEND=hf-causal-vllm"
set "MAPFIN_LIMIT=1"
set "MAPFIN_EVAL_SPLIT=test"
set "PYTHON_EXE=C:\Users\18388\.conda\envs\MapFinBen\python.exe"

:: Resolve absolute paths from the script directory.
for %%i in ("%~dp0.") do set "SCRIPT_DIR=%%~fi"
for %%i in ("%SCRIPT_DIR%\..\..") do set "PROJECT_ROOT=%%~fi"
set "MAIN_ROOT=%PROJECT_ROOT%\main"
set "EVAL_SCRIPT=%MAIN_ROOT%\src\eval.py"
set "OUTPUT_DIR=%MAIN_ROOT%\outputs"
set "ENV_FILE=%PROJECT_ROOT%\.env"
set "DATA_PATH=%PROJECT_ROOT%\data"

if exist "%ENV_FILE%" (
    for /f "usebackq eol=# tokens=1* delims==" %%a in ("%ENV_FILE%") do (
        if not "%%a"=="" set "%%a=%%b"
    )
)

if defined MAPFIN_MODEL_PATH set "MODEL_PATH=%MAPFIN_MODEL_PATH%"
for %%i in ("%MODEL_PATH%") do set "MODEL_NAME=%%~nxi"
if defined MAPFIN_MODEL_BACKEND set "MODEL_BACKEND=%MAPFIN_MODEL_BACKEND%"
if defined MAPFIN_DATA_PATH set "DATA_PATH=%MAPFIN_DATA_PATH%"
if not "%DATA_PATH:~1,1%"==":" set "DATA_PATH=%PROJECT_ROOT%\%DATA_PATH%"
for %%i in ("%DATA_PATH%") do set "DATA_PATH=%%~fi"
if defined MAPFIN_MAX_GEN_TOKS set "MAX_GEN_TOKS=%MAPFIN_MAX_GEN_TOKS%"
if defined MAPFIN_BATCH_SIZE set "BATCH_SIZE=%MAPFIN_BATCH_SIZE%"
if defined MAPFIN_USE_ACCELERATE set "USE_ACCELERATE=%MAPFIN_USE_ACCELERATE%"
if defined MAPFIN_PYTHON set "PYTHON_EXE=%MAPFIN_PYTHON%"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

if not defined MAPFIN_EVAL_SPLIT set "MAPFIN_EVAL_SPLIT=test"
if /I "%MAPFIN_EVAL_SPLIT%"=="validation" set "MAPFIN_EVAL_SPLIT=valid"
set "VALID_SPLIT=0"
if /I "%MAPFIN_EVAL_SPLIT%"=="test" set "VALID_SPLIT=1"
if /I "%MAPFIN_EVAL_SPLIT%"=="valid" set "VALID_SPLIT=1"
if "%VALID_SPLIT%"=="0" (
    echo [ERROR] Invalid MAPFIN_EVAL_SPLIT: %MAPFIN_EVAL_SPLIT%
    echo [ERROR] Allowed values are: test, valid.
    exit /b 1
)

if not exist "%MODEL_PATH%" (
    echo [ERROR] MODEL_PATH does not exist: %MODEL_PATH%
    exit /b 1
)

if not exist "%DATA_PATH%" (
    echo [ERROR] DATA_PATH does not exist: %DATA_PATH%
    exit /b 1
)

if not exist "%EVAL_SCRIPT%" (
    echo [ERROR] eval.py not found: %EVAL_SCRIPT%
    exit /b 1
)

if not defined MAPFIN_TASK_LIST set "MAPFIN_TASK_LIST=%DEFAULT_TASK_LIST%"
if not defined MAPFIN_LIMIT set "MAPFIN_LIMIT=5"
if not defined OPENAI_EMBEDDING_MODEL set "OPENAI_EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5"

if defined MAPFIN_OPENAI_BASE_URL set "OPENAI_BASE_URL=%MAPFIN_OPENAI_BASE_URL%"
if defined MAPFIN_OPENAI_CHAT_URL set "OPENAI_CHAT_URL=%MAPFIN_OPENAI_CHAT_URL%"

if defined MAPFIN_API_TOKEN (
    set "OPENAI_API_SECRET_KEY=%MAPFIN_API_TOKEN%"
    set "OPENAI_API_KEY=%MAPFIN_API_TOKEN%"
) else (
    if defined LM_STUDIO_API_TOKEN (
        set "OPENAI_API_SECRET_KEY=%LM_STUDIO_API_TOKEN%"
        set "OPENAI_API_KEY=%LM_STUDIO_API_TOKEN%"
    ) else (
        if not defined OPENAI_API_SECRET_KEY if defined OPENAI_API_KEY set "OPENAI_API_SECRET_KEY=%OPENAI_API_KEY%"
        if not defined OPENAI_API_KEY if defined OPENAI_API_SECRET_KEY set "OPENAI_API_KEY=%OPENAI_API_SECRET_KEY%"
    )
)

if not exist "%OUTPUT_DIR%" (
    mkdir "%OUTPUT_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create output directory: %OUTPUT_DIR%
        exit /b 1
    )
)

set "MAPFIN_DATA_PATH=%DATA_PATH%"

"%PYTHON_EXE%" -c "import sys; print(sys.executable)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python failed to start before running any task.
    echo [ERROR] This is an environment problem, not an eval.py task failure.
    echo [ERROR] Reinstall the editable mapfinben package in the active Conda environment.
    exit /b 1
)

"%PYTHON_EXE%" -c "import torch, transformers, datasets, openai" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Required Python packages are missing in the active environment.
    echo [ERROR] Expected at least: torch, transformers, datasets, openai
    exit /b 1
)

if /I "%MODEL_BACKEND%"=="hf-causal-vllm" (
    "%PYTHON_EXE%" -c "import vllm" >nul 2>&1
    if errorlevel 1 (
        echo [WARN] vllm is not installed in this Python environment; falling back to hf-causal.
        set "MODEL_BACKEND=hf-causal"
    )
)

if /I "%MODEL_BACKEND%"=="hf-causal" (
    set "MODEL_ARGS=pretrained=%MODEL_PATH%,tokenizer=%MODEL_PATH%,dtype=auto,trust_remote_code=True"
) else (
    set "MODEL_ARGS=use_accelerate=%USE_ACCELERATE%,pretrained=%MODEL_PATH%,tokenizer=%MODEL_PATH%,use_fast=False,max_gen_toks=%MAX_GEN_TOKS%,dtype=auto,trust_remote_code=True"
)

echo Model path : %MODEL_PATH%
echo Data path  : %DATA_PATH%
echo Data split : %MAPFIN_EVAL_SPLIT%
echo Backend    : %MODEL_BACKEND%
echo Model name : %MODEL_NAME%
echo Python     : %PYTHON_EXE%
echo Eval path  : %EVAL_SCRIPT%
echo Output dir : %OUTPUT_DIR%
echo.

echo ===== Environment Variables =====
echo OPENAI_BASE_URL=%OPENAI_BASE_URL%
echo OPENAI_CHAT_URL=%OPENAI_CHAT_URL%
echo OPENAI_EMBEDDING_MODEL=%OPENAI_EMBEDDING_MODEL%
echo ================================
echo.

setlocal EnableDelayedExpansion
for %%t in (%MAPFIN_TASK_LIST%) do (
    echo ===== Running: %%t =====
    "%PYTHON_EXE%" "%EVAL_SCRIPT%" ^
      --model %MODEL_BACKEND% ^
      --tasks %%t ^
      --model_args "%MODEL_ARGS%" ^
      --no_cache ^
      --batch_size "%BATCH_SIZE%" ^
      --device auto ^
      --output_path "%OUTPUT_DIR%" ^
      --write_out ^
      --output_base_path "%MODEL_NAME%_%MAPFIN_EVAL_SPLIT%_%%t" ^
      --limit "%MAPFIN_LIMIT%" ^
      --eval_split "%MAPFIN_EVAL_SPLIT%"

    set "TASK_EXIT=!ERRORLEVEL!"
    if not "!TASK_EXIT!"=="0" (
        echo [ERROR] Task %%t failed with exit code !TASK_EXIT!.
        exit /b !TASK_EXIT!
    )
    echo.
)
endlocal

echo Done
exit /b 0
