#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="${MODEL_PATH:-}"
MAX_GEN_TOKS="${MAX_GEN_TOKS:-300}"
BATCH_SIZE="${BATCH_SIZE:-1}"
USE_ACCELERATE="${USE_ACCELERATE:-False}"
DEFAULT_TASK_LIST="mapfin_AS mapfin_SA mapfin_TC mapfin_TS mapfin_QA"
MODEL_BACKEND="${MODEL_BACKEND:-hf-causal-vllm}"
MAPFIN_LIMIT="${MAPFIN_LIMIT:-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MAIN_ROOT="$PROJECT_ROOT/main"
EVAL_SCRIPT="$MAIN_ROOT/src/eval.py"
OUTPUT_DIR="$MAIN_ROOT/outputs"
ENV_FILE="$PROJECT_ROOT/.env"
DATA_PATH="${DATA_PATH:-$PROJECT_ROOT/data}"
PYTHON_EXE="${PYTHON_EXE:-}"

if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

if [ -n "${MAPFIN_MODEL_PATH:-}" ]; then
    MODEL_PATH="$MAPFIN_MODEL_PATH"
fi

MODEL_NAME="$(basename "$MODEL_PATH")"

if [ -n "${MAPFIN_MODEL_BACKEND:-}" ]; then
    MODEL_BACKEND="$MAPFIN_MODEL_BACKEND"
fi

if [ -n "${MAPFIN_DATA_PATH:-}" ]; then
    DATA_PATH="$MAPFIN_DATA_PATH"
fi

