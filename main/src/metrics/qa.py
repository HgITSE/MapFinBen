import re
import unicodedata
from collections import Counter


def normalize(text: str) -> str:
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return text.strip()


def tokenize(text: str):
    text = normalize(text)
    return re.findall(r"\w+", text, flags=re.UNICODE)


def normalized_exact_match(pred: str, gold: str) -> float:
    return 1.0 if normalize(pred) == normalize(gold) else 0.0


def token_f1(pred: str, gold: str) -> float:
    pred_tokens = tokenize(pred)
    gold_tokens = tokenize(gold)

    if len(pred_tokens) == 0 and len(gold_tokens) == 0:
        return 1.0
    if len(pred_tokens) == 0 or len(gold_tokens) == 0:
        return 0.0

    pred_counter = Counter(pred_tokens)
    gold_counter = Counter(gold_tokens)

    overlap = sum((pred_counter & gold_counter).values())

    precision = overlap / len(pred_tokens)
    recall = overlap / len(gold_tokens)

    if precision + recall == 0:
        return 0.0

    return 2 * precision * recall / (precision + recall)


def qa_metrics(pred: str, gold: str) -> dict:
    acc = 1.0 if pred == gold else 0.0
    norm_acc = normalized_exact_match(pred, gold)
    f1 = token_f1(pred, gold)
    final_correct = acc == 1.0 or norm_acc == 1.0 or f1 >= 0.9

    return {
        "acc": acc,
        "norm_acc": norm_acc,
        "token_f1": f1,
        "final_correct": final_correct,
    }