case "$DATA_PATH" in
    /*|[A-Za-z]:*)
        ;;
    *)
        DATA_PATH="$PROJECT_ROOT/$DATA_PATH"
        ;;
esac

if [ -n "${MAPFIN_MAX_GEN_TOKS:-}" ]; then
    MAX_GEN_TOKS="$MAPFIN_MAX_GEN_TOKS"
fi

if [ -n "${MAPFIN_BATCH_SIZE:-}" ]; then
    BATCH_SIZE="$MAPFIN_BATCH_SIZE"
fi

if [ -n "${MAPFIN_USE_ACCELERATE:-}" ]; then
    USE_ACCELERATE="$MAPFIN_USE_ACCELERATE"
fi

if [ -n "${MAPFIN_PYTHON:-}" ]; then
    PYTHON_EXE="$MAPFIN_PYTHON"
elif [ -z "$PYTHON_EXE" ]; then
    if [ -x "/c/Users/18388/.conda/envs/MapFinBen/python.exe" ]; then
        PYTHON_EXE="/c/Users/18388/.conda/envs/MapFinBen/python.exe"
    else
        PYTHON_EXE="python"
    fi
fi

if [ -n "${MAPFIN_TASK_LIST:-}" ]; then
    TASK_LIST="$MAPFIN_TASK_LIST"
elif [ -n "${MAPFIN_TASKS:-}" ]; then
    TASK_LIST="$MAPFIN_TASKS"
else
    TASK_LIST="$DEFAULT_TASK_LIST"
fi

if [ -z "${MAPFIN_LIMIT:-}" ]; then
    MAPFIN_LIMIT=1
fi

MAPFIN_EVAL_SPLIT="${MAPFIN_EVAL_SPLIT:-test}"
case "${MAPFIN_EVAL_SPLIT,,}" in
    validation)
        MAPFIN_EVAL_SPLIT="valid"
        ;;
    test|valid)
        ;;
    *)
        echo "[ERROR] Invalid MAPFIN_EVAL_SPLIT: $MAPFIN_EVAL_SPLIT"
        echo "[ERROR] Allowed values are: test, valid."
        exit 1
        ;;
esac

if [ -z "${OPENAI_EMBEDDING_MODEL:-}" ]; then
    export OPENAI_EMBEDDING_MODEL="text-embedding-nomic-embed-text-v1.5"
fi

if [ -n "${MAPFIN_OPENAI_BASE_URL:-}" ]; then
    export OPENAI_BASE_URL="$MAPFIN_OPENAI_BASE_URL"
fi

if [ -n "${MAPFIN_OPENAI_CHAT_URL:-}" ]; then
    export OPENAI_CHAT_URL="$MAPFIN_OPENAI_CHAT_URL"
fi

if [ -n "${MAPFIN_API_TOKEN:-}" ]; then
    export OPENAI_API_SECRET_KEY="$MAPFIN_API_TOKEN"
    export OPENAI_API_KEY="$MAPFIN_API_TOKEN"
elif [ -n "${LM_STUDIO_API_TOKEN:-}" ]; then
    export OPENAI_API_SECRET_KEY="$LM_STUDIO_API_TOKEN"
    export OPENAI_API_KEY="$LM_STUDIO_API_TOKEN"
else
    if [ -n "${OPENAI_API_KEY:-}" ] && [ -z "${OPENAI_API_SECRET_KEY:-}" ]; then
        export OPENAI_API_SECRET_KEY="$OPENAI_API_KEY"
    fi

    if [ -n "${OPENAI_API_SECRET_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
        export OPENAI_API_KEY="$OPENAI_API_SECRET_KEY"
    fi
fi

if [ -z "$MODEL_PATH" ] || [ ! -d "$MODEL_PATH" ]; then
    echo "[ERROR] Model path not found: ${MODEL_PATH:-<empty>}"
    exit 1
fi

if [ ! -d "$DATA_PATH" ]; then
    echo "[ERROR] Data path not found: $DATA_PATH"
    exit 1
fi

if [ ! -f "$EVAL_SCRIPT" ]; then
    echo "[ERROR] eval.py not found: $EVAL_SCRIPT"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
export MAPFIN_DATA_PATH="$DATA_PATH"

if ! "$PYTHON_EXE" -c "print('Python OK')" >/dev/null 2>&1; then
    echo "[ERROR] Python failed to start. Please activate the correct environment."
    exit 1
fi

if ! "$PYTHON_EXE" -c "import torch, transformers, datasets, openai; print('Dependencies OK')" >/dev/null 2>&1; then
    echo "[ERROR] Missing Python dependencies. Required: torch transformers datasets openai"
    exit 1
fi

if [ "$MODEL_BACKEND" = "hf-causal-vllm" ] && ! "$PYTHON_EXE" -c "import vllm" >/dev/null 2>&1; then
    echo "[WARN] vllm is not installed in this Python environment; falling back to hf-causal."
    MODEL_BACKEND="hf-causal"
fi

if [ "$MODEL_BACKEND" = "hf-causal" ]; then
    MODEL_ARGS="pretrained=$MODEL_PATH,tokenizer=$MODEL_PATH,dtype=auto,trust_remote_code=True"
else
    MODEL_ARGS="use_accelerate=$USE_ACCELERATE,pretrained=$MODEL_PATH,tokenizer=$MODEL_PATH,use_fast=False,max_gen_toks=$MAX_GEN_TOKS,dtype=auto,trust_remote_code=True"
fi

EVAL_SUPPORTS_SPLIT=False
if "$PYTHON_EXE" "$EVAL_SCRIPT" --help 2>&1 | grep -q -- "--eval_split"; then
    EVAL_SUPPORTS_SPLIT=True
fi

echo
echo "Model path : $MODEL_PATH"
echo "Data path  : $DATA_PATH"
echo "Data split : $MAPFIN_EVAL_SPLIT"
echo "Backend    : $MODEL_BACKEND"
echo "Model name : $MODEL_NAME"
echo "Python     : $PYTHON_EXE"
echo "Eval path  : $EVAL_SCRIPT"
echo "Output dir : $OUTPUT_DIR"
echo
echo "===== Environment Variables ====="
echo "OPENAI_BASE_URL=${OPENAI_BASE_URL:-}"
echo "OPENAI_CHAT_URL=${OPENAI_CHAT_URL:-}"
echo "OPENAI_EMBEDDING_MODEL=${OPENAI_EMBEDDING_MODEL:-}"
echo "================================"
echo

for task in $TASK_LIST; do
    echo "===== Running: $task ====="
    cmd=(
        "$PYTHON_EXE" "$EVAL_SCRIPT"
        --model "$MODEL_BACKEND"
        --tasks "$task"
        --model_args "$MODEL_ARGS"
        --no_cache
        --batch_size "$BATCH_SIZE"
        --device auto
        --output_path "$OUTPUT_DIR"
        --write_out
        --output_base_path "${MODEL_NAME}_${MAPFIN_EVAL_SPLIT}_${task}"
        --limit "$MAPFIN_LIMIT"
    )
    if [ "$EVAL_SUPPORTS_SPLIT" = "True" ]; then
        cmd+=(--eval_split "$MAPFIN_EVAL_SPLIT")
    else
        echo "[WARN] eval.py does not support --eval_split; using its built-in default split."
    fi

    if "${cmd[@]}"; then
        echo
    else
        exit_code=$?
        echo "[ERROR] Task $task failed with exit code $exit_code."
        exit "$exit_code"
    fi

done

echo "Done"
